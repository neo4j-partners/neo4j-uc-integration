# Federated Agents: Natural Language to Neo4j via UC Federation

The goal: a user asks a natural language question and the system **automatically federates** across Neo4j graph data and Delta lakehouse tables -- all through Unity Catalog, with no direct Python drivers or Spark Connectors in the loop.

---

## The Key Insight

The full chain already exists in pieces. Connecting them end-to-end gives us:

```
Natural Language
      │
      ▼
   Genie (NL → SQL)
      │
      ▼
   Spark SQL Engine
      │
      ├── Delta tables ──► direct read
      │
      └── remote_query() ──► UC JDBC Connection
                                    │
                                    ▼
                              Neo4j JDBC Driver
                              (SQL → Cypher via enableSQLTranslation=true)
                                    │
                                    ▼
                                 Neo4j
```

Every layer is UC-governed. The LLM never sees Cypher, the user never writes SQL, and Neo4j is queried through the same federation path this project already built and tested.

---

## How It Works

### Step 1: Materialize Neo4j Data as UC Delta Tables

Live `CREATE VIEW` over `remote_query()` doesn't work due to two Neo4j JDBC limitations:
1. **`query` option**: Spark wraps in subquery for schema inference → Neo4j can't parse it
2. **`dbtable` option**: Avoids subquery but Neo4j returns `NullType` → requires `customSchema` (DataFrame API only, not available in `remote_query()`)

The workaround: use the **DataFrame API** with `dbtable` + `customSchema` to read Neo4j labels, then **materialize as managed Delta tables** via `saveAsTable()`. Re-run the notebook to refresh data from Neo4j.

```python
# Example: materialize MaintenanceEvent nodes as a Delta table
MAINTENANCE_SCHEMA = """`v$id` STRING, aircraft_id STRING, system_id STRING,
    component_id STRING, event_id STRING, severity STRING, fault STRING,
    corrective_action STRING, reported_at STRING"""

df = spark.read.format("jdbc") \
    .option("databricks.connection", UC_CONNECTION_NAME) \
    .option("dbtable", "MaintenanceEvent") \
    .option("customSchema", MAINTENANCE_SCHEMA) \
    .load() \
    .select("aircraft_id", "fault", "severity", "corrective_action", "reported_at")

df.write.mode("overwrite").saveAsTable("lakehouse.neo4j_maintenance_events")
```

The same pattern is used for `neo4j_flights`, `neo4j_airports`, and `neo4j_flight_airports` (a Spark SQL JOIN of flights + airports). See `federated_views_agent_ready.ipynb` for the complete implementation.

Once these tables exist, Genie (or any SQL tool) can query them like regular tables -- GROUP BY, ORDER BY, JOINs with Delta tables all work because the Neo4j data is materialized as standard Delta tables.

### Step 2: Genie Space Includes Both Delta Tables and Neo4j Views

Create a Genie space that includes **all** data sources as a unified catalog:

**Delta tables (direct):**
- `lakehouse.aircraft` -- aircraft fleet registry
- `lakehouse.systems` -- aircraft systems (Engine, APU, etc.)
- `lakehouse.sensors` -- sensor metadata (EGT, Vibration, FuelFlow, N1Speed)
- `lakehouse.sensor_readings` -- 345K+ time-series sensor readings

**Neo4j views (via `remote_query()` with `dbtable`):**
- `lakehouse.neo4j_maintenance_events` -- maintenance events from the graph
- `lakehouse.neo4j_flights` -- flight operations from the graph
- `lakehouse.neo4j_airports` -- airport reference data from the graph
- `lakehouse.neo4j_flight_airports` -- flight→airport mapping (Spark SQL JOIN)

Genie sees all 8 as regular UC tables. It generates SQL that JOINs across them transparently -- the federation is invisible to the LLM.

### Step 3: Genie Instructions Teach the Join Patterns

Genie spaces support up to 100 instructions (example SQL, SQL functions, plain text). These teach Genie the domain and JOIN patterns:

**Plain text instruction:**
```
This space combines aircraft sensor telemetry (Delta lakehouse) with maintenance
events and flight operations (Neo4j knowledge graph) via Unity Catalog federation.

Delta tables contain time-series sensor readings: EGT (Exhaust Gas Temperature in
Celsius), Vibration (IPS), FuelFlow (kg/s), and N1Speed (RPM).

Neo4j views contain graph-sourced data: maintenance events with severity levels
(CRITICAL, MAJOR, MINOR), flight operations with origin/destination airports, and
flight-to-airport graph relationships.

Join aircraft_id across both sources to correlate sensor health with maintenance
and flight activity.
```

**Example SQL queries:**

```sql
-- Fleet health: sensor averages + maintenance counts per aircraft
SELECT
    a.tail_number,
    a.model,
    a.operator,
    ROUND(AVG(CASE WHEN sen.type = 'EGT' THEN r.value END), 1) AS avg_egt_c,
    ROUND(AVG(CASE WHEN sen.type = 'Vibration' THEN r.value END), 4) AS avg_vib_ips,
    COUNT(DISTINCT m.fault) AS maintenance_events,
    SUM(CASE WHEN m.severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_events
FROM aircraft a
JOIN systems sys ON a.`:ID(Aircraft)` = sys.aircraft_id
JOIN sensors sen ON sys.`:ID(System)` = sen.system_id
JOIN sensor_readings r ON sen.`:ID(Sensor)` = r.sensor_id
LEFT JOIN neo4j_maintenance_events m ON a.`:ID(Aircraft)` = m.aircraft_id
GROUP BY a.tail_number, a.model, a.operator
ORDER BY critical_events DESC;
```

```sql
-- Aircraft with high EGT that also have critical maintenance events
SELECT
    a.tail_number,
    a.model,
    ROUND(AVG(r.value), 1) AS avg_egt,
    COUNT(DISTINCT m.fault) AS critical_faults
FROM aircraft a
JOIN systems sys ON a.`:ID(Aircraft)` = sys.aircraft_id
JOIN sensors sen ON sys.`:ID(System)` = sen.system_id
JOIN sensor_readings r ON sen.`:ID(Sensor)` = r.sensor_id
JOIN neo4j_maintenance_events m ON a.`:ID(Aircraft)` = m.aircraft_id
WHERE sen.type = 'EGT' AND m.severity = 'CRITICAL'
GROUP BY a.tail_number, a.model
ORDER BY avg_egt DESC;
```

```sql
-- Flight activity + engine performance per aircraft
SELECT
    a.tail_number,
    COUNT(DISTINCT f.flight_number) AS total_flights,
    COUNT(DISTINCT f.destination) AS unique_destinations,
    ROUND(AVG(CASE WHEN sen.type = 'EGT' THEN r.value END), 1) AS avg_egt_c,
    ROUND(AVG(CASE WHEN sen.type = 'FuelFlow' THEN r.value END), 2) AS avg_fuel_kgs
FROM aircraft a
JOIN neo4j_flights f ON a.`:ID(Aircraft)` = f.aircraft_id
JOIN systems sys ON a.`:ID(Aircraft)` = sys.aircraft_id
JOIN sensors sen ON sys.`:ID(System)` = sen.system_id
JOIN sensor_readings r ON sen.`:ID(Sensor)` = r.sensor_id
WHERE sys.type = 'Engine'
GROUP BY a.tail_number
ORDER BY total_flights DESC;
```

### Step 4: Expose via Genie MCP Server or Conversation API

The Genie space is accessed programmatically through either:

**Option A: Genie Managed MCP Server** (for agent integration)
```
https://<workspace>/api/2.0/mcp/genie/<space_id>
```

An agent connects to this MCP server and sends natural language queries. Genie generates SQL, Spark executes it (federating to Neo4j via `remote_query()` views), and results come back.

**Option B: Genie Conversation API** (for direct app integration)
```
POST /api/2.0/genie/spaces/{space_id}/start-conversation
{"content": "Which aircraft with high EGT readings also had critical maintenance events?"}
```

Poll for results, then extract the generated SQL and result set from the response attachments.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         User (Natural Language)                         │
│   "Which aircraft with high EGT also had critical maintenance events?"  │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    Genie Space (NL → SQL)                               │
│   Tables: aircraft, systems, sensors, sensor_readings,                  │
│           neo4j_maintenance_events, neo4j_flights,                      │
│           neo4j_airports, neo4j_flight_airports                         │
│   Instructions: domain context + example SQL + JOIN patterns            │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ Generated SQL
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      Spark SQL Engine                                   │
│                                                                         │
│   SELECT a.tail_number, AVG(r.value) AS avg_egt,                       │
│          COUNT(m.fault) AS critical_faults                              │
│   FROM aircraft a                                                       │
│   JOIN ... sensor_readings r ...                                        │
│   JOIN neo4j_maintenance_events m ...  ◄── UC view over remote_query() │
│   WHERE sen.type = 'EGT' AND m.severity = 'CRITICAL'                  │
│   GROUP BY ...                                                          │
│                                                                         │
├────────────────────────────┬─────────────────────────────────────────────┤
│  Delta Lakehouse (direct)  │  Neo4j (via remote_query dbtable → JDBC)  │
│                            │                                             │
│  sensor_readings           │  MaintenanceEvent nodes                     │
│  sensors                   │  Flight nodes                               │
│  systems                   │  Airport nodes                              │
│  aircraft                  │                                             │
│                            │  UC JDBC Connection                         │
│                            │  enableSQLTranslation=true                  │
│                            │  dbtable avoids subquery wrapping           │
└────────────────────────────┴─────────────────────────────────────────────┘
```

**Everything flows through Unity Catalog.** No Spark Connector, no direct Bolt connection, no Python driver. The Neo4j JDBC driver's `enableSQLTranslation=true` handles SQL-to-Cypher translation transparently.

---

## Agent Integration Patterns

### Pattern 1: Genie as Standalone Agent (Simplest)

A single Genie space handles all queries. Best when:
- Questions map cleanly to SQL over the unified table set
- No multi-step reasoning needed
- The `remote_query()` views cover the needed Neo4j access patterns

```python
from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksMCPClient

workspace_client = WorkspaceClient(profile="my-profile")
genie_mcp = DatabricksMCPClient(
    server_url=f"https://{host}/api/2.0/mcp/genie/{space_id}",
    workspace_client=workspace_client
)
```

### Pattern 2: Multi-Agent with Genie + DBSQL MCP (Flexible)

For questions that need both NL-to-SQL (Genie) and ad-hoc federated SQL (DBSQL MCP server running `remote_query()` directly):

```
┌────────────────────────────────┐
│     Supervisor (LangGraph)     │
├───────────────┬────────────────┤
│               │                │
▼               ▼                │
Genie MCP    DBSQL MCP          │
(NL→SQL      (ad-hoc SQL        │
 over all    with remote_query   │
 tables)     for custom Neo4j    │
             queries)            │
```

The DBSQL MCP server can execute arbitrary SQL including `remote_query()` calls, so it handles edge cases where the pre-built views don't cover a specific Neo4j query pattern.

```python
# Supervisor can route to either:
genie_mcp = DatabricksMCPClient(
    server_url=f"https://{host}/api/2.0/mcp/genie/{space_id}",
    workspace_client=workspace_client
)
dbsql_mcp = DatabricksMCPClient(
    server_url=f"https://{host}/api/2.0/mcp/sql",
    workspace_client=workspace_client
)
```

### Pattern 3: Agent Bricks Supervisor (No-Code)

Use Agent Bricks to create a supervisor that coordinates a Genie sub-agent (for the federated fleet data) with other agents (e.g., a RAG agent for unstructured maintenance manuals). This is the "Lab 6" pattern referenced in the notebook -- but now the Genie space itself handles the federation transparently.

---

## Implementation Checklist

### Prerequisites (Already Done)
- [x] Neo4j UC JDBC connection configured (`neo4j_uc_connection`)
- [x] Delta lakehouse tables exist (`aircraft`, `systems`, `sensors`, `sensor_readings`)
- [x] `remote_query()` tested and working against Neo4j
- [x] SafeSpark memory configs applied
- [x] Neo4j JDBC driver JARs uploaded to UC Volume

### New Work
- [x] **Create permanent UC views** using `remote_query()` with `dbtable` parameter
  - `neo4j_maintenance_events` -- all maintenance events
  - `neo4j_flights` -- all flight operations
  - `neo4j_airports` -- airport reference data
  - `neo4j_flight_airports` -- flight→airport mapping (Spark SQL JOIN)
  - See `federated_views_agent_ready.ipynb` for the working notebook
- [ ] **Create Genie space** with all 8 tables/views
- [ ] **Add Genie instructions** -- domain context, JOIN patterns, example SQL
- [ ] **Add example queries** -- the federated queries from the notebook as Genie examples
- [ ] **Test NL queries** -- verify Genie generates correct federated SQL
- [ ] **Connect to agent** via Genie MCP server or Conversation API
- [ ] **Optional: Add DBSQL MCP** for ad-hoc `remote_query()` fallback

---

## Constraints and Limitations

| Constraint | Impact | Mitigation |
|---|---|---|
| `remote_query()` with `dbtable` returns all rows from a label | Large Neo4j result sets may be slow | Keep Neo4j views focused; use column selection in the view definition |
| `remote_query()` with `query` option breaks for non-aggregate SELECT | Spark wraps in subquery for schema inference | Use `dbtable` parameter instead; apply column selection and joins in Spark SQL |
| `remote_query()` is read-only | Cannot write to Neo4j through federation | Write operations handled outside the agent |
| Neo4j JDBC SQL translation is limited | Complex Cypher patterns (variable-length paths, APOC) may not translate | Use the Neo4j Spark Connector for complex graph patterns |
| Genie: 30 table/view limit per space | Must choose which views to expose | Focus on the most common Neo4j query patterns |
| Genie: 5 queries/min/workspace (preview) | Rate-limited for high-throughput use | Suitable for interactive analytics, not batch processing |
| Genie: read-only generated queries | No write-back to either source | Agent is purely analytical |
| JDBC memory limit: 400 MiB | Large Neo4j result sets may hit this | Filter data in the `remote_query()` SQL before returning |
| `enableSQLTranslation=true` required | Must be in the JDBC URL | Already configured in the UC connection |

---

## SQL-to-Cypher Translation Reference

The Neo4j JDBC driver translates SQL to Cypher using these patterns (relevant for what Genie-generated SQL will actually execute):

| SQL Pattern | Cypher Translation |
|---|---|
| `SELECT * FROM NodeLabel` | `MATCH (n:NodeLabel) RETURN n.*` |
| `FROM A NATURAL JOIN REL NATURAL JOIN B` | `MATCH (a:A)-[:REL]->(b:B) RETURN ...` |
| `WHERE severity = 'CRITICAL'` | `WHERE n.severity = 'CRITICAL'` |
| `COUNT(*), SUM(), AVG()` | Cypher aggregation functions |

Full reference: [Neo4j JDBC SQL2Cypher](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)

---

## References

### UC Federation (Core)
- [Lakehouse Federation overview](https://docs.databricks.com/aws/en/query-federation/)
- [remote_query() reference](https://docs.databricks.com/aws/en/query-federation/remote-queries)
- [JDBC Unity Catalog connection](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Neo4j JDBC SQL2Cypher](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)

### Genie / AI-BI
- [What is an AI/BI Genie space](https://docs.databricks.com/aws/en/genie/)
- [Set up a Genie space](https://docs.databricks.com/aws/en/genie/set-up)
- [Genie Conversation API](https://docs.databricks.com/aws/en/genie/conversation-api)
- [Use Genie in multi-agent systems](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/agent-framework/multi-agent-genie)

### Agent Framework
- [Mosaic AI Agent Framework](https://docs.databricks.com/aws/en/generative-ai/agent-framework/index.html)
- [Managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [Multi-Agent Supervisor Architecture (Blog)](https://www.databricks.com/blog/multi-agent-supervisor-architecture-orchestrating-enterprise-ai-scale)

### Project Documentation
- [GUIDE_NEO4J_UC.md](GUIDE_NEO4J_UC.md) -- Full UC JDBC integration guide
- [federated_views_agent_ready.ipynb](uc-neo4j-test-suite/federated_views_agent_ready.ipynb) -- Permanent UC views for Genie (dbtable approach)
- [federated_lakehouse_query.ipynb](uc-neo4j-test-suite/federated_lakehouse_query.ipynb) -- Working federated query examples (Spark Connector + remote_query)
