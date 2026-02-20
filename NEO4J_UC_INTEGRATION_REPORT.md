# Neo4j Unity Catalog JDBC Integration: Build and Test Report

The Neo4j JDBC driver connects to Databricks Unity Catalog through Lakehouse Federation, translating SQL to Cypher at the driver level so Spark treats Neo4j as another SQL data source. This report covers what we built, the engineering problems we solved, the query patterns we validated, and how we extended the integration into Genie for natural language access.

All queries shown here ran on a live Databricks cluster (Runtime 17.3 LTS) connected to Neo4j Aura. The output is real, not mocked.

## The SafeSpark Problem and Fix

The integration hit a wall immediately. The Neo4j Python driver worked fine. The Neo4j Spark Connector worked fine. Direct JDBC outside of UC worked fine. Every UC JDBC attempt failed with the same error:

```
Connection was closed before the operation completed
```

The stack trace pointed to `com.databricks.safespark.jdbc.grpc_client.JdbcConnectClient.awaitWhileConnected`, which meant the failure was in the SafeSpark sandbox, not in Neo4j. The Neo4j JDBC driver loads significantly more classes during initialization than a typical JDBC driver because it bundles a full SQL-to-Cypher translation engine (ANTLR parser, Cypher AST, translation rules). The default SafeSpark metaspace allocation couldn't accommodate that class loading, so the sandboxed JVM crashed silently.

Three Spark configuration properties fix it:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

These go in the cluster's Advanced Options > Spark > Spark Config. Without them, every UC JDBC query to Neo4j fails regardless of whether the query itself is valid. We worked with Databricks engineering to identify and validate this fix.

## Integration Architecture

Two JDBC JARs are uploaded to a UC Volume:

| JAR | Purpose |
|-----|---------|
| `neo4j-jdbc-full-bundle-6.10.3.jar` | JDBC driver with built-in SQL-to-Cypher translation |
| `neo4j-jdbc-translator-sparkcleaner-6.10.3.jar` | Strips Spark-generated subquery wrappers before translation |

The spark cleaner JAR exists because of how Spark performs schema inference. Spark wraps JDBC queries in a subquery for probing:

```sql
SELECT * FROM (
    <original_query>
) SPARK_GEN_SUBQ_0 WHERE 1=0
```

The cleaner detects the `SPARK_GEN_SUBQ` marker, extracts the inner query, validates whether it's Cypher, and if so, wraps it with a `/*+ NEO4J FORCE_CYPHER */` hint to bypass further SQL translation. This is discovered automatically via Java SPI when the JAR is on the classpath.

The UC connection itself is a single `CREATE CONNECTION` statement:

```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '[
    "/Volumes/catalog/schema/jars/neo4j-jdbc-full-bundle-6.10.3.jar",
    "/Volumes/catalog/schema/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar"
  ]'
)
OPTIONS (
  url 'jdbc:neo4j+s://host:7687/neo4j?enableSQLTranslation=true',
  user secret('neo4j-uc-creds', 'user'),
  password secret('neo4j-uc-creds', 'password'),
  driver 'org.neo4j.jdbc.Neo4jDriver',
  externalOptionsAllowList 'dbtable,query,customSchema'
)
```

The `enableSQLTranslation=true` parameter in the JDBC URL activates the driver's SQL-to-Cypher translator. The `externalOptionsAllowList` includes `customSchema`, which is mandatory (explained below).

### Prerequisites

Two preview features must be enabled in the workspace:

- **Custom JDBC on UC Compute** for loading custom JDBC driver JARs
- **`remote_query` table-valued function** for the `remote_query()` SQL function

Credentials are stored in a Databricks secret scope (`neo4j-uc-creds`) with keys for host, user, password, JAR paths, and connection name.

## SQL-to-Cypher Translation

The Neo4j JDBC driver translates standard SQL into Cypher automatically. Neo4j labels become SQL tables, relationship types become JOIN targets, and node properties become columns. Here are the translations we validated:

| SQL | Cypher |
|-----|--------|
| `SELECT COUNT(*) FROM Flight` | `MATCH (n:Flight) RETURN count(n)` |
| `SELECT COUNT(*) FROM Aircraft WHERE manufacturer = 'Boeing'` | `MATCH (n:Aircraft) WHERE n.manufacturer = 'Boeing' RETURN count(n)` |
| `SELECT COUNT(DISTINCT manufacturer) FROM Aircraft` | `MATCH (n:Aircraft) RETURN count(DISTINCT n.manufacturer)` |
| `FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a` | `MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport)` |

The `NATURAL JOIN` syntax is how graph traversals work in SQL. The first table is the source node label, the middle "table" is the relationship type, and the last table is the target node label. This maps directly to Cypher pattern matching.

## The customSchema Requirement

Spark's JDBC reader runs a schema inference step before executing any query, sending a modified version with `WHERE 1=0` to get column metadata. Neo4j's JDBC driver returns `NullType()` for all columns during this step, causing Spark to fail with `No column has been read prior to this call`.

The fix is to always provide an explicit `customSchema` option:

```python
# Fails -- Spark can't infer the schema
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .load()

# Works -- schema specified explicitly
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \
    .load()
```

Every query through the UC JDBC connection needs `customSchema`. No exceptions. Column names must match the SQL aliases, and types must match what Neo4j returns (typically `LONG` for counts, `STRING` for text, `DOUBLE` for floats).

## Validated Query Patterns

We ran a 12-test suite (`full_uc_tests.py`) against a live Neo4j Aura instance through the UC JDBC connection. Total execution time was approximately 194 seconds, with most time spent on connection initialization rather than query execution.

### Passing Tests (9/9 supported patterns)

| Test | Result |
|------|--------|
| Basic query (`SELECT 1 AS test`) | 1 |
| COUNT aggregate | 2,400 flights |
| Multiple aggregates (COUNT, MIN, MAX) | 60 aircraft, AC1001-AC1020 |
| COUNT DISTINCT | 3 unique manufacturers |
| Aggregate with WHERE (equals) | 15 Boeing aircraft |
| Aggregate with WHERE (IN clause) | 45 Boeing+Airbus aircraft |
| Aggregate with WHERE (AND) | 15 Boeing with model |
| Aggregate with WHERE (IS NOT NULL) | 60 aircraft with icao24 |
| JOIN with aggregate (2-hop traversal) | 11,200 relationships |

### Expected Failures (3/3 confirmed)

| Pattern | Failure Reason |
|---------|---------------|
| GROUP BY | Invalid inside the subquery wrapper Spark generates |
| Non-aggregate SELECT | Same subquery limitation |
| ORDER BY | Same subquery limitation |

The practical boundary is clear: UC JDBC works for aggregate analytics (COUNT, SUM, AVG, MIN, MAX) with optional WHERE filters and NATURAL JOINs. Row-level data access, GROUP BY, ORDER BY, and HAVING all fail because Spark's subquery wrapping conflicts with the Neo4j SQL translator. For those patterns, the Neo4j Spark Connector is the workaround.

## Two Federation Methods

The integration supports two complementary methods, each with distinct tradeoffs:

| Method | Pros | Cons |
|--------|------|------|
| `remote_query()` via UC JDBC | Pure SQL, no cluster library needed, UC governed | Aggregate-only (no GROUP BY, ORDER BY) |
| Neo4j Spark Connector | Full Cypher support, row-level data, GROUP BY | Requires cluster library, no UC governance |

The federated queries in our test suite use both methods, choosing whichever fits the query pattern. The most comprehensive example (Query 5, Fleet Health Dashboard) uses both simultaneously in a single analysis.

## Demo Dataset: Aircraft Digital Twin

We validated the integration against a synthetic aerospace IoT dataset modeling a fleet of 20 aircraft over 90 days. The data is split across both systems:

| Database | Data | Volume |
|----------|------|--------|
| Delta Lakehouse | Sensor telemetry, aircraft metadata, system and sensor catalogs | 345,600 sensor readings, 20 aircraft, 80 systems, 160 sensors |
| Neo4j Graph | Flights, airports, maintenance events, component topology | 800 flights, 12 airports, 300 maintenance events |

This split reflects what each system does best: high-volume time-series analytics in Delta, relationship traversals and topology in Neo4j.

## Federated Query Examples

### Query 1: Verify Data Sources

Confirms both sides are accessible. Delta tables are counted with standard SQL; Neo4j is verified with `remote_query()` calls, including a graph traversal test:

```sql
SELECT * FROM remote_query('neo4j_uc_connection',
    query => 'SELECT COUNT(*) AS cnt
              FROM Flight f
              NATURAL JOIN DEPARTS_FROM r
              NATURAL JOIN Airport a')
```

This exercises the full chain: `remote_query()` to UC JDBC to Neo4j JDBC driver to SQL-to-Cypher translation to Cypher execution.

### Query 2: Fleet Summary (Pure SQL Federation)

A single SQL statement that CROSS JOINs four `remote_query()` calls (maintenance counts, critical events, flight count, graph traversals) with a Delta subquery computing fleet-wide sensor averages across 345K+ readings:

```sql
SELECT
    neo4j.total_maintenance_events,
    neo4j.critical_events,
    neo4j.total_flights,
    neo4j.flight_airport_connections,
    ROUND(sensor.avg_egt, 1) AS avg_egt_celsius,
    ROUND(sensor.avg_vibration, 4) AS avg_vibration_ips,
    sensor.total_readings
FROM (
    SELECT
        maint.cnt AS total_maintenance_events,
        crit.cnt AS critical_events,
        flights.cnt AS total_flights,
        deps.cnt AS flight_airport_connections
    FROM
        remote_query('neo4j_uc_connection',
            query => 'SELECT COUNT(*) AS cnt FROM MaintenanceEvent') AS maint
    CROSS JOIN
        remote_query('neo4j_uc_connection',
            query => 'SELECT COUNT(*) AS cnt FROM MaintenanceEvent
                      WHERE severity = ''CRITICAL''') AS crit
    CROSS JOIN
        remote_query('neo4j_uc_connection',
            query => 'SELECT COUNT(*) AS cnt FROM Flight') AS flights
    CROSS JOIN
        remote_query('neo4j_uc_connection',
            query => 'SELECT COUNT(*) AS cnt
                      FROM Flight f
                      NATURAL JOIN DEPARTS_FROM r
                      NATURAL JOIN Airport a') AS deps
) neo4j
CROSS JOIN (
    SELECT
        AVG(CASE WHEN sen.type = 'EGT' THEN r.value END) AS avg_egt,
        AVG(CASE WHEN sen.type = 'Vibration' THEN r.value END) AS avg_vibration,
        COUNT(*) AS total_readings
    FROM sensor_readings r
    JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
) sensor
```

Live output:

```
+------------------------+---------------+-------------+--------------------------+---------------+-----------------+--------------+
|total_maintenance_events|critical_events|total_flights|flight_airport_connections|avg_egt_celsius|avg_vibration_ips|total_readings|
+------------------------+---------------+-------------+--------------------------+---------------+-----------------+--------------+
|300                     |0              |800          |800                       |671.6          |0.2659           |345600        |
+------------------------+---------------+-------------+--------------------------+---------------+-----------------+--------------+
```

This pattern works because `remote_query()` returns a single-row table per call, making CROSS JOINs natural for combining aggregate metrics. No GROUP BY needed, so it stays within the UC JDBC supported patterns.

### Query 3: Sensor Health + Maintenance Correlation (Spark Connector)

This query needs per-aircraft grouping, which means GROUP BY, which means `remote_query()` is out. Instead, we load maintenance events from Neo4j via the Spark Connector into a temp view, then JOIN with Delta sensor data in standard Spark SQL:

```python
neo4j_maintenance = spark.read.format("org.neo4j.spark.DataSource") \
    .option("url", NEO4J_BOLT_URI) \
    .option("authentication.type", "basic") \
    .option("authentication.basic.username", NEO4J_USER) \
    .option("authentication.basic.password", NEO4J_PASSWORD) \
    .option("labels", "MaintenanceEvent") \
    .load()

neo4j_maintenance.createOrReplaceTempView("neo4j_maintenance")
```

The federated SQL then JOINs three CTEs: `aircraft_ref` from Delta, `sensor_health` aggregating EGT and vibration per aircraft from Delta, and `maintenance_summary` grouping Neo4j events by aircraft and severity. The result correlates sensor health with maintenance frequency across all 20 aircraft. Sample output:

```
+-----------+--------+-----------+------------+--------+-----+-----+---------+---------+-----------+-----------+
|tail_number|model   |operator   |maint_events|critical|major|minor|avg_egt_c|max_egt_c|avg_vib_ips|max_vib_ips|
+-----------+--------+-----------+------------+--------+-----+-----+---------+---------+-----------+-----------+
|N76758N    |A320-200|SkyWays    |26          |7       |13   |6    |671.6    |698.2    |0.2659     |0.4911     |
|N53032E    |B737-800|ExampleAir |25          |8       |9    |8    |671.6    |698.4    |0.266      |0.4913     |
|N54980C    |A321neo |RegionalCo |20          |8       |6    |6    |671.6    |697.8    |0.266      |0.4898     |
+-----------+--------+-----------+------------+--------+-----+-----+---------+---------+-----------+-----------+
(20 rows total)
```

### Query 4: Flight Operations + Engine Performance

Same pattern as Query 3 with a different angle. Flight nodes are loaded from Neo4j via Spark Connector, grouped by aircraft to compute flight counts and unique origin/destination airports, then INNER JOINed with engine-specific sensor readings (filtered to `sys.type = 'Engine'`) from Delta. The result shows aircraft utilization correlated with engine health.

### Query 5: Fleet Health Dashboard (Hybrid)

The most comprehensive query combines both federation methods simultaneously:

- **`remote_query()`** provides a fleet-wide graph traversal metric (Flight-[:DEPARTS_FROM]->Airport connections: 800)
- **Spark Connector temp views** provide per-aircraft maintenance events and flight counts from Neo4j
- **Delta tables** provide per-aircraft sensor aggregates (EGT, vibration, fuel flow)

Everything LEFT JOINs on `aircraft_id`, sorted by critical maintenance events descending:

```
+-----------+--------+-----------+-------+------------+--------+-----+-------+--------+--------+
|tail_number|model   |operator   |flights|maint_events|critical|egt_c|vib_ips|fuel_kgs|readings|
+-----------+--------+-----------+-------+------------+--------+-----+-------+--------+--------+
|N53032E    |B737-800|ExampleAir |27     |25          |8       |671.6|0.266  |1.39    |17280   |
|N54980C    |A321neo |RegionalCo |34     |20          |8       |671.6|0.266  |1.39    |17280   |
|N76758N    |A320-200|SkyWays    |46     |26          |7       |671.6|0.2659 |1.39    |17280   |
+-----------+--------+-----------+-------+------------+--------+-----+-------+--------+--------+
(20 rows total)
```

This demonstrates that the dual-method approach works in production: `remote_query()` for fleet-wide aggregate metrics that fit within UC JDBC constraints, Spark Connector for row-level data that requires grouping.

## Genie Integration: Natural Language Access

The federated queries work, but they require hand-written SQL. We extended the integration to support natural language queries through Genie by materializing Neo4j data as managed Delta tables.

### Why Materialization

Live UC views over `remote_query()` would be the ideal approach, but two schema-inference limitations prevent it:

| Approach | Problem |
|----------|---------|
| `remote_query()` with `query` parameter | Spark wraps the inner query in a subquery; Neo4j's translator can't parse subqueries |
| `remote_query()` with `dbtable` parameter | Spark issues `SELECT * FROM Label WHERE 1=0`; Neo4j JDBC returns `NullType` for all columns |

The working approach uses the Spark DataFrame JDBC reader with `dbtable` (avoids subquery wrapping) and `customSchema` (fixes NullType inference), then saves the results as managed Delta tables:

```python
MAINTENANCE_SCHEMA = """`v$id` STRING, aircraft_id STRING, system_id STRING,
    component_id STRING, event_id STRING, severity STRING, fault STRING,
    corrective_action STRING, reported_at STRING"""

df = spark.read.format("jdbc") \
    .option("databricks.connection", UC_CONNECTION_NAME) \
    .option("dbtable", "MaintenanceEvent") \
    .option("customSchema", MAINTENANCE_SCHEMA) \
    .load() \
    .select("aircraft_id", "fault", "severity", "corrective_action", "reported_at")

df.write.mode("overwrite").saveAsTable("lakehouse.neo4j_maintenance_events")
```

The same pattern materializes `neo4j_flights`, `neo4j_airports`, and `neo4j_flight_airports`.

### Genie Space Configuration

The Genie space sees 8 tables total, 4 Delta (direct) and 4 Neo4j (materialized):

**Delta tables:** `aircraft`, `systems`, `sensors`, `sensor_readings`

**Materialized Neo4j tables:** `neo4j_maintenance_events`, `neo4j_flights`, `neo4j_airports`, `neo4j_flight_airports`

Genie treats all 8 as regular UC tables. Instructions in the space teach the LLM the sensor data model (readings require a 4-table join chain through `aircraft` -> `systems` -> `sensors` -> `sensor_readings`, filtered by `sensors.type`), Neo4j table schemas, cross-source JOIN patterns, and example SQL.

### Genie Output: Cross-Source Federation

When asked "For each aircraft, show the number of flights, maintenance events, and average engine temperature," Genie generated this SQL without any human intervention:

```sql
SELECT
    COALESCE(f.aircraft_id, m.aircraft_id, e.aircraft_id) AS aircraft_id,
    COALESCE(f.num_flights, 0) AS num_flights,
    COALESCE(m.num_maintenance_events, 0) AS num_maintenance_events,
    ROUND(e.avg_egt, 2) AS avg_egt_celsius
FROM (
    SELECT aircraft_id, COUNT(*) AS num_flights
    FROM neo4j_flights
    GROUP BY aircraft_id
) f
FULL OUTER JOIN (
    SELECT aircraft_id, COUNT(*) AS num_maintenance_events
    FROM neo4j_maintenance_events
    GROUP BY aircraft_id
) m ON f.aircraft_id = m.aircraft_id
FULL OUTER JOIN (
    SELECT sys.aircraft_id, AVG(r.value) AS avg_egt
    FROM sensor_readings r
    JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
    JOIN systems sys ON sen.system_id = sys.`:ID(System)`
    WHERE sen.type = 'EGT'
    GROUP BY sys.aircraft_id
) e ON COALESCE(f.aircraft_id, m.aircraft_id) = e.aircraft_id
ORDER BY aircraft_id
```

This federates across three data sources (Neo4j flights, Neo4j maintenance, Delta sensors) in a single generated query. The LLM never sees Cypher, the user never writes SQL.

### Agent Integration Patterns

The Genie space supports programmatic access through either the Genie Managed MCP Server (for agent integration) or the Genie Conversation API (for direct app integration). Three patterns are viable:

1. **Genie as standalone agent**, handling all queries when they map to SQL over the unified table set
2. **Multi-agent with Genie + DBSQL MCP**, where a supervisor routes between Genie for NL-to-SQL and DBSQL for ad-hoc federated SQL including `remote_query()` calls
3. **Agent Bricks supervisor** coordinating a Genie sub-agent with other agents (for example, a RAG agent over unstructured maintenance manuals)

## Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| No GROUP BY through UC JDBC | Cannot aggregate per-entity through `remote_query()` | Use Neo4j Spark Connector for row-level data, aggregate in Spark SQL |
| No ORDER BY / LIMIT through UC JDBC | Cannot sort or paginate at the Neo4j source | Apply sorting and limiting in Spark after the query returns |
| `customSchema` required on every JDBC query | Schema inference fails because Neo4j returns NullType | Always specify column names and types explicitly |
| Materialized Neo4j tables are point-in-time snapshots | Genie queries may reflect stale data | Re-run the materialization notebook; consider scheduling as a Databricks job |
| Neo4j JDBC SQL translation limited to basic patterns | Complex Cypher (variable-length paths, APOC procedures) won't translate from SQL | Use the Spark Connector with native Cypher for complex graph patterns |
| Genie 30-table limit per space | Must select which tables to expose | Focus on the most common query patterns |
| SafeSpark memory settings required | Without them, all UC JDBC queries fail silently | Document the Spark config prominently; validated values: 128/300/512 MiB |

## Component Test Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Network connectivity | PASS | TCP to Neo4j port 7687 |
| Neo4j Python Driver | PASS | Bolt protocol works |
| Neo4j Spark Connector | PASS | `org.neo4j.spark.DataSource` works |
| Neo4j JDBC SQL-to-Cypher | PASS | Aggregates, JOINs, dbtable all work |
| Direct JDBC (non-UC) | PASS | Works with `customSchema` workaround |
| Unity Catalog JDBC | PASS | Works with SafeSpark memory configuration |
| UC schema discovery | PASS | Works with SafeSpark memory configuration |
| `remote_query()` aggregates | PASS | 9/9 supported patterns |
| `remote_query()` GROUP BY | EXPECTED FAIL | Subquery wrapping limitation |
| Federated queries (hybrid) | PASS | 5 validated query patterns |
| Genie NL-to-SQL federation | PASS | Cross-source queries generated correctly |

## Choosing the Right Method

| Use Case | Recommended Method |
|----------|-------------------|
| Aggregate analytics (COUNT, SUM, AVG, MIN, MAX) | UC JDBC via `remote_query()` or DataFrame API |
| Graph traversal counts | UC JDBC with NATURAL JOIN |
| Row-level data access | Neo4j Spark Connector |
| GROUP BY analytics | Neo4j Spark Connector |
| Complex Cypher (variable-length paths, graph algorithms) | Neo4j Spark Connector |
| Natural language queries | Genie over materialized Delta tables |
| Ad-hoc graph exploration | Neo4j Python Driver |

## Repository and Resources

- [neo4j-uc-integration repo](https://github.com/neo4j-partners/neo4j-uc-integration) containing the test suite, notebooks, and configuration
- [federated_lakehouse_query.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/federated_lakehouse_query.ipynb) with all 5 federated query examples
- [federated_views_agent_ready.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/federated_views_agent_ready.ipynb) with the Neo4j materialization notebook for Genie
- [Aircraft Digital Twin dataset](https://github.com/neo4j-field/databricks-neo4j-mcp-demo/tree/main/aircraft_digital_twin_data) used for all testing
- [Neo4j JDBC SQL2Cypher documentation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j Spark Connector documentation](https://neo4j.com/docs/spark/current/)
