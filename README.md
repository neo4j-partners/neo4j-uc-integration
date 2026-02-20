# Neo4j + Databricks Unity Catalog Integration

**Documentation Site:** [https://neo4j-partners.github.io/neo4j-uc-integration](https://neo4j-partners.github.io/neo4j-uc-integration)

This project is a working prototype and proposal for integrating Neo4j as a federated data source within Databricks Unity Catalog. It demonstrates the full stack: JDBC connectivity with automatic SQL-to-Cypher translation, federated queries joining Neo4j graph data with Delta lakehouse tables, metadata synchronization that maps Neo4j's graph schema into UC's three-level namespace, and natural language query support through Databricks Genie.

All queries shown in this repo ran on a live Databricks cluster (Runtime 17.3 LTS) connected to Neo4j Aura. The output is real, not mocked.

---

## Overview of Neo4j Integration Patterns

**JDBC Connectivity** — Neo4j connects to Unity Catalog via a generic JDBC connection (`TYPE JDBC`) using the [Neo4j JDBC driver](https://neo4j.com/docs/jdbc-manual/current/) with built-in SQL-to-Cypher translation. A SafeSpark compatibility issue (metaspace memory exhaustion) was resolved in collaboration with Databricks engineering. With three Spark configuration settings, UC JDBC connections to Neo4j work correctly — including queries, aggregates, JOINs, and schema discovery.

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
| Neo4j JDBC SQL-to-Cypher | **PASS** | Aggregates, JOINs, dbtable all work |
| Direct JDBC (Non-UC) | **PASS** | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **PASS** | Works with SafeSpark memory configuration |
| **UC Schema Discovery** | **PASS** | Works with SafeSpark memory configuration |

**Test Results: 9/9 supported patterns pass, 3 expected failures documented (100% success rate)**

---

## How It Works

### JDBC Driver JARs

Two JARs are uploaded to a Unity Catalog Volume:

| JAR | Purpose |
|-----|---------|
| `neo4j-jdbc-full-bundle-6.10.3.jar` | JDBC driver with built-in SQL-to-Cypher translation engine |
| `neo4j-jdbc-translator-sparkcleaner-6.10.3.jar` | Preprocesses Spark-generated SQL artifacts before translation |

The spark cleaner handles a Spark-specific behavior: when Spark connects via JDBC, it wraps queries in a subquery for schema probing (`SELECT * FROM (<query>) SPARK_GEN_SUBQ_0 WHERE 1=0`). The cleaner detects this marker, extracts the inner query, and routes it correctly. See [CLEANER.md](./docs/CLEANER.md) for details.

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
  java_dependencies '["path/to/neo4j-jdbc-full-bundle-6.10.3.jar", "path/to/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar"]'
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
| `FROM A NATURAL JOIN REL NATURAL JOIN B` | `MATCH (a:A)-[:REL]->(b:B)` |
| `WHERE prop = 'value'` | `WHERE n.prop = 'value'` |

**Supported through UC JDBC:**
- Aggregate queries (COUNT, MIN, MAX, SUM, AVG)
- COUNT DISTINCT
- Aggregates with WHERE clauses
- Aggregates with NATURAL JOIN (graph traversals)

**Not supported through UC JDBC** (use Neo4j Spark Connector instead):
- Non-aggregate SELECT
- GROUP BY / HAVING
- ORDER BY / LIMIT

Spark wraps JDBC queries in subqueries for schema resolution. Neo4j's SQL translator cannot handle certain constructs inside subqueries. Aggregate queries work because their results don't require this wrapping. See [GUIDE_NEO4J_UC.md](./docs/GUIDE_NEO4J_UC.md) for workarounds.

---

## Metadata Synchronization

The JDBC connection provides query connectivity but does not expose Neo4j's schema as browsable UC objects. Metadata synchronization completes the picture:

| Aspect | JDBC Connection (Current) | With Metadata Sync |
|--------|--------------------------|-------------------|
| What's registered in UC | A `CONNECTION` object only | Catalog + schemas + tables + columns |
| Schema browsing in Catalog Explorer | No | Yes |
| Access control granularity | Connection-level only | Table-level and column-level |
| Lineage tracking | No | Yes |
| Query model | `spark.read.format('jdbc')...` | `SELECT * FROM neo4j_catalog.nodes.aircraft` |

### Graph-to-Relational Mapping

```
Unity Catalog                  Neo4j
─────────────                  ─────
Catalog: neo4j_catalog    →   Neo4j database
  Schema: nodes            →   Node labels namespace
    Table: aircraft        →   :Aircraft label
      Column: aircraft_id  →   aircraft_id property (STRING)
      Column: manufacturer →   manufacturer property (STRING)
  Schema: relationships    →   Relationship types namespace
    Table: departs_from    →   :DEPARTS_FROM type
      Column: source_id    →   Start node identifier
      Column: target_id    →   End node identifier
```

Two approaches are prototyped:

| Approach | How It Works | Trade-offs |
|----------|-------------|------------|
| **Materialized Delta Tables** | Reads Neo4j via Spark Connector, writes as managed Delta tables | Full UC integration (Catalog Explorer, INFORMATION_SCHEMA, SQL). Requires scheduled refresh. |
| **External Metadata API** | Registers Neo4j schema as external metadata objects via REST API | No data copied — metadata-only for discoverability and lineage. No direct SQL query support. |

See [METADATA.md](./docs/METADATA.md) for the full design and [METADATA_SYNC_REPORT.md](./METADATA_SYNC_REPORT.md) for prototype results.

---

## Federated Agents and Genie Integration

Neo4j data materialized as Delta tables becomes queryable through Databricks AI/BI Genie without any direct graph database access. Users ask natural language questions and Genie generates SQL that federates across Neo4j graph data and Delta lakehouse tables — all governed by Unity Catalog. The LLM never sees Cypher and the user never writes SQL.

This supports several agent integration patterns: Genie as a standalone NL-to-SQL agent, multi-agent setups pairing Genie with a DBSQL MCP server, and Agent Bricks supervisors coordinating Genie with other agents (e.g., RAG over maintenance manuals).

See [FEDERATED_AGENTS.md](./docs/FEDERATED_AGENTS.md) for the full architecture, Genie space setup instructions, example questions, and agent integration patterns.

---

## Repository Structure

```
neo4j-uc-integration/
├── README.md                          # This file
├── METADATA_SYNC_REPORT.md            # Metadata sync prototype report
├── NEO4J_UC_INTEGRATION_REPORT.md     # Full integration proposal for Databricks
├── docs/
│   ├── GUIDE_NEO4J_UC.md              # Detailed JDBC usage guide
│   ├── METADATA.md                    # Metadata synchronization design
│   ├── FEDERATED_AGENTS.md            # Federated agents + Genie integration
│   └── CLEANER.md                     # Spark subquery cleaner explanation
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
