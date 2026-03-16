# Neo4j + Databricks Unity Catalog Integration

**Documentation Site:** [https://neo4j-partners.github.io/neo4j-uc-integration](https://neo4j-partners.github.io/neo4j-uc-integration)

This project shows how to query a Neo4j graph database directly from Databricks using Unity Catalog. You write SQL in Databricks and the Neo4j JDBC driver automatically translates it to Cypher — the graph query language Neo4j uses — so you don't need to learn Cypher to get data out of Neo4j.

The connection works through Unity Catalog's JDBC support, which means your Neo4j access is governed by the same permissions, credentials, and audit controls as the rest of your lakehouse. Once connected, you can join Neo4j graph data (like flights, airports, and relationships between them) with your existing Delta tables in a single query.

The project also demonstrates how to make Neo4j's schema (node labels, relationship types, properties) visible in Databricks Catalog Explorer through metadata synchronization, and how to make Neo4j data queryable in plain English through Databricks AI/BI Genie.

All queries shown in this repo ran on a live Databricks cluster (Runtime 17.3 LTS) connected to Neo4j Aura. The output is real, not mocked.

For a step-by-step setup and usage guide, see [neo4j_uc_jdbc_guide.md](./docs/neo4j_uc_jdbc_guide.md).

---

## Overview of Neo4j Integration Patterns

**JDBC Connectivity** — Neo4j connects to Unity Catalog via a generic JDBC connection (`TYPE JDBC`) using the [Neo4j JDBC driver](https://neo4j.com/docs/jdbc-manual/current/) with built-in SQL-to-Cypher translation. A SafeSpark compatibility issue (metaspace memory exhaustion) was resolved in collaboration with Databricks engineering. With three Spark configuration settings, UC JDBC connections to Neo4j work correctly — including queries, aggregates, GROUP BY, HAVING, ORDER BY, JOINs, and schema discovery.

**Federated Queries** — Once connected, Neo4j graph data (flights, airports, maintenance events, component hierarchies) can be joined with Delta lakehouse tables (sensor readings, time-series analytics) in a single Spark SQL statement. No ETL pipelines required — each database is queried where the data lives, with results combined at read time.

**Metadata Synchronization** — The JDBC connection registers credentials and a driver, but does not expose Neo4j's schema as browsable UC objects. This project prototypes two approaches to metadata sync: materialized Delta tables (full data copy with Catalog Explorer, `INFORMATION_SCHEMA`, and SQL access) and the External Metadata API (metadata-only registration for discoverability and lineage). The graph-to-relational mapping is well-defined: node labels become tables in a `nodes` schema, relationship types become tables in a `relationships` schema, and properties become columns with mapped types.

**Natural Language via Genie** — Neo4j data materialized as managed Delta tables becomes transparently queryable through Databricks AI/BI Genie. Users ask plain-English questions and Genie generates SQL that federates across Neo4j graph data and Delta lakehouse tables, all governed by Unity Catalog.

**Proposal for First-Class Support** — The prototype demonstrates that Neo4j can be elevated from a generic JDBC bring-your-own-driver configuration to a natively supported Lakehouse Federation data source (`TYPE NEO4J`), with automatic metadata sync, table-level governance, and lineage tracking on par with currently supported sources like PostgreSQL, Snowflake, and BigQuery.

---

## Notebooks

All notebooks are in `uc-neo4j-test-suite/` and should be imported to your Databricks workspace. See [uc-neo4j-test-suite/README.md](./uc-neo4j-test-suite/README.md) for prerequisites and setup instructions.

| Notebook | What It Covers |
|----------|---------------|
| `neo4j_databricks_sql_translation.ipynb` | UC JDBC connection and SQL-to-Cypher translation tests (sections 1-7 covering environment, network, drivers, direct JDBC, and UC JDBC) |
| `metadata_sync_delta.ipynb` | Metadata sync via materialized Delta tables — reads Neo4j schema via Spark Connector, writes as managed Delta tables with full Catalog Explorer and `INFORMATION_SCHEMA` integration |
| `metadata_sync_external.ipynb` | Metadata sync via External Metadata API — registers Neo4j schema as external metadata objects for discoverability and lineage without copying data |
| `federated_lakehouse_query.ipynb` | Federated query patterns joining Neo4j graph data with Delta lakehouse tables in a single Spark SQL statement |
| `federated_views_agent_ready.ipynb` | Agent-ready federated views that make Neo4j data queryable through Databricks Genie natural language interface |

---

## Validated Components

| Component | Status | Notes |
|-----------|--------|-------|
| Network Connectivity | **PASS** | TCP to Neo4j port 7687 |
| Neo4j Python Driver | **PASS** | Bolt protocol works |
| Neo4j Spark Connector | **PASS** | `org.neo4j.spark.DataSource` works |
| Neo4j JDBC SQL-to-Cypher | **PASS** | Aggregates, GROUP BY, HAVING, ORDER BY, JOINs, dbtable all work |
| Direct JDBC (Non-UC) | **PASS** | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **PASS** | Works with SafeSpark memory configuration |
| **UC Schema Discovery** | **PASS** | Works with SafeSpark memory configuration |

**Test Results: 14/14 supported patterns pass, 1 expected failure documented (100% success rate)**

---

## How It Works

### JDBC Driver JAR

A single shaded JAR is uploaded to a Unity Catalog Volume:

| JAR | Purpose |
|-----|---------|
| `neo4j-unity-catalog-connector-<version>.jar` | Bundles the Neo4j JDBC driver, SQL-to-Cypher translator, and Spark subquery cleaner |

Download the latest release from [neo4j-unity-catalog-connector releases](https://github.com/neo4j-labs/neo4j-unity-catalog-connector/tags). See the [neo4j-unity-catalog-connector](https://github.com/neo4j-labs/neo4j-unity-catalog-connector) repo for details on what the JAR contains and how it is built.

The JAR includes a Spark subquery cleaner that handles a Spark-specific behavior: when Spark connects via JDBC, it wraps queries in a subquery for schema probing (`SELECT * FROM (<query>) SPARK_GEN_SUBQ_0 WHERE 1=0`). The cleaner detects this marker, extracts the inner query, and routes it correctly. See [neo4j_jdbc_cleaner.md](./docs/neo4j_jdbc_cleaner.md) for details.

### SafeSpark Configuration

Databricks runs custom JDBC drivers in an isolated SafeSpark sandbox. The Neo4j JDBC driver requires more metaspace than the default allocation. Without these settings, the sandbox JVM crashes with "Connection was closed before the operation completed" errors:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

### UC Connection

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '["path/to/neo4j-unity-catalog-connector-<version>.jar"]'  -- must be a UC Volume path
)
OPTIONS (
  url 'jdbc:neo4j+s://your-host:7687/neo4j?enableSQLTranslation=true',
  user secret('scope', 'neo4j-user'),
  password secret('scope', 'neo4j-password'),
  driver 'org.neo4j.jdbc.Neo4jDriver',
  externalOptionsAllowList 'dbtable,query,customSchema'
)
```

### Query Neo4j

```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \
    .load()
df.show()
```

### Prerequisites

Enable these preview features in your Databricks workspace:

| Feature | Required For |
|---------|--------------|
| Custom JDBC on UC Compute | Loading custom JDBC drivers in UC connections |
| remote_query table-valued function | Using `remote_query()` SQL function |

---

## SQL-to-Cypher Translation

The Neo4j JDBC driver automatically translates SQL to Cypher when `enableSQLTranslation=true`:

| SQL | Cypher |
|-----|--------|
| `SELECT COUNT(*) FROM Flight` | `MATCH (n:Flight) RETURN count(n)` |
| `SELECT COUNT(DISTINCT manufacturer) FROM Aircraft` | `MATCH (n:Aircraft) RETURN count(DISTINCT n.manufacturer)` |
| `SELECT COUNT(*) FROM Aircraft WHERE manufacturer = 'Boeing'` | `MATCH (n:Aircraft) WHERE n.manufacturer = 'Boeing' RETURN count(n)` |
| `FROM A NATURAL JOIN REL NATURAL JOIN B` | `MATCH (a:A)-[:REL]->(b:B)` |
| `SELECT name, count(*) FROM People p GROUP BY name` | `MATCH (p:People) RETURN p.name AS name, count(*)` |
| `SELECT sum(age) FROM People p GROUP BY name` | `MATCH (p:People) WITH sum(p.age) AS __with_col_0, p.name AS __group_col_1 RETURN __with_col_0` |
| `SELECT name, count(*) AS cnt FROM People p GROUP BY name HAVING cnt > 5` | `MATCH (p:People) WITH p.name AS name, count(*) AS cnt WHERE cnt > 5 RETURN name, cnt` |
| `SELECT name FROM People p GROUP BY name HAVING count(*) > 5` | `MATCH (p:People) WITH p.name AS name, count(*) AS __having_col_0 WHERE __having_col_0 > 5 RETURN name` |
| `SELECT name FROM People p GROUP BY name HAVING count(*) > 5 AND max(age) > 50` | `MATCH (p:People) WITH p.name AS name, count(*) AS __having_col_0, max(p.age) AS __having_col_1 WHERE (__having_col_0 > 5 AND __having_col_1 > 50) RETURN name` |
| `SELECT sum(age) FROM People p GROUP BY name ORDER BY sum(age)` | `MATCH (p:People) WITH sum(p.age) AS __with_col_0, p.name AS __group_col_1 RETURN __with_col_0 ORDER BY __with_col_0` |
| `SELECT c.name, count(*) FROM Customers c JOIN Orders o ON c.id = o.customer_id GROUP BY c.name` | `MATCH (c:Customers)<-[customer_id:CUSTOMER_ID]-(o:Orders) RETURN c.name, count(*)` |
| `SELECT DISTINCT name FROM People p GROUP BY name HAVING count(*) > 5 ORDER BY name LIMIT 10 OFFSET 5` | `MATCH (p:People) WITH p.name AS name, count(*) AS __having_col_0 WHERE __having_col_0 > 5 RETURN DISTINCT name ORDER BY name SKIP 5 LIMIT 10` |

**Supported through UC JDBC:**
- Aggregate queries (COUNT, MIN, MAX, SUM, AVG, percentileCont, percentileDisc, stDev, stDevP)
- COUNT DISTINCT
- Aggregates with WHERE clauses
- Aggregates with NATURAL JOIN (graph traversals)
- GROUP BY (implicit grouping and explicit WITH-clause generation)
- HAVING (simple, compound, mixed aggregates, without GROUP BY)
- ORDER BY (including on aggregate aliases and after WITH clauses)
- DISTINCT with GROUP BY/HAVING
- LIMIT and OFFSET
- Full clause combinations (WHERE + GROUP BY + HAVING + DISTINCT + ORDER BY + LIMIT + OFFSET)

**New SQL functionality supported:**
- **GROUP BY** — implicit grouping (columns match SELECT) and explicit WITH-clause generation (columns differ from SELECT)
- **HAVING** — simple conditions, compound conditions (AND/OR), mixed SELECT/HAVING aggregates, HAVING without GROUP BY, HAVING on non-aggregate GROUP BY columns
- **ORDER BY on aggregate aliases** — `ORDER BY cnt` where `cnt` aliases `count(*)`, with correct alias resolution after WITH clauses
- **DISTINCT with GROUP BY/HAVING** — correct `RETURN DISTINCT` placement
- **LIMIT and OFFSET with WITH clauses** — correct attachment to the final RETURN
- **WHERE + GROUP BY combinations** — WHERE filters before aggregation, HAVING filters after
- **JOIN + GROUP BY** — aggregation across relationships
- **COUNT(DISTINCT) in HAVING** — the DISTINCT flag is preserved through the entire pipeline
- **Additional aggregate functions** — `percentileCont`, `percentileDisc`, `stDev`, `stDevP`

> The examples above cover GROUP BY, HAVING, ORDER BY, LIMIT/OFFSET, DISTINCT, and their combinations with WHERE and JOIN. **Coming soon:** non-aggregate SELECT (`SELECT col1, col2 FROM Label`) and relationship property aggregation (aggregating over properties stored on Neo4j relationships rather than node properties).

**Not supported through UC JDBC** (use Neo4j Spark Connector instead):
- Non-aggregate SELECT
- Relationship property aggregation

See [neo4j_uc_jdbc_guide.md](./docs/neo4j_uc_jdbc_guide.md) for full details and workarounds.

---

## Metadata Synchronization

Setting up a JDBC connection lets you query Neo4j from Databricks, but it doesn't make Neo4j's schema visible in Unity Catalog. Without metadata sync, there's no way to browse Neo4j's node labels and relationship types in Catalog Explorer, set table-level permissions, or track data lineage — the connection just shows up as a single opaque object.

Metadata synchronization solves this by mapping Neo4j's graph structure into Unity Catalog's three-level namespace. Node labels (like `Aircraft` or `Flight`) become tables in a `nodes` schema, relationship types (like `DEPARTS_FROM`) become tables in a `relationships` schema, and properties become columns with the appropriate data types. The result is that Neo4j data looks like any other set of tables in your catalog — you can browse it, grant access to specific tables, and see it in lineage views.

This project prototypes two approaches:

- **Materialized Delta Tables** — Reads data from Neo4j using the Spark Connector and writes it as managed Delta tables. This gives you the full Unity Catalog experience: Catalog Explorer browsing, `INFORMATION_SCHEMA` queries, standard SQL access, and Delta features like time travel. The trade-off is that it copies the data, so you need scheduled jobs to keep it fresh.

- **External Metadata API** — Registers Neo4j's schema as metadata-only entries via Databricks REST API. No data is copied — it just makes Neo4j objects discoverable in the catalog for search and lineage purposes. The trade-off is that you can't query these entries directly with SQL.

For the full design, type mappings, and implementation details, see [metadata_synchronization.md](./docs/metadata_synchronization.md). For prototype results from running the sync notebooks, see [METADATA_SYNC_REPORT.md](./METADATA_SYNC_REPORT.md).

---

## Federated Agents and Genie Integration

Neo4j data materialized as Delta tables becomes queryable through Databricks AI/BI Genie without any direct graph database access. Users ask natural language questions and Genie generates SQL that federates across Neo4j graph data and Delta lakehouse tables — all governed by Unity Catalog. The LLM never sees Cypher and the user never writes SQL.

This supports several agent integration patterns: Genie as a standalone NL-to-SQL agent, multi-agent setups pairing Genie with a DBSQL MCP server, and Agent Bricks supervisors coordinating Genie with other agents (e.g., RAG over maintenance manuals).

See [federated_agents.md](./docs/federated_agents.md) for the full architecture, Genie space setup instructions, example questions, and agent integration patterns.

---

## Repository Structure

```
neo4j-uc-integration/
├── README.md                          # This file
├── METADATA_SYNC_REPORT.md            # Metadata sync prototype report
├── NEO4J_UC_INTEGRATION_REPORT.md     # Full integration proposal for Databricks
├── docs/
│   ├── neo4j_uc_jdbc_guide.md         # Detailed JDBC usage guide
│   ├── metadata_synchronization.md    # Metadata synchronization design
│   ├── federated_agents.md            # Federated agents + Genie integration
│   └── neo4j_jdbc_cleaner.md          # Spark subquery cleaner explanation
├── uc-neo4j-test-suite/               # Databricks notebooks and test suite
│   ├── neo4j_databricks_sql_translation.ipynb  # UC JDBC and SQL translation tests
│   ├── metadata_sync_delta.ipynb               # Metadata sync via Delta tables
│   ├── metadata_sync_external.ipynb            # Metadata sync via External Metadata API
│   ├── federated_lakehouse_query.ipynb         # Federated query patterns
│   └── federated_views_agent_ready.ipynb       # Agent-ready federated views
```

---

## References

- [Neo4j JDBC Driver](https://neo4j.com/docs/jdbc-manual/current/)
- [Neo4j SQL2Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Databricks Unity Catalog JDBC](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Databricks Lakehouse Federation](https://docs.databricks.com/aws/en/query-federation/)
- [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/)
