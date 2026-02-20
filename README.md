# Neo4j Unity Catalog JDBC Integration

**Documentation Site:** [https://neo4j-partners.github.io/neo4j-uc-integration](https://neo4j-partners.github.io/neo4j-uc-integration)

This project demonstrates and validates using Neo4j as a federated data source within Databricks Unity Catalog using the Neo4j JDBC driver.

**Status: Fully Working** - All integration issues have been resolved. The root cause was metaspace memory exhaustion in the Databricks SafeSpark sandbox during Neo4j JDBC driver initialization. With the correct Spark configuration, Unity Catalog JDBC connections to Neo4j work correctly — including queries, aggregates, JOINs, and schema discovery. See the full validated test results below.

For detailed usage instructions, supported query patterns, and troubleshooting, see **[GUIDE_NEO4J_UC.md](./GUIDE_NEO4J_UC.md)**.

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

## What This Enables

- Query Neo4j graph data from Databricks using SQL
- Unity Catalog governance at the connection level
- Join Neo4j results with other Databricks data sources
- Automatic SQL-to-Cypher translation via the Neo4j JDBC driver

---

## Quick Start

### 1. Enable Preview Features

In your Databricks workspace, enable these preview features:

| Feature | Required For |
|---------|--------------|
| Custom JDBC on UC Compute | Loading custom JDBC drivers in UC connections |
| remote_query table-valued function | Using `remote_query()` SQL function |

### 2. Upload JDBC JARs

Download and upload to a Unity Catalog Volume:

- [neo4j-jdbc-full-bundle-6.10.3.jar](https://github.com/neo4j/neo4j-jdbc/releases/download/6.10.3/neo4j-jdbc-full-bundle-6.10.3.jar)
- [neo4j-jdbc-translator-sparkcleaner-6.10.3.jar](https://repo.maven.apache.org/maven2/org/neo4j/neo4j-jdbc-translator-sparkcleaner/6.10.3/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar)

### 3. Configure Cluster

Add these Spark configuration settings to prevent SafeSpark memory exhaustion:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

### 4. Create Connection

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

### 5. Query Neo4j

```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \
    .load()
df.show()
```

---

## Repository Structure

```
neo4j-uc-integration/
├── GUIDE_NEO4J_UC.md              # Detailed usage guide
├── uc-neo4j-test-suite/           # Databricks notebooks and test suite
│   ├── full_uc_tests.py           # Standalone Python test suite
│   ├── neo4j_databricks_sql_translation.ipynb  # Full test notebook
│   └── neo4j_schema_test.ipynb    # Schema testing notebook
├── pyspark-translation-example/   # Local PySpark SQL translation tests
├── sample-sql-translation/        # Spring Boot JDBC connectivity demo
├── java-metadata-demo/            # Java JDBC metadata exploration
└── neo4j_jdbc_spark_cleaning/     # Spark cleaner translator info
```

---

## Running the Examples

### Databricks Notebooks

Import notebooks from `uc-neo4j-test-suite/` to your Databricks workspace:

1. **neo4j_databricks_sql_translation.ipynb** - Full test suite covering network, drivers, direct JDBC, and UC JDBC
2. **neo4j_schema_test.ipynb** - Focused schema testing

Or run the standalone test suite:

```python
# In a Databricks notebook
%run ./full_uc_tests
```

### Local PySpark Tests

```bash
cd pyspark-translation-example
uv sync
uv run test-sql
```

### Spring Boot Demo

```bash
cd sample-sql-translation
./mvnw spring-boot:run
```

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

See [GUIDE_NEO4J_UC.md](./GUIDE_NEO4J_UC.md) for complete details.

---

## Technical Background

### The SafeSpark Fix

This integration was validated by working with Databricks engineering to resolve a SafeSpark compatibility issue. Databricks runs custom JDBC drivers in an isolated SafeSpark sandbox for security. The Neo4j JDBC driver requires more metaspace for class loading than the default sandbox allocation. Without the memory configuration, the sandbox JVM crashes with "Connection was closed before the operation completed" errors. Adding three Spark configuration settings resolves this completely.

### Why Aggregate Queries Only Through UC?

Spark wraps JDBC queries in subqueries for schema resolution (`SELECT * FROM (query) WHERE 1=0`). Neo4j's SQL translator cannot handle certain constructs inside subqueries (GROUP BY, ORDER BY, LIMIT, non-aggregate SELECT). Aggregate queries work because their results don't require this wrapping. For unsupported patterns, use the Neo4j Spark Connector or Direct JDBC — see [GUIDE_NEO4J_UC.md](./GUIDE_NEO4J_UC.md) for workarounds.

---

## References

- [Neo4j JDBC Driver](https://neo4j.com/docs/jdbc-manual/current/)
- [Neo4j SQL2Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Databricks Unity Catalog JDBC](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/)
