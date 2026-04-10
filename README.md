# Neo4j + Databricks Lakehouse Federation

**Documentation Site:** [https://neo4j-partners.github.io/neo4j-uc-integration](https://neo4j-partners.github.io/neo4j-uc-integration)

This project shows how to query a Neo4j graph database directly from Databricks using Unity Catalog. You write SQL in Databricks and the Neo4j JDBC driver automatically translates it to Cypher — the graph query language Neo4j uses — so you don't need to learn Cypher to get data out of Neo4j.

The connection works through Unity Catalog's JDBC support, which means your Neo4j access is governed by the same permissions, credentials, and audit controls as the rest of your lakehouse. Once connected, you can join Neo4j graph data (like flights, airports, and relationships between them) with your existing Delta tables in a single query.

The project also demonstrates how to make Neo4j's schema (node labels, relationship types, properties) visible in Databricks Catalog Explorer through metadata synchronization, and how to make Neo4j data queryable in plain English through Databricks AI/BI Genie.

All queries shown in this repo ran on a live Databricks cluster (Runtime 17.3 LTS) connected to Neo4j Aura. The output is real, not mocked.

For a step-by-step setup and usage guide, see [neo4j_uc_jdbc_guide.md](./docs/neo4j_uc_jdbc_guide.md).

---

## Getting Started with the Neo4j Federated JDBC UC Connection

The `getting-started/` directory contains four notebooks that walk through the Neo4j Federated JDBC UC Connection end to end. The notebooks cover loading graph data into Neo4j, establishing the Unity Catalog JDBC connection, running federated queries that join graph topology with Delta time-series data, and materializing Neo4j node labels as managed Delta tables. The dataset is an aircraft digital twin: 20 aircraft, 160 sensors, 800 flights, and 172,800 sensor readings stored across Neo4j and a Delta table.

For prerequisites, cluster configuration, setup steps, and an explanation of each notebook, see [getting-started/README.md](./getting-started/README.md). For the full JDBC setup reference and query patterns, see [docs/neo4j_uc_jdbc_guide.md](./docs/neo4j_uc_jdbc_guide.md).

---

## Overview of Neo4j Integration Patterns

**JDBC Connectivity** — Neo4j connects to Unity Catalog via a generic JDBC connection (`TYPE JDBC`) using the [Neo4j JDBC driver](https://neo4j.com/docs/jdbc-manual/current/) with built-in SQL-to-Cypher translation. A SafeSpark compatibility issue (metaspace memory exhaustion) was resolved in collaboration with Databricks engineering. With three Spark configuration settings, the Neo4j Federated JDBC UC Connection works correctly — including queries, aggregates, GROUP BY, HAVING, ORDER BY, JOINs, and schema discovery.

**Federated Queries** — Once connected, Neo4j graph data (flights, airports, maintenance events, component hierarchies) can be joined with Delta lakehouse tables (sensor readings, time-series analytics) in a single Spark SQL statement. No ETL pipelines required — each database is queried where the data lives, with results combined at read time.

**Metadata Synchronization** — The JDBC connection registers credentials and a driver, but does not expose Neo4j's schema as browsable UC objects. This project prototypes two approaches to metadata sync: materialized Delta tables (full data copy with Catalog Explorer, `INFORMATION_SCHEMA`, and SQL access) and the External Metadata API (metadata-only registration for discoverability and lineage). The graph-to-relational mapping is well-defined: node labels become tables in a `nodes` schema, relationship types become tables in a `relationships` schema, and properties become columns with mapped types.

**Natural Language via Genie** — Neo4j data materialized as managed Delta tables becomes transparently queryable through Databricks AI/BI Genie. Users ask plain-English questions and Genie generates SQL that federates across Neo4j graph data and Delta lakehouse tables, all governed by Unity Catalog.

**Proposal for First-Class Support** — The prototype demonstrates that Neo4j can be elevated from a generic JDBC bring-your-own-driver configuration to a natively supported Lakehouse Federation data source (`TYPE NEO4J`), with automatic metadata sync, table-level governance, and lineage tracking on par with currently supported sources like PostgreSQL, Snowflake, and BigQuery.

---

## What First-Class Lakehouse Federation Support Would Unlock

The integration works today through Unity Catalog's custom JDBC connection. Elevating Neo4j to an officially supported Lakehouse Federation source (`TYPE NEO4J`) would replace the current manual workarounds with native platform capabilities:

- **Foreign catalog** — `CREATE FOREIGN CATALOG neo4j_graph USING CONNECTION neo4j_conn` registers the full Neo4j schema as a browsable three-level namespace in Unity Catalog, making graph data discoverable alongside Delta tables without materialization jobs or External Metadata API workarounds
- **Table-level governance** — UC grants (`SELECT`, `USE SCHEMA`, `BROWSE`) on individual Neo4j-backed tables rather than connection-level-only access control; data tagging and classification per table
- **Column-level lineage and audit** — Every query tracked in `system.access.audit` with full context; column-level lineage for notebooks, jobs, and dashboards
- **Improved query pushdown** — Broader filter, projection, aggregate, and sort pushdown managed by Databricks; potential join pushdown mapping cross-table joins to native graph traversals
- **Genie and AI/BI Dashboards** — Neo4j foreign tables queryable via natural language and drag-and-drop dashboards without materialization as a prerequisite
- **Service principal and OAuth support** — Native credential management rather than user/password stored in connection options

For the full capability breakdown and trade-offs, see [docs/unlock.md](./docs/unlock.md).

---

## Notebooks

All notebooks are in `getting-started/` and should be imported to your Databricks workspace. See [getting-started/README.md](./getting-started/README.md) for prerequisites and setup instructions.

| Notebook | What It Covers |
|----------|---------------|
| `00-load-graph.ipynb` | Loads the aircraft digital twin dataset into Neo4j from CSV files in a UC Volume |
| `01-simple-connect-test.ipynb` | Creates the UC JDBC connection and runs basic SQL queries against Neo4j |
| `02-federated-queries.ipynb` | Federated queries joining Neo4j graph topology with Delta sensor time-series data |
| `03-materialized-tables.ipynb` | Materializes Neo4j node labels as managed Delta tables for unrestricted SQL access |

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

**All supported patterns pass. Use the Neo4j Spark Connector for relationship property aggregation.**

---

## How It Works

### JDBC Driver JAR

A single shaded JAR is uploaded to a Unity Catalog Volume:

| JAR | Purpose |
|-----|---------|
| `neo4j-unity-catalog-connector-<version>.jar` | Neo4j JDBC Lakehouse Federation Connector — bundles the Neo4j JDBC driver, SQL-to-Cypher translator, and Spark subquery cleaner |

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

The Neo4j JDBC driver automatically translates SQL to Cypher when `enableSQLTranslation=true`. For the full translation reference, supported patterns, and examples see [docs/neo4j_uc_jdbc_guide.md](./docs/neo4j_uc_jdbc_guide.md).

---

## Metadata Synchronization

Setting up a JDBC connection lets you query Neo4j from Databricks, but it doesn't make Neo4j's schema visible in Unity Catalog. Metadata synchronization maps Neo4j's graph structure (node labels → tables, relationship types → tables, properties → columns) into Unity Catalog's three-level namespace so it can be browsed, governed, and tracked for lineage.

For design details, type mappings, and implementation, see [docs/metadata_synchronization.md](./docs/metadata_synchronization.md).

---

## Federated Agents and Genie Integration

Neo4j data materialized as Delta tables becomes queryable through Databricks AI/BI Genie without any direct graph database access. Users ask natural language questions and Genie generates SQL that federates across Neo4j graph data and Delta lakehouse tables — all governed by Unity Catalog. The LLM never sees Cypher and the user never writes SQL.

---

## Repository Structure

```
neo4j-uc-integration/
├── README.md
├── docs/
│   ├── neo4j_uc_jdbc_guide.md          # JDBC setup, query patterns, troubleshooting
│   ├── metadata_synchronization.md     # Metadata sync design and implementation
│   └── neo4j_jdbc_cleaner.md           # Spark subquery cleaner explanation
├── getting-started/                    # Intro notebooks (import to Databricks workspace)
│   ├── 00-load-graph.ipynb
│   ├── 01-simple-connect-test.ipynb
│   ├── 02-federated-queries.ipynb
│   └── 03-materialized-tables.ipynb
├── neo4j-uc-federation-lab/            # Full test suite notebooks
├── validate-federation/                # Validation scripts
├── deploy-lakebase/                    # Lakebase deployment scripts
└── site/                              # Antora documentation site
```

---

## References

- [Neo4j JDBC Driver](https://neo4j.com/docs/jdbc-manual/current/)
- [Neo4j SQL2Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Databricks Unity Catalog JDBC](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Databricks Lakehouse Federation](https://docs.databricks.com/aws/en/query-federation/)
- [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/)
- [getting-started/README.md](./getting-started/README.md) — notebook prerequisites and setup
- [docs/neo4j_uc_jdbc_guide.md](./docs/neo4j_uc_jdbc_guide.md) — JDBC setup, query patterns, troubleshooting
