# Proposal: Neo4j as a First-Class Lakehouse Federation Data Source

This document proposes adding Neo4j as a natively supported connection type (`TYPE NEO4J`) in Unity Catalog's Lakehouse Federation. We have built a working prototype using the existing generic JDBC path (`TYPE JDBC`) with Neo4j's JDBC driver in a bring-your-own-driver configuration. The prototype is fully functional and we want to work with Databricks to make Neo4j an officially supported integration.

We understand that to be considered for official support, we need to deliver a working prototype of UC Federation with the Neo4j JDBC driver and a detailed proposal for how first-class UC Federation support would work. This report includes both.

All queries shown here ran on a live Databricks cluster (Runtime 17.3 LTS) connected to Neo4j Aura. The output is real, not mocked.

## Current State: Generic JDBC Path (TYPE JDBC)

Today, connecting Neo4j to Unity Catalog requires using `TYPE JDBC` -- the generic JDBC connector -- with a bring-your-own-driver configuration. The integration uses two JARs uploaded to a Unity Catalog Volume and a single `CREATE CONNECTION` statement. Once in place, Neo4j is queryable through `remote_query()`, the Spark DataFrame JDBC reader, or materialized Delta tables for Genie.

### JDBC Driver JARs

| JAR | Purpose |
|-----|---------|
| `neo4j-jdbc-full-bundle-6.10.3.jar` | JDBC driver with built-in SQL-to-Cypher translation engine |
| `neo4j-jdbc-translator-sparkcleaner-6.10.3.jar` | Preprocesses Spark-generated SQL artifacts before translation |

The spark cleaner JAR handles a Spark-specific behavior. When Spark connects to any database via JDBC, it wraps queries in a subquery for schema probing:

```sql
SELECT * FROM (
    <original_query>
) SPARK_GEN_SUBQ_0 WHERE 1=0
```

The cleaner detects the `SPARK_GEN_SUBQ` marker, extracts the inner query, validates whether it's Cypher, and if so wraps it with a `/*+ NEO4J FORCE_CYPHER */` hint to bypass further SQL translation. Discovery is automatic via Java SPI when the JAR is on the classpath.

### UC Connection

A single SQL statement creates the connection:

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

The `enableSQLTranslation=true` parameter in the JDBC URL activates the driver's SQL-to-Cypher translator. The `ENVIRONMENT` block loads both JARs from the UC Volume into the SafeSpark sandbox. The `externalOptionsAllowList` includes `customSchema`, which is needed for the Spark DataFrame API (explained in the schema inference section below).

Credentials are stored in a Databricks secret scope (`neo4j-uc-creds`) with keys for host, user, password, JAR paths, and connection name. A `setup.sh` script in the test suite reads from a `.env` file and configures these secrets automatically using the Databricks CLI.

### Prerequisites

Two preview features must be enabled in the workspace:

- **Custom JDBC on UC Compute** for loading custom JDBC driver JARs in UC connections
- **`remote_query` table-valued function** for the `remote_query()` SQL function

For federated queries that also use the Neo4j Spark Connector (Queries 3-5), the connector must be installed as a cluster library (`org.neo4j:neo4j-connector-apache-spark:5.3.10`). The UC JDBC connection itself does not require cluster libraries since the JARs load from the UC Volume.

## How SQL-to-Cypher Translation Works

The Neo4j JDBC driver translates standard SQL into Cypher automatically. Neo4j node labels become SQL tables, relationship types become JOIN targets, and node properties become columns. Here are the translations we validated:

| SQL | Cypher |
|-----|--------|
| `SELECT COUNT(*) FROM Flight` | `MATCH (n:Flight) RETURN count(n)` |
| `SELECT COUNT(*) FROM Aircraft WHERE manufacturer = 'Boeing'` | `MATCH (n:Aircraft) WHERE n.manufacturer = 'Boeing' RETURN count(n)` |
| `SELECT COUNT(DISTINCT manufacturer) FROM Aircraft` | `MATCH (n:Aircraft) RETURN count(DISTINCT n.manufacturer)` |
| `FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a` | `MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport)` |

The `NATURAL JOIN` syntax is how graph traversals work in SQL. The first table is the source node label, the middle "table" is the relationship type, and the last table is the target node label. This maps directly to Cypher pattern matching, which means multi-hop graph traversals can be expressed as standard SQL JOINs.

## Two Ways to Query

Once the connection exists, there are two ways to use it.

### remote_query() SQL Function

The `remote_query()` function lets SQL queries reference the connection directly, without PySpark:

```sql
SELECT * FROM remote_query(
    'neo4j_connection',
    query => 'SELECT COUNT(*) AS cnt FROM Flight'
)
```

This is pure SQL, useful for dashboards, SQL notebooks, and cases where the query result feeds directly into a larger SQL statement. It handles schema inference internally, so `customSchema` is not required. The federated query examples in this report use `remote_query()` extensively for aggregate metrics.

### Spark DataFrame API

The DataFrame API uses `spark.read.format("jdbc")` with the `databricks.connection` option:

```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight") \
    .option("customSchema", "cnt LONG") \
    .load()
```

This returns a standard Spark DataFrame that can be joined with Delta tables, registered as a temp view, or used in any Spark operation.

### The customSchema Requirement (Generic JDBC Path)

Spark's JDBC reader runs a schema inference step before executing any query, sending a modified version with `WHERE 1=0` to get column metadata. Neo4j's JDBC driver returns `NullType()` for all columns during this step, causing Spark to fail with `No column has been read prior to this call`.

The fix is to always provide an explicit `customSchema` option when using the DataFrame API:

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

Column names in the schema must match the aliases in the SQL query, and the types must match what Neo4j returns (typically `LONG` for counts, `STRING` for text, `DOUBLE` for floats). This applies to every DataFrame API query through the UC JDBC connection. The `remote_query()` function does not have this requirement. With a first-class connector, native schema inference would handle this automatically.

## Proposed First-Class Support: TYPE NEO4J Connection

The prototype above works using `TYPE JDBC` -- the generic connector for any JDBC-compatible database. We are proposing a first-class `TYPE NEO4J` connection type that would bring Neo4j to parity with natively supported data sources like PostgreSQL, Snowflake, and SQL Server. Here is what that integration would look like and what Neo4j is prepared to build in partnership with Databricks.

### Connection Creation

Today (generic JDBC):

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
  user secret('scope', 'user'),
  password secret('scope', 'password'),
  driver 'org.neo4j.jdbc.Neo4jDriver',
  externalOptionsAllowList 'dbtable,query,customSchema'
)
```

Proposed (first-class):

```sql
CREATE CONNECTION neo4j_connection TYPE NEO4J
OPTIONS (
  host 'host:7687',
  user secret('scope', 'user'),
  password secret('scope', 'password')
)
```

The JDBC driver and Spark cleaner JARs would ship as part of the integration. No UC Volume upload, no `java_dependencies`, no `externalOptionsAllowList`, no manual driver class specification.

### Foreign Catalog Support

Today, `CREATE FOREIGN CATALOG` is not supported with generic JDBC connections. Users must use `remote_query()` or the DataFrame API with explicit query strings.

With `TYPE NEO4J`, the integration could support:

```sql
CREATE FOREIGN CATALOG neo4j_catalog USING CONNECTION neo4j_connection
```

This would expose Neo4j node labels as tables and node properties as columns inside a UC catalog, making Neo4j data browsable in Catalog Explorer alongside Delta tables and other federated sources. The Neo4j JDBC driver already implements `DatabaseMetaData` APIs that map graph schema to relational metadata -- node labels as tables, properties as columns, relationship types as foreign key relationships -- so the schema discovery infrastructure exists.

### Automatic Schema Inference

Today, Spark's JDBC schema inference sends `SELECT * FROM (query) WHERE 1=0` to the driver. The Neo4j JDBC driver returns `NullType()` for all columns during this probe, so every DataFrame API query requires a manual `customSchema` option specifying column names and types.

A first-class connector would implement schema inference by querying Neo4j's schema metadata (node labels, property keys, property types) directly, making the `customSchema` workaround unnecessary. The Neo4j JDBC driver already exposes this metadata through standard `DatabaseMetaData` APIs.

### SafeSpark Sandbox Defaults

Today, the Neo4j JDBC driver's SQL-to-Cypher translation engine (ANTLR parser, Cypher AST, translation rules) loads more classes than typical JDBC drivers. The default SafeSpark sandbox metaspace is too small, causing the sandboxed JVM to crash. Users must add three Spark configuration properties to every cluster (see the SafeSpark section below for details).

A first-class connector would include appropriate sandbox defaults for the Neo4j driver, similar to how other native connectors configure their sandbox environments.

### Broader Query Pattern Support

Today, Spark's subquery wrapping (`SELECT * FROM (query) SPARK_GEN_SUBQ_N WHERE 1=0`) interacts with the Neo4j SQL translator in ways that block GROUP BY, ORDER BY, non-aggregate SELECT, and LIMIT. The driver handles all of these correctly outside the Spark wrapper. A first-class connector could either:

1. Skip the subquery wrapping for Neo4j queries (as other native connectors do), or
2. Use the Neo4j JDBC driver's spark-cleaner module with deeper integration to handle the wrapping transparently.

This would unlock row-level data access, GROUP BY, ORDER BY, and LIMIT through the UC connection, giving users a single unified query path for all patterns.

## Prototype Validation: Query Patterns

We ran a 12-test suite against a live Neo4j Aura instance through the UC JDBC connection. Total execution time was approximately 194 seconds, with most time spent on connection initialization rather than query execution.

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

### Patterns Blocked by Generic JDBC Subquery Wrapping (3/3 confirmed)

| Pattern | Generic JDBC Limitation |
|---------|------------------------|
| GROUP BY | Invalid inside the subquery wrapper Spark generates |
| Non-aggregate SELECT | Same subquery limitation |
| ORDER BY | Same subquery limitation |

Through the generic JDBC path, UC JDBC works for aggregate analytics (COUNT, SUM, AVG, MIN, MAX) with optional WHERE filters and NATURAL JOINs. Row-level data access, GROUP BY, ORDER BY, and HAVING are blocked by Spark's subquery wrapping interacting with the Neo4j SQL translator. The Neo4j driver handles all of these correctly outside the Spark wrapper -- a first-class connector would open up these patterns. For the prototype, the Neo4j Spark Connector covers them.

## Two Federation Methods

The integration supports two complementary methods for combining Neo4j graph data with Delta lakehouse tables:

| Method | Pros | Cons |
|--------|------|------|
| `remote_query()` via UC JDBC | Pure SQL, no cluster library needed, UC governed | Aggregate-only (no GROUP BY, ORDER BY) |
| Neo4j Spark Connector | Full Cypher support, row-level data, GROUP BY | Requires cluster library, no UC governance |

The federated queries in our test suite use both methods, choosing whichever fits the query pattern. The most comprehensive example (Query 5) uses both simultaneously in a single analysis. With a first-class `TYPE NEO4J` connector, these would converge into a single unified query path through the UC connection.

## Demo Dataset: Aircraft Digital Twin

We validated the integration against a synthetic aerospace IoT dataset modeling a fleet of 20 aircraft over 90 days. The data is split across both systems based on what each does best:

| Database | Data | Volume |
|----------|------|--------|
| Delta Lakehouse | Sensor telemetry, aircraft metadata, system and sensor catalogs | 345,600 sensor readings, 20 aircraft, 80 systems, 160 sensors |
| Neo4j Graph | Flights, airports, maintenance events, component topology | 800 flights, 12 airports, 300 maintenance events |

High-volume time-series analytics run in Delta. Relationship traversals and topology queries run in Neo4j. Federated queries join both to answer questions neither database could answer alone.

## Federated Query Examples

All source code is in the [federated_lakehouse_query.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/federated_lakehouse_query.ipynb) notebook.

### Query 1: Verify Data Sources

Confirms both sides are accessible before running federated queries. Delta tables are counted with standard SQL; Neo4j is verified with `remote_query()` calls, including a graph traversal test:

```sql
SELECT * FROM remote_query('neo4j_uc_connection',
    query => 'SELECT COUNT(*) AS cnt
              FROM Flight f
              NATURAL JOIN DEPARTS_FROM r
              NATURAL JOIN Airport a')
```

This exercises the full chain: `remote_query()` to UC JDBC connection to Neo4j JDBC driver to SQL-to-Cypher translation to Cypher execution against Neo4j Aura.

Live output:

```
DELTA LAKEHOUSE TABLES
  aircraft: 20 rows
  systems: 80 rows
  sensors: 160 rows
  sensor_readings: 345,600 rows

Sample aircraft data:
+-----------+-----------+--------+------------+-----------+
|aircraft_id|tail_number|model   |manufacturer|operator   |
+-----------+-----------+--------+------------+-----------+
|AC1001     |N95040A    |B737-800|Boeing      |ExampleAir |
|AC1002     |N30268B    |A320-200|Airbus      |SkyWays    |
|AC1003     |N54980C    |A321neo |Airbus      |RegionalCo |
|AC1004     |N37272D    |E190    |Embraer     |NorthernJet|
|AC1005     |N53032E    |B737-800|Boeing      |ExampleAir |
+-----------+-----------+--------+------------+-----------+
```

### Query 2: Fleet Summary (Pure SQL Federation)

A single SQL statement that CROSS JOINs four `remote_query()` calls (maintenance event counts, critical event counts, flight counts, graph traversals) with a Delta subquery computing fleet-wide sensor averages across 345K+ readings:

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
+------------------------+---------------+-------------+--------------------------+---------------+-----------------+-----------------+----------------+--------------+
|total_maintenance_events|critical_events|total_flights|flight_airport_connections|avg_egt_celsius|avg_vibration_ips|avg_fuel_flow_kgs|avg_n1_speed_rpm|total_readings|
+------------------------+---------------+-------------+--------------------------+---------------+-----------------+-----------------+----------------+--------------+
|300                     |0              |800          |800                       |671.6          |0.2659           |1.39             |4768.0          |345600        |
+------------------------+---------------+-------------+--------------------------+---------------+-----------------+-----------------+----------------+--------------+
```

This pattern works because `remote_query()` returns a single-row table per call, making CROSS JOINs natural for combining aggregate metrics. No GROUP BY needed, so it stays within the UC JDBC supported patterns.

### Query 3: Sensor Health + Maintenance Correlation (Spark Connector)

This query needs per-aircraft grouping, which requires GROUP BY, which means `remote_query()` is out. Instead, maintenance events are loaded from Neo4j via the Spark Connector into a temp view, then JOINed with Delta sensor data in standard Spark SQL:

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

The federated SQL then JOINs three CTEs: `aircraft_ref` from Delta, `sensor_health` aggregating EGT and vibration per aircraft from Delta, and `maintenance_summary` grouping Neo4j events by aircraft and severity. The result correlates sensor health with maintenance frequency across all 20 aircraft.

Live output:

```
+-----------+--------+-----------+------------+--------+-----+-----+---------+---------+-----------+-----------+
|tail_number|model   |operator   |maint_events|critical|major|minor|avg_egt_c|max_egt_c|avg_vib_ips|max_vib_ips|
+-----------+--------+-----------+------------+--------+-----+-----+---------+---------+-----------+-----------+
|N76758N    |A320-200|SkyWays    |26          |7       |13   |6    |671.6    |698.2    |0.2659     |0.4911     |
|N53032E    |B737-800|ExampleAir |25          |8       |9    |8    |671.6    |698.4    |0.266      |0.4913     |
|N54980C    |A321neo |RegionalCo |20          |8       |6    |6    |671.6    |697.8    |0.266      |0.4898     |
|N46224T    |E190    |NorthernJet|18          |4       |9    |5    |671.6    |697.1    |0.2661     |0.4922     |
|N30268B    |A320-200|SkyWays    |18          |6       |8    |4    |671.6    |697.2    |0.2659     |0.4907     |
|N86057G    |A321neo |RegionalCo |18          |6       |4    |8    |671.6    |698.5    |0.2659     |0.4874     |
|N84110I    |B737-800|ExampleAir |17          |6       |4    |7    |671.6    |699.3    |0.2659     |0.4912     |
|N37272D    |E190    |NorthernJet|15          |6       |4    |5    |671.6    |698.3    |0.266      |0.4875     |
|N96107S    |A321neo |RegionalCo |15          |3       |3    |9    |671.6    |697.6    |0.2659     |0.4922     |
|N81338F    |A320-200|SkyWays    |14          |6       |3    |5    |671.6    |698.8    |0.2659     |0.4943     |
|N15332P    |E190    |NorthernJet|14          |2       |4    |8    |671.6    |697.3    |0.2658     |0.4901     |
|N13211H    |E190    |NorthernJet|13          |6       |3    |4    |671.6    |699.1    |0.266      |0.4897     |
|N26760M    |B737-800|ExampleAir |13          |6       |5    |2    |671.6    |697.0    |0.2659     |0.4884     |
|N44342Q    |B737-800|ExampleAir |13          |5       |2    |6    |671.6    |697.9    |0.2658     |0.4953     |
|N32276J    |A320-200|SkyWays    |12          |3       |4    |5    |671.6    |698.9    |0.266      |0.4929     |
|N89365K    |A321neo |RegionalCo |12          |5       |2    |5    |671.6    |696.9    |0.2659     |0.4898     |
|N95040A    |B737-800|ExampleAir |11          |5       |4    |2    |671.6    |697.8    |0.2659     |0.4886     |
|N84703L    |E190    |NorthernJet|10          |5       |1    |4    |671.6    |698.3    |0.2659     |0.4976     |
|N65164O    |A321neo |RegionalCo |9           |3       |2    |4    |671.7    |697.3    |0.2659     |0.4902     |
|N63098R    |A320-200|SkyWays    |7           |1       |4    |2    |671.6    |699.3    |0.2658     |0.4959     |
+-----------+--------+-----------+------------+--------+-----+-----+---------+---------+-----------+-----------+
```

### Query 4: Flight Operations + Engine Performance

Same pattern as Query 3 with a different angle. Flight nodes are loaded from Neo4j via Spark Connector, grouped by aircraft to compute flight counts and unique origin/destination airports, then INNER JOINed with engine-specific sensor readings (filtered to `sys.type = 'Engine'`) from Delta. The result shows aircraft utilization correlated with engine health metrics (EGT, fuel flow, N1 speed).

Live output:

```
+-----------+--------+-----------+-------------+-------+------------+---------+--------+------+
|tail_number|model   |operator   |total_flights|origins|destinations|avg_egt_c|fuel_kgs|n1_rpm|
+-----------+--------+-----------+-------------+-------+------------+---------+--------+------+
|N86057G    |A321neo |RegionalCo |51           |12     |12          |671.6    |1.39    |4768.0|
|N63098R    |A320-200|SkyWays    |48           |11     |12          |671.6    |1.39    |4768.0|
|N89365K    |A321neo |RegionalCo |48           |12     |12          |671.6    |1.39    |4768.0|
|N95040A    |B737-800|ExampleAir |47           |12     |12          |671.6    |1.39    |4768.0|
|N76758N    |A320-200|SkyWays    |46           |12     |12          |671.6    |1.39    |4768.0|
|N15332P    |E190    |NorthernJet|46           |10     |11          |671.6    |1.39    |4768.0|
|N81338F    |A320-200|SkyWays    |45           |12     |12          |671.6    |1.39    |4768.0|
|N84110I    |B737-800|ExampleAir |43           |12     |12          |671.6    |1.39    |4768.0|
|N30268B    |A320-200|SkyWays    |41           |12     |12          |671.6    |1.39    |4768.0|
|N96107S    |A321neo |RegionalCo |41           |12     |12          |671.6    |1.39    |4768.0|
|N44342Q    |B737-800|ExampleAir |41           |12     |12          |671.6    |1.39    |4768.0|
|N46224T    |E190    |NorthernJet|40           |12     |10          |671.6    |1.39    |4768.0|
|N84703L    |E190    |NorthernJet|40           |12     |12          |671.6    |1.39    |4768.0|
|N13211H    |E190    |NorthernJet|39           |9      |12          |671.6    |1.39    |4768.0|
|N54980C    |A321neo |RegionalCo |34           |12     |11          |671.6    |1.39    |4768.0|
|N32276J    |A320-200|SkyWays    |33           |12     |12          |671.6    |1.39    |4768.0|
|N37272D    |E190    |NorthernJet|30           |11     |10          |671.6    |1.39    |4768.0|
|N65164O    |A321neo |RegionalCo |30           |12     |12          |671.7    |1.39    |4768.0|
|N26760M    |B737-800|ExampleAir |30           |11     |12          |671.6    |1.39    |4769.0|
|N53032E    |B737-800|ExampleAir |27           |10     |12          |671.6    |1.39    |4768.0|
+-----------+--------+-----------+-------------+-------+------------+---------+--------+------+
```

### Query 5: Fleet Health Dashboard (Hybrid)

The most comprehensive query combines both federation methods simultaneously:

- **`remote_query()`** provides a fleet-wide graph traversal metric (Flight-[:DEPARTS_FROM]->Airport connections: 800)
- **Spark Connector temp views** provide per-aircraft maintenance events and flight counts from Neo4j
- **Delta tables** provide per-aircraft sensor aggregates (EGT, vibration, fuel flow)

Everything LEFT JOINs on `aircraft_id`, sorted by critical maintenance events descending:

Live output:

```
Graph traversal (Flight)-[:DEPARTS_FROM]->(Airport): 800 connections

+-----------+--------+-----------+-------+------------+--------+-----+-------+--------+--------+
|tail_number|model   |operator   |flights|maint_events|critical|egt_c|vib_ips|fuel_kgs|readings|
+-----------+--------+-----------+-------+------------+--------+-----+-------+--------+--------+
|N53032E    |B737-800|ExampleAir |27     |25          |8       |671.6|0.266  |1.39    |17280   |
|N54980C    |A321neo |RegionalCo |34     |20          |8       |671.6|0.266  |1.39    |17280   |
|N76758N    |A320-200|SkyWays    |46     |26          |7       |671.6|0.2659 |1.39    |17280   |
|N30268B    |A320-200|SkyWays    |41     |18          |6       |671.6|0.2659 |1.39    |17280   |
|N86057G    |A321neo |RegionalCo |51     |18          |6       |671.6|0.2659 |1.39    |17280   |
|N84110I    |B737-800|ExampleAir |43     |17          |6       |671.6|0.2659 |1.39    |17280   |
|N37272D    |E190    |NorthernJet|30     |15          |6       |671.6|0.266  |1.39    |17280   |
|N81338F    |A320-200|SkyWays    |45     |14          |6       |671.6|0.2659 |1.39    |17280   |
|N13211H    |E190    |NorthernJet|39     |13          |6       |671.6|0.266  |1.39    |17280   |
|N26760M    |B737-800|ExampleAir |30     |13          |6       |671.6|0.2659 |1.39    |17280   |
|N44342Q    |B737-800|ExampleAir |41     |13          |5       |671.6|0.2658 |1.39    |17280   |
|N89365K    |A321neo |RegionalCo |48     |12          |5       |671.6|0.2659 |1.39    |17280   |
|N95040A    |B737-800|ExampleAir |47     |11          |5       |671.6|0.2659 |1.39    |17280   |
|N84703L    |E190    |NorthernJet|40     |10          |5       |671.6|0.2659 |1.39    |17280   |
|N46224T    |E190    |NorthernJet|40     |18          |4       |671.6|0.2661 |1.39    |17280   |
|N96107S    |A321neo |RegionalCo |41     |15          |3       |671.6|0.2659 |1.39    |17280   |
|N32276J    |A320-200|SkyWays    |33     |12          |3       |671.6|0.266  |1.39    |17280   |
|N65164O    |A321neo |RegionalCo |30     |9           |3       |671.7|0.2659 |1.39    |17280   |
|N15332P    |E190    |NorthernJet|46     |14          |2       |671.6|0.2658 |1.39    |17280   |
|N63098R    |A320-200|SkyWays    |48     |7           |1       |671.6|0.2658 |1.39    |17280   |
+-----------+--------+-----------+-------+------------+--------+-----+-------+--------+--------+
```

This demonstrates both federation methods coexisting in a single analysis: `remote_query()` for fleet-wide aggregate metrics, Spark Connector for row-level Neo4j data that requires grouping, and Delta tables as the foundation for time-series sensor analytics.

## Genie Integration: Natural Language Access

We extended the integration to support natural language queries through Genie by materializing Neo4j data as managed Delta tables.

### Why Materialization

Live UC views over `remote_query()` would be the ideal approach, but two schema-inference limitations prevent it:

| Approach | Problem |
|----------|---------|
| `remote_query()` with `query` parameter | Spark wraps the inner query in a subquery; Neo4j's translator can't parse the nested structure |
| `remote_query()` with `dbtable` parameter | Spark issues `SELECT * FROM Label WHERE 1=0`; Neo4j JDBC returns `NullType` for all columns, so all values come back as NULL |

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

The same pattern materializes `neo4j_flights`, `neo4j_airports`, and `neo4j_flight_airports`. Data is a point-in-time snapshot; re-running the materialization notebook refreshes it.

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

This federates across three data sources (Neo4j flights, Neo4j maintenance, Delta sensors) in a single generated query. The LLM never sees Cypher, and the user never writes SQL.

Results across all 20 aircraft showed consistent EGT values (671.55-671.66 C) while flight counts (27-51) and maintenance events (7-26) varied more widely, demonstrating that the cross-source JOINs produced coherent analytical results.

### Agent Integration Patterns

The Genie space supports programmatic access through either the Genie Managed MCP Server (for agent integration) or the Genie Conversation API (for direct app integration). Three patterns are viable:

1. **Genie as standalone agent**, handling all queries when they map to SQL over the unified table set
2. **Multi-agent with Genie + DBSQL MCP**, where a supervisor routes between Genie for NL-to-SQL and DBSQL for ad-hoc federated SQL including `remote_query()` calls
3. **Agent Bricks supervisor** coordinating a Genie sub-agent with other agents (for example, a RAG agent over unstructured maintenance manuals)

## Prototype Test Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Network connectivity | PASS | TCP to Neo4j port 7687 |
| Neo4j Python Driver | PASS | Bolt protocol, credentials validated |
| Neo4j Spark Connector | PASS | `org.neo4j.spark.DataSource` reads and queries work |
| Neo4j JDBC SQL-to-Cypher | PASS | Aggregates, JOINs, dbtable all work |
| Direct JDBC (non-UC) | PASS | Works with `customSchema` |
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
| Graph traversal counts (relationships between labels) | UC JDBC with NATURAL JOIN |
| Row-level data access | Neo4j Spark Connector |
| GROUP BY analytics | Neo4j Spark Connector |
| Complex Cypher (variable-length paths, graph algorithms) | Neo4j Spark Connector |
| Natural language queries | Genie over materialized Delta tables |
| Ad-hoc graph exploration | Neo4j Python Driver |

## What First-Class Support Would Enable

The following are specific areas where a native `TYPE NEO4J` connection type would improve the user experience over the current generic JDBC path.

| Current Limitation (TYPE JDBC) | Impact | How TYPE NEO4J Resolves It |
|-------------------------------|--------|---------------------------|
| No GROUP BY / ORDER BY / LIMIT through UC JDBC | Cannot do per-entity aggregation or sorting at the Neo4j source | Native connector skips Spark's subquery wrapping, enabling full SQL pattern support |
| `customSchema` required on every DataFrame API query | Users must know exact column names and types before querying | Native schema inference from Neo4j's metadata (labels, property keys, types) |
| Manual SafeSpark memory tuning required | Cluster config must include 3 Spark properties or connection crashes | Bundled driver with appropriate sandbox defaults |
| Bring-your-own-driver JAR management | Users must download, upload, and version-manage 2 JARs in a UC Volume | Driver ships with the integration; no user-managed JARs |
| No foreign catalog support | Cannot browse Neo4j schema in Catalog Explorer | `CREATE FOREIGN CATALOG` exposes labels as tables |
| Materialized tables required for Genie | Neo4j data in Genie is point-in-time snapshots requiring manual refresh | Live foreign catalog tables eliminate materialization step |
| Neo4j JDBC SQL translation covers basic patterns | Complex Cypher (variable-length paths, APOC procedures) won't translate from SQL | Native connector could support Cypher passthrough alongside SQL translation |

## SafeSpark Configuration

During prototype development, the UC JDBC connection initially failed with `Connection was closed before the operation completed`. We worked with Databricks engineering to identify the root cause: the Neo4j JDBC driver loads more classes during initialization than a typical JDBC driver because it bundles the SQL-to-Cypher translation engine (ANTLR parser, Cypher AST, translation rules). The default SafeSpark sandbox metaspace allocation needed to be increased for that class loading.

Together we identified three Spark configuration properties that resolve this:

```
spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
spark.databricks.safespark.jdbcSandbox.size.default.mib 512
```

These go in the cluster's Advanced Options > Spark > Spark Config. With these settings in place, all UC JDBC tests pass consistently. The test notebook (`neo4j_databricks_sql_translation.ipynb`) includes a systematic test progression from network connectivity through Python driver, Spark Connector, direct JDBC, and finally UC JDBC, which was the methodology used to isolate the SafeSpark issue from other potential failure points.

With a first-class `TYPE NEO4J` connection, these sandbox parameters would be set automatically as part of the connector configuration.

## Repository and Resources

- [neo4j-uc-integration repo](https://github.com/neo4j-partners/neo4j-uc-integration) containing the test suite, notebooks, and configuration
- [federated_lakehouse_query.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/federated_lakehouse_query.ipynb) with all 5 federated query examples
- [neo4j_databricks_sql_translation.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) with the full UC JDBC test progression
- [federated_views_agent_ready.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/federated_views_agent_ready.ipynb) with the Neo4j materialization notebook for Genie
- [Aircraft Digital Twin dataset](https://github.com/neo4j-field/databricks-neo4j-mcp-demo/tree/main/aircraft_digital_twin_data) used for all testing
- [Neo4j JDBC SQL2Cypher documentation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j Spark Connector documentation](https://neo4j.com/docs/spark/current/)
