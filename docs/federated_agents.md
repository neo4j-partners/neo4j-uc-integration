# Federated Agents: Natural Language to Neo4j via Unity Catalog

A user asks a natural language question and the system **automatically federates** across Neo4j graph data and Delta lakehouse tables — all through Unity Catalog, with no direct Python drivers or Spark Connectors in the loop.

---

## The Key Insight

The full chain already exists:

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
      └── Neo4j tables ──► materialized Delta tables (via UC JDBC)
```

Every layer is UC-governed. The LLM never sees Cypher, the user never writes SQL, and Neo4j data is queryable through the same federation path as any other UC table.

---

## Notebooks Overview

The `uc-neo4j-test-suite/` directory contains five notebooks that build up the integration layer by layer. Each notebook is self-contained with its own configuration, verification steps, and tests.

### 1. SQL Translation Validation (`neo4j_databricks_sql_translation.ipynb`)

A systematic test suite that validates Neo4j connectivity through Unity Catalog's generic JDBC path. It progresses from basic network connectivity through the full UC JDBC connection, documenting what works and where limitations exist.

**What it covers:**
- Network connectivity (TCP layer to Neo4j)
- Neo4j Python driver authentication
- Neo4j Spark Connector baseline (Bolt protocol)
- Direct JDBC with SQL-to-Cypher translation (`enableSQLTranslation=true`)
- Unity Catalog JDBC connection creation and configuration
- `remote_query()` function tests through UC

**Key findings:**
- The `dbtable` option with `customSchema` is required because Neo4j JDBC returns `NullType` during Spark schema inference
- The `query` option fails because Spark wraps inner queries in subqueries that Neo4j's SQL translator cannot parse
- SafeSpark sandbox memory configuration requires three Spark properties (documented in the notebook)
- SQL aggregates (`COUNT`, `MIN`, `MAX`, `COUNT DISTINCT`) and `NATURAL JOIN` relationship traversals all translate correctly to Cypher

### 2. Federated Lakehouse Queries (`federated_lakehouse_query.ipynb`)

Demonstrates querying both Delta lakehouse tables and Neo4j graph data in unified federated queries. Uses two federation methods: `remote_query()` for aggregate queries and the Neo4j Spark Connector for row-level data.

**What it covers:**
- Fleet-wide summary combining Neo4j graph metrics with Delta sensor analytics
- Per-aircraft correlation of sensor health (Delta) with maintenance events (Neo4j)
- Flight operations correlated with engine performance data
- A comprehensive fleet health dashboard combining all data sources
- UC audit trail showing what Unity Catalog captured about federated queries

**Federation methods compared:**

| Method | Strengths | Limitations |
|--------|-----------|-------------|
| `remote_query()` | Pure SQL, no cluster library, UC governed | Aggregate-only (no GROUP BY on results) |
| Spark Connector | Full Cypher support, row-level data | Requires cluster library, no UC governance |

### 3. Agent-Ready Federated Views (`federated_views_agent_ready.ipynb`)

Creates the **materialized Delta tables** that make Neo4j data queryable by Genie and other SQL tools. This is the notebook that bridges the gap between raw Neo4j federation and agent-ready data.

**What it does:**
- Reads Neo4j node labels (MaintenanceEvent, Flight, Airport) via the DataFrame API with `dbtable` + `customSchema`
- Materializes each as a managed Delta table in Unity Catalog using `saveAsTable()`
- Creates a flight-to-airport mapping table via Spark SQL JOIN
- Validates that standard SQL operations (GROUP BY, ORDER BY, WHERE, aggregations, DISTINCT) all work on the materialized tables
- Runs the same federated queries from notebook #2, but using only UC federation (no Spark Connector)

**Why materialized tables instead of live views?** Two Neo4j JDBC limitations prevent `CREATE VIEW` over `remote_query()`:
1. The `query` option triggers Spark's subquery wrapping, which Neo4j can't parse
2. The `dbtable` option returns `NullType` and requires `customSchema`, which is only available on the DataFrame API

The workaround is to materialize as Delta tables and re-run the notebook to refresh data.

**Tables created:**

| Table | Source | Description |
|-------|--------|-------------|
| `neo4j_maintenance_events` | MaintenanceEvent nodes | Severity, fault, corrective action |
| `neo4j_flights` | Flight nodes | Flight operations with origin/destination |
| `neo4j_airports` | Airport nodes | Airport reference data (IATA, name, city) |
| `neo4j_flight_airports` | Flights + Airports JOIN | Flight-to-departure-airport mapping |

### 4. Metadata Sync via Delta Tables (`metadata_sync_delta.ipynb`)

Materializes Neo4j node labels and relationship types as managed Delta tables in a dedicated `neo4j_metadata` catalog. When data is written as a Delta table, UC automatically registers full schema metadata — column names, types, nullability — making it browsable in Catalog Explorer and queryable via `INFORMATION_SCHEMA`.

**What it does:**
- Discovers all Neo4j labels and relationship types using built-in `db.schema.nodeTypeProperties()` and `db.schema.relTypeProperties()` procedures
- Reads each label and relationship via the Spark Connector
- Writes each as a managed Delta table (`neo4j_metadata.nodes.*` and `neo4j_metadata.relationships.*`)
- Verifies metadata appears in `INFORMATION_SCHEMA`

**Requires:** Single-user access mode cluster with the Neo4j Spark Connector installed.

### 5. Metadata Sync via External Metadata API (`metadata_sync_external.ipynb`)

Registers Neo4j schema as external metadata objects in Unity Catalog using the [External Metadata API](https://docs.databricks.com/api/workspace/externalmetadata). No data is copied — this is metadata-only registration for discoverability and lineage tracking.

**What it does:**
- Discovers Neo4j schema (same discovery as notebook #4)
- Registers each node label and relationship type via the REST API
- Encodes Neo4j property types in the metadata properties map
- Lists and verifies all registered objects
- Includes optional cleanup to delete registered metadata

**Comparison of metadata sync approaches:**

| Aspect | External Metadata API (#5) | Materialized Delta Tables (#4) |
|--------|---------------------------|-------------------------------|
| Data copied | No | Yes |
| Catalog Explorer visible | No | Yes |
| SQL queryable | No | Yes |
| Column types in UC | Properties map only | Full native types |
| Storage cost | None | Delta storage |
| Setup complexity | Lower | Higher (Spark Connector needed) |

The recommendation is to use both: materialized tables for high-value labels that need SQL access, and the External Metadata API for comprehensive metadata coverage.

---

## Setting Up a Genie Space

Once the materialized tables from notebook #3 exist, create a Genie space that includes all data sources as a unified catalog:

**Delta tables (direct from lakehouse):**
- `aircraft` — fleet registry
- `systems` — aircraft systems (Engine, APU, etc.)
- `sensors` — sensor metadata (EGT, Vibration, FuelFlow, N1Speed)
- `sensor_readings` — 345K+ time-series sensor readings

**Neo4j tables (materialized):**
- `neo4j_maintenance_events` — maintenance events from the graph
- `neo4j_flights` — flight operations from the graph
- `neo4j_airports` — airport reference data from the graph
- `neo4j_flight_airports` — flight-to-airport mapping

Genie sees all 8 as regular UC tables and generates SQL that JOINs across them transparently. The federation is invisible to the LLM.

### Genie Instructions

Genie spaces support up to 100 instructions (example SQL, plain text) that teach the domain and JOIN patterns. Key things to communicate:

- The sensor data model is normalized across 4 tables. There is no direct "EGT" column — sensor type is in `sensors.type` and the reading value is in `sensor_readings.value`. Queries must JOIN through the chain: `aircraft → systems → sensors → sensor_readings`.
- Neo4j tables use `aircraft_id` as the join key, matching `aircraft.:ID(Aircraft)` in the Delta tables.
- Sensor types include EGT (Celsius), Vibration (IPS), FuelFlow (kg/s), and N1Speed (RPM).
- Severity levels for maintenance events are CRITICAL, MAJOR, and MINOR.

---

## Example Questions

Use these natural language questions to verify that Genie correctly federates across Neo4j and Delta tables.

### Single-Source: Neo4j Tables Only

- How many maintenance events are there by severity level?
- Which aircraft have the most flights?
- List all airports with their city and country.
- Show me all critical maintenance events and their corrective actions.

### Single-Source: Delta Tables Only

- What is the average EGT across all sensor readings?
- Which aircraft have the highest vibration readings?
- How many sensors does each aircraft system have?

### Cross-Source: Neo4j + Delta (Federated)

- Which aircraft had critical maintenance events and what were the faults reported?
- Which aircraft with high EGT readings also had critical maintenance events?
- For each aircraft, show the number of flights, maintenance events, and average engine temperature.
- Which operators have the most critical maintenance events, and what are their fleet's average sensor readings?
- Show me aircraft with above-average vibration that also have major or critical maintenance events.
- Which departure airports have the highest average EGT across their fleet?
- Compare flight activity and engine health — do aircraft with more flights have higher EGT?

### Advanced: Multi-Table Federated

- Give me a fleet health dashboard: tail number, model, operator, flight count, maintenance events, critical count, average EGT, and average vibration for every aircraft.
- Which Boeing aircraft flying out of the busiest airports have had critical maintenance and high fuel flow?

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
│   Instructions: domain context + JOIN patterns                          │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ Generated SQL
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      Spark SQL Engine                                   │
│                                                                         │
├────────────────────────────┬─────────────────────────────────────────────┤
│  Delta Lakehouse (direct)  │  Neo4j (materialized via JDBC dbtable)    │
│                            │                                             │
│  sensor_readings           │  neo4j_maintenance_events                   │
│  sensors                   │  neo4j_flights                              │
│  systems                   │  neo4j_airports                             │
│  aircraft                  │  neo4j_flight_airports                      │
│                            │                                             │
│                            │  Re-run federated_views_agent_ready.ipynb   │
│                            │  to refresh from Neo4j                      │
└────────────────────────────┴─────────────────────────────────────────────┘
```

Everything flows through Unity Catalog. No Spark Connector, no direct Bolt connection, no Python driver.

---

## Agent Integration Patterns

### Pattern 1: Genie as Standalone Agent

A single Genie space handles all queries. Best when questions map cleanly to SQL over the unified table set and no multi-step reasoning is needed. Connect via the Genie MCP server endpoint or the Conversation API.

### Pattern 2: Multi-Agent with Genie + DBSQL MCP

For questions that need both NL-to-SQL (Genie) and ad-hoc federated SQL, pair a Genie agent with a DBSQL MCP server. The DBSQL MCP server can execute arbitrary SQL including `remote_query()` calls, handling edge cases where the materialized tables don't cover a specific Neo4j query pattern.

### Pattern 3: Agent Bricks Supervisor

Use Agent Bricks to create a supervisor that coordinates a Genie sub-agent (for the federated fleet data) with other agents (e.g., a RAG agent for unstructured maintenance manuals). The Genie space handles the federation transparently.

---

## Constraints and Limitations

| Constraint | Impact | Mitigation |
|---|---|---|
| Neo4j data is materialized (snapshot), not live | Data may be stale if Neo4j is updated | Re-run `federated_views_agent_ready.ipynb` to refresh; consider scheduling as a job |
| `remote_query()` with `query` option breaks | Spark wraps in subquery for schema inference | Use DataFrame API with `dbtable` + `customSchema` instead |
| `remote_query()` with `dbtable` returns NullType | Live views return NULL data | Use `customSchema` (DataFrame API only) and materialize as Delta tables |
| Neo4j JDBC SQL translation is limited | Complex Cypher patterns (variable-length paths, APOC) may not translate | Use the Neo4j Spark Connector for complex graph patterns |
| Genie: 30 table/view limit per space | Must choose which views to expose | Focus on the most common Neo4j query patterns |
| Genie: 5 queries/min/workspace (preview) | Rate-limited for high-throughput use | Suitable for interactive analytics, not batch processing |
| Genie: read-only generated queries | No write-back to either source | Agent is purely analytical |
| JDBC memory limit: 400 MiB | Large Neo4j result sets may hit this | Filter data in the query before returning |

---

## SQL-to-Cypher Translation Reference

The Neo4j JDBC driver translates SQL to Cypher using these patterns (relevant for what Genie-generated SQL will actually execute against Neo4j):

| SQL Pattern | Cypher Translation |
|---|---|
| `SELECT * FROM NodeLabel` | `MATCH (n:NodeLabel) RETURN n.*` |
| `FROM A NATURAL JOIN REL NATURAL JOIN B` | `MATCH (a:A)-[:REL]->(b:B) RETURN ...` |
| `WHERE severity = 'CRITICAL'` | `WHERE n.severity = 'CRITICAL'` |
| `COUNT(*), SUM(), AVG()` | Cypher aggregation functions |

Full reference: [Neo4j JDBC SQL2Cypher](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)

See `neo4j_databricks_sql_translation.ipynb` for tested examples of each pattern.

---

## References

### Project Notebooks
- [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) — UC JDBC validation test suite
- [`federated_lakehouse_query.ipynb`](uc-neo4j-test-suite/federated_lakehouse_query.ipynb) — Federated query examples (Spark Connector + remote_query)
- [`federated_views_agent_ready.ipynb`](uc-neo4j-test-suite/federated_views_agent_ready.ipynb) — Materialized UC tables for Genie
- [`metadata_sync_delta.ipynb`](uc-neo4j-test-suite/metadata_sync_delta.ipynb) — Schema sync via Delta materialization
- [`metadata_sync_external.ipynb`](uc-neo4j-test-suite/metadata_sync_external.ipynb) — Schema sync via External Metadata API

### Project Documentation
- [neo4j_uc_jdbc_guide.md](neo4j_uc_jdbc_guide.md) — UC JDBC integration guide

### Databricks
- [Lakehouse Federation overview](https://docs.databricks.com/aws/en/query-federation/)
- [remote_query() reference](https://docs.databricks.com/aws/en/query-federation/remote-queries)
- [What is an AI/BI Genie space](https://docs.databricks.com/aws/en/genie/)
- [Set up a Genie space](https://docs.databricks.com/aws/en/genie/set-up)
- [Genie Conversation API](https://docs.databricks.com/aws/en/genie/conversation-api)
- [Managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)

### Neo4j
- [Neo4j JDBC SQL2Cypher](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/)
