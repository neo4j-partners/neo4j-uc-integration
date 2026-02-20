# Metadata Sync Prototype Plan

This plan builds two Databricks notebooks that prototype Unity Catalog metadata synchronization for Neo4j, following the same patterns as the existing `uc-neo4j-test-suite/` (Databricks secrets via `setup.sh`, step-by-step notebook cells, try/except wrapping, status output).

Both notebooks live in `uc-neo4j-test-suite/` and reuse the existing `neo4j-uc-creds` secret scope and `.env` setup.

---

## Notebook 1: `metadata_sync_delta.ipynb` (Approach 3 — Materialized Delta Tables)

This is the simplest approach. Read Neo4j labels via the Spark Connector and write them as managed Delta tables in Unity Catalog. Metadata (columns, types, statistics) registers automatically on write.

### Cell 1: Introduction (Markdown)

Explain what this notebook does: materialize Neo4j node labels as Delta tables in Unity Catalog so they appear in Catalog Explorer with full schema metadata, column types, and row counts.

### Cell 2: Configuration

Load credentials from the existing `neo4j-uc-creds` secret scope (same pattern as `neo4j_schema_test.ipynb`). Build the Bolt URI from the host secret. Define the target UC catalog and schema names where Delta tables will be created (e.g., `neo4j_metadata` catalog, `nodes` schema). Print all loaded config values.

### Cell 3: Verify Neo4j Connectivity

Connect to Neo4j with the Python driver. Run `RETURN 1 AS test` to confirm credentials work. Print the Neo4j version. Close the driver. This is the same connectivity check used in the existing notebooks.

### Cell 4: Discover Node Labels

Connect to Neo4j with the Python driver. Run `CALL db.schema.nodeTypeProperties()` to get all node labels and their properties with types. This is a built-in procedure — no APOC required. Store the results in a Python dictionary keyed by label name, with each entry listing property names, types, and whether they're mandatory. Print a summary showing each label and its property count.

### Cell 5: Create Target Catalog and Schema

Use `spark.sql()` to create the target catalog and schema if they don't exist:
- `CREATE CATALOG IF NOT EXISTS neo4j_metadata`
- `CREATE SCHEMA IF NOT EXISTS neo4j_metadata.nodes`

Print confirmation.

### Cell 6: Materialize One Label as a Delta Table (Single Label Test)

Pick the first discovered label (e.g., `Aircraft`). Read it from Neo4j using the Spark Connector (`org.neo4j.spark.DataSource`) with the `labels` option. Show the inferred schema with `printSchema()`. Show 5 sample rows. Write it as a managed Delta table with `df.write.mode("overwrite").saveAsTable("neo4j_metadata.nodes.aircraft")`. Print success.

### Cell 7: Verify Metadata in Unity Catalog

Query `INFORMATION_SCHEMA` to confirm the table and its columns are now visible in UC:
- `SELECT * FROM neo4j_metadata.information_schema.tables WHERE table_schema = 'nodes'`
- `SELECT column_name, data_type, is_nullable FROM neo4j_metadata.information_schema.columns WHERE table_name = 'aircraft'`

Show the results. This proves metadata sync worked — the table appears in Catalog Explorer with full column definitions.

### Cell 8: Materialize All Discovered Labels

Loop through all discovered labels from Cell 4. For each label, read from Neo4j via the Spark Connector and write as a Delta table in `neo4j_metadata.nodes`. Use lowercase label names for table names. Wrap each write in try/except and track pass/fail. Print a summary table showing each label, row count, column count, and status.

### Cell 9: Materialize Relationships (Optional)

Pick one or two relationship types discovered from Neo4j (query `CALL db.schema.relTypeProperties()` or use the Python driver to run `SHOW RELATIONSHIP TYPES`). Read each relationship using the Spark Connector's `relationship` option with `relationship.source.labels` and `relationship.target.labels`. Create a `neo4j_metadata.relationships` schema and write the relationship data as Delta tables. This shows that both nodes and relationships can be materialized.

### Cell 10: Final Verification and Summary

Query `INFORMATION_SCHEMA` again to show all tables created across both schemas. Count total tables, total columns, and total rows materialized. Print a final summary. Note that these tables are now browsable in Catalog Explorer, governed by UC permissions, and queryable via standard SQL without any JDBC connection.

---

## Notebook 2: `metadata_sync_external.ipynb` (Approach 2 — External Metadata API)

This approach registers Neo4j schema metadata in Unity Catalog without copying any data. It uses the Databricks REST API to create external metadata objects that appear in the UC lineage tracking system.

### Cell 1: Introduction (Markdown)

Explain what this notebook does: register Neo4j node labels and relationship types as external metadata objects in Unity Catalog using the External Metadata API. No data is copied — this is metadata-only registration for discoverability and lineage tracking.

### Cell 2: Configuration

Load Neo4j credentials from the existing `neo4j-uc-creds` secret scope. Auto-discover the Databricks workspace URL and auth token from the notebook context — no extra secrets needed:
- `dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()` for the workspace URL
- `dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()` for the session token

The session token inherits the current user's permissions, so as long as they have the `CREATE_EXTERNAL_METADATA` privilege, no personal access token secret is needed. Print all config values (masking the token).

### Cell 3: Verify Neo4j Connectivity

Same as Notebook 1 Cell 3 — connect with the Python driver, run a test query, print the Neo4j version.

### Cell 4: Discover Neo4j Schema

Same as Notebook 1 Cell 4 — run `CALL db.schema.nodeTypeProperties()` and `CALL db.schema.relTypeProperties()` to discover all labels, relationship types, properties, and types. Store in a dictionary. Print summary.

### Cell 5: Explain the External Metadata API (Markdown)

Briefly explain the API: endpoint is `POST /api/2.0/lineage-tracking/external-metadata`. It accepts a name, system_type (we use `OTHER` since Neo4j isn't in the enum), entity_type (free-form — we use `NodeLabel` or `RelationshipType`), columns (list of property names), and a properties map (where we encode type info). Note that this is a Public Preview API.

### Cell 6: Register One Label (Single Test)

Pick the first label. Build the request payload with the label name, `system_type: "OTHER"`, `entity_type: "NodeLabel"`, columns as a list of property names, and property types encoded in the properties map. POST to the External Metadata API using the `requests` library. Print the response. Verify success by doing a GET back on the returned ID.

### Cell 7: Register All Node Labels

Loop through all discovered labels. For each, build the payload and POST to the API. Track success/failure per label. Print a summary table showing each label, property count, and registration status.

### Cell 8: Register Relationship Types

Loop through discovered relationship types. Use `entity_type: "RelationshipType"`. Include source and target label info in the properties map. POST each one. Print summary.

### Cell 9: List All Registered Metadata

GET `/api/2.0/lineage-tracking/external-metadata` to list everything we registered. Display as a table showing name, entity_type, column count, and created timestamp. This proves the metadata is now visible in UC's lineage tracking system.

### Cell 10: Cleanup (Optional)

Provide commented-out code that DELETEs all the external metadata objects created during this notebook, using the IDs collected during registration. Explain that these objects persist until deleted.

### Cell 11: Summary and Comparison (Markdown)

Compare Approach 2 vs Approach 3:
- Approach 3 (Delta) gives full UC integration — tables in Catalog Explorer, INFORMATION_SCHEMA visibility, SQL queryability, column types — but copies data
- Approach 2 (External Metadata API) gives metadata registration without data copy — good for lineage and discoverability — but objects don't appear in INFORMATION_SCHEMA, columns have no type info in the API (types go in properties map), and there's no query routing back to Neo4j

Recommend using both: Approach 3 for high-value labels that need SQL access, Approach 2 for everything else to maintain a complete metadata catalog.

---

## No New Secrets Needed

Both notebooks reuse the existing `neo4j-uc-creds` secret scope. The External Metadata API notebook auto-discovers the Databricks workspace URL and auth token from the notebook session context, so no additional secrets or `.env` changes are required.

The current user just needs the `CREATE_EXTERNAL_METADATA` privilege on the metastore.

---

## Prerequisites

Both notebooks require the same cluster setup as the existing test suite:
- SafeSpark memory settings (for any JDBC operations)
- Neo4j Spark Connector library installed (`org.neo4j:neo4j-connector-apache-spark:5.3.10`)
- Neo4j Python driver installed (`neo4j`)
- Single user access mode (required by the Spark Connector)
- Secrets configured via `setup.sh`
