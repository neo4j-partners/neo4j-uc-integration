# Neo4j Databricks JDBC Federation Testing Status

## Overview

I created a JDBC Unity Catalog connection to test the Neo4j JDBC driver with Unity Catalog. I uploaded the Neo4j JDBC driver JAR to a Unity Catalog Volume, created a connection using `CREATE CONNECTION`, and attempted to query Neo4j using both the Spark Data Source API (with the `databricks.connection` option) and the Remote Query SQL API (`remote_query()` function).

The Neo4j JDBC driver works when I load it directly into Spark and bypass Unity Catalog. SELECT queries, COUNT aggregates, and NATURAL JOINs all translate correctly from SQL to Cypher and return expected results. The driver, the network, and the credentials are all working.

The problem occurs when I route queries through the JDBC Unity Catalog connection. Both query methods fail with the same error: "Connection was closed before the operation completed." The error stack traces point to `com.databricks.safespark.jdbc.grpc_client.JdbcConnectClient`, which indicates the failure is happening inside Databricks' internal isolation layer for custom JDBC drivers. The connection closes during metadata resolution before any query reaches Neo4j.

---

## Summary

### Notebooks

The following two Databricks notebooks demonstrate the issue and can be imported to reproduce it:

| Notebook | Status | Description |
|----------|--------|-------------|
| [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) | **FAIL** | Full test suite (Sections 1-8) covering network, drivers, direct JDBC, and Unity Catalog JDBC |
| [`neo4j_schema_test.ipynb`](uc-neo4j-test-suite/neo4j_schema_test.ipynb) | **FAIL** | Focused schema testing (Sections 1, 3, 8) for JDBC metadata and UC object creation |

### Component Test Results

| Component | Status | Notes |
|-----------|--------|-------|
| Network Connectivity | PASS | TCP to Neo4j port 7687 |
| Neo4j Python Driver | PASS | Bolt protocol works |
| Neo4j Spark Connector | PASS | `org.neo4j.spark.DataSource` works |
| Neo4j JDBC SQL-to-Cypher | PASS | Aggregates, JOINs, and dbtable all work |
| Direct JDBC (Non-UC) | PASS | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **FAIL** | SafeSpark incompatibility |
| **JDBC Schema Discovery via UC** | **FAIL** | SafeSpark closes connection during metadata resolution |

### Core Issue: SafeSpark Incompatibility

**The Neo4j JDBC driver works correctly with Spark.** I verified this by loading the driver directly into the Spark classpath and running queries without Unity Catalog. SELECT queries work. Aggregates like COUNT work. NATURAL JOINs translate to Cypher relationship traversals. The driver's SQL-to-Cypher translation is functioning as expected.

**The failure happens inside Databricks' SafeSpark isolation layer.** When I create a JDBC Unity Catalog connection and query through it, the request goes through SafeSpark, which runs custom JDBC drivers in a sandboxed process and communicates with Spark via gRPC. The Neo4j driver never receives the query. Instead, SafeSpark closes the connection during its metadata resolution phase, before any SQL reaches the driver.

**What I tried that did not fix the issue:**

1. **Added `customSchema` to bypass Spark's schema inference.** This works for direct JDBC but does not help with Unity Catalog connections. SafeSpark still attempts its own metadata resolution.

2. **Added `customSchema` to `externalOptionsAllowList` in the connection definition.** This allows users to pass the option at query time, but SafeSpark still wraps queries in a subquery (`SELECT * FROM (query) WHERE 1=0`) for schema discovery, which fails.

3. **Used the `FORCE_CYPHER` hint to send native Cypher.** The hint tells the Neo4j driver to skip SQL translation, but the query never reaches the driver because SafeSpark fails first.

**What I believe is happening:** SafeSpark wraps the query to discover its schema before executing it. During this step, something about the Neo4j JDBC driver's response causes SafeSpark to close the connection. The error message "Connection was closed before the operation completed" suggests a timeout, crash, or protocol mismatch in the gRPC communication between Spark and the sandboxed driver process.

**Conclusion:** This appears to be a compatibility issue between the Neo4j JDBC driver and Databricks SafeSpark that requires Databricks engineering support to investigate.

---

## Environment Setup to Reproduce the Issues

To run the two notebooks above and reproduce the issue, I used the following environment setup on Databricks.

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
| neo4j-jdbc-full-bundle | 6.10.3 | Installed (Cluster & UC Volume) |
| neo4j-jdbc-translator-sparkcleaner | 6.10.3 | Installed (UC Volume) |

### Unity Catalog Resources
| Resource | Path/Name | Status |
|----------|-----------|--------|
| JDBC Full Bundle JAR | `/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-full-bundle-6.10.3.jar` | Uploaded |
| JDBC Spark Cleaner JAR | `/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar` | Uploaded |
| Connection | `neo4j_connection` | Created |

---

## Test Results from Notebooks

The following results are from running the Databricks notebooks listed above. Each section corresponds to a cell or group of cells in the notebooks.

### 1. Network Connectivity (TCP Layer)
**Status**: PASS

```sql
SELECT connectionTest('3f1f827a.databases.neo4j.io', '7687')
```
**Result**: `SUCCESS`. TCP connectivity to port 7687 is open.

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

The Neo4j JDBC driver works within the Spark environment when used directly.

#### SQL-to-Cypher Translation Examples

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
- [`pyspark-translation-example/`](./pyspark-translation-example/) is a local PySpark test suite
- [`sample-sql-translation/`](./sample-sql-translation/) is a Spring Boot connectivity test
- [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) is the full Databricks notebook (Sections 1-8)
- [`neo4j_schema_test.ipynb`](uc-neo4j-test-suite/neo4j_schema_test.ipynb) is the schema testing notebook (Sections 1, 3, 8)

See [Neo4j JDBC SQL2Cypher docs](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) for full translation rules.

### 5. Unity Catalog Connection Creation
**Status**: PASS

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC ...
```
**Result**: Connection created successfully. `DESCRIBE CONNECTION` shows correct configuration.

### 6. Unity Catalog JDBC Read (SafeSpark Wrapper)
**Status**: FAIL (Connection Closed)

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

I confirmed the following components work correctly:

1. Network connectivity passes the TCP test.
2. Credentials work with the Python driver.
3. Spark can exchange data with Neo4j using the Spark Connector.
4. The JDBC driver works with Spark when loaded directly.

The failure only occurs when using the JDBC Unity Catalog connection. This connection uses SafeSpark, which runs the JDBC driver in a separate sandboxed process and communicates via gRPC.

### Potential Causes

The Neo4j JDBC driver might be doing something during metadata retrieval or connection handshake that the SafeSpark gRPC wrapper does not handle correctly. The error message "Connection was closed before the operation completed" suggests the isolated process might be crashing or timing out during initialization.


---

## References

- [Spark JDBC Data Sources Documentation](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html) for `customSchema` option details
- [Neo4j JDBC Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) for driver options and SQL translation
- [Databricks Unity Catalog JDBC Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) for `externalOptionsAllowList` configuration
- [Neo4j JDBC GitHub](https://github.com/neo4j/neo4j-jdbc) for driver source and issues
- [Neo4j Spark Connector Documentation](https://neo4j.com/docs/spark/current/) for an alternative integration method