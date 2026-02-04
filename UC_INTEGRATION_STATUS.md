# Neo4j Databricks JDBC Federation Testing Status

## SUCCESS: Issue Resolved with Databricks Support

**We worked with Databricks engineering and successfully resolved the SafeSpark compatibility issue!**

The root cause was identified as **metaspace running out of memory inside the SafeSpark sandbox**. The Neo4j JDBC driver requires more memory for class loading than the default sandbox allocation provides.

### Solution

Add the following Spark configuration settings to your cluster:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

With these settings, the Unity Catalog JDBC connection to Neo4j works correctly.

---

## Overview

I created a JDBC Unity Catalog connection to test the Neo4j JDBC driver with Unity Catalog. I uploaded the Neo4j JDBC driver JAR to a Unity Catalog Volume, created a connection using `CREATE CONNECTION`, and queried Neo4j using both the Spark Data Source API (with the `databricks.connection` option) and the Remote Query SQL API (`remote_query()` function).

The Neo4j JDBC driver works when I load it directly into Spark and bypass Unity Catalog. SELECT queries, COUNT aggregates, and NATURAL JOINs all translate correctly from SQL to Cypher and return expected results. The driver, the network, and the credentials are all working.

Previously, without the memory configuration settings above, queries through the JDBC Unity Catalog connection failed with the error: "Connection was closed before the operation completed." This was caused by metaspace memory exhaustion in the SafeSpark sandbox during driver initialization.

---

## Summary

### Notebooks

The following two Databricks notebooks demonstrate the integration and can be imported to test it:

| Notebook | Status | Description |
|----------|--------|-------------|
| [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) | **PASS** | Full test suite (Sections 1-8) covering network, drivers, direct JDBC, and Unity Catalog JDBC |
| [`neo4j_schema_test.ipynb`](uc-neo4j-test-suite/neo4j_schema_test.ipynb) | **PASS** | Focused schema testing (Sections 1, 3, 8) for JDBC metadata and UC object creation |

**Note:** Ensure the SafeSpark memory configuration settings are applied to your cluster before running these notebooks.

### Component Test Results

| Component | Status | Notes |
|-----------|--------|-------|
| Network Connectivity | PASS | TCP to Neo4j port 7687 |
| Neo4j Python Driver | PASS | Bolt protocol works |
| Neo4j Spark Connector | PASS | `org.neo4j.spark.DataSource` works |
| Neo4j JDBC SQL-to-Cypher | PASS | Aggregates, JOINs, and dbtable all work |
| Direct JDBC (Non-UC) | PASS | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **PASS** | Works with SafeSpark memory configuration |
| **JDBC Schema Discovery via UC** | **PASS** | Works with SafeSpark memory configuration |

### Root Cause and Resolution

**The Neo4j JDBC driver works correctly with Spark.** I verified this by loading the driver directly into the Spark classpath and running queries without Unity Catalog. SELECT queries work. Aggregates like COUNT work. NATURAL JOINs translate to Cypher relationship traversals. The driver's SQL-to-Cypher translation is functioning as expected.

**The root cause was metaspace memory exhaustion in the SafeSpark sandbox.** When using a JDBC Unity Catalog connection, SafeSpark runs custom JDBC drivers in a sandboxed process with limited memory. The Neo4j JDBC driver requires more metaspace for class loading than the default allocation provides, causing the connection to close during initialization.

**The fix:** Increase the SafeSpark sandbox memory by adding these Spark configuration settings to your cluster:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

With these settings, all Unity Catalog JDBC tests pass, including SQL aggregates, JOINs, filtering, and sorting.

---

## Environment Setup

To run the two notebooks above, use the following environment setup on Databricks.

### Required Spark Configuration

**Critical:** Add these settings to your cluster to provide sufficient memory for the Neo4j JDBC driver in the SafeSpark sandbox:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

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
**Status**: PASS (with memory configuration)

Uses the connection created in Step 5 (which uses Databricks "SafeSpark" isolation).

**Required Configuration:** Add these Spark settings to your cluster:
```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

**Test 1: Spark DataFrame API** - PASS
```python
df = spark.read.format("jdbc").option("databricks.connection", "neo4j_connection")...
```

**Test 2: remote_query()** - PASS
```sql
SELECT * FROM remote_query('neo4j_connection', query => 'SELECT 1')
```

**Test 3: SQL Aggregate (COUNT)** - PASS
```sql
SELECT COUNT(*) AS flight_count FROM Flight
```

**Test 4: SQL JOIN Translation** - PASS
```sql
SELECT COUNT(*) FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a
```
Translates to Cypher: `MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*)`

**Test 5: SQL Filtering and Sorting** - PASS
```sql
SELECT aircraft_id, tail_number, manufacturer, model FROM Aircraft
WHERE manufacturer = 'Boeing' ORDER BY aircraft_id LIMIT 5
```

**Note**: Without the memory configuration, these tests fail with "Connection was closed before the operation completed" due to metaspace exhaustion in the SafeSpark sandbox.

---

## Resolution Details

### Root Cause Analysis

Working with Databricks engineering, we identified that the "Connection was closed before the operation completed" error was caused by **metaspace running out of memory inside the SafeSpark sandbox**.

The Neo4j JDBC driver requires more memory for class loading during initialization than the default SafeSpark sandbox allocation provides. When metaspace is exhausted, the JVM in the sandbox crashes, causing SafeSpark to report the connection as closed.

### Fix Applied

The following Spark configuration settings increase the SafeSpark sandbox memory allocation:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

With these settings, the Neo4j JDBC driver initializes successfully and Unity Catalog JDBC connections work as expected.


---

## References

- [Spark JDBC Data Sources Documentation](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html) for `customSchema` option details
- [Neo4j JDBC Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) for driver options and SQL translation
- [Databricks Unity Catalog JDBC Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) for `externalOptionsAllowList` configuration
- [Neo4j JDBC GitHub](https://github.com/neo4j/neo4j-jdbc) for driver source and issues
- [Neo4j Spark Connector Documentation](https://neo4j.com/docs/spark/current/) for an alternative integration method