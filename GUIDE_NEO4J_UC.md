# Guide: Using Neo4j with Databricks Unity Catalog JDBC

This guide explains how to connect to Neo4j from Databricks using a Unity Catalog JDBC connection, including required configuration, supported query patterns, and best practices.

---

## Overview

This integration was validated by working with Databricks engineering to resolve a SafeSpark compatibility issue. The root cause was **metaspace memory exhaustion** in the SafeSpark sandbox during Neo4j JDBC driver initialization. With the correct Spark configuration, Unity Catalog JDBC connections to Neo4j work correctly.

### Component Test Results

| Component | Status | Notes |
|-----------|--------|-------|
| Network Connectivity | **PASS** | TCP to Neo4j port 7687 |
| Neo4j Python Driver | **PASS** | Bolt protocol works |
| Neo4j Spark Connector | **PASS** | `org.neo4j.spark.DataSource` works |
| Neo4j JDBC SQL-to-Cypher | **PASS** | Aggregates, JOINs, dbtable all work |
| Direct JDBC (Non-UC) | **PASS** | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **PASS** | Works with SafeSpark memory configuration |
| **UC Schema Discovery** | **PASS** | Works with SafeSpark memory configuration |

---

## Prerequisites

### 1. Databricks Preview Features

Enable these preview features in your Databricks workspace:

| Feature | Required For |
|---------|--------------|
| Custom JDBC on UC Compute | Loading custom JDBC drivers in UC connections |
| remote_query table-valued function | Using `remote_query()` SQL function |

### 2. Neo4j JDBC Driver JARs

Upload these JARs to a Unity Catalog Volume:

| JAR | Purpose |
|-----|---------|
| `neo4j-jdbc-full-bundle-6.x.x.jar` | Main JDBC driver with SQL-to-Cypher translation |
| `neo4j-jdbc-translator-sparkcleaner-6.x.x.jar` | Cleans Spark-generated SQL artifacts |

Example path: `/Volumes/catalog/schema/jars/`

### 3. Cluster Libraries

For comprehensive testing, install these libraries on your cluster:

| Library | Version | Purpose |
|---------|---------|---------|
| org.neo4j:neo4j-connector-apache-spark | 5.3.10 (Spark 3) | Neo4j Spark Connector |
| neo4j (Python) | 6.0.2 | Neo4j Python Driver |
| neo4j-jdbc-full-bundle | 6.10.3 | JDBC driver (cluster library for Direct JDBC) |

For UC JDBC only, the cluster libraries are optional—the JARs are loaded from the UC Volume.

---

## Required Spark Configuration

**Critical:** Add these settings to your Databricks cluster to prevent SafeSpark sandbox memory exhaustion:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

Without these settings, you'll see: `Connection was closed before the operation completed`

**Why this is needed:** The Neo4j JDBC driver requires more memory for class loading than the default SafeSpark sandbox allocation. When metaspace is exhausted, the sandbox JVM crashes.

---

## Creating the Unity Catalog Connection

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
)
```

**Key options:**
- `enableSQLTranslation=true` - Enables automatic SQL-to-Cypher translation
- `externalOptionsAllowList` - Allows passing `customSchema` at query time

---

## Querying Neo4j through UC

### Method 1: Spark DataFrame API

```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \
    .load()

df.show()
```

### Method 2: remote_query() Function

```sql
SELECT * FROM remote_query(
    'neo4j_connection',
    query => 'SELECT COUNT(*) AS cnt FROM Flight'
)
```

**Note:** Always use `customSchema` with the DataFrame API. Neo4j JDBC returns `NullType()` during Spark's schema inference, causing errors.

---

## Validated Test Results

The following results are from testing against a Neo4j Aura instance:

| Test | Status | Result |
|------|--------|--------|
| Basic Query (`SELECT 1`) | **PASS** | 1 |
| COUNT Aggregate | **PASS** | 2,400 flights |
| Multiple Aggregates (COUNT, MIN, MAX) | **PASS** | 60 total, AC1001-AC1020 |
| COUNT DISTINCT | **PASS** | 3 unique manufacturers |
| Aggregate with WHERE (equals) | **PASS** | 15 Boeing aircraft |
| Aggregate with WHERE (IN clause) | **PASS** | 45 Boeing+Airbus aircraft |
| Aggregate with WHERE (AND) | **PASS** | 15 Boeing with model |
| Aggregate with WHERE (IS NOT NULL) | **PASS** | 60 aircraft with icao24 |
| JOIN with Aggregate (2-hop) | **PASS** | 11,200 relationships |
| GROUP BY | **EXPECTED FAIL** | Subquery limitation |
| Non-aggregate SELECT | **EXPECTED FAIL** | Subquery limitation |
| ORDER BY | **EXPECTED FAIL** | Subquery limitation |

**Success Rate: 100%** (9/9 supported patterns passed, 3 expected failures documented)

---

## Supported Query Patterns

These SQL patterns have been validated to work through Unity Catalog JDBC:

### Simple Expressions
```sql
SELECT 1 AS test
-- Result: 1
```

### Aggregates (COUNT, MIN, MAX, SUM, AVG)
```sql
SELECT COUNT(*) AS total FROM Flight
-- Result: 2,400
```

### Multiple Aggregates
```sql
SELECT COUNT(*) AS total,
       MIN(aircraft_id) AS first_id,
       MAX(aircraft_id) AS last_id
FROM Aircraft
-- Result: {total: 60, first_id: 'AC1001', last_id: 'AC1020'}
```

### COUNT DISTINCT
```sql
SELECT COUNT(DISTINCT manufacturer) AS unique_manufacturers FROM Aircraft
-- Result: 3
```

### Aggregates with WHERE (Multiple Patterns)
```sql
-- Equals
SELECT COUNT(*) AS boeing_count
FROM Aircraft
WHERE manufacturer = 'Boeing'
-- Result: 15

-- IN clause
SELECT COUNT(*) AS cnt
FROM Aircraft
WHERE manufacturer IN ('Boeing', 'Airbus')
-- Result: 45

-- AND with IS NOT NULL
SELECT COUNT(*) AS cnt
FROM Aircraft
WHERE manufacturer = 'Boeing' AND model IS NOT NULL
-- Result: 15

-- IS NOT NULL
SELECT COUNT(*) AS cnt
FROM Aircraft
WHERE icao24 IS NOT NULL
-- Result: 60
```

### Aggregates with JOIN (Graph Traversal)
```sql
SELECT COUNT(*) AS relationship_count
FROM Flight f
NATURAL JOIN DEPARTS_FROM r
NATURAL JOIN Airport a
-- Result: 11,200
```

This translates to Cypher: `MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*)`

---

## Unsupported Query Patterns

These patterns **do not work** through UC because Spark wraps queries in subqueries for schema resolution, and Neo4j's SQL translator cannot handle certain constructs inside subqueries.

| Pattern | Why It Fails |
|---------|--------------|
| `SELECT col1, col2 FROM Label` | Non-aggregate SELECT fails in subquery |
| `GROUP BY` | GROUP BY inside subquery is invalid |
| `HAVING` | HAVING inside subquery is invalid |
| `ORDER BY` | ORDER BY inside subquery is invalid |
| `LIMIT` | LIMIT inside subquery is invalid |

### Workarounds

**For GROUP BY / HAVING:** Use Direct JDBC (bypassing UC) or the Neo4j Spark Connector.

**For ORDER BY / LIMIT:** Apply sorting and limiting in Spark after the query:
```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \
    .load()

# Apply sorting and limiting in Spark
df.orderBy("cnt", ascending=False).limit(10).show()
```

**For non-aggregate queries:** Use the Neo4j Spark Connector:
```python
df = spark.read.format("org.neo4j.spark.DataSource") \
    .option("url", "neo4j+s://your-host") \
    .option("authentication.type", "basic") \
    .option("authentication.basic.username", user) \
    .option("authentication.basic.password", password) \
    .option("query", "MATCH (a:Aircraft) RETURN a.aircraft_id, a.manufacturer LIMIT 10") \
    .load()
```

---

## SQL-to-Cypher Translation Reference

The Neo4j JDBC driver automatically translates SQL to Cypher when `enableSQLTranslation=true`:

| SQL | Cypher |
|-----|--------|
| `SELECT COUNT(*) FROM Flight` | `MATCH (n:Flight) RETURN count(n)` |
| `SELECT * FROM Aircraft LIMIT 5` | `MATCH (n:Aircraft) RETURN n LIMIT 5` |
| `FROM A NATURAL JOIN REL NATURAL JOIN B` | `MATCH (a:A)-[:REL]->(b:B)` |
| `WHERE prop = 'value'` | `WHERE n.prop = 'value'` |

See [Neo4j JDBC SQL2Cypher docs](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) for complete translation rules.

---

## Best Practices

### 1. Always Use customSchema

```python
# Good
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \  # Required!
    .load()

# Bad - will fail with NullType errors
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .load()
```

### 2. Use Aggregates for UC JDBC

UC JDBC works best for aggregate queries (analytics, counts, summaries). For row-level data access, use the Neo4j Spark Connector.

### 3. Use NATURAL JOIN for Relationships

```sql
-- Query relationships between nodes
SELECT COUNT(*) AS cnt
FROM Flight f
NATURAL JOIN DEPARTS_FROM r
NATURAL JOIN Airport a
```

The relationship type becomes the "table" name in the JOIN.

### 4. Store Credentials in Secrets

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
OPTIONS (
  user secret('neo4j-scope', 'username'),
  password secret('neo4j-scope', 'password'),
  ...
)
```

### 5. Create a Helper Function for Tests

```python
def query_neo4j(sql_query, schema):
    """Execute a SQL query against Neo4j via UC JDBC."""
    return spark.read.format("jdbc") \
        .option("databricks.connection", "neo4j_connection") \
        .option("query", sql_query) \
        .option("customSchema", schema) \
        .load()

# Usage
df = query_neo4j(
    "SELECT COUNT(*) AS cnt FROM Flight",
    "cnt LONG"
)
```

---

## Choosing the Right Integration Method

| Use Case | Recommended Method |
|----------|-------------------|
| Aggregate analytics (COUNT, SUM, etc.) | UC JDBC Connection |
| Graph traversal counts | UC JDBC with NATURAL JOIN |
| Row-level data access | Neo4j Spark Connector |
| Complex Cypher queries | Neo4j Spark Connector |
| GROUP BY analytics | Direct JDBC or Spark Connector |
| Ad-hoc exploration | Neo4j Python Driver |

---

## Troubleshooting

### "Connection was closed before the operation completed"

**Cause:** SafeSpark sandbox ran out of memory.

**Fix:** Add these Spark settings to your cluster:
```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

### "syntax error or access rule violation - invalid syntax"

**Cause:** Query pattern not supported through UC (GROUP BY, ORDER BY, LIMIT, or non-aggregate SELECT).

**Fix:** Use Direct JDBC or Neo4j Spark Connector for unsupported patterns.

### "No column has been read prior to this call" / NullType errors

**Cause:** Missing `customSchema` option.

**Fix:** Always specify `customSchema` with explicit column types.

---

## References

### Documentation
- [Neo4j JDBC Driver Documentation](https://neo4j.com/docs/jdbc-manual/current/)
- [Neo4j SQL2Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/)
- [Databricks Unity Catalog JDBC](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Spark JDBC Data Sources](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html)

### Notebooks

| File | Description |
|------|-------------|
| `uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb` | UC JDBC connection and SQL-to-Cypher translation tests |
| `uc-neo4j-test-suite/metadata_sync_delta.ipynb` | Metadata sync via materialized Delta tables |
| `uc-neo4j-test-suite/metadata_sync_external.ipynb` | Metadata sync via External Metadata API |
| `uc-neo4j-test-suite/federated_lakehouse_query.ipynb` | Federated query testing |
| `uc-neo4j-test-suite/federated_views_agent_ready.ipynb` | Agent-ready federated views |

### Additional Examples

| Directory | Description |
|-----------|-------------|
| `pyspark-translation-example/` | Local PySpark tests for SQL-to-Cypher translation |
| `sample-sql-translation/` | Spring Boot app for JDBC connectivity testing |
