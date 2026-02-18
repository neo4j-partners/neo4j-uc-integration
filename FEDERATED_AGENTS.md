# Federated Agents: Neo4j + Databricks Lakehouse

Building a Databricks AI agent that leverages federated queries across Neo4j graph data and Delta lakehouse tables.

---

## Context

The [`federated_lakehouse_query.ipynb`](uc-neo4j-test-suite/federated_lakehouse_query.ipynb) notebook demonstrates two federation methods for combining Neo4j and Delta data:

1. **`remote_query()`** via UC JDBC -- pure SQL, aggregate-only, no cluster library needed
2. **Neo4j Spark Connector** -- row-level data loaded into temp views for rich JOINs

These work well for direct SQL analytics. An AI agent can add natural language routing on top, automatically selecting the right data source and query pattern based on the user's question -- the same dual-source pattern referenced as "AgentBricks (Lab 6)" in the notebook.

---

## Architecture Options

### Option 1: Multi-Agent Supervisor (Recommended)

A **supervisor agent** (LangGraph) routes natural language questions to specialized sub-agents:

```
+---------------------------------+
|       Supervisor Agent          |
|  (LangGraph + ChatDatabricks)   |
+-------+------------+-----------+
        |            |           |
        v            v           v
    Genie        Neo4j        UC Function
    Agent        Graph         Tools
   (Delta        Agent       (Pre-built
    NL->SQL)   (Cypher via     queries)
              Spark Connector
              or UC JDBC)
```

**How it works:**
- **Genie Agent** handles sensor analytics questions ("What's the avg EGT for aircraft N101?") by querying Delta lakehouse tables via a Genie Space with natural language
- **Neo4j Graph Agent** handles relationship/topology questions ("What maintenance events led to this component failure?") via UC JDBC `remote_query()` or Spark Connector
- **Supervisor** uses an LLM to classify the question and route to the right sub-agent, or orchestrates multi-step queries across both

**Key references:**
- [Multi-Agent Supervisor Architecture (Databricks Blog)](https://www.databricks.com/blog/multi-agent-supervisor-architecture-orchestrating-enterprise-ai-scale)
- [Use Genie in multi-agent systems (Azure Databricks)](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/agent-framework/multi-agent-genie)
- [Example notebook (GitHub Gist)](https://gist.github.com/prithvikannan/82e789730c2fceec11932816bda50e59)

---

### Option 2: MCP-Based Agent (Modern, Standardized)

Use **Databricks managed MCP servers** as tools for a single agent:

| MCP Server | URL Pattern | Use Case |
|---|---|---|
| **DBSQL** | `/api/2.0/mcp/sql` | Execute SQL against UC tables, including `remote_query()` for Neo4j |
| **Genie** | `/api/2.0/mcp/genie/{id}` | NL-to-SQL for Delta sensor analytics |
| **UC Functions** | `/api/2.0/mcp/functions/{catalog}/{schema}/{function}` | Pre-defined parameterized fleet health queries |

```python
from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksMCPClient

workspace_client = WorkspaceClient(profile="my-profile")

# Connect to DBSQL MCP (can run remote_query() for Neo4j + Delta queries)
sql_mcp = DatabricksMCPClient(
    server_url=f"https://{host}/api/2.0/mcp/sql",
    workspace_client=workspace_client
)

# Connect to Genie MCP (NL->SQL for sensor analytics)
genie_mcp = DatabricksMCPClient(
    server_url=f"https://{host}/api/2.0/mcp/genie/{space_id}",
    workspace_client=workspace_client
)
```

The DBSQL MCP server can execute `remote_query()` calls, meaning it can federate to Neo4j through the existing UC JDBC connection -- an agent can run the exact SQL from the notebook.

**Key references:**
- [Managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [MCP on Databricks overview](https://docs.databricks.com/aws/en/generative-ai/mcp/)

---

### Option 3: UC Function Tools + Anthropic SDK

Register federated queries as **Unity Catalog SQL functions**, then use them as tools with the Anthropic Claude SDK directly:

```sql
-- Pre-built federated query as a UC function
CREATE OR REPLACE FUNCTION lakehouse.tools.fleet_health_summary(
  aircraft_id STRING COMMENT 'Aircraft ID to get health summary for'
)
RETURNS STRING
COMMENT 'Returns fleet health combining Neo4j maintenance events with Delta sensor data'
RETURN SELECT CONCAT(
    'Maintenance Events: ', COALESCE(m.cnt, 0), ', ',
    'Avg EGT: ', ROUND(s.avg_egt, 1), 'C, ',
    'Avg Vibration: ', ROUND(s.avg_vib, 4), ' IPS'
  )
  FROM (
    SELECT COUNT(*) AS cnt FROM remote_query('neo4j_conn',
      query => CONCAT(
        'SELECT COUNT(*) AS cnt FROM MaintenanceEvent WHERE aircraft_id = ''',
        aircraft_id, ''''
      ))
  ) m
  CROSS JOIN (
    SELECT
      AVG(CASE WHEN sen.type = 'EGT' THEN r.value END) AS avg_egt,
      AVG(CASE WHEN sen.type = 'Vibration' THEN r.value END) AS avg_vib
    FROM sensor_readings r
    JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
    JOIN systems sys ON sen.system_id = sys.`:ID(System)`
    WHERE sys.aircraft_id = aircraft_id
  ) s;
```

```python
# Wire into Anthropic SDK
from unitycatalog.ai.anthropic.toolkit import UCFunctionToolkit
from unitycatalog.ai.core.base import get_uc_function_client

client = get_uc_function_client()
toolkit = UCFunctionToolkit(
    function_names=["lakehouse.tools.fleet_health_summary"],
    client=client
)
# Pass toolkit.tools to Claude API calls
```

**Key references:**
- [Anthropic UC Integration](https://docs.databricks.com/aws/en/generative-ai/agent-framework/anthropic-uc-integration)
- [Create AI agent tools with UC functions](https://docs.databricks.com/aws/en/generative-ai/agent-framework/create-custom-tool)

---

## Agent Framework Details

### Mosaic AI Agent Framework

Databricks' platform for building, evaluating, deploying, and monitoring production agents. Four creation methods:

| Method | Description |
|---|---|
| **Agent Bricks** | Automated: specify use case and data, Databricks builds agent systems |
| **Code Authoring** | MLflow + any library (LangGraph, OpenAI Agents SDK, LlamaIndex, custom Python) |
| **AI Playground** | Low-code UI for prototyping, then export to notebook |
| **Templates** | Pre-built starters (e.g., `agent-openai-agents-sdk`) |

The recommended interface is **`ResponsesAgent`** (from MLflow), providing typed Python authoring, multi-agent support, streaming, and automatic compatibility with AI Playground, Agent Evaluation, and Databricks Apps deployment.

### How Agents Execute SQL

| Mechanism | Best For | Notes |
|---|---|---|
| **UC SQL Functions** | Known query patterns, parameterized retrieval | Agent supplies parameters to pre-defined SQL |
| **DBSQL MCP Server** | Ad-hoc SQL execution | Arbitrary read/write SQL via SQL warehouse |
| **Genie MCP Server** | Natural language to SQL | Up to 30 tables per space, read-only |
| **`system.ai.python_exec`** | Dynamic code execution | Built-in UC function for running Python with Spark |

### Tool Types

| Tool Type | Mechanism | Best For |
|---|---|---|
| UC SQL Functions | Pre-defined SQL with agent-supplied parameters | Known query patterns, structured retrieval |
| UC Python Functions | Python UDFs registered in UC | Custom logic, calculations, API calls |
| Managed MCP Servers | Pre-built (Vector Search, Genie, DBSQL, UC Functions) | Standardized Databricks data access |
| External MCP Servers | Third-party API connections | Slack, GitHub, external services |
| Custom MCP Servers | Self-hosted via Databricks Apps | Specialized business logic |

**Key packages:** `databricks-mcp`, `databricks-langchain`, `unitycatalog-ai`, `mlflow`

---

## Neo4j-Specific Considerations

| Concern | Detail |
|---|---|
| **Not a native federation source** | Neo4j is absent from the official supported list (MySQL, PostgreSQL, etc.). Integration works via the generic **JDBC Unity Catalog connection** with custom driver JARs -- a preview feature |
| **`remote_query()` limitations** | Aggregate-only for JDBC connections (Spark wraps queries for schema inference, breaking GROUP BY/ORDER BY in the inner query) |
| **Spark Connector = no UC governance** | Direct Bolt connection bypasses Unity Catalog access controls |
| **JDBC memory limit** | 400 MiB for the JDBC driver sandbox |
| **SafeSpark configs required** | Must set `maxMetaspace.mib 128`, `xmx.mib 300`, `size.default.mib 512` |
| **Authentication** | Only basic username/password for JDBC connections (no OAuth) |
| **SQL-to-Cypher translation** | Neo4j JDBC driver handles this when `enableSQLTranslation=true` is set |

### Creating the UC JDBC Connection for Neo4j

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '[
    "/Volumes/catalog/schema/jars/neo4j-jdbc-full-bundle-6.10.3.jar",
    "/Volumes/catalog/schema/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar"
  ]'
)
OPTIONS (
  url 'jdbc:neo4j+s://your-host:7687/neo4j?enableSQLTranslation=true',
  user secret('scope', 'neo4j-user'),
  password secret('scope', 'neo4j-password'),
  driver 'org.neo4j.jdbc.Neo4jDriver',
  externalOptionsAllowList 'dbtable,query,customSchema'
);
```

See [GUIDE_NEO4J_UC.md](GUIDE_NEO4J_UC.md) for full setup details.

---

## Genie for Delta Lakehouse Analytics

**AI/BI Genie** converts natural language questions into SQL queries against Unity Catalog tables. Key details:

- Up to **30 tables/views** per Genie space
- Supports managed tables, external tables, **foreign tables** (via Lakehouse Federation), views, metric views
- Up to **100 instructions** (example SQL, SQL functions, plain text combined)
- **Read-only** generated queries
- Rate limit: **5 queries/min/workspace** (preview tier)
- Programmatic access via **Genie Conversation API** (`POST /api/2.0/genie/spaces/{id}/start-conversation`)

For the fleet health scenario, a Genie space would include: `aircraft`, `systems`, `sensors`, `sensor_readings` with example SQL queries showing common analytics patterns (avg EGT by aircraft, vibration trends, fuel flow anomalies).

---

## Recommended Approach

For the fleet health scenario in this project, combine **Option 1** (Multi-Agent Supervisor) with **Option 2** (MCP servers):

1. **Genie Space** for Delta lakehouse (`sensor_readings`, `aircraft`, `systems`, `sensors`) -- handles natural language sensor analytics
2. **Custom MCP server** (or UC functions) for Neo4j graph queries -- wraps `remote_query()` or Spark Connector calls for maintenance/flight/topology queries
3. **LangGraph supervisor** that routes based on whether the question is about sensor data (Genie) vs graph relationships (Neo4j tool)
4. **MLflow ResponsesAgent** wrapper for deployment, evaluation, and monitoring

This mirrors the AgentBricks Lab 6 dual-source pattern, but with full control over routing logic and tool implementations.

```
User: "Which aircraft with high EGT readings also had critical maintenance events?"

Supervisor -> routes to BOTH sub-agents:
  1. Genie Agent: queries Delta for aircraft with EGT above threshold
  2. Neo4j Agent: queries graph for aircraft with CRITICAL MaintenanceEvents
Supervisor -> combines results and responds
```

---

## References

### Databricks Agent Framework
- [Mosaic AI Agent Framework](https://docs.databricks.com/aws/en/generative-ai/agent-framework/index.html)
- [Create an AI agent](https://docs.databricks.com/aws/en/generative-ai/agent-framework/create-agent)
- [Author an AI agent](https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent)
- [AI agent tools](https://docs.databricks.com/aws/en/generative-ai/agent-framework/agent-tool)
- [Create AI agent tools with UC functions](https://docs.databricks.com/aws/en/generative-ai/agent-framework/create-custom-tool)
- [Structured retrieval tools](https://docs.databricks.com/aws/en/generative-ai/agent-framework/structured-retrieval-tools)

### MCP Integration
- [MCP on Databricks](https://docs.databricks.com/aws/en/generative-ai/mcp/)
- [Managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [Announcing managed MCP servers (Blog)](https://www.databricks.com/blog/announcing-managed-mcp-servers-unity-catalog-and-mosaic-ai-integration)

### Genie / AI-BI
- [What is an AI/BI Genie space](https://docs.databricks.com/aws/en/genie/)
- [Set up a Genie space](https://docs.databricks.com/aws/en/genie/set-up)
- [Genie Conversation API](https://docs.databricks.com/aws/en/genie/conversation-api)
- [Use Genie in multi-agent systems](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/agent-framework/multi-agent-genie)

### Lakehouse Federation
- [Lakehouse Federation overview](https://docs.databricks.com/aws/en/query-federation/)
- [Query federation](https://docs.databricks.com/aws/en/query-federation/database-federation)
- [remote_query() reference](https://docs.databricks.com/aws/en/query-federation/remote-queries)
- [JDBC Unity Catalog connection](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Federation performance recommendations](https://docs.databricks.com/aws/en/query-federation/performance-recommendations)

### Anthropic / Claude Integration
- [Anthropic UC Integration](https://docs.databricks.com/aws/en/generative-ai/agent-framework/anthropic-uc-integration)
- [Unity Catalog tool integration with third parties](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/agent-framework/unity-catalog-tool-integration)

### Multi-Agent Patterns
- [Multi-Agent Supervisor Architecture (Blog)](https://www.databricks.com/blog/multi-agent-supervisor-architecture-orchestrating-enterprise-ai-scale)
- [Example multiagent_genie notebook](https://gist.github.com/prithvikannan/82e789730c2fceec11932816bda50e59)
- [Multi-Genie-Agent Solution with Databricks Apps](https://www.ikidata.fi/post/creating-a-multi-genie-agent-solution-with-databricks-apps-code-included)

### Neo4j + Databricks
- [Neo4j Spark Connector - Databricks quickstart](https://neo4j.com/docs/spark/current/databricks/)
- [Neo4j JDBC SQL2Cypher](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j-Databricks Connector (Blog)](https://neo4j.com/blog/news/neo4j-databricks-connector/)
