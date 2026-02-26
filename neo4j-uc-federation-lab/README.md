# Neo4j Unity Catalog Integration — Notebooks

Databricks notebooks for validating Neo4j JDBC connectivity through Unity Catalog, running federated queries across Neo4j and Delta lakehouse tables, and synchronizing Neo4j metadata into Unity Catalog.

**Jump to:** [Metadata Sync Notebooks](#metadata-sync-notebooks)

## Notebooks

| Notebook | Description |
|----------|-------------|
| `neo4j_databricks_sql_translation.ipynb` | UC JDBC connection and SQL-to-Cypher translation validation |
| `federated_lakehouse_query.ipynb` | Federated queries joining Neo4j graph data with Delta lakehouse tables |
| `federated_views_agent_ready.ipynb` | Materializes Neo4j data as Delta tables for Genie natural language queries |
| `metadata_sync_delta.ipynb` | Metadata sync via materialized Delta tables |
| `metadata_sync_external.ipynb` | Metadata sync via External Metadata API |

### neo4j_databricks_sql_translation.ipynb

Sections 1–7:
- Section 1: Environment Information
- Section 2: Network Connectivity Test
- Section 3: Neo4j Python Driver Test
- Section 4: Neo4j Spark Connector Test
- Section 5: Direct JDBC Tests
- Section 6: Unity Catalog JDBC Connection Setup
- Section 7: Unity Catalog JDBC Tests

### federated_lakehouse_query.ipynb

Demonstrates two federation methods in a single notebook:
- `remote_query()` — UC JDBC table-valued function for Neo4j aggregate queries (no cluster library needed)
- Neo4j Spark Connector — Row-level Neo4j data loaded into temp views for JOINs with Delta tables

Requires the Neo4j Spark Connector as a cluster library and a single-user access mode cluster.

### federated_views_agent_ready.ipynb

Materializes Neo4j node labels (MaintenanceEvent, Flight, Airport) as managed Delta tables in Unity Catalog using the DataFrame API with `dbtable` + `customSchema`. Creates a flight-to-airport mapping table via Spark SQL JOIN. These tables make Neo4j data queryable by Genie and other SQL tools — GROUP BY, ORDER BY, and JOINs all work because the data is materialized as regular Delta tables.

Uses pure UC JDBC federation only — no Spark Connector or cluster libraries required.

---

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

See [neo4j_jdbc_cleaner.md](../docs/neo4j_jdbc_cleaner.md) for details on the SparkSubqueryCleaningTranslator.

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

### Expected Secrets

| Key | Required | Description |
|-----|----------|-------------|
| `host` | Yes | Neo4j host (e.g., `xxxxx.databases.neo4j.io`) |
| `user` | Yes | Neo4j username |
| `password` | Yes | Neo4j password |
| `connection_name` | Yes | UC JDBC connection name (e.g., `neo4j_connection`) — workspace-level, not catalog.schema scoped |
| `database` | No | Database name (defaults to `neo4j`) |

### 3. Cluster Requirements

| Requirement | JDBC / Federated Views Notebooks | Federated Lakehouse Notebook | Metadata Sync (Delta) | Metadata Sync (External API) |
|-------------|----------------------------------|------------------------------|----------------------|------------------------------|
| Access mode | Any | **Single user** | **Single user** | Any |
| Neo4j Spark Connector | Not needed | **Required** | **Required** | Not needed |
| Neo4j Python driver | Not needed | Not needed | **Required** | **Required** |
| SafeSpark memory settings | **Required** | **Required** | Not needed | Not needed |

**Installing cluster libraries:**

- Neo4j Spark Connector: **Compute** > your cluster > **Libraries** > **Install new** > **Maven** > `org.neo4j:neo4j-connector-apache-spark_2.12:5.4.0_for_spark_3`
- Neo4j Python driver: **Compute** > your cluster > **Libraries** > **Install new** > **PyPI** > `neo4j`

---

## Best Practices

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

## Metadata Sync Notebooks

Two notebooks prototype Unity Catalog metadata synchronization for Neo4j. See [metadata_synchronization.md](../docs/metadata_synchronization.md) for the full design.

| Notebook | Approach | What It Does |
|----------|----------|-------------|
| `metadata_sync_delta.ipynb` | Materialized Delta Tables | Reads Neo4j labels/relationships via Spark Connector, writes as managed Delta tables. Full UC integration — Catalog Explorer, INFORMATION_SCHEMA, SQL access. |
| `metadata_sync_external.ipynb` | External Metadata API | Registers Neo4j schema as external metadata objects via REST API. No data copied — metadata-only for discoverability and lineage. |

### Additional Prerequisites for Metadata Sync

Beyond the [common prerequisites](#prerequisites) above, the metadata sync notebooks have additional requirements:

**For `metadata_sync_delta.ipynb`:**
- **Target catalog must already exist.** The notebook does not create it. Create it before running:
  ```sql
  CREATE CATALOG neo4j_metadata;
  ```
  Or with a specific storage location:
  ```sql
  CREATE CATALOG neo4j_metadata MANAGED LOCATION '<your-storage-location>';
  ```
  The notebook will create the `nodes` and `relationships` schemas within this catalog.
- **Single-user access mode** cluster with the Neo4j Spark Connector installed.
- **UC privileges:** `USE CATALOG`, `CREATE SCHEMA` on the target catalog.

**For `metadata_sync_external.ipynb`:**
- **UC privilege:** `CREATE_EXTERNAL_METADATA` on the metastore. Ask your admin:
  ```sql
  GRANT CREATE_EXTERNAL_METADATA ON METASTORE TO `user@email.com`;
  ```
- Workspace URL and auth token are auto-discovered from the notebook context — no manual configuration needed.

### Running metadata_sync_delta.ipynb

Run cells in order. Each cell builds on the previous one.

| Cell | What It Does | What to Check |
|------|-------------|---------------|
| Configuration | Loads secrets, sets target catalog name | Verify host and catalog name are correct |
| Verify Connectivity | Tests Neo4j Python driver | Should print `[PASS]` and Neo4j version |
| Discover Schema | Runs `db.schema.nodeTypeProperties()` and `db.schema.relTypeProperties()` | Should list all node labels and properties |
| Create Schemas | Verifies catalog exists, creates `nodes` and `relationships` schemas | Should print `[PASS]` for each |
| Materialize One Label | Reads first label via Spark Connector, writes as Delta table | Check `printSchema()` output and row count |
| Verify INFORMATION_SCHEMA | Queries `information_schema.tables` and `columns` | Columns and types should appear |
| Materialize All Labels | Loops through all labels | Check pass/fail summary |
| Materialize Relationships | Discovers relationship patterns via MATCH query, writes as Delta tables | Check pass/fail summary |
| Final Summary | Shows all tables in the catalog | Verify total table count and row counts |

**Expected output after final cell:**

```
METADATA SYNC SUMMARY
  Target Catalog: neo4j_metadata
  Node label tables: N (in nodes)
  Relationship tables: N (in relationships)
  Total tables: N
  Total data rows: N,NNN

  All tables are:
    - Browsable in Catalog Explorer
    - Visible in INFORMATION_SCHEMA
    - Queryable via standard SQL
    - Governed by UC permissions

[PASS] Metadata synchronization complete
```

**After running, verify in Catalog Explorer:**

1. Navigate to **Data** > **neo4j_metadata** catalog
2. Open the **nodes** schema — each Neo4j label should appear as a table
3. Click any table — columns, types, and row counts should be visible
4. Open the **relationships** schema — each relationship type should appear
5. Try running a SQL query: `SELECT * FROM neo4j_metadata.nodes.aircraft LIMIT 5`

### Running metadata_sync_external.ipynb

Run cells in order.

| Cell | What It Does | What to Check |
|------|-------------|---------------|
| Configuration | Loads secrets, auto-discovers workspace URL and token | Verify workspace URL is correct, token shows `********` |
| Verify Connectivity | Tests Neo4j Python driver | Should print `[PASS]` |
| Discover Schema | Gets labels, relationships, and properties via `db.schema.nodeTypeProperties()` and `db.schema.relTypeProperties()` | Should list all labels and relationship types |
| Register One Label | POSTs one label to External Metadata API | Should return an ID and print `[PASS]` |
| Register All Labels | Loops through all labels | Check pass/fail summary |
| Register Relationships | Loops through all relationship types | Check pass/fail summary |
| List All Metadata | GETs all registered objects | Should show a table of all registered entries |
| Cleanup | Commented out — uncomment to delete | Only run if you want to remove the metadata |

**Expected output after list cell:**

```
ALL REGISTERED EXTERNAL METADATA

+------------------+------------------+-------+----------------+
| name             | entity_type      |columns| created_by     |
+------------------+------------------+-------+----------------+
| Aircraft         | NodeLabel        | 4     | user@email.com |
| Flight           | NodeLabel        | 6     | user@email.com |
| Airport          | NodeLabel        | 7     | user@email.com |
| DEPARTS_FROM     | RelationshipType | 0     | user@email.com |
| ...              | ...              | ...   | ...            |
+------------------+------------------+-------+----------------+
```

**Note:** External metadata objects do **not** appear in Catalog Explorer or `INFORMATION_SCHEMA`. They are only visible via the REST API. This is a limitation of the External Metadata API (Public Preview).

### Customization

In `metadata_sync_delta.ipynb`, edit the configuration cell to change target names:

```python
TARGET_CATALOG = "neo4j_metadata"     # Change this
NODES_SCHEMA = "nodes"                # Change this
RELATIONSHIPS_SCHEMA = "relationships" # Change this
```

### Metadata Sync Troubleshooting

**"Catalog 'neo4j_metadata' was not found"** — The catalog must be created before running the notebook. See [Additional Prerequisites](#additional-prerequisites-for-metadata-sync) above.

**"403 Forbidden" on External Metadata API** — The current user needs `CREATE_EXTERNAL_METADATA` privilege on the metastore.

**"org.neo4j.spark.DataSource not found"** — The Neo4j Spark Connector library is not installed on the cluster. Install via **Compute** > **Libraries** > **Maven**: `org.neo4j:neo4j-connector-apache-spark_2.12:5.4.0_for_spark_3`

**"Single user access mode required"** — The Neo4j Spark Connector only works with single-user access mode. Change your cluster's access mode in **Compute** > your cluster > **Configuration** > **Access mode**.

**Schema mismatch on rerun** — The notebooks use `.option("overwriteSchema", "true")` so reruns work even if the Neo4j schema changed. This is safe for prototype use.

**Empty schema discovery** — If `db.schema.nodeTypeProperties()` returns no results, the Neo4j database may be empty or the credentials may point to the wrong database. Check the `NEO4J_DATABASE` value in your `.env` file.

**Multi-label nodes** — Nodes with multiple labels (e.g., `:Person:Employee`) are discovered under each individual label but not as a combined type. The notebook prints a warning showing how many multi-label entries were skipped.

---

## References

### Neo4j Documentation

- [Neo4j JDBC Driver Manual](https://neo4j.com/docs/jdbc-manual/current/) — Complete driver reference
- [SQL to Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) — Supported SQL constructs and configuration
- [Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) — Connection options and parameters
- [GitHub: neo4j/neo4j-jdbc](https://github.com/neo4j/neo4j-jdbc) — Source code and issue tracking

### Databricks Documentation

- [JDBC Unity Catalog Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) — Creating and using UC JDBC connections
- [Work with Foreign Tables](https://docs.databricks.com/aws/en/tables/foreign) — Foreign table concepts and patterns
- [Manage Foreign Catalogs](https://docs.databricks.com/aws/en/query-federation/foreign-catalogs) — Query federation vs JDBC comparison

### Driver Downloads

- [Maven Central: neo4j-jdbc-full-bundle](https://repo1.maven.org/maven2/org/neo4j/neo4j-jdbc-full-bundle/) — Official releases
- [Maven Central: neo4j-jdbc-translator-sparkcleaner](https://repo.maven.apache.org/maven2/org/neo4j/neo4j-jdbc-translator-sparkcleaner/) — Spark subquery cleaner
