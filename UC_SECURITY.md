# Unity Catalog Security: Auditing, Authorization, and Tracing for Neo4j Federation

How Unity Catalog provides governance, audit trails, and access control for federated Neo4j JDBC queries — and how to demo each capability.

---

## Two Federation Paths, Different Governance Levels

UC offers two paths for querying external data sources. The governance capabilities differ significantly:

| Capability | UC JDBC Connection (`remote_query()` / Spark JDBC) | Lakehouse Federation (Foreign Catalog) |
|---|---|---|
| **Access control granularity** | Connection-level only (`USE CONNECTION`) | Table-level (`GRANT SELECT ON TABLE`) |
| **Row filters / column masks** | No — no table object to attach policy to | Yes — apply directly to foreign tables |
| **Appears in `system.access.audit`** | Yes | Yes |
| **Appears in `system.query.history`** | Yes (SQL warehouse / serverless only) | Yes (SQL warehouse / serverless only) |
| **Lineage tracking** | Partial — entity metadata may be null | Yes — foreign table name appears in lineage |
| **`information_schema` visibility** | Connection only | Connection + catalog + tables + columns |
| **Credential isolation** | Yes — credentials stored in connection object | Yes — credentials stored in connection object |
| **GA status** | Beta (DBR 17.3+, SQL WH 2025.35+) | GA for supported databases; JDBC type is Beta |

The Neo4j integration in this repo uses **UC JDBC Connection** (Path B) because Neo4j is not a natively supported Lakehouse Federation source (Postgres, MySQL, Snowflake, etc. have native support). Foreign Catalog creation requires a natively supported `CONNECTION TYPE`.

---

## 1. Audit Logging via `system.access.audit`

Every interaction with a UC JDBC connection generates audit events in the `system.access.audit` system table.

### What Gets Logged

| Event | `service_name` | `action_name` | What It Captures |
|---|---|---|---|
| Connection created | `unityCatalog` | `createConnection` | Who created it, connection type, URL |
| Connection modified | `unityCatalog` | `updateConnection` | What changed |
| Connection dropped | `unityCatalog` | `deleteConnection` | Who dropped it |
| Connection viewed | `unityCatalog` | `getConnection` | Who looked at it |
| Permissions changed | `unityCatalog` | `updatePermissions` | Who granted/revoked what |
| Query submitted | `databrickssql` or `clusters` | `commandSubmit` | Full SQL text including `remote_query()` calls |

### Demo: Query Connection Lifecycle Events

```sql
-- Find all connection creation/modification events
SELECT
  event_time,
  user_identity.email AS user,
  action_name,
  request_params['name']            AS connection_name,
  request_params['connection_type'] AS connection_type,
  response.status_code
FROM system.access.audit
WHERE service_name = 'unityCatalog'
  AND action_name IN ('createConnection', 'updateConnection', 'deleteConnection')
ORDER BY event_time DESC;
```

### Demo: Find All `remote_query()` Calls to Neo4j

```sql
-- Find all queries that used remote_query() (Neo4j federated queries)
SELECT
  event_time,
  user_identity.email   AS user,
  action_name,
  request_params['commandText'] AS query_text,
  request_params['clusterId']   AS cluster_id,
  source_ip_address,
  response.status_code
FROM system.access.audit
WHERE action_name = 'commandSubmit'
  AND request_params['commandText'] LIKE '%remote_query%'
ORDER BY event_time DESC;
```

### Demo: Track Permission Changes on Connections

```sql
-- Who granted or revoked access to which connections?
SELECT
  event_time,
  user_identity.email                   AS granting_user,
  request_params['securable_type']      AS securable_type,
  request_params['securable_full_name'] AS object_name,
  request_params['changes']             AS changes_json
FROM system.access.audit
WHERE service_name = 'unityCatalog'
  AND action_name = 'updatePermissions'
  AND request_params['securable_type'] = 'connection'
ORDER BY event_time DESC;
```

### Demo: Enumerate All UC Event Types (Discovery)

```sql
-- Run this first to see what your environment actually logs
SELECT
  action_name,
  COUNT(*) AS event_count
FROM system.access.audit
WHERE service_name = 'unityCatalog'
GROUP BY action_name
ORDER BY event_count DESC;
```

---

## 2. Query History via `system.query.history`

The `system.query.history` system table captures query text, execution status, timing, and the user who ran it.

**Important:** Only queries run on SQL warehouses or serverless compute appear here. Classic cluster queries do NOT populate this table — they only appear in `system.access.audit`.

### Demo: Find Federated Neo4j Queries in History

```sql
-- Find all queries that reference the Neo4j connection
SELECT
  executed_by,
  start_time,
  statement_text,
  execution_status,
  total_duration_ms,
  client_application,
  compute.warehouse_id
FROM system.query.history
WHERE statement_text LIKE '%neo4j%'
   OR statement_text LIKE '%remote_query%'
ORDER BY start_time DESC
LIMIT 100;
```

### Demo: Daily Query Volume to Neo4j

```sql
-- How many federated queries are hitting Neo4j per day?
SELECT
  DATE(start_time) AS query_date,
  executed_by,
  COUNT(*)         AS query_count,
  AVG(total_duration_ms) AS avg_duration_ms,
  SUM(read_rows)   AS total_rows_read
FROM system.query.history
WHERE statement_text LIKE '%remote_query%'
  AND statement_text LIKE '%neo4j%'
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

### What's Captured vs. What's Not

| Captured | Not Captured |
|---|---|
| The Spark SQL text (`SELECT * FROM remote_query(...)`) | The actual Cypher pushed down to Neo4j |
| User who ran the query | Neo4j server-side execution time |
| Total duration (Spark-side) | Which Neo4j labels/relationships were accessed |
| Rows returned to Spark | Neo4j query plan |

The pushed-down Cypher is visible in the **Query Profile UI** in Databricks SQL (verbose mode shows JDBC execution details) but does not appear in system tables.

---

## 3. Authorization: Connection-Level Access Control

### The Permissions Model

UC JDBC connections use a simple permission model:

| Privilege | What It Grants |
|---|---|
| `CREATE CONNECTION` | Granted on **metastore** — allows creating new connections |
| `USE CONNECTION` | Granted on **connection** — allows querying through it |
| `MANAGE` | View/manage privileges, transfer ownership, drop/rename |
| `ALL PRIVILEGES` | Everything above |

### Demo: Grant and Revoke Access

```sql
-- Grant a team access to query Neo4j through the UC connection
GRANT USE CONNECTION ON CONNECTION neo4j_connection TO `data-analysts@company.com`;

-- Revoke access
REVOKE USE CONNECTION ON CONNECTION neo4j_connection FROM `intern@company.com`;

-- View who has access
SHOW GRANTS ON CONNECTION neo4j_connection;
```

### Demo: Least-Privilege Setup

```sql
-- Step 1: Only admins can create connections
GRANT CREATE CONNECTION ON METASTORE TO `platform-admins`;

-- Step 2: Analysts can query Neo4j but not create/modify connections
GRANT USE CONNECTION ON CONNECTION neo4j_connection TO `data-analysts`;

-- Step 3: Analysts also need READ on the Volume containing JDBC JARs
GRANT READ VOLUME ON VOLUME catalog.schema.jars TO `data-analysts`;
```

### What UC Provides Over Raw JDBC

| Without UC (raw JDBC) | With UC JDBC Connection |
|---|---|
| Credentials visible in notebook code | Credentials stored in connection object, never exposed |
| Anyone with cluster access can query | Only users with `USE CONNECTION` can query |
| No audit trail of who queried what | Full audit trail in `system.access.audit` |
| No central management of connections | `SHOW CONNECTIONS`, `DESCRIBE CONNECTION`, `information_schema.CONNECTIONS` |
| Arbitrary JDBC options can be set | `externalOptionsAllowList` restricts what users can override |

### Credential Isolation

The `CREATE CONNECTION` statement stores credentials server-side. Querying users never see them:

```sql
-- This reveals connection metadata but NOT credentials
DESCRIBE CONNECTION neo4j_connection;

-- information_schema also hides credentials
SELECT connection_name, connection_type, url, connection_owner
FROM system.information_schema.CONNECTIONS
WHERE connection_name = 'neo4j_connection';
```

The `externalOptionsAllowList` in the connection definition controls which Spark JDBC options users can pass at query time. In the Neo4j setup, only `dbtable`, `query`, and `customSchema` are allowed — users cannot override `url`, `user`, or `password`.

---

## 4. Lineage Tracking

### What's Available

UC tracks data lineage in two system tables:
- `system.access.table_lineage` — table-level source/target relationships
- `system.access.column_lineage` — column-level source/target relationships

### Limitations for UC JDBC Connections

For `remote_query()` / Spark JDBC queries, lineage tracking is limited:
- The Databricks documentation notes that JDBC queries may produce lineage records with **null `entity_metadata`** — meaning the system knows data was accessed but cannot always attribute it to a specific notebook or job.
- There is no `FOREIGN` value in `source_type` — federated data appears as `TABLE` when referenced by a UC-registered name.
- Queries using `remote_query()` may not generate lineage entries at all since the external source is not a registered UC table.

### Demo: Check for Lineage from Federated Queries

```sql
-- Look for any lineage entries involving the Neo4j connection or views
SELECT
  event_time,
  created_by,
  source_table_full_name,
  source_type,
  target_table_full_name,
  target_type,
  entity_type
FROM system.access.table_lineage
WHERE source_table_full_name LIKE '%neo4j%'
   OR target_table_full_name LIKE '%neo4j%'
ORDER BY event_time DESC;
```

---

## 5. Connection Metadata via Information Schema

### Demo: List All Connections

```sql
-- List all connections visible to current user
SELECT
  connection_name,
  connection_type,
  connection_owner,
  url,
  created,
  last_altered
FROM system.information_schema.CONNECTIONS;

-- Or using DDL syntax
SHOW CONNECTIONS;
SHOW CONNECTIONS LIKE 'neo4j%';

-- Full details for a specific connection
DESCRIBE CONNECTION neo4j_connection;
```

---

## 6. Putting It Together: A Demo Script

This notebook cell sequence demonstrates the full audit + authorization story:

### Step 1: Show the Connection Exists and Who Owns It

```python
# Show connection metadata
display(spark.sql("DESCRIBE CONNECTION neo4j_connection"))

# Show who has access
display(spark.sql("SHOW GRANTS ON CONNECTION neo4j_connection"))
```

### Step 2: Run a Federated Query

```python
# This query will appear in audit logs and query history
result = spark.sql("""
    SELECT * FROM remote_query('neo4j_connection',
        query => 'SELECT COUNT(*) AS cnt FROM MaintenanceEvent')
""")
display(result)
```

### Step 3: Show the Query in Audit Logs

```sql
-- Find the query we just ran (may take a few minutes to appear)
SELECT
  event_time,
  user_identity.email AS user,
  request_params['commandText'] AS query_text,
  response.status_code
FROM system.access.audit
WHERE action_name = 'commandSubmit'
  AND request_params['commandText'] LIKE '%MaintenanceEvent%'
ORDER BY event_time DESC
LIMIT 5;
```

### Step 4: Show Permission Denied Without Access

```python
# If running as a user WITHOUT USE CONNECTION, this will fail with a permission error.
# Demo: temporarily revoke access from a test user, then try the query.
#
# REVOKE USE CONNECTION ON CONNECTION neo4j_connection FROM `test-user@company.com`;
#
# When test-user runs the remote_query(), they'll get:
#   "User does not have USE CONNECTION on Connection 'neo4j_connection'"
```

### Step 5: Show Credential Isolation

```python
# Credentials are never exposed — even to users with USE CONNECTION
conn_info = spark.sql("DESCRIBE CONNECTION neo4j_connection")
display(conn_info)
# Note: password field is NOT in the output
```

---

## 7. Enabling System Tables

System tables (`system.access.audit`, `system.query.history`, etc.) must be enabled
and granted before they can be queried. This requires **account admin** or **metastore admin**
privileges — workspace admin is not sufficient.

### Prerequisites

- **Account admin** or **metastore admin** role (workspace admin alone cannot enable or grant)
- Metastore on UC Privilege Model Version 1.0
- At least one UC-enabled workspace

### Step 1: Enable System Schemas

Each schema under the `system` catalog must be enabled individually.

**Using the Databricks CLI:**

```bash
# Find your metastore ID
databricks --profile <PROFILE> metastores summary

# Enable the schemas
databricks --profile <PROFILE> system-schemas enable <METASTORE_ID> access
databricks --profile <PROFILE> system-schemas enable <METASTORE_ID> query
databricks --profile <PROFILE> system-schemas enable <METASTORE_ID> lineage
databricks --profile <PROFILE> system-schemas enable <METASTORE_ID> billing
```

**Using the REST API:**

```bash
# PUT with no body — just the schema name in the path
PUT https://<workspace-url>/api/2.0/unity-catalog/metastores/<metastore-id>/systemschemas/access
```

A convenience script is provided at `uc-neo4j-test-suite/enable_system_tables.sh`:

```bash
./enable_system_tables.sh <databricks-profile>
```

### Step 2: Grant Access to Users

Once enabled, account admins have access by default. For other users:

```sql
GRANT USE CATALOG ON CATALOG system TO `account users`;
GRANT USE SCHEMA ON SCHEMA system.access TO `account users`;
GRANT USE SCHEMA ON SCHEMA system.query TO `account users`;
GRANT SELECT ON SCHEMA system.access TO `account users`;
GRANT SELECT ON SCHEMA system.query TO `account users`;
```

### Step 3: Verify

```sql
SELECT COUNT(*) FROM system.access.audit
WHERE event_date >= CURRENT_DATE - INTERVAL 1 DAY;
```

You can also verify from the CLI using the Statement Execution API:

```bash
databricks --profile <PROFILE> api post /api/2.0/sql/statements --json '{
  "warehouse_id": "<WAREHOUSE_ID>",
  "statement": "SELECT COUNT(*) FROM system.access.audit WHERE event_date >= CURRENT_DATE - INTERVAL 1 DAY",
  "wait_timeout": "30s"
}'
```

### Azure Databricks: Account Console Access

On Azure, the Account Console is at [https://accounts.azuredatabricks.net](https://accounts.azuredatabricks.net).
Accessing it for the first time requires special attention:

**Common issue: redirect to workspace instead of Account Console.** This happens when
no account admin has been established yet — especially on auto-provisioned workspaces
(created after November 2023) where the metastore owner is `"System user"` with no
human metastore admin assigned.

**To initialize the Account Console (first time):**

1. You must be a **Microsoft Entra ID (Azure AD) Global Administrator** for the first login
2. Open an **incognito/private browser window**
3. Go to [https://accounts.azuredatabricks.net](https://accounts.azuredatabricks.net)
4. Sign in and **consent** to the Databricks Enterprise App when prompted
5. You'll land in the Account Console and automatically become the first Account Admin
6. From there, assign yourself (or others) as **metastore admin**

**To check if you're an Azure AD Global Admin:**
- [Azure Portal](https://portal.azure.com) > **Microsoft Entra ID** > **Roles and administrators** > **Global Administrator**

**If you're not a Global Admin:**
- Ask your organization's Azure Global Admin to do the first login at `accounts.azuredatabricks.net`
- They can then assign you the Account Admin role

**How to check the current metastore owner:**

```bash
databricks --profile <PROFILE> metastores summary -o json | jq '{owner, name, metastore_id}'
# If owner is "System user", no human admin has been assigned
```

**Once you have account/metastore admin access**, you can:
1. Enable system schemas (Step 1 above)
2. Grant access to users and groups (Step 2 above)
3. Assign metastore admin to other users via the Account Console

---

## 8. What UC JDBC Does NOT Provide (Gaps)


| Gap | Workaround |
|---|---|
| No table-level permissions (only connection-level) | Create separate connections per access tier |
| No row filters or column masks | Apply filters in the SQL passed to `remote_query()`, or use Neo4j-side RBAC |
| No pushed-down query capture in system tables | Check Query Profile UI manually, or log on the Neo4j side |
| No lineage to Neo4j labels/relationships | Use Neo4j query logging for server-side audit |
| Query history not captured for classic clusters | Use SQL warehouses or serverless compute |
| No foreign catalog support for Neo4j | Use UC JDBC connection (current approach) |

### Complementary Neo4j-Side Auditing

For a complete audit trail, enable Neo4j's own query logging:
- **Neo4j Aura**: Query logs are available in the Aura console
- **Neo4j Self-Managed**: Configure `dbms.logs.query.enabled=INFO` in `neo4j.conf`
- Correlate Neo4j server-side logs with Databricks audit logs by timestamp

---

## 9. Recommended Demo Flow

For presenting the security story to stakeholders:

1. **"Who can access Neo4j?"** → `SHOW GRANTS ON CONNECTION neo4j_connection`
2. **"What happens when I query?"** → Run a `remote_query()`, then show it in `system.access.audit`
3. **"Are credentials safe?"** → `DESCRIBE CONNECTION` shows no passwords; `externalOptionsAllowList` blocks overrides
4. **"Can I track query patterns?"** → `system.query.history` dashboard showing Neo4j query volume over time
5. **"What if someone shouldn't have access?"** → Revoke `USE CONNECTION`, show permission denied error
6. **"What about the views?"** → UC views over `remote_query()` (from `federated_views_agent_ready.ipynb`) go through the same governance path

---

## References

- [Audit log system table reference](https://docs.databricks.com/aws/en/admin/system-tables/audit-logs)
- [Audit Unity Catalog events](https://docs.databricks.com/aws/en/data-governance/unity-catalog/audit)
- [Query history system table reference](https://docs.databricks.com/aws/en/admin/system-tables/query-history)
- [Lineage system tables reference](https://docs.databricks.com/aws/en/admin/system-tables/lineage)
- [UC privileges and securable objects](https://docs.databricks.com/aws/en/data-governance/unity-catalog/manage-privileges/privileges)
- [JDBC Unity Catalog connection](https://docs.databricks.com/aws/en/connect/jdbc-connection)
- [Manage connections for Lakehouse Federation](https://docs.databricks.com/aws/en/query-federation/connections)
- [Row filters and column masks](https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks)
- [INFORMATION_SCHEMA.CONNECTIONS](https://docs.databricks.com/en/sql/language-manual/information-schema/connections.html)
- [View data lineage using Unity Catalog](https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-lineage)
