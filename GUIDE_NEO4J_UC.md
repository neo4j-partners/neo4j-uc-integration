# Guide: Using Neo4j with Databricks Unity Catalog JDBC

This guide explains how to connect to Neo4j from Databricks using a Unity Catalog JDBC connection, including required configuration, supported query patterns, and best practices.

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

### 3. Cluster Libraries (for Direct JDBC)

If using Direct JDBC (bypassing UC), install the JDBC JAR as a cluster library.

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

## Supported Query Patterns

These SQL patterns work through Unity Catalog JDBC:

### Simple Expressions
```sql
SELECT 1 AS test
```

### Aggregates (COUNT, MIN, MAX, SUM, AVG)
```sql
SELECT COUNT(*) AS total FROM Flight
```

### Multiple Aggregates
```sql
SELECT COUNT(*) AS total,
       MIN(aircraft_id) AS first_id,
       MAX(aircraft_id) AS last_id
FROM Aircraft
```

### COUNT DISTINCT
```sql
SELECT COUNT(DISTINCT manufacturer) AS unique_manufacturers FROM Aircraft
```

### Aggregates with WHERE
```sql
SELECT COUNT(*) AS boeing_count
FROM Aircraft
WHERE manufacturer = 'Boeing'
```

### Aggregates with JOIN (Graph Traversal)
```sql
SELECT COUNT(*) AS relationship_count
FROM Flight f
NATURAL JOIN DEPARTS_FROM r
NATURAL JOIN Airport a
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

- [Neo4j JDBC Driver Documentation](https://neo4j.com/docs/jdbc-manual/current/)
- [Neo4j SQL2Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/)
- [Databricks Unity Catalog JDBC](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Spark JDBC Data Sources](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html)
