# Neo4j JDBC Unity Catalog Integration: RESOLVED

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

## Background

I performed extensive connectivity testing to validate the Neo4j JDBC driver, Neo4j Spark Connector, and network connectivity to Neo4j from Databricks. All connectivity tests pass. I then created a JDBC Unity Catalog connection to test the Neo4j JDBC driver with Unity Catalog. I uploaded the Neo4j JDBC driver JAR to a Unity Catalog Volume, created a connection using `CREATE CONNECTION`, and then queried Neo4j using both the Spark Data Source API (with the `databricks.connection` option) and the Remote Query SQL API (`remote_query()` function).

The Neo4j JDBC driver works when I load it directly into Spark and bypass Unity Catalog. SELECT queries, COUNT aggregates, and NATURAL JOINs all translate correctly from SQL to Cypher and return expected results. The driver, the network, and the credentials are all working. Queries successfully connect to Neo4j, execute Cypher, and return result sets back to Spark DataFrames.

Previously, when routing queries through the JDBC Unity Catalog connection without the memory settings above, both query methods failed with the error: "Connection was closed before the operation completed." This was caused by metaspace memory exhaustion in the SafeSpark sandbox during driver initialization.

All of the connectivity tests can be viewed, run, and tested from this GitHub repo: [neo4j_databricks_sql_translation.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb). If you would like Neo4j connection info or help setting up or running the tests, please let me know.

## Test Results Summary

- Network Connectivity (TCP Layer): **PASS** - Verified using the [Databricks connectivity test](https://docs.databricks.com/aws/en/connect/jdbc-connection#connectivity-test); TCP connection to Neo4j port 7687 confirmed working
- Neo4j Python Driver: **PASS** - Bolt protocol connection and authentication verified
- Neo4j Spark Connector: **PASS** - `org.neo4j.spark.DataSource` reads data successfully
- Direct JDBC - dbtable option: **PASS** - Reads Neo4j labels as tables with `customSchema`
- Direct JDBC - SQL Translation: **PASS** - SQL queries translate to Cypher and execute
- Direct JDBC - SQL Aggregate (COUNT): **PASS** - `SELECT COUNT(*)` translates to Cypher `count()`
- Direct JDBC - SQL JOIN Translation: **PASS** - `NATURAL JOIN` translates to Cypher relationship patterns
- Unity Catalog Connection Setup: **PASS** - `CREATE CONNECTION` succeeds with JDBC driver JARs
- Unity Catalog - Spark DataFrame API: **PASS** - Works with SafeSpark memory configuration
- Unity Catalog - remote_query() Function: **PASS** - Works with SafeSpark memory configuration
- Unity Catalog - SQL Aggregate (COUNT): **PASS** - `SELECT COUNT(*)` works through UC connection
- Unity Catalog - SQL JOIN Translation: **PASS** - `NATURAL JOIN` translates to Cypher via UC (11,200 relationships)
- Unity Catalog - SQL Filtering (WHERE/LIMIT): **PASS** - `WHERE` and `LIMIT` work through UC

## Root Cause (Resolved)

The failure was happening inside Databricks' SafeSpark isolation layer. When queries are routed through the JDBC Unity Catalog connection, SafeSpark runs the JDBC driver in a sandboxed process with limited memory. The Neo4j JDBC driver requires more metaspace for class loading than the default sandbox allocation provides.

**The error message was:** `java.lang.RuntimeException: Connection was closed before the operation completed` with stack traces pointing to `com.databricks.safespark.jdbc.grpc_client.JdbcConnectClient` and `JdbcGetRowsClient.fetchMetadata`.

**The fix:** Increase the SafeSpark sandbox memory allocation with the following Spark configuration:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

With these settings applied to the cluster, the Unity Catalog JDBC connection works correctly.

**Stack Trace:**
```
============================================================
TEST: Unity Catalog - Spark DataFrame API
============================================================

Connection: [REDACTED]
Testing: Can we query Neo4j via UC JDBC connection using DataFrame API?
Query: SELECT 1 AS test

[FAIL] Unity Catalog Spark DataFrame API failed:

Error: An error occurred while calling o687.load.
: java.lang.RuntimeException: Connection was closed before the operation completed.
    at com.databricks.safespark.jdbc.grpc_client.JdbcConnectClient.awaitWhileConnected(JdbcConnectClient.scala:96)
    at com.databricks.safespark.jdbc.grpc_client.JdbcGetRowsClient.fetchMetadata(JdbcGetRowsClient.scala:102)
```

More details are below.

---

This document summarizes the connectivity and functionality tests in `uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb`.

## Section 1: Environment Information
- **Status: VERIFIED WORKING**
- Captures Spark version, Databricks Runtime version, Python version
- Checks Neo4j Python driver installation and version
- Verifies JDBC JAR and Cleaner JAR files exist in UC Volume

## Section 2: Network Connectivity (TCP Layer)
- **Status: VERIFIED WORKING**
- Tests TCP connectivity to Neo4j host on port 7687 using `netcat`
- Validates network path is open before attempting database connections

**Test Results:**
```
============================================================
TEST: Network Connectivity (TCP)
============================================================

Target: [REDACTED]:7687 (Bolt protocol port)
Testing: Can Databricks reach Neo4j at the network level?

============================================================
>>> CONNECTIVITY VERIFIED <<<
============================================================

[PASS] TCP connection established in 96.4ms

Connection Details:
  - Host: [REDACTED]
  - Port: 7687 (Bolt)
  - TCP Latency: 96.4ms
  - Total Test Time: 5671.7ms
  - Raw Output: Warning: inverse host lookup failed for 20.124.3.249: Unknown host
[REDACTED] [20.124.3.249] 7687 (?) open
```

## Section 3: Neo4j Python Driver
- **Status: VERIFIED WORKING**
- Tests direct connectivity using the Neo4j Python driver
- Verifies credentials work with `driver.verify_connectivity()`
- Executes simple query (`RETURN 1 AS test`)
- Retrieves Neo4j version via `dbms.components()`

**Test Results:**
```
============================================================
TEST: Neo4j Python Driver
============================================================

Target: [REDACTED]+s://[REDACTED]
Testing: Can we authenticate and execute queries via Bolt protocol?

============================================================
>>> AUTHENTICATION SUCCESSFUL <<<
============================================================

[PASS] Driver connected and authenticated in 211.7ms
[PASS] Query executed: RETURN 1 = 1 (8.5ms)

Connection Details:
  - URI: [REDACTED]+s://[REDACTED]
  - User: [REDACTED]
  - Database: [REDACTED]
  - Neo4j Server: Neo4j Kernel ['5.27-aura'], Cypher ['5', '25']
  - Connection Time: 211.7ms
  - Total Test Time: 225.7ms

------------------------------------------------------------
RESULT: Neo4j Python Driver connection WORKING
        Credentials valid, Bolt protocol functional
------------------------------------------------------------

Status: PASS
```

## Section 4: Neo4j Spark Connector (Working Baseline)
- **Status: VERIFIED WORKING**
- Tests `org.neo4j.spark.DataSource` format
- Establishes working baseline proving Spark can communicate with Neo4j
- Uses basic authentication with Bolt URI

**Test Results:**
```
============================================================
TEST: Neo4j Spark Connector (org.[REDACTED].spark.DataSource)
============================================================

Target: [REDACTED]+s://[REDACTED]
Testing: Can Spark connect to Neo4j using the native Spark Connector?
Method: org.[REDACTED].spark.DataSource (uses Bolt protocol internally)

============================================================
>>> SPARK CONNECTOR WORKING <<<
============================================================

[PASS] Spark Connector query executed successfully in 628.2ms

Query Results:
+----------------------+-----+
|message               |value|
+----------------------+-----+
|Spark Connector Works!|1    |
+----------------------+-----+

Connection Details:
  - Connector: org.[REDACTED].spark.DataSource
  - URL: [REDACTED]+s://[REDACTED]
  - Auth Type: basic
  - Rows Returned: 1
  - Execution Time: 628.2ms

------------------------------------------------------------
RESULT: Neo4j Spark Connector WORKING
        Spark can communicate with Neo4j via Bolt protocol
        This is the recommended approach for Spark-Neo4j integration
------------------------------------------------------------

Status: PASS
```

## Section 5: Direct JDBC Tests (Bypassing Unity Catalog)
- **Status: VERIFIED WORKING**
- **dbtable option**: Reads Neo4j label as a table with `customSchema` to avoid NullType inference
- **SQL Translation**: Tests `SELECT 1 AS value` with SQL translation enabled (`enableSQLTranslation=true`)
- **SQL Aggregate (COUNT)**: Tests `SELECT COUNT(*) FROM Flight` aggregate query
- **SQL JOIN Translation**: Tests SQL JOIN to Cypher relationship pattern conversion (`Flight -[:DEPARTS_FROM]-> Airport`)

**Test Results:**
```
============================================================
TEST: Direct JDBC - dbtable option (reads label as table)
============================================================

JDBC URL: jdbc:[REDACTED]+s://[REDACTED]:7687/[REDACTED]?enableSQLTranslation=true
Testing: Can Spark read Neo4j nodes via JDBC using dbtable option?
Method: spark.read.format('jdbc') with Neo4j JDBC Driver

Label: Aircraft
Custom Schema: `v$id` STRING, aircraft_id STRING, tail_number STRING, icao24 STRING, model STRING, operator STRING, manufacturer STRING

============================================================
>>> DIRECT JDBC CONNECTION WORKING <<<
============================================================

[PASS] Direct JDBC dbtable 'Aircraft' read successfully in 3174.0ms

DataFrame Schema:
  - v$id: StringType()
  - aircraft_id: StringType()
  - tail_number: StringType()
  - icao24: StringType()
  - model: StringType()
  - operator: StringType()
  - manufacturer: StringType()

Sample Data (5 rows shown):
+----------------------------------------+-----------+-----------+------+--------+-----------+------------+
|v$id                                    |aircraft_id|tail_number|icao24|model   |operator   |manufacturer|
+----------------------------------------+-----------+-----------+------+--------+-----------+------------+
|4:f05031ca-ab90-4139-b702-98a47fe3d9d5:0|AC1001     |N95040A    |448367|B737-800|ExampleAir |Boeing      |
|4:f05031ca-ab90-4139-b702-98a47fe3d9d5:1|AC1002     |N30268B    |aee78a|A320-200|SkyWays    |Airbus      |
|4:f05031ca-ab90-4139-b702-98a47fe3d9d5:2|AC1003     |N54980C    |7c6b17|A321neo |RegionalCo |Airbus      |
|4:f05031ca-ab90-4139-b702-98a47fe3d9d5:3|AC1004     |N37272D    |fe5e91|E190    |NorthernJet|Embraer     |
|4:f05031ca-ab90-4139-b702-98a47fe3d9d5:4|AC1005     |N53032E    |232296|B737-800|ExampleAir |Boeing      |
+----------------------------------------+-----------+-----------+------+--------+-----------+------------+
only showing top 5 rows
Connection Details:
  - Driver: org.[REDACTED].jdbc.Neo4jDriver
  - URL: jdbc:[REDACTED]+s://[REDACTED]:7687/[REDACTED]?enableSQLTranslation=true
  - Label/Table: Aircraft
  - SQL Translation: Enabled
  - Execution Time: 3174.0ms

------------------------------------------------------------
RESULT: Direct JDBC Connection WORKING
        Neo4j JDBC Driver loaded and functional
        SQL-to-Cypher translation enabled
------------------------------------------------------------

Status: PASS
```

```
============================================================
TEST: Direct JDBC - SQL JOIN Translation
============================================================

JDBC URL: jdbc:[REDACTED]+s://[REDACTED]:7687/[REDACTED]?enableSQLTranslation=true
Testing: Can Neo4j JDBC translate SQL JOINs to Cypher relationships?

SQL Query:
  SELECT COUNT(*) AS cnt FROM Flight f
  NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a

Expected Cypher:
  MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*)

Ref: https://[REDACTED].com/docs/jdbc-manual/current/sql2cypher/

============================================================
>>> SQL JOIN TRANSLATION WORKING <<<
============================================================

[PASS] SQL JOIN query translated and executed in 1304.8ms

Query Results:
+-----+
|cnt  |
+-----+
|11200|
+-----+

Translation Details:
  - SQL Tables: Flight, DEPARTS_FROM, Airport
  - Cypher Pattern: (f:Flight)-[:DEPARTS_FROM]->(a:Airport)
  - Matching Relationships: 11,200
  - Execution Time: 1304.8ms

------------------------------------------------------------
RESULT: SQL JOIN to Cypher Relationship Translation WORKING
        NATURAL JOIN successfully mapped to graph traversal
------------------------------------------------------------

Status: PASS
```

## Section 6: Unity Catalog JDBC Connection Setup
- **Status: VERIFIED WORKING**
- Drops existing connection if present
- Creates UC JDBC connection with:
  - `java_dependencies` pointing to JDBC full bundle and Spark cleaner JARs
  - `externalOptionsAllowList` for dbtable, query, customSchema, etc.
- Verifies connection configuration with `DESCRIBE CONNECTION`

**Test Results:**
```
============================================================
SETUP: Create Unity Catalog JDBC Connection
============================================================

Connection Name: [REDACTED]
JDBC URL: jdbc:[REDACTED]+s://[REDACTED]:7687/[REDACTED]?enableSQLTranslation=true
Driver: org.[REDACTED].jdbc.Neo4jDriver

[INFO] Dropped existing connection (if any): [REDACTED]
[INFO] Java Dependencies:
  - [REDACTED]
  - [REDACTED]

============================================================
>>> UC CONNECTION CREATED <<<
============================================================

[PASS] Connection '[REDACTED]' created in 241.1ms

Connection Configuration:
  - Name: [REDACTED]
  - Type: JDBC
  - Driver: org.[REDACTED].jdbc.Neo4jDriver
  - SQL Translation: Enabled
  - Spark Cleaner: Included
  ```

## Section 7: Unity Catalog JDBC Tests
- **Status: WORKING** (with SafeSpark memory configuration)
- **Spark DataFrame API**: Tests basic query via `databricks.connection` option - **PASS**
- **remote_query() Function**: Tests Spark SQL `remote_query()` function - **PASS**
- **SQL Aggregate (COUNT)**: Tests COUNT query through UC connection - **PASS**
- **SQL JOIN Translation**: Tests NATURAL JOIN to Cypher relationship patterns via UC - **PASS** (11,200 relationships)
- **SQL Filtering (WHERE/LIMIT)**: Tests WHERE and LIMIT through UC connection - **PASS**

**Required Spark Configuration:**
```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

With these settings, Unity Catalog JDBC queries to Neo4j work correctly.

**Note on ORDER BY:** `ORDER BY` is not supported through Unity Catalog because Spark wraps queries in a subquery for schema resolution (`SELECT * FROM (query) WHERE 1=0`), and `ORDER BY` inside subqueries is invalid SQL.

## Known Limitations
- Neo4j JDBC returns `NullType()` during schema inference; `customSchema` is required
- SafeSpark sandbox requires increased memory allocation for the Neo4j JDBC driver
- `ORDER BY` is not supported through UC (Spark wraps queries in subqueries for schema resolution)
