# Neo4j Unity Catalog JDBC Test Suite

A diagnostic test suite for validating Neo4j JDBC connectivity through Databricks Unity Catalog.

## Notebook Status

| Notebook | Status | Description |
|----------|--------|-------------|
| `neo4j_databricks_sql_translation.ipynb` | **FAIL** | **SafeSpark incompatibility - blocked** |
| `neo4j_schema_test.ipynb` | **FAIL** | **SafeSpark incompatibility - blocked** |

## Notebooks

### neo4j_databricks_sql_translation.ipynb
Full test suite with all sections (1-8):
- Section 1: Environment Information
- Section 2: Network Connectivity Test
- Section 3: Neo4j Python Driver Test
- Section 4: Neo4j Spark Connector Test
- Section 5: Direct JDBC Tests
- Section 6: Unity Catalog JDBC Connection Setup
- Section 7: Unity Catalog JDBC Tests
- Section 8: Schema Synchronization POC

### neo4j_schema_test.ipynb
Focused notebook for schema testing (Sections 1, 3, 8 only):
- Section 1: Environment Information
- Section 3: Neo4j Python Driver Test
- Section 8: Schema Synchronization POC

## Overview

This test suite runs on a Databricks cluster and validates:

1. **Environment** - Python version, Neo4j driver availability, configuration
2. **Neo4j Driver** - Direct connectivity using the Neo4j Python driver (Bolt protocol)
3. **Unity Catalog JDBC** - JDBC connectivity through UC's SafeSpark wrapper

## Prerequisites

### 1. Neo4j JDBC Driver JARs

Upload **both** Neo4j JDBC JAR files to a Unity Catalog Volume:

```sql
-- Create a volume for JDBC drivers
CREATE SCHEMA IF NOT EXISTS main.jdbc_drivers;
CREATE VOLUME IF NOT EXISTS main.jdbc_drivers.jars;
```

**Required: Download both JARs from Maven Central**

1. **Full Bundle** (contains the driver class `org.neo4j.jdbc.Neo4jDriver`):
   - [neo4j-jdbc-full-bundle-6.10.3.jar](https://repo.maven.apache.org/maven2/org/neo4j/neo4j-jdbc-full-bundle/6.10.3/neo4j-jdbc-full-bundle-6.10.3.jar)
   - Upload to: `/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-full-bundle-6.10.3.jar`

2. **Spark Cleaner** (handles Spark's subquery wrapping):
   - [neo4j-jdbc-translator-sparkcleaner-6.10.3.jar](https://repo.maven.apache.org/maven2/org/neo4j/neo4j-jdbc-translator-sparkcleaner/6.10.3/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar)
   - Upload to: `/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar`

- [All full-bundle versions](https://repo.maven.apache.org/maven2/org/neo4j/neo4j-jdbc-full-bundle/)
- [All sparkcleaner versions](https://repo.maven.apache.org/maven2/org/neo4j/neo4j-jdbc-translator-sparkcleaner/)

See [CLEANER.md](../neo4j_jdbc_spark_cleaning/CLEANER.md) for details on the SparkSubqueryCleaningTranslator.

### 2. Databricks Secrets

**Option A: Use setup script (recommended)**

```bash
# Copy and edit .env file
cp .env.sample .env
# Edit .env with your Neo4j credentials

# Run setup script
./setup.sh
```

**Option B: Manual setup**

```bash
# Create the secret scope
databricks secrets create-scope neo4j-uc-creds

# Add secrets (you'll be prompted for values)
databricks secrets put-secret neo4j-uc-creds host
databricks secrets put-secret neo4j-uc-creds user
databricks secrets put-secret neo4j-uc-creds password
databricks secrets put-secret neo4j-uc-creds connection_name

# Optional: custom database name (defaults to "neo4j")
databricks secrets put-secret neo4j-uc-creds database
```

## Test Details

### Environment Test
- Reports Python version and platform
- Checks Neo4j Python driver installation
- Displays loaded configuration

### Neo4j Driver Test
- Connects using Bolt protocol (`neo4j+s://`)
- Verifies connectivity
- Executes simple query (`RETURN 1`)
- Retrieves Neo4j server version

### Unity Catalog JDBC Test
- Creates a UC JDBC connection with the Neo4j driver
- Tests DataFrame API with UC connection
- Tests native Cypher with `FORCE_CYPHER` hint
- Tests `remote_query()` function

## Expected Secrets

The secret scope should contain:

| Key | Required | Description |
|-----|----------|-------------|
| `host` | Yes | Neo4j host (e.g., `xxxxx.databases.neo4j.io`) |
| `user` | Yes | Neo4j username |
| `password` | Yes | Neo4j password |
| `connection_name` | Yes | UC JDBC connection name (e.g., `neo4j_connection`) - workspace-level, not catalog.schema scoped |
| `database` | No | Database name (defaults to `neo4j`) |

---

## Section 8: Neo4j Schema Synchronization with Unity Catalog

Section 8 of the notebook demonstrates a proof of concept for synchronizing Neo4j graph schema with Unity Catalog. This enables SQL-based access to graph data through UC governance.

### The Challenge

Unity Catalog's Foreign Catalog feature only supports specific databases (PostgreSQL, MySQL, Snowflake, etc.) - not generic JDBC connections. This means Neo4j cannot be automatically registered as a foreign catalog. Instead, we must manually create UC objects backed by the JDBC connection.

### The Solution

The notebook demonstrates a three-phase approach:

**Phase 1: Schema Discovery**

Neo4j's JDBC driver exposes complete graph schema through standard JDBC `DatabaseMetaData` APIs. Using Spark's JVM gateway (`spark._jvm`), we call:
- `getTables(TABLE)` to discover all node labels
- `getTables(RELATIONSHIP)` to discover relationship patterns
- `getColumns()` to discover properties and their types
- `getPrimaryKeys()` to identify element ID columns

This builds an in-memory schema model without requiring hardcoded label names.

**Phase 2: Unity Catalog Registration**

Three approaches are tested, each in a separate notebook cell:

| Option | Approach | Description |
|--------|----------|-------------|
| **A** | Views with inferred schema | Schema discovered at query time; simplest but less control |
| **B** | Tables with explicit schema | Schema from DatabaseMetaData; predictable types |
| **C** | Hybrid with registry | Schema registry table + views; best for visibility |

**Phase 3: Verification**

Queries are executed through Unity Catalog to verify:
- Data is accessible via SQL
- Schema is correctly mapped
- UC governance (permissions, audit) applies

### Key Findings

1. **JDBC DatabaseMetaData works**: Complete schema discovery without Cypher procedures
2. **All three UC approaches work**: Views, tables, and hybrid all successfully query Neo4j
3. **SQL JOINs translate to relationships**: `NATURAL JOIN` correctly becomes Cypher traversals
4. **Governance applies**: All queries go through UC connection

### Limitations

- No automatic foreign catalog sync (must manually create UC objects)
- Temp views used for demo (production would use permanent objects)
- Schema refresh requires re-running discovery

### References

- [META.md](../META.md) - Full proposal document with detailed technical decisions
- [Neo4j JDBC DatabaseMetaData](https://neo4j.com/docs/jdbc-manual/current/) - How schema is exposed
- [Databricks JDBC Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) - UC JDBC integration

---

## Best Practices

This section summarizes best practices for using the Neo4j JDBC driver with Databricks Unity Catalog, based on official Neo4j and Databricks documentation.

### Neo4j JDBC Driver Configuration

**Use the Full Bundle JAR**

The `neo4j-jdbc-full-bundle` artifact includes all required components: the core driver, SQL-to-Cypher translator, and Spark subquery cleaner. This eliminates classpath issues and ensures all translation features work out of the box.

**Enable SQL Translation via URL Parameter**

Add `enableSQLTranslation=true` to your JDBC URL to activate automatic SQL-to-Cypher translation. This allows standard SQL queries to be transparently converted to Cypher, making Neo4j accessible to SQL-based tools and frameworks.

**Always Specify customSchema for Spark Reads**

Spark's automatic schema inference wraps queries in subqueries for metadata discovery, which can cause issues with Neo4j. The `customSchema` option bypasses this inference entirely and must be included in `externalOptionsAllowList` when creating UC connections. Column names in customSchema must exactly match query result aliases.

**Use Table-to-Label Mappings for Clarity**

Configure `s2c.tableToLabelMappings` to explicitly map SQL table names to Neo4j labels. This improves query predictability and avoids reliance on automatic name inference.

**Tune Relationship Sample Size for Large Graphs**

The driver samples relationships to infer schema metadata. The default sample size (1000) may miss relationships in large graphs. Increase `relationshipSampleSize` in the JDBC URL for more comprehensive schema discovery, or decrease it for better performance when schema accuracy is less critical.

### Databricks Unity Catalog Integration

**Store JDBC Driver in Unity Catalog Volumes**

JDBC drivers must be stored in a UC Volume and referenced via `java_dependencies` in the connection definition. Users querying the connection need `READ` access to the volume location. This ensures consistent driver availability across all compute types.

**Configure externalOptionsAllowList Appropriately**

The allowlist controls which Spark options users can specify at query time. For Neo4j integration, include: `dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize,customSchema`. Options not in this list can only be set at connection creation time.

**Use Secrets for Credentials**

Store Neo4j credentials in Databricks Secrets rather than hardcoding them in notebooks or connection strings. The connection definition should reference credentials directly so querying users never see them.

**Understand UC JDBC vs Query Federation**

Unity Catalog offers both JDBC connections and Query Federation. JDBC connections provide more flexibility (supports writes, custom drivers, Spark options) but only connection-level governance. Query Federation provides table-level governance but doesn't support all databases. For Neo4j, JDBC is the appropriate choice since Query Federation doesn't support graph databases.

### SQL-to-Cypher Translation

**Supported Constructs**

The translator supports SELECT with DISTINCT, ORDER BY, LIMIT/OFFSET; basic JOINs (INNER, NATURAL); INSERT, UPDATE, DELETE, TRUNCATE; aggregate functions like COUNT; and common SQL functions (string, numeric, scalar). Outer joins and window functions are not supported.

**JOIN Translation to Relationships**

The driver maps SQL JOINs to Neo4j relationship patterns. NATURAL JOIN translates to anonymous relationships, while explicit JOINs use column names to infer relationship types. For predictable results, use `s2c.joinColumnsToTypeMappings` to explicitly map join columns to relationship types.

**Use FORCE_CYPHER for Complex Queries**

When SQL translation doesn't produce the desired Cypher, bypass translation entirely with the hint `/*+ NEO4J FORCE_CYPHER */` followed by your Cypher query. This is especially useful for complex graph traversals that don't map naturally to SQL.

**Enumerate Columns Instead of Star-Selects**

When the driver cannot access database metadata (offline mode), star-selects cannot expand to actual properties. Explicitly list the columns you need for more reliable query translation.

### Schema Synchronization

**Graph-to-Relational Mapping Concepts**

The Neo4j JDBC driver exposes graph schema through standard JDBC metadata APIs. Labels become tables (via `getTables()`), properties become columns (via `getColumns()`), element IDs serve as primary keys, and relationships can be represented as foreign keys or join tables.

**Leverage Built-in Metadata Discovery**

Use `db.labels()`, `db.relationshipTypes()`, and `db.propertyKeys()` Cypher procedures to discover schema. The driver also supports `db.schema.visualization()` for complete graph meta-model discovery when available.

**Consider Cypher-Backed Views for Complex Patterns**

For graph patterns that don't map cleanly to tables (multi-hop traversals, variable-length paths), define Cypher-backed views using `s2c.viewDefinitions`. These appear as tables in JDBC metadata but execute arbitrary Cypher.

**Cache Management After Schema Changes**

The driver caches metadata for performance. After Neo4j schema changes, flush the cache using `connection.unwrap(Neo4jConnection.class).flushTranslationCache()` or establish a new connection.

### Performance Considerations

**Pushdown Queries to Neo4j**

Use the Spark `query` option with complete SQL statements rather than `dbtable` with simple table names. This allows the full query (including filters and aggregations) to be pushed to Neo4j rather than fetching all data to Spark.

**Partition Large Result Sets**

For large data transfers, use Spark's partitioning options (`partitionColumn`, `lowerBound`, `upperBound`, `numPartitions`) to parallelize reads. Choose a numeric or date column with even distribution.

**Use Aggregate Queries When Possible**

Queries like `SELECT COUNT(*) FROM Label` are efficiently translated to `MATCH (n:Label) RETURN count(n)` and execute entirely in Neo4j, avoiding data transfer overhead.

---

## References

### Notebook Code Sections

The test notebooks demonstrate these practices:

- **Section 5**: Direct JDBC with `customSchema` and SQL translation
- **Section 6**: Unity Catalog connection creation with `externalOptionsAllowList`
- **Section 7**: UC JDBC queries with DataFrame API and `remote_query()`
- **Section 8**: Schema discovery prototypes using JDBC metadata and Cypher procedures

### Neo4j Documentation

- [Neo4j JDBC Driver Manual](https://neo4j.com/docs/jdbc-manual/current/) - Complete driver reference
- [SQL to Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) - Supported SQL constructs and configuration
- [Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) - Connection options and parameters
- [GitHub: neo4j/neo4j-jdbc](https://github.com/neo4j/neo4j-jdbc) - Source code and issue tracking

### Databricks Documentation

- [JDBC Unity Catalog Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) - Creating and using UC JDBC connections
- [Work with Foreign Tables](https://docs.databricks.com/aws/en/tables/foreign) - Foreign table concepts and patterns
- [Manage Foreign Catalogs](https://docs.databricks.com/aws/en/query-federation/foreign-catalogs) - Query federation vs JDBC comparison

### Driver Downloads

- **Recommended**: Use `../neo4j_jdbc_spark_cleaning/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar` (includes SparkSubqueryCleaningTranslator)
- [Maven Central: neo4j-jdbc-full-bundle](https://repo1.maven.org/maven2/org/neo4j/neo4j-jdbc-full-bundle/) - Official releases (without SparkCleaner)
- [CLEANER_USER.md](../CLEANER_USER.md) - Build instructions for custom JAR with SparkCleaner

