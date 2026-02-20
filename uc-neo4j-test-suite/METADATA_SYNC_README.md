# Metadata Sync Notebooks — Testing Guide

Two notebooks prototype Unity Catalog metadata synchronization for Neo4j:

| Notebook | Approach | What It Does |
|----------|----------|-------------|
| `metadata_sync_delta.ipynb` | Materialized Delta Tables | Reads Neo4j labels/relationships via Spark Connector, writes as managed Delta tables. Full UC integration — Catalog Explorer, INFORMATION_SCHEMA, SQL access. |
| `metadata_sync_external.ipynb` | External Metadata API | Registers Neo4j schema as external metadata objects via REST API. No data copied — metadata-only for discoverability and lineage. |

---

## Prerequisites

### 1. Secrets Already Configured

Both notebooks reuse the existing `neo4j-uc-creds` secret scope. If you've already run the UC JDBC test suite, no additional setup is needed.

If not, configure secrets first:

```bash
cp .env.sample .env
# Edit .env with your Neo4j credentials
./setup.sh
```

### 2. Create the Target Catalog

The notebook does **not** create the catalog automatically. You (or your workspace admin) must create it before running the notebook:

```sql
CREATE CATALOG neo4j_metadata MANAGED LOCATION '<your-storage-location>';
```

For example, using an existing external location:

```sql
CREATE CATALOG neo4j_metadata MANAGED LOCATION 'abfss://container@storageaccount.dfs.core.windows.net/neo4j_metadata';
```

Or if your metastore has a default storage root configured:

```sql
CREATE CATALOG neo4j_metadata;
```

You can create the catalog from the **Databricks SQL editor**, a **notebook**, or via the **Catalog Explorer UI** (**Data** > **+** > **Create Catalog**).

The notebook will create the `nodes` and `relationships` schemas within this catalog.

### 3. Cluster Requirements

| Requirement | Notebook 1 (Delta) | Notebook 2 (External API) |
|-------------|--------------------|-----------------------------|
| Access mode | **Single user** (required by Spark Connector) | Any |
| Neo4j Spark Connector | **Required** (`org.neo4j:neo4j-connector-apache-spark_2.12:5.4.0_for_spark_3`) | Not needed |
| Neo4j Python driver | **Required** (`neo4j`) | **Required** (`neo4j`) |
| SafeSpark memory settings | Not needed (uses Spark Connector, not JDBC) | Not needed |
| UC privilege | `USE CATALOG`, `CREATE SCHEMA` on `neo4j_metadata` | `CREATE_EXTERNAL_METADATA` on metastore |

### 4. Install Cluster Libraries

For `metadata_sync_delta.ipynb`, install the Spark Connector on your cluster:

1. Go to **Compute** > your cluster > **Libraries** > **Install new**
2. Select **Maven** and enter: `org.neo4j:neo4j-connector-apache-spark_2.12:5.4.0_for_spark_3`
3. Install the Neo4j Python driver: `neo4j` (via PyPI)

For `metadata_sync_external.ipynb`, only the Python driver is needed:

1. Install `neo4j` via PyPI
2. `requests` is pre-installed on Databricks

---

## Running the Notebooks

### Notebook 1: `metadata_sync_delta.ipynb`

**Run cells in order.** Each cell builds on the previous one.

| Cell | What It Does | What to Check |
|------|-------------|---------------|
| Configuration | Loads secrets, sets target catalog name, sets Neo4j creds at session level | Verify host and catalog name are correct |
| Verify Connectivity | Tests Neo4j Python driver | Should print `[PASS]` and Neo4j version |
| Discover Schema | Runs `db.schema.nodeTypeProperties()` | Should list all node labels and properties |
| Create Schemas | Verifies catalog exists, creates `nodes` and `relationships` schemas | Should print `[PASS]` for each |
| Materialize One Label | Reads first label, writes as Delta table | Check `printSchema()` output and row count |
| Verify INFORMATION_SCHEMA | Queries `information_schema.tables` and `columns` | **Key proof** — columns and types should appear |
| Materialize All Labels | Loops through all labels | Check pass/fail summary at the end |
| Materialize Relationships | Writes relationship types as Delta tables | Check pass/fail summary |
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

### Notebook 2: `metadata_sync_external.ipynb`

**Run cells in order.**

| Cell | What It Does | What to Check |
|------|-------------|---------------|
| Configuration | Loads secrets, auto-discovers workspace URL and token | Verify workspace URL is correct, token shows `********` |
| Verify Connectivity | Tests Neo4j Python driver | Should print `[PASS]` |
| Discover Schema | Gets labels, relationships, properties, patterns | Should list all labels and relationship patterns |
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

---

## Customization

### Change the Target Catalog Name

In `metadata_sync_delta.ipynb`, edit the configuration cell:

```python
TARGET_CATALOG = "neo4j_metadata"     # Change this
NODES_SCHEMA = "nodes"                # Change this
RELATIONSHIPS_SCHEMA = "relationships" # Change this
```

### Use a Different Catalog

If you already have a catalog you'd like to use, update `TARGET_CATALOG` in the configuration cell to match. The notebook will create the `nodes` and `relationships` schemas within it.

---

## Troubleshooting

### "Catalog 'neo4j_metadata' was not found"

The catalog must be created before running the notebook. See [Create the Target Catalog](#2-create-the-target-catalog) above.

### "403 Forbidden" on External Metadata API

The current user needs `CREATE_EXTERNAL_METADATA` privilege on the metastore. Ask your admin:

```sql
GRANT CREATE_EXTERNAL_METADATA ON METASTORE TO `user@email.com`;
```

### Spark Connector: "org.neo4j.spark.DataSource not found"

The Neo4j Spark Connector library is not installed on the cluster. Install it via **Compute** > **Libraries** > **Maven**: `org.neo4j:neo4j-connector-apache-spark_2.12:5.4.0_for_spark_3`

### Spark Connector: "Single user access mode required"

The Neo4j Spark Connector only works with **Single user** access mode. Change your cluster's access mode in **Compute** > your cluster > **Configuration** > **Access mode**.

### Schema mismatch on rerun

The notebooks use `.option("overwriteSchema", "true")` so reruns work even if the Neo4j schema changed (e.g., new properties added). This is safe for prototype use. In production, you may want to diff the schema before overwriting.

### Empty schema discovery

If `db.schema.nodeTypeProperties()` returns no results, the Neo4j database may be empty or the credentials may point to the wrong database. Check the `NEO4J_DATABASE` value in your `.env` file.

### Multi-label nodes

Nodes with multiple labels (e.g., `:Person:Employee`) are discovered under each individual label but not as a combined type. The notebook prints a warning showing how many multi-label entries were skipped.
