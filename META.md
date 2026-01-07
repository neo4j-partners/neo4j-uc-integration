# Proposal: Neo4j Schema Synchronization with Unity Catalog

## Executive Summary

This document proposes a proof-of-concept approach for synchronizing Neo4j graph schema with Databricks Unity Catalog. The goal is to demonstrate how Neo4j's graph schema (labels, properties, relationships) can be discovered and mapped to queryable Unity Catalog objects.

**Scope**: This is a proof of concept only. It demonstrates the feasibility of each approach without automation, production hardening, or scheduled synchronization.

## The Problem

### Current State

The notebook's Section 8 attempts schema discovery but faces fundamental limitations:

1. **Cannot call Cypher procedures**: Spark wraps queries in subqueries, breaking native Cypher syntax like `CALL db.labels()` or `CALL db.schema.visualization()`

2. **Hardcoded label names**: The current approach requires knowing label names in advance, defeating the purpose of automatic schema discovery

3. **Fragmented schema information**: Label discovery, property discovery, and relationship discovery are separate manual processes

4. **No Unity Catalog integration**: Discovered schema is not persisted to Unity Catalog in any usable form

### What We Want to Demonstrate

A proof of concept that:
- Discovers Neo4j labels, their properties, and relationship patterns via JDBC DatabaseMetaData
- Loads the complete schema into memory as a Python data structure
- Tests multiple approaches for creating Unity Catalog objects from the in-memory schema
- Enables SQL queries against Neo4j data through UC governance

## Technical Constraints

### Unity Catalog Foreign Catalog Limitations

Research into Databricks documentation reveals a critical constraint:

**Foreign Catalogs only work with specific database types** (PostgreSQL, MySQL, Redshift, Snowflake, BigQuery, SQL Server, Oracle, Teradata). Neo4j is not in this list.

This means:
- We cannot use `CREATE FOREIGN CATALOG` with a Neo4j JDBC connection
- Unity Catalog will not automatically sync Neo4j metadata
- The `remote_query()` function does not support Neo4j connections
- We must manually create UC objects backed by the JDBC connection

### What JDBC Connections Provide

A Unity Catalog JDBC connection with a custom driver (Neo4j JDBC) enables:
- Spark DataFrame reads via `databricks.connection` option
- SQL translation (SQL queries automatically converted to Cypher)
- Schema inference from JDBC ResultSetMetaData at query time

## Proposed Solution

### Architecture Overview

The proof of concept uses a three-phase approach:

```
Phase 1: Schema Discovery (In-Memory)
    Neo4j JDBC DatabaseMetaData API
           ↓
    Extract labels, properties, relationships, types
           ↓
    Build Python dict/dataclass schema model in memory

Phase 2: Unity Catalog Registration (Test All Options)
    Option A: Views with inferred schema
    Option B: Tables with explicit schema
    Option C: Hybrid (views + schema registry table)
           ↓
    Test each approach in separate notebook cells

Phase 3: Query Execution & Verification
    SQL queries through Unity Catalog
           ↓
    Verify governance, permissions, query results
```

### Phase 1: Schema Discovery via JDBC DatabaseMetaData

The pyspark-translation-example demonstrates that Neo4j JDBC exposes complete graph schema through standard JDBC APIs.

**Approach: Direct JVM Access**

Using `spark._jvm` (Py4J gateway), call standard JDBC DatabaseMetaData methods:
- `getTables()` with type "TABLE" returns all node labels
- `getTables()` with type "RELATIONSHIP" returns relationship patterns
- `getColumns()` returns properties with SQL type mappings
- `getPrimaryKeys()` returns element ID columns

**Schema Storage: In-Memory Python Data Structure**

The discovered schema will be stored in memory as a Python dictionary or dataclass:

```
schema = {
    "labels": {
        "Aircraft": {
            "columns": [
                {"name": "aircraft_id", "type": "STRING", "nullable": True},
                {"name": "tail_number", "type": "STRING", "nullable": True},
                ...
            ],
            "primary_key": "v$id"
        },
        "Airport": { ... },
        "Flight": { ... }
    },
    "relationships": [
        {"from": "Flight", "type": "DEPARTS_FROM", "to": "Airport"},
        {"from": "Flight", "type": "ARRIVES_AT", "to": "Airport"},
        ...
    ]
}
```

This in-memory schema is then used to generate Unity Catalog DDL statements in Phase 2.

### Phase 2: Unity Catalog Table Registration

Since foreign catalogs are not available, we must manually create Unity Catalog objects. **Each option will be tested in a separate notebook cell** to compare approaches.

---

**Option A: Create Views with Inferred Schema**

Create Unity Catalog views that query through the JDBC connection. Schema is inferred at query time.

```sql
CREATE OR REPLACE VIEW neo4j_catalog.graph.aircraft AS
SELECT * FROM read_jdbc(
    connection => 'neo4j_connection',
    dbtable => 'Aircraft'
)
```

Characteristics:
- Schema is inferred from JDBC ResultSetMetaData at query time
- Always reflects current Neo4j data
- No explicit column definitions needed
- May have type inference issues with some Neo4j property types

**Test Cell**: Create view for one label, query it, verify schema inference works.

---

**Option B: Create Tables with Explicit Schema**

Create Unity Catalog tables with explicit column definitions derived from the in-memory schema.

```sql
CREATE TABLE neo4j_catalog.graph.aircraft (
    `v$id` STRING,
    aircraft_id STRING,
    tail_number STRING,
    icao24 STRING,
    model STRING,
    operator STRING,
    manufacturer STRING
)
USING JDBC
CONNECTION neo4j_connection
OPTIONS (dbtable 'Aircraft')
```

Characteristics:
- Explicit schema definition from discovered metadata
- Avoids schema inference issues
- Schema is static - won't reflect Neo4j property changes until recreated
- More control over column types

**Test Cell**: Generate DDL from in-memory schema, execute it, verify table works.

---

**Option C: Hybrid Approach**

Combine views for live data access with a schema registry table for metadata visibility.

1. **Schema Registry Table**: Store discovered Neo4j schema as UC table data
   ```sql
   CREATE TABLE neo4j_catalog.metadata.schema_registry (
       label_name STRING,
       column_name STRING,
       column_type STRING,
       is_primary_key BOOLEAN,
       discovered_at TIMESTAMP
   )
   ```

2. **Label Views**: Create views for each label (like Option A)

3. **Utility**: Query the registry to see what Neo4j schema looks like in relational terms

Characteristics:
- Schema metadata is queryable through UC
- Views provide live data access
- Registry can be refreshed independently
- Good for understanding the graph-to-relational mapping

**Test Cell**: Create schema registry, populate from in-memory schema, create views, verify both work.

---

### Phase 3: Relationship Representation (Optional Tests)

If time permits, test relationship handling approaches:

**Test: Relationship as Join View**

```sql
CREATE VIEW neo4j_catalog.graph.flight_departures AS
SELECT * FROM read_jdbc(
    connection => 'neo4j_connection',
    query => 'SELECT * FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a LIMIT 100'
)
```

This tests whether SQL JOINs correctly translate to Cypher relationship traversals through UC.

## Notebook Section 8 Cell Structure

### Cell 8.1: Introduction

Markdown cell explaining the approach and what will be tested.

### Cell 8.2: JDBC DatabaseMetaData Schema Discovery

Code cell that:
- Creates JDBC connection via `spark._jvm`
- Calls `getTables(TABLE)` to get all labels
- Calls `getTables(RELATIONSHIP)` to get relationship patterns
- Calls `getColumns()` for each label
- Builds in-memory schema dictionary
- Prints summary of discovered schema

### Cell 8.3: Display In-Memory Schema Model

Code cell that:
- Pretty-prints the discovered schema
- Shows labels with their columns and types
- Shows relationship patterns
- Displays statistics (label count, total columns, relationship count)

### Cell 8.4: Option A - Views with Inferred Schema

Code cell that:
- Generates CREATE VIEW DDL for one label (e.g., Aircraft)
- Executes the DDL
- Queries the view to verify it works
- Shows the inferred schema via DESCRIBE
- Documents any issues encountered

### Cell 8.5: Option B - Tables with Explicit Schema

Code cell that:
- Generates CREATE TABLE DDL from in-memory schema for one label
- Includes explicit column definitions
- Executes the DDL
- Queries the table to verify it works
- Compares with Option A results

### Cell 8.6: Option C - Hybrid with Schema Registry

Code cell that:
- Creates schema registry table
- Inserts discovered schema metadata
- Creates view for one label
- Queries both registry and view
- Demonstrates metadata visibility

### Cell 8.7: Verification and Comparison

Code cell that:
- Queries each created object (view from A, table from B, view+registry from C)
- Compares query results
- Tests UC governance (DESCRIBE, SHOW CREATE TABLE)
- Summarizes pros/cons of each approach observed

### Cell 8.8: Relationship View Test (Optional)

Code cell that:
- Creates a view for a relationship traversal pattern
- Tests SQL JOIN translation through UC
- Verifies relationship data is accessible

### Cell 8.9: Cleanup

Code cell that:
- Drops test tables and views created during the demo
- Provides option to keep them for further exploration

## Success Criteria

The proof of concept will be considered successful when:

1. **Schema Discovery Works**: All Neo4j labels and relationships are discovered via JDBC DatabaseMetaData without hardcoding

2. **In-Memory Schema**: Complete schema is loaded into a Python data structure that can be inspected and used

3. **Option A Works**: At least one label is queryable through a UC view with inferred schema

4. **Option B Works**: At least one label is queryable through a UC table with explicit schema from discovered metadata

5. **Option C Works**: Schema registry table is populated and queryable alongside label views

6. **Comparison Complete**: Clear understanding of trade-offs between the three approaches

## Out of Scope

The following are explicitly out of scope for this proof of concept:

- Automated schema synchronization
- Scheduled refresh jobs
- Production error handling
- Performance optimization
- Multi-label batch creation
- Schema drift detection
- CI/CD integration

These would be addressed in future work if the proof of concept is successful.

## References

### Databricks Documentation
- [Work with foreign tables](https://docs.databricks.com/aws/en/tables/foreign)
- [What is query federation?](https://docs.databricks.com/aws/en/query-federation/database-federation)
- [Query external databases using remote_query](https://docs.databricks.com/aws/en/query-federation/remote-queries)
- [JDBC Unity Catalog connection](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Federated queries (Lakehouse Federation)](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-federated-queries)

### Neo4j Documentation
- [Neo4j JDBC Driver - SQL Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
- [Neo4j JDBC Driver - DatabaseMetaData](https://neo4j.com/docs/jdbc-manual/current/)

### Project Resources
- `pyspark-translation-example/neo4j_sql_tests/jdbc_metadata.py` - Direct JDBC metadata access implementation
- `pyspark-translation-example/README.md` - Test suite documentation
