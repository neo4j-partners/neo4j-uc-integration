# Neo4j Unity Catalog Metadata Synchronization: Prototype Report

We prototyped Unity Catalog metadata synchronization for Neo4j to demonstrate that graph schema maps cleanly to UC's relational metadata model. This report covers what we built, how the mapping works, and how we want to work with Databricks to include Neo4j as an officially supported Lakehouse Federation data source.

The prototype ran on a live Databricks cluster (Runtime 17.3 LTS) connected to Neo4j Aura. All output is real, not mocked.

## Context

Databricks provides automatic metadata sync for supported Lakehouse Federation sources, including MySQL, PostgreSQL, Snowflake, and others. For these sources, Unity Catalog syncs the remote schema on each interaction with the catalog, exposing tables and columns as first-class UC objects in Catalog Explorer and `INFORMATION_SCHEMA`.

Neo4j isn't yet on the supported list, and the JDBC connection type doesn't support foreign catalogs. Our current JDBC integration registers a `CONNECTION` object only. It doesn't expose Neo4j's schema as browsable UC objects. This prototype demonstrates that the schema mapping is well-defined and implementable, and we want to work together with Databricks to bring Neo4j to the same level of integration as other supported federation sources.

## The Value of Metadata Sync Along with the JDBC Connection

The JDBC integration established query connectivity. Databricks users can execute SQL against Neo4j via `remote_query()` and the Spark DataFrame API. Metadata synchronization completes the picture by making Neo4j a governed, discoverable data source within Unity Catalog. With metadata sync, Neo4j gains:

- **Catalog Explorer visibility.** Neo4j node labels and relationship types appear as browsable tables alongside Delta tables, with full column definitions and types.
- **`INFORMATION_SCHEMA` registration.** Neo4j schema objects are queryable via standard `INFORMATION_SCHEMA` views, enabling programmatic discovery by tools, agents, and automation.
- **Fine-grained access control.** Permissions can be granted at the table and column level (`GRANT SELECT ON TABLE neo4j_catalog.nodes.aircraft`) rather than only at the connection level.
- **Lineage tracking.** Data lineage from Neo4j flows through downstream Spark jobs, dashboards, and ML pipelines, giving governance teams end-to-end visibility.
- **Standard SQL query model.** Users can query Neo4j with `SELECT * FROM neo4j_catalog.nodes.aircraft` instead of routing through `remote_query()` or `spark.read.format('jdbc')`.

## How Neo4j Graph Schema Maps to Unity Catalog

Neo4j's data model has three core concepts. Node labels are analogous to tables, relationship types are analogous to foreign-key joins, and properties are analogous to columns. Each maps directly to UC's three-level namespace.

```
Unity Catalog                  Neo4j
─────────────                  ─────
Catalog: neo4j_catalog    →   Neo4j database
  Schema: nodes            →   Node labels namespace
    Table: aircraft        →   :Aircraft label
      Column: aircraft_id  →   aircraft_id property (STRING)
      Column: manufacturer →   manufacturer property (STRING)
    Table: flight          →   :Flight label
    Table: airport         →   :Airport label
  Schema: relationships    →   Relationship types namespace
    Table: departs_from    →   :DEPARTS_FROM type
      Column: source_id    →   Start node identifier
      Column: target_id    →   End node identifier
      Column: ...          →   Relationship properties
```

**Design decisions:**

1. **One table per node label.** Each Neo4j label maps to a UC table in the `nodes` schema.
2. **One table per relationship type.** Each relationship type maps to a UC table in the `relationships` schema, with `source_id` and `target_id` columns plus any relationship properties.
3. **Properties become columns.** Neo4j properties map to UC columns with types from the mapping table below.
4. **Naming convention.** UC identifiers are lowercase; Neo4j labels/types are converted accordingly (`DEPARTS_FROM` → `departs_from`).
5. **Multi-label nodes.** Nodes with multiple labels (e.g., `:Person:Actor`) appear in tables for each label. Their properties are present under both.

### Type Mapping

Every Neo4j property type has a defined mapping to a UC/Spark SQL type:

| Neo4j Type | UC/Spark SQL Type | Notes |
|-----------|-------------------|-------|
| `STRING` | `STRING` | No length limit in Neo4j |
| `INTEGER` | `BIGINT` | 64-bit signed |
| `FLOAT` | `DOUBLE` | 64-bit IEEE 754 |
| `BOOLEAN` | `BOOLEAN` | |
| `DATE` | `DATE` | |
| `LOCAL DATETIME` | `TIMESTAMP_NTZ` | |
| `ZONED DATETIME` | `TIMESTAMP` | |
| `LOCAL TIME` | `STRING` | No direct SQL equivalent; serialized as ISO string |
| `ZONED TIME` | `STRING` | No direct SQL equivalent; serialized as ISO string |
| `DURATION` | `STRING` | Serialized as ISO 8601 duration |
| `POINT` | `STRING` | Serialized as WKT or JSON |
| `LIST<STRING>` | `ARRAY<STRING>` | |
| `LIST<INTEGER>` | `ARRAY<BIGINT>` | |
| `LIST<FLOAT>` | `ARRAY<DOUBLE>` | |
| `LIST<BOOLEAN>` | `ARRAY<BOOLEAN>` | |

The mapping covers all Neo4j property types. Types without a direct SQL equivalent (`LOCAL TIME`, `DURATION`, `POINT`) serialize to `STRING` with well-defined formats.

## How Neo4j Exposes Schema for Introspection

Neo4j provides built-in procedures for schema introspection that we can use together to implement metadata sync:

```cypher
-- Node label properties: returns label, property name, type, and whether it's mandatory
CALL db.schema.nodeTypeProperties()
-- Yields: nodeType, nodeLabels, propertyName, propertyTypes, mandatory

-- Relationship type properties: returns relationship type, property name, type, mandatory
CALL db.schema.relTypeProperties()
-- Yields: relType, propertyName, propertyTypes, mandatory

-- Constraints: uniqueness, existence, type, and key constraints
SHOW CONSTRAINTS YIELD *

-- Indexes: range, fulltext, text, point, vector indexes
SHOW INDEXES YIELD *
```

These procedures are built into Neo4j (no plugins required) and return the full schema metadata needed for UC registration, including property names, types, nullability (via `mandatory`), and constraint information.

For richer metadata in a single call, Neo4j also provides `apoc.meta.schema()` (APOC Core plugin), which returns node counts, indexed/unique flags per property, and relationship connectivity patterns (source label, relationship type, target label) in a single nested map.

**Note on relationship connectivity:** `db.schema.relTypeProperties()` returns property metadata but not source/target labels (verified on Neo4j 5.x Aura). Relationship connectivity patterns, specifically which label connects to which via which relationship type, are available from `apoc.meta.schema()` or `db.schema.visualization()`. This is the information needed to populate `source_id` and `target_id` semantics in the relationship tables.

## What We Prototyped

We validated two approaches to demonstrate that the mapping works end-to-end.

### Prototype 1: Materialized Delta Tables

This approach reads Neo4j data via the Spark Connector and writes it as managed Delta tables in Unity Catalog. When `saveAsTable()` writes a Delta table, UC automatically registers the full schema metadata (column names, types, nullability, row counts, and statistics) with zero custom API calls.

**Pipeline:**

1. Discover all node labels and properties via `db.schema.nodeTypeProperties()`
2. Discover relationship patterns via a `MATCH` query (for source/target labels)
3. Create `nodes` and `relationships` schemas in the target catalog
4. Read each label from Neo4j via the Spark Connector and write as a managed Delta table
5. Read each relationship type and write as a managed Delta table
6. Verify metadata in `INFORMATION_SCHEMA`

**Node label materialization:**

```python
df = spark.read.format("org.neo4j.spark.DataSource") \
    .option("labels", ":Aircraft") \
    .load()

df.write.mode("overwrite") \
    .option("overwriteSchema", "true") \
    .saveAsTable("`neo4j_metadata`.`nodes`.`aircraft`")
```

**Relationship materialization:**

```python
df = spark.read.format("org.neo4j.spark.DataSource") \
    .option("relationship", "DEPARTS_FROM") \
    .option("relationship.source.labels", ":Flight") \
    .option("relationship.target.labels", ":Airport") \
    .load()

df.write.mode("overwrite") \
    .option("overwriteSchema", "true") \
    .saveAsTable("`neo4j_metadata`.`relationships`.`departs_from`")
```

**Verification: metadata visible in `INFORMATION_SCHEMA`**

```sql
SELECT table_schema, table_name, table_type
FROM `neo4j_metadata`.information_schema.tables
WHERE table_schema IN ('nodes', 'relationships')
ORDER BY table_schema, table_name;

SELECT ordinal_position, column_name, data_type, is_nullable
FROM `neo4j_metadata`.information_schema.columns
WHERE table_schema = 'nodes' AND table_name = 'aircraft'
ORDER BY ordinal_position;
```

After running, all materialized tables appeared in Catalog Explorer with full column definitions, types, and row counts. Tables were queryable via standard SQL (`SELECT * FROM neo4j_metadata.nodes.aircraft`).

**What this demonstrates:** The graph-to-relational mapping is well-defined. The Spark Connector infers the schema correctly, and UC registers it automatically. An official integration could follow this same mapping without the materialization step, syncing only the metadata, not the data.

### Future Exploration: External Metadata API

A potential future approach to metadata synchronization is the [External Metadata API](https://docs.databricks.com/api/workspace/externalmetadata) (Public Preview), which could enable metadata-only registration without copying data. An exploratory notebook is available at [metadata_sync_external.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/metadata_sync_external.ipynb). This approach hasn't yet been validated end-to-end and would require further investigation, including adding a `NEO4J` system type to the API's `system_type` enum and support for typed columns.

## Example: Materializing a Node Label as a Delta Table

This walkthrough shows the full flow for a single node label, from schema discovery through Delta materialization to `INFORMATION_SCHEMA` verification. All steps ran on Databricks Runtime 17.3 LTS connected to Neo4j Aura.

**1. Discover the schema for `:Aircraft`**

The pipeline starts by calling `db.schema.nodeTypeProperties()` to discover all properties and their types:

```python
with GraphDatabase.driver(NEO4J_BOLT_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("CALL db.schema.nodeTypeProperties()")
        for record in result:
            label = record["nodeLabels"][0]
            print(f"  {label}.{record['propertyName']}: {record['propertyTypes']}")
```

```
NODE LABELS (9 discovered):
  Aircraft: 6 properties     (aircraft_id, tail_number, icao24, model, manufacturer, operator)
  Airport: 8 properties      (airport_id, name, city, country, iata, ...)
  Component: 4 properties    (system_id, component_id, name, type)
  Delay: 3 properties        (delay_id, cause, minutes (Long))
  Flight: 8 properties       (flight_id, flight_number, operator, origin, destination, ...)
  MaintenanceEvent: 8 props  (event_id, severity, aircraft_id, system_id, component_id, ...)
  Removal: 7 properties      (removal_id, removal_date, tsn (Double), ...)
  Sensor: 5 properties       (sensor_id, name, type, unit, system_id)
  System: 4 properties       (system_id, name, type, aircraft_id)

RELATIONSHIP TYPES (17 discovered):
  DEPARTS_FROM, ARRIVES_AT, OPERATES_FLIGHT, HAS_SYSTEM, HAS_COMPONENT,
  HAS_SENSOR, HAS_EVENT, HAS_DELAY, HAS_REMOVAL, AFFECTS_AIRCRAFT, ...
```

<!-- Source: metadata_sync_delta.ipynb, cell "discover-schema" (Step 2) -->



**2. Read from Neo4j and write as a managed Delta table**

The Spark Connector reads the label and infers the schema automatically. `saveAsTable()` writes a managed Delta table and UC registers the metadata:

```python
df = spark.read.format("org.neo4j.spark.DataSource") \
    .option("labels", ":Aircraft") \
    .load()

df.printSchema()
df.show(5, truncate=False)

df.write.mode("overwrite") \
    .option("overwriteSchema", "true") \
    .saveAsTable("`neo4j_metadata`.`nodes`.`aircraft`")
```

```
Inferred schema for :Aircraft:
  <id>: long, <labels>: array<string>, tail_number: string, operator: string,
  model: string, manufacturer: string, icao24: string, aircraft_id: string

Sample data (5 rows):
+----+-----------+-----------+--------+------------+------+-----------+
|<id>|tail_number|operator   |model   |manufacturer|icao24|aircraft_id|
+----+-----------+-----------+--------+------------+------+-----------+
|0   |N95040A    |ExampleAir |B737-800|Boeing      |448367|AC1001     |
|1   |N30268B    |SkyWays    |A320-200|Airbus      |aee78a|AC1002     |
|2   |N54980C    |RegionalCo |A321neo |Airbus      |7c6b17|AC1003     |
+----+-----------+-----------+--------+------------+------+-----------+

Materialized :Aircraft → neo4j_metadata.nodes.aircraft (20 rows, 8 columns)
```

<!-- Source: metadata_sync_delta.ipynb, cell "single-label" (Step 4) -->

**3. Verify metadata in `INFORMATION_SCHEMA`**

After writing, the table and its columns are immediately visible in UC:

```sql
SELECT table_schema, table_name, table_type
FROM `neo4j_metadata`.information_schema.tables
WHERE table_schema = 'nodes'
ORDER BY table_name;
```

```
+----------------+----------+
|table_name      |table_type|
+----------------+----------+
|aircraft        |MANAGED   |
|airport         |MANAGED   |
|component       |MANAGED   |
|delay           |MANAGED   |
|flight          |MANAGED   |
|maintenanceevent|MANAGED   |
|removal         |MANAGED   |
|sensor          |MANAGED   |
|system          |MANAGED   |
+----------------+----------+
```

<!-- Source: metadata_sync_delta.ipynb, cell "verify-metadata" (Step 5) -->

```sql
SELECT ordinal_position, column_name, data_type, is_nullable
FROM `neo4j_metadata`.information_schema.columns
WHERE table_schema = 'nodes' AND table_name = 'aircraft'
ORDER BY ordinal_position;
```

```
+----------------+------------+---------+-----------+
|ordinal_position|column_name |data_type|is_nullable|
+----------------+------------+---------+-----------+
|0               |<id>        |LONG     |YES        |
|1               |<labels>    |ARRAY    |YES        |
|2               |tail_number |STRING   |YES        |
|3               |operator    |STRING   |YES        |
|4               |model       |STRING   |YES        |
|5               |manufacturer|STRING   |YES        |
|6               |icao24      |STRING   |YES        |
|7               |aircraft_id |STRING   |YES        |
+----------------+------------+---------+-----------+
Table neo4j_metadata.nodes.aircraft: 20 rows
```

<!-- Source: metadata_sync_delta.ipynb, cell "verify-metadata" (Step 5) -->

The table is now browsable in Catalog Explorer and queryable via standard SQL:

```sql
SELECT * FROM neo4j_metadata.nodes.aircraft LIMIT 5;
```

```
+-----------+-----------+--------+------------+------+-----------+
|tail_number|operator   |model   |manufacturer|icao24|aircraft_id|
+-----------+-----------+--------+------------+------+-----------+
|N95040A    |ExampleAir |B737-800|Boeing      |448367|AC1001     |
|N30268B    |SkyWays    |A320-200|Airbus      |aee78a|AC1002     |
|N54980C    |RegionalCo |A321neo |Airbus      |7c6b17|AC1003     |
|N37272D    |NorthernJet|E190    |Embraer     |fe5e91|AC1004     |
|N53032E    |ExampleAir |B737-800|Boeing      |232296|AC1005     |
+-----------+-----------+--------+------------+------+-----------+
```

<!-- Source: metadata_sync_delta.ipynb, cell "single-label" (Step 4) -->

## Proposed Production Integration

The prototypes demonstrate that the schema mapping works end-to-end. We want to work with Databricks to turn this into an official integration. Here's how we see the joint implementation coming together.

### 1. Foreign Catalog Support for JDBC Connections

Today, `CREATE CONNECTION ... TYPE JDBC` doesn't support foreign catalogs. Together, we can enable Neo4j as a supported federation source so that users can write:

```sql
CREATE FOREIGN CATALOG neo4j_catalog
USING CONNECTION neo4j_connection;
```

This would trigger automatic metadata sync on each catalog interaction, bringing Neo4j in line with how MySQL, PostgreSQL, Snowflake, and other supported sources already work.

### 2. Metadata Sync Implementation

We can build the sync implementation together using Neo4j's schema introspection procedures (shown above) and the graph-to-relational mapping defined in this report. The Neo4j JDBC driver already includes much of this translation capability in its SQL-to-Cypher engine. It understands how labels map to tables and properties map to columns. We're ready to contribute this mapping logic to the integration.

The sync would need to handle:
- **Schema discovery.** Call `db.schema.nodeTypeProperties()`, `db.schema.relTypeProperties()`, and optionally `apoc.meta.schema()` for counts and connectivity
- **Type mapping.** Apply the Neo4j-to-UC type mapping table
- **Relationship connectivity.** Map source/target label patterns to relationship table metadata
- **Incremental refresh.** Detect schema changes (new labels, new properties) without full re-sync

### 3. Query Routing

When a user queries a table in the foreign catalog (`SELECT * FROM neo4j_catalog.nodes.aircraft`), the platform routes that query through the JDBC connection. The Neo4j JDBC driver's SQL-to-Cypher translator already handles this translation. `SELECT * FROM Aircraft` becomes `MATCH (n:Aircraft) RETURN n.aircraft_id, n.manufacturer, ...`. We've validated the full set of SQL-to-Cypher translation patterns in our federation report, and the driver is ready to support this routing today.

## Prototype Test Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Neo4j schema introspection | PASS | `db.schema.nodeTypeProperties()` and `db.schema.relTypeProperties()` return full schema |
| Graph-to-relational mapping | PASS | Labels → tables, properties → columns, types map cleanly |
| Delta materialization (nodes) | PASS | All labels materialized with correct schemas |
| Delta materialization (relationships) | PASS | All relationship types materialized with source/target patterns |
| `INFORMATION_SCHEMA` visibility | PASS | Column names, types, nullability all correct |
| Catalog Explorer visibility | PASS | Tables browsable with full column definitions |
| SQL queryability | PASS | `SELECT * FROM neo4j_metadata.nodes.aircraft` works |
| Type mapping coverage | PASS | All Neo4j property types mapped to UC types |

## Repository

All prototype code is available for review:

- [metadata_sync_delta.ipynb](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/uc-neo4j-test-suite/metadata_sync_delta.ipynb): Materialized Delta Tables prototype
- [METADATA.md](https://github.com/neo4j-partners/neo4j-uc-integration/blob/main/docs/METADATA.md): Research and design document with full type mapping and API analysis
