# Neo4j Databricks JDBC Federation - Testing Status

**Last Updated**: 2026-01-04
**Databricks Runtime**: 17.3 LTS
**Neo4j Instance**: Aura (3f1f827a.databases.neo4j.io)

---

## Executive Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Network Connectivity | PASS | TCP to Neo4j port 7687 |
| Neo4j Python Driver | PASS | Bolt protocol works |
| Neo4j Spark Connector | PASS | `org.neo4j.spark.DataSource` works |
| **Neo4j JDBC SQL-to-Cypher** | **PASS** | **Tested & verified** - aggregates, JOINs, dbtable |
| Direct JDBC (Non-UC) | PASS | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **FAIL** | **SafeSpark incompatibility** |

### Core Issue: SafeSpark Incompatibility

**The Neo4j JDBC driver is fully functional** - it works with:
- Direct Spark JDBC (bypassing Unity Catalog)
- SQL-to-Cypher translation
- All query patterns (dbtable, aggregates, JOINs)

**The failure is isolated to Databricks SafeSpark**, the isolation layer Unity Catalog uses for custom JDBC drivers. When queries are routed through a UC Connection, SafeSpark:
1. Runs the JDBC driver in a separate sandboxed process
2. Communicates via gRPC
3. **Fails during metadata/schema resolution** before any query executes

**Attempted Fixes That Did Not Resolve SafeSpark Issue:**
- Adding `customSchema` to bypass Spark schema inference
- Adding `customSchema` to `externalOptionsAllowList` in connection definition
- Using `FORCE_CYPHER` hint for native Cypher queries

The SafeSpark wrapper still attempts schema resolution via subquery wrapping (`SELECT * FROM (query) WHERE 1=0`) which fails regardless of `customSchema` settings.

**Conclusion:** This appears to be a compatibility issue between the Neo4j JDBC driver and Databricks SafeSpark that requires Databricks engineering support to resolve.

---

## Environment Setup

### Preview Features
| Feature | Status |
|---------|--------|
| Custom JDBC on UC Compute | Enabled |
| remote_query table-valued function | Enabled |

### Cluster Libraries Installed
| Library | Version | Status |
|---------|---------|--------|
| org.neo4j:neo4j-connector-apache-spark | 5.3.10 (Spark 3) | Installed |
| neo4j (Python driver) | 6.0.2 | Installed |
| neo4j-jdbc-full-bundle | 6.x | Installed (Cluster & UC Volume) |

### Unity Catalog Resources
| Resource | Path/Name | Status |
|----------|-----------|--------|
| JDBC Driver JAR | `/Volumes/uc-w-neo4j/jdbc_drivers/jars/neo4j-jdbc-full-bundle.jar` | Uploaded |
| Connection | `neo4j_connection` | Created |

---

## Test Results

### 1. Network Connectivity (TCP Layer)
**Status**: PASS

```sql
SELECT connectionTest('3f1f827a.databases.neo4j.io', '7687')
```
**Result**: `SUCCESS` - TCP connectivity to port 7687 is open.

### 2. Neo4j Python Driver Connectivity
**Status**: PASS

**Result**: Driver connects successfully, queries execute. Verifies credentials and general Neo4j availability.

### 3. Neo4j Spark Connector (Baseline)
**Status**: PASS

**Result**: `org.neo4j.spark.DataSource` works correctly.
```python
df = spark.read.format("org.neo4j.spark.DataSource")...
```
This confirms that the Spark cluster *can* talk to Neo4j and exchange data, ruling out fundamental Spark-Neo4j incompatibility.

### 4. Direct JDBC Connectivity (Bypassing Unity Catalog)
**Status**: PASS (with workarounds)

Tests running the JDBC driver directly in Spark (bypassing the SafeSpark wrapper used by Unity Catalog).

- **dbtable (Label Read)**: PASS
    - *Note*: Requires `customSchema` option because Spark schema inference returns NullType for Neo4j JDBC columns.
- **query (SQL Translation)**: PASS
    - *Note*: Works with `customSchema`. Translates SQL `SELECT 1` to Cypher.
- **SQL Aggregates**: PASS
    - `SELECT COUNT(*) FROM Flight` translates correctly to Cypher `count()`.
- **SQL JOINs**: PASS
    - `NATURAL JOIN` translates correctly to Cypher relationship patterns.

**Key Finding**: The Neo4j JDBC driver is fully functional within the Spark environment when used directly.

#### SQL-to-Cypher Translation Examples (Verified Working)

The Neo4j JDBC driver with `enableSQLTranslation=true` successfully translates SQL to Cypher:

| SQL Query | Cypher Translation | Result |
|-----------|-------------------|--------|
| `SELECT COUNT(*) FROM Flight` | `MATCH (n:Flight) RETURN count(*)` | PASS |
| `SELECT * FROM Aircraft LIMIT 5` | `MATCH (n:Aircraft) RETURN n LIMIT 5` | PASS |
| `SELECT COUNT(*) FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a` | `MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*)` | PASS |
| `SELECT MAX(flight_number) FROM Flight` | `MATCH (n:Flight) RETURN max(n.flight_number)` | PASS |

**Code Example:**
```python
df = spark.read.format("jdbc") \
    .option("url", "jdbc:neo4j+s://host:7687/db?enableSQLTranslation=true") \
    .option("driver", "org.neo4j.jdbc.Neo4jDriver") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a") \
    .option("customSchema", "cnt LONG") \
    .load()
```

**Projects demonstrating SQL translation:**
- [`pyspark-translation-example/`](./pyspark-translation-example/) - Local PySpark test suite
- [`sample-sql-translation/`](./sample-sql-translation/) - Spring Boot connectivity test
- [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) - Full Databricks notebook (Sections 1-8)
- [`neo4j_schema_test.ipynb`](uc-neo4j-test-suite/neo4j_schema_test.ipynb) - Schema testing notebook (Sections 1, 3, 8)

See [Neo4j JDBC SQL2Cypher docs](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) for full translation rules.

### 5. Unity Catalog Connection Creation
**Status**: PASS

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC ...
```
**Result**: Connection created successfully. `DESCRIBE CONNECTION` shows correct configuration.

### 6. Unity Catalog JDBC Read (SafeSpark Wrapper)
**Status**: FAIL - Connection Closed

Attempts to use the connection created in Step 5 (which uses Databricks "SafeSpark" isolation).

**Test 1: Spark DataFrame**
```python
df = spark.read.format("jdbc").option("databricks.connection", "neo4j_connection")...
```

**Test 2: remote_query()**
```sql
SELECT * FROM remote_query('neo4j_connection', query => 'SELECT 1')
```

**Error (Both Tests)**:
```
java.lang.RuntimeException: Connection was closed before the operation completed.
    at com.databricks.safespark.jdbc.grpc_client.JdbcConnectClient.awaitWhileConnected(JdbcConnectClient.scala:96)
    at com.databricks.safespark.jdbc.grpc_client.JdbcGetRowsClient.fetchMetadata(JdbcGetRowsClient.scala:102)
```

**Observation**: The error originates entirely within the Databricks SafeSpark JDBC gRPC client. Since Direct JDBC (Step 4) works, the issue is specific to how SafeSpark wraps or interacts with the Neo4j JDBC driver.

---

## Error Analysis

### Isolation to SafeSpark

We have confirmed:
1.  **Network is fine** (TCP test passed).
2.  **Credentials are fine** (Python driver passed).
3.  **Spark <-> Neo4j is fine** (Spark Connector passed).
4.  **JDBC Driver <-> Spark is fine** (Direct JDBC tests passed).

The failure only occurs when invoking the **Unity Catalog Connection**, which employs the **SafeSpark** architecture (running the JDBC driver in a separate, isolated process communicating via gRPC).

### Potential Causes
1.  **SafeSpark Protocol Incompatibility**: The Neo4j JDBC driver might be doing something (e.g., in its metadata retrieval or connection handshake) that the SafeSpark gRPC wrapper doesn't handle or expects differently.
2.  **Timeout/Race Condition**: The "Connection was closed before the operation completed" suggests the isolated process might be crashing or timing out during initialization.
3.  **Missing Dependencies in Sandbox**: The SafeSpark sandbox might lack access to something the driver needs, though the JAR is provided.

---

## Known Issues & Fixes

### Issue 1: "No column has been read prior to this call" Error

**Error Message**:
```
org.neo4j.jdbc.Neo4jException: general processing exception - No column has been read prior to this call
```

**Root Cause**: When using Spark's `dbtable` or `query` options with Neo4j JDBC:
1. Spark performs schema inference by querying JDBC metadata
2. Neo4j JDBC returns `NullType()` for all columns
3. When Spark reads data with `NullType()`, the JDBC `wasNull()` method is called before any column getter - violating JDBC spec

**Evidence**:
```
Schema: StructType([StructField('v$id', NullType(), True), StructField('aircraft_id', NullType(), True), ...])
```

**Fix**: Use `customSchema` option to explicitly specify column types, bypassing schema inference:
```python
df = spark.read.format("jdbc") \
    .option("url", NEO4J_JDBC_URL_SQL) \
    .option("driver", "org.neo4j.jdbc.Neo4jDriver") \
    .option("user", NEO4J_USER) \
    .option("password", NEO4J_PASSWORD) \
    .option("dbtable", "Aircraft") \
    .option("customSchema", "`v$id` STRING, aircraft_id STRING, tail_number STRING") \
    .load()
```

### Issue 2: Special Characters in Column Names (Parse Error)

**Error Message**:
```
[PARSE_SYNTAX_ERROR] Syntax error at or near '. SQLSTATE: 42601 (line 1, pos 1)
== SQL ==
v$id STRING, aircraft_id STRING...
-^^^
```

**Root Cause**: Column names containing special characters (like `$` in `v$id`) cause Spark SQL parsing errors.

**Fix**: Escape column names with backticks in `customSchema`:
```python
# WRONG - causes parse error
SCHEMA = "v$id STRING, aircraft_id STRING"

# CORRECT - use backticks for special characters
SCHEMA = "`v$id` STRING, aircraft_id STRING"
```

### Issue 3: "Option customSchema is not allowed by connection"

**Error Message**:
```
[DATA_SOURCE_OPTION_NOT_ALLOWED_BY_CONNECTION] Option customschema is not allowed by connection neo4j_connection and cannot be provided externally. SQLSTATE: 42000
```

**Root Cause**: Unity Catalog JDBC connections have an `externalOptionsAllowList` that controls which Spark options users can specify at query time. By default, `customSchema` is NOT in this list.

**Fix**: Add `customSchema` to `externalOptionsAllowList` when creating the connection:
```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '["/Volumes/catalog/schema/volume/neo4j-jdbc-full-bundle.jar"]'
)
OPTIONS (
  url 'jdbc:neo4j+s://host:7687/database?enableSQLTranslation=true',
  user 'neo4j',
  password secret('scope', 'key'),
  driver 'org.neo4j.jdbc.Neo4jDriver',
  externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize,customSchema'
)
```

### Issue 4: SIGALRM Timeout Corrupts Py4J Connections

**Error Message**:
```
ERROR:root:Exception while sending command.
File ".../tests/base.py", line 111, in handler
    raise TestTimeoutError(
tests.base.TestTimeoutError: Operation timed out after 30 seconds
...
py4j.protocol.Py4JNetworkError: Error while sending or receiving
```

**Root Cause**: Python's `signal.SIGALRM` timeout mechanism is incompatible with PySpark's Py4J bridge. When SIGALRM fires during a Spark operation, it interrupts the socket connection between Python and the JVM, corrupting the Py4J communication state.

This causes tests to fail with misleading errors even when the underlying Spark/JDBC operations would succeed. The notebook doesn't have this issue because cells run independently without signal-based timeouts.

**Fix**: Use `ThreadPoolExecutor` instead of `signal.SIGALRM` for timeouts:
```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

def run_with_timeout(func, timeout_seconds, *args, **kwargs):
    """Thread-based timeout that doesn't corrupt Py4J."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            raise TestTimeoutError(f"Operation timed out after {timeout_seconds} seconds")
```

**References**:
- [Py4J Architecture](https://www.py4j.org/advanced_topics.html) - Py4J uses socket communication
- [Python signal module limitations](https://docs.python.org/3/library/signal.html#execution-of-python-signal-handlers) - Signals can interrupt any operation
- [PySpark Internals](https://spark.apache.org/docs/latest/api/python/development/internals.html) - PySpark-JVM communication

### Issue 5: Spark Subquery Wrapping Breaks Native Cypher

**Error Message**:
```
[JDBC_EXTERNAL_ENGINE_SYNTAX_ERROR.DURING_OUTPUT_SCHEMA_RESOLUTION]
The error was caused by the query SELECT * FROM (/*+ NEO4J FORCE_CYPHER */ RETURN 1 AS test) SPARK_GEN_SUBQ_559 WHERE 1=0
```

**Root Cause**: Spark wraps the `query` option in a subquery for schema inference:
```sql
SELECT * FROM (your_query) SPARK_GEN_SUBQ_N WHERE 1=0
```
This breaks native Cypher even with `FORCE_CYPHER` hint because the hint is inside the subquery while the outer wrapper is SQL.

**Fix**: Use `customSchema` to bypass schema inference entirely:
```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", UC_CONNECTION_NAME) \
    .option("query", "/*+ NEO4J FORCE_CYPHER */ RETURN 1 AS test") \
    .option("customSchema", "test INT") \
    .load()
```

---

## Best Practices

### 1. Always Use `customSchema` with Neo4j JDBC

Neo4j JDBC schema inference doesn't work reliably with Spark. Always specify `customSchema`:

```python
# For dbtable (reading a Neo4j label as table)
df = spark.read.format("jdbc") \
    .option("url", "jdbc:neo4j+s://host:7687/db?enableSQLTranslation=true") \
    .option("driver", "org.neo4j.jdbc.Neo4jDriver") \
    .option("dbtable", "Person") \
    .option("customSchema", "name STRING, age INT, created TIMESTAMP") \
    .load()

# For query (SQL or Cypher)
df = spark.read.format("jdbc") \
    .option("url", "jdbc:neo4j+s://host:7687/db?enableSQLTranslation=true") \
    .option("driver", "org.neo4j.jdbc.Neo4jDriver") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Person") \
    .option("customSchema", "cnt LONG") \
    .load()
```

### 2. Escape Special Characters in Column Names

Neo4j internal columns like `v$id` contain special characters. Always use backticks:

```python
SCHEMA = "`v$id` STRING, `element$id` STRING, name STRING"
```

### 3. Unity Catalog Connection Configuration

When creating UC JDBC connections for Neo4j, include all required options in `externalOptionsAllowList`:

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '["/Volumes/catalog/schema/volume/neo4j-jdbc-full-bundle.jar"]'
)
OPTIONS (
  url 'jdbc:neo4j+s://host:7687/database?enableSQLTranslation=true',
  user 'neo4j',
  password secret('scope', 'key'),
  driver 'org.neo4j.jdbc.Neo4jDriver',
  externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize,customSchema'
)
```

### 4. Use Thread-Based Timeouts (Not SIGALRM) with PySpark

When implementing timeouts in Python applications that use PySpark, never use `signal.SIGALRM`. Use `ThreadPoolExecutor` instead:

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

def run_spark_with_timeout(func, timeout_seconds):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        return future.result(timeout=timeout_seconds)
```

---

## References & Sources

- [Spark JDBC Data Sources Documentation](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html) - `customSchema` option details
- [Neo4j JDBC Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) - Driver options and SQL translation
- [Databricks Unity Catalog JDBC Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) - `externalOptionsAllowList` configuration
- [Neo4j JDBC GitHub](https://github.com/neo4j/neo4j-jdbc) - Driver source and issues
- [Neo4j Spark Connector Documentation](https://neo4j.com/docs/spark/current/) - Alternative integration method