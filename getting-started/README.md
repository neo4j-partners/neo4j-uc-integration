# Getting Started: Neo4j + Databricks Unity Catalog Federation

A graph database stores which companies compete with each other and what products they offer. A lakehouse stores how many shares institutional investors hold in those companies and what financial metrics their 10-K filings report. A risk analyst needs both in the same query: traverse competitive relationships in the graph, then join the result with ownership data in Delta tables. Neither system can answer that question alone.

These three notebooks walk through the integration pattern that connects Neo4j to Databricks through Unity Catalog's JDBC support. The connector translates SQL to Cypher automatically, so Spark treats Neo4j labels like tables. The progression moves from validating that the connection works, to running federated queries across both systems, to materializing graph data as Delta tables where standard SQL and Genie can reach it.

## Architecture

```
                        ┌─────────────────────────┐
                        │   Spark SQL / Genie      │
                        └────────┬────────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 │               │               │
                 ▼               ▼               ▼
          ┌────────────┐  ┌───────────┐  ┌─────────────────┐
          │ Delta      │  │ UC JDBC   │  │ Materialized    │
          │ Tables     │  │ Connection│  │ Delta Tables    │
          │            │  │           │  │ (from Neo4j)    │
          │ financials │  │ SQL→Cypher│  │                 │
          │ holdings   │  │ translation│ │ products        │
          │ asset mgrs │  │           │  │ competitors     │
          └────────────┘  └─────┬─────┘  │ risk factors    │
                                │        └────────┬────────┘
                                │                 │
                                ▼          periodic refresh
                        ┌──────────────┐          │
                        │  Neo4j Aura  │◄─────────┘
                        │              │
                        │  Company     │
                        │  Product     │
                        │  RiskFactor  │
                        │  OFFERS      │
                        │  COMPETES_WITH│
                        │  HAS_RISK    │
                        └──────────────┘
```

Three paths to the same graph data, each with different tradeoffs. The UC JDBC connection gives real-time access but limits SQL operations to what the connector can translate. Materialized Delta tables support full SQL and Genie but require periodic refresh. The notebooks demonstrate both approaches so you can choose based on your query patterns.

## Data Model

The dataset is a small slice of SEC 10-K filing data for six public companies: Amazon, Apple, Microsoft, NVIDIA, PG&E, and PayPal.

**Neo4j (graph-native data)**
- 6 Company nodes with `companyId`, `name`, `ticker`
- 30 Product nodes (5 per company) linked by `OFFERS` relationships
- 78 `COMPETES_WITH` relationships, including external competitors
- 48 RiskFactor nodes (8 per company) linked by `HAS_RISK` relationships

**Databricks Delta (tabular data)**
- `companies` (6 rows) serving as the bridge table between systems
- `financial_metrics` (90 rows) with metric name, value, and period
- `asset_managers` (15 rows) covering major institutional investors
- `asset_manager_holdings` (72 rows) with share counts per company

The company `companyId` is the join key across both systems. Graph data captures qualitative structure (who competes with whom, what products a company offers, what risks they face). Tabular data captures quantitative measures (financial metrics, share counts). Federated queries combine both.

## Notebooks

### 01 — Simple Connect Test

Validates connectivity at each layer before attempting anything complex. Runs in sequence: TCP socket check on port 7687, Neo4j Python driver authentication, sample graph data creation, Unity Catalog JDBC connection setup, and SQL queries through the connector.

Creates a small test graph (4 companies, 8 products, `OFFERS` and `COMPETES_WITH` relationships) using the same domain as the later notebooks. The UC JDBC connection created here is reused by notebooks 02 and 03.

### 02 — Federated Queries

Loads the full dataset into both systems and runs queries that span them. Delta tables are created from CSV files following the Databricks `read_files()` pattern. Graph data is loaded into Neo4j via the Python driver.

The federated queries read from Neo4j through the UC JDBC connection (returning Spark DataFrames) and join the results with Delta tables in Spark. Three query patterns demonstrate the approach: company products from the graph joined with financial metric counts from Delta, NVIDIA's competitors from a graph traversal joined with asset manager holdings, and risk factor counts from the graph alongside financial summaries.

### 03 — Materialized Tables

Reads graph data from Neo4j and writes it as managed Delta tables in Unity Catalog. Once materialized, the data supports full SQL: GROUP BY, ORDER BY, WHERE filters, aggregations, DISTINCT, and multi-table JOINs all work without JDBC at query time.

Node labels (Company, Product, RiskFactor) are materialized via the JDBC `dbtable` option with `customSchema` to handle Neo4j's NullType inference behavior. Relationship data (OFFERS, COMPETES_WITH, HAS_RISK) is read through the Python driver, converted to Spark DataFrames, and written as Delta mapping tables. Four federated queries then join the materialized Neo4j tables with the original Delta tables using pure SQL, producing the kind of results a Genie agent could answer from natural language.

## Setup

### Prerequisites

#### 1. Databricks Preview Features

Enable these preview features in your Databricks workspace:

| Feature | Required For |
|---------|--------------|
| Custom JDBC on UC Compute | Loading custom JDBC drivers in UC connections |
| remote_query table-valued function | Using `remote_query()` SQL function |

#### 2. Neo4j Unity Catalog Connector JAR

Download the latest release from [neo4j-unity-catalog-connector releases](https://github.com/neo4j-labs/neo4j-unity-catalog-connector/tags) and upload it to a Unity Catalog Volume.

The JAR is a shaded bundle containing the JDBC driver, SQL-to-Cypher translator, and Spark subquery cleaner. See the [neo4j-unity-catalog-connector](https://github.com/neo4j-labs/neo4j-unity-catalog-connector) repo for details on what it contains and how it is built.

The `java_dependencies` option in `CREATE CONNECTION TYPE JDBC` only accepts Unity Catalog Volume paths (e.g., `/Volumes/catalog/schema/jars/neo4j-unity-catalog-connector.jar`). Cluster-installed libraries (Maven coordinates, uploaded JARs) cannot be referenced here. The JAR must be in a UC Volume.

#### 3. Neo4j Aura Instance

A Neo4j Aura instance with Bolt connectivity on port 7687. The notebooks use the `neo4j+s://` URI scheme (Bolt over TLS), which is the default for Aura.

#### 4. Cluster Libraries

Install the Neo4j Python driver on your cluster:

| Library | Version | Purpose |
|---------|---------|---------|
| neo4j (Python) | 6.0+ | Neo4j Python Driver for direct Cypher queries |

For UC JDBC connections, cluster libraries are not used for the Java side. The `java_dependencies` option in `CREATE CONNECTION` references the JAR in a UC Volume. The Python driver is only needed for notebooks that write data to Neo4j (01 and 02) and for materializing relationship data (03).

### Required Spark Configuration

Add these settings to your Databricks cluster configuration to prevent SafeSpark sandbox memory exhaustion:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

Without these settings, UC JDBC connections to Neo4j will fail with: `Connection was closed before the operation completed`

The Neo4j JDBC driver requires more memory for class loading than the default SafeSpark sandbox allocation. When metaspace is exhausted, the sandbox JVM crashes silently and the connection drops. These three settings increase the metaspace limit, heap size, and overall sandbox size to accommodate the driver's initialization.

For the full reference on connection setup, query patterns, and troubleshooting, see [docs/neo4j_uc_jdbc_guide.md](../docs/neo4j_uc_jdbc_guide.md).

## Getting Started

1. Update the configuration cell in `01-simple-connect-test.ipynb` with your Neo4j URI, credentials, JAR path, and UC connection name.
2. Run notebook 01 end-to-end. All five sections should report PASS.
3. Copy the same configuration into notebook 02, adding your UC catalog and schema. Run end-to-end.
4. Copy configuration into notebook 03 and run. The materialized tables will appear in Catalog Explorer.

The configuration values are intentionally repeated in each notebook rather than shared through a setup script, keeping each notebook self-contained and runnable independently after the initial connection is established.

## Tradeoffs

**Real-time JDBC vs. materialized tables.** The UC JDBC connection in notebook 02 queries Neo4j on every read, so results reflect the current graph state. But SQL operations are limited to what the connector's SQL-to-Cypher translator supports (aggregates, WHERE, GROUP BY, ORDER BY, LIMIT, JOINs mapped to graph traversals). Materialized tables in notebook 03 support unrestricted SQL but show a snapshot that must be refreshed.

**`dbtable` vs. `query` for JDBC reads.** The `dbtable` option avoids Spark's subquery wrapping during schema inference, which the Neo4j JDBC driver handles more reliably. The `query` option provides more flexibility (custom projections, filters) but requires `customSchema` and depends on the SparkSubqueryCleaningTranslator to strip Spark's generated wrapper. The notebooks use `dbtable` for simple node reads and the Python driver for relationship traversals.

**Data volume.** This dataset is deliberately small (under 300 rows per table) for quick iteration. The same patterns apply to larger graphs, though materialization becomes more important as query latency matters and the graph grows beyond what real-time JDBC translation handles comfortably.
