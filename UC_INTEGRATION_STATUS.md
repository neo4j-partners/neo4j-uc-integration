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


---

## References & Sources

- [Spark JDBC Data Sources Documentation](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html) - `customSchema` option details
- [Neo4j JDBC Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) - Driver options and SQL translation
- [Databricks Unity Catalog JDBC Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) - `externalOptionsAllowList` configuration
- [Neo4j JDBC GitHub](https://github.com/neo4j/neo4j-jdbc) - Driver source and issues
- [Neo4j Spark Connector Documentation](https://neo4j.com/docs/spark/current/) - Alternative integration method