# Proposal: Neo4j as a Federated Data Source for Databricks Unity Catalog

## Partnership Opportunity

Neo4j and Databricks together create capabilities that neither platform provides alone. Graph algorithms detect fraud patterns in lakehouse data. AI agents bridge structured graphs with unstructured documents. Knowledge graphs grow smarter through continuous enrichment loops. The missing piece is a native connection between Neo4j and Databricks Unity Catalog's Lakehouse Federation.

This proposal outlines how to establish that connection using Unity Catalog's JDBC federation with the Neo4j JDBC driver. The integration enables SQL-based queries against graph data, Unity Catalog governance at the connection level, and the foundation for advanced patterns like agent-augmented knowledge graphs.

**Joint opportunities this enables:**

- **Fraud detection pipelines**: Graph algorithms like community detection and PageRank run on entities loaded from Delta Lake, with results flowing back to gold layer tables for ML training
- **Agent-augmented knowledge graphs**: Databricks AI agents (Genie for structured queries, Knowledge Assistants for document RAG) analyze gaps between graph data and unstructured documents, proposing enrichments that write back to Neo4j
- **Customer 360 views**: Transactional data in the lakehouse combines with relationship-rich graph traversals for recommendation systems and churn prediction
- **Continuous enrichment loops**: Each cycle compounds insights as agents discover relationships that graph algorithms then surface for business users


## Proposed Solution

Databricks provides a mechanism for connecting unsupported databases through the [JDBC Unity Catalog connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) feature with a "bring your own driver" capability. This allows organizations to upload custom JDBC driver JAR files to Unity Catalog volumes and create connections to any JDBC-compliant database.

Neo4j provides an official, production-ready [JDBC driver (version 6.10.3)](https://github.com/neo4j/neo4j-jdbc) that adheres to JDBC 4.3 specification. This driver can translate SQL queries into Cypher (Neo4j's query language) and expose graph data through standard JDBC metadata interfaces.

The proposed solution connects Neo4j to Databricks through the JDBC Unity Catalog connection mechanism, enabling Spark-based queries against Neo4j data with Unity Catalog governance at the connection level.

## Expected Outcomes

- Direct SQL-based query access to Neo4j graph data from Databricks notebooks, SQL editor, and connected BI tools
- Unity Catalog governance and access control at the connection level
- Ability to join Neo4j graph results with other Databricks data sources
- Validation of integration feasibility before committing to larger-scale deployment

---

## Technical Foundation

### Databricks JDBC Connection Requirements

Per the [Databricks JDBC connection documentation](https://docs.databricks.com/aws/en/connect/jdbc-connection):

1. **Compute Requirements**: Databricks Runtime 17.3 LTS or above (serverless, standard, or dedicated access mode), or SQL warehouses using pro/serverless version 2025.35 or above

2. **Driver Storage**: Custom JDBC drivers must be stored in Unity Catalog volumes and referenced via the `java_dependencies` environment parameter

3. **Authentication**: Only basic authentication (username and password) is supported; no OAuth or service credentials

4. **Connection Type**: The `TYPE JDBC` connection provides connection-level governance only (not table-level like native query federation sources)

### Neo4j JDBC Driver Capabilities

Per the [Neo4j JDBC Driver documentation](https://github.com/neo4j/neo4j-jdbc) (version 6.10.3):

1. **JDBC Compliance**: Full JDBC 4.3 compliance with `DatabaseMetaData` and `ResultSetMetaData` implementations

2. **Driver Class**: `org.neo4j.jdbc.Neo4jDriver`

3. **Connection URL Format**: `jdbc:neo4j://[host]:[port]/[database]` (with `+s` or `+ssc` suffixes for SSL)

4. **SQL Translation**: Optional automatic SQL-to-Cypher translation via the `enableSQLTranslation=true` parameter

5. **Metadata Mapping** (from `docs/src/main/asciidoc/modules/ROOT/pages/metadata.adoc`):
   - Catalog: Equals the connected Neo4j database name
   - Schema: Always reports as "public"
   - Tables: Node labels are exposed as tables with `TABLE_TYPE` = "TABLE"
   - Primary Keys: Derived from unique constraints, or uses virtual `elementId()` column

6. **Distribution Options**:
   - `neo4j-jdbc-bundle`: Small bundle without SQL translator (for native Cypher queries)
   - `neo4j-jdbc-full-bundle`: Full bundle with SQL-to-Cypher translator (recommended for this use case)

### Critical Limitations to Understand

**From Databricks**:
- JDBC connections do not support foreign catalog creation; governance is at connection-level only
- No predicate pushdown optimization for JDBC data sources
- URL and host parameters cannot be overridden at query time (security restriction)

**From Neo4j JDBC Driver** (from `docs/src/main/asciidoc/modules/ROOT/pages/sql2cypher.adoc`):
- SQL-to-Cypher translation supports only a subset of SQL:
  - No `LEFT JOIN`, `RIGHT JOIN`, `FULL OUTER JOIN` (only `INNER JOIN` and `NATURAL JOIN`)
  - No `GROUP BY`, `HAVING` clauses
  - No window functions
  - No set operations (`UNION`, `EXCEPT`, `INTERSECT`)
  - Limited aggregate functions (primarily `COUNT`)
- Multi-label nodes appear as multiple table entries (can cause result duplication)
- No reliable datatype detection without scanning all node properties

---

## Phased Validation Approach

### Phase 1: Basic Connectivity Proof-of-Concept

**Objective**: Validate that the Neo4j JDBC driver can be loaded by Databricks and establish a basic connection.

**Prerequisites**:
- Access to a Databricks workspace with Unity Catalog enabled
- A Neo4j instance (version 5.5 or higher) accessible from Databricks compute
- Network connectivity between Databricks and Neo4j (firewall rules, VPC peering if needed)
- Unity Catalog metastore admin or `CREATE CONNECTION` privilege
- **"Custom JDBC on UC Compute" preview feature enabled** (see Step 1.0)

**Steps**:

#### Step 1.0: Enable the Custom JDBC Preview Feature

The JDBC Unity Catalog connection with custom drivers is currently a **Private Preview** feature that must be explicitly enabled in your Databricks workspace.

**Verify your SQL warehouse version first:**
```sql
SELECT current_version()
```
The result must show `dbsql_version` of **2025.35 or above**. If using a cluster, ensure it runs **Databricks Runtime 17.3 LTS or higher**.

**Enable the required previews:**
1. Click your **username** in the top bar of the Databricks workspace
2. Select **Previews** from the dropdown menu
3. Enable the following two preview features:

| Preview Feature | Description | Required For |
|-----------------|-------------|--------------|
| **Custom JDBC on UC Compute** | Enables JDBC connections with custom drivers through Unity Catalog | Creating the Neo4j connection |
| **Enables remote query table-valued function (remote_query)** | Allows executing queries using credentials from a Unity Catalog connection | Using `SELECT * FROM remote_query(...)` syntax |

**Preview Descriptions**:

- **Custom JDBC on UC Compute**: *"This feature enables users to connect to data sources using a custom JDBC driver through the Spark Data Source API. The new UC Connection of type JDBC, runs a user-provided JDBC driver powered by Lakeguard isolation on UC-supported compute: serverless, standard, and dedicated clusters with DBR 17.3 or higher."*

- **remote_query function**: *"Function allows users to execute query in remote engine syntax using credentials from a Unity Catalog connection. Function is available on Databricks Runtime 17.3 or above."* (Public Preview)

**Important**: Without these previews enabled:
- Missing **Custom JDBC on UC Compute**: You will receive the error `[UNSUPPORTED_FEATURE.ENVIRONMENT_NOT_ALLOWED] The feature is not supported: Environment clause is not supported in this context` when attempting to create a JDBC connection with the `ENVIRONMENT` clause.
- Missing **remote_query function**: The `remote_query()` table-valued function will not be available for executing SQL queries against the connection.

For additional details, see the [Databricks Custom JDBC Connection documentation](https://docs.google.com/document/d/1xQvePREa0JxdMK5XHYjqSFXKT08C_qap17oGthRdESE/edit?tab=t.0).

**Reference Documentation**: The official Databricks guide for this feature is available at:
- **[Custom JDBC on UC Compute - Private Preview Documentation](https://docs.google.com/document/d/1xQvePREa0JxdMK5XHYjqSFXKT08C_qap17oGthRdESE/edit?tab=t.0)** - Contains detailed setup instructions, limitations, and best practices for using custom JDBC drivers with Unity Catalog.

#### Step 1.1: Obtain the Neo4j JDBC Driver JAR

Use the prebuilt JAR from this repository that includes the **SparkSubqueryCleaningTranslator** module for better Spark compatibility:

```
neo4j_jdbc_spark_cleaning/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar
```

This custom build includes:
- **neo4j-jdbc-full-bundle**: Core driver with SQL-to-Cypher translation
- **neo4j-jdbc-translator-sparkcleaner**: Handles Spark's schema inference subquery wrapping (`SELECT * FROM (query) SPARK_GEN_SUBQ_0 WHERE 1=0`)

**Important**: The driver class name is `org.neo4j.jdbc.Neo4jDriver`.

**Alternative: Official Release (without SparkCleaner)**

If you prefer the official release (note: does not include SparkSubqueryCleaningTranslator):
```
https://github.com/neo4j/neo4j-jdbc/releases/download/6.10.3/neo4j-jdbc-full-bundle-6.10.3.jar
```

**Need to Rebuild?**

If you need to rebuild the JAR with sparkcleaner from source (e.g., for a newer version), see [CLEANER_USER.md](./CLEANER_USER.md) for complete build instructions. Key requirements:
- JDK 25 to build (outputs JDK 17 bytecode for Databricks Runtime 17.3 LTS compatibility)
- Modify `bundles/neo4j-jdbc-full-bundle/pom.xml` to add sparkcleaner dependency
- Build with `./mvnw -Dfast package`

#### Step 1.2: Create a Unity Catalog Volume for the Driver

Run this SQL in the Databricks SQL editor or a notebook cell to create a volume for storing JDBC drivers:

```sql
-- Create a schema for JDBC drivers if it doesn't exist
CREATE SCHEMA IF NOT EXISTS main.jdbc_drivers;

-- Create a volume to store custom JDBC driver JARs
CREATE VOLUME IF NOT EXISTS main.jdbc_drivers.jars;
```

After creating the volume, upload the JAR file:
1. Navigate to **Catalog** in the Databricks workspace
2. Browse to `main` > `jdbc_drivers` > `jars`
3. Click **Upload to this volume**
4. Select `neo4j-jdbc-translator-sparkcleaner-6.10.3.jar` from `neo4j_jdbc_spark_cleaning/`

The driver will be available at path: `/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar`

#### Step 1.3: Create Databricks Secrets (Recommended)

Set up a secret scope and secrets using the Databricks CLI to securely store Neo4j credentials:

```bash
# Create a secret scope for Neo4j credentials
databricks secrets create-scope neo4j-secrets

# Add the username secret
databricks secrets put-secret neo4j-secrets username --string-value "neo4j"

# Add the password secret
databricks secrets put-secret neo4j-secrets password --string-value "your-password"
```

#### Step 1.4: Create the JDBC Connection

Run this SQL to create the Neo4j connection. Replace the placeholder values with your actual Neo4j instance details:

```sql
-- Drop existing connection if re-creating
DROP CONNECTION IF EXISTS neo4j_connection;

-- Create the Neo4j JDBC connection with SQL translation enabled
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '["/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar"]'
)
OPTIONS (
  url 'jdbc:neo4j://your-neo4j-host:7687/neo4j?enableSQLTranslation=true',
  user SECRET('neo4j-secrets', 'username'),
  password SECRET('neo4j-secrets', 'password'),
  externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize'
);
```

**Important**: The `enableSQLTranslation=true` parameter is essential for executing SQL queries against Neo4j. Without this parameter, only native Cypher queries will work.

**Connection URL Format Options** (per [Neo4j JDBC documentation](https://github.com/neo4j/neo4j-jdbc)):

| URL Format | Description |
|------------|-------------|
| `jdbc:neo4j://host:7687/database?enableSQLTranslation=true` | Bolt protocol, no encryption, SQL enabled |
| `jdbc:neo4j+s://host:7687/database?enableSQLTranslation=true` | Bolt with SSL (CA-verified certificate) |
| `jdbc:neo4j+ssc://host:7687/database?enableSQLTranslation=true` | Bolt with SSL (self-signed certificate allowed) |

**For Neo4j Aura (cloud)**:
```sql
OPTIONS (
  url 'jdbc:neo4j+s://xxxxxxxx.databases.neo4j.io:7687/neo4j?enableSQLTranslation=true',
  ...
)
```

**Alternative: Plaintext credentials for initial testing** (not recommended for production):
```sql
CREATE CONNECTION neo4j_connection_test TYPE JDBC
ENVIRONMENT (
  java_dependencies '["/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar"]'
)
OPTIONS (
  url 'jdbc:neo4j://your-neo4j-host:7687/neo4j?enableSQLTranslation=true',
  user 'neo4j',
  password 'your-password',
  externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize'
);
```

#### Step 1.5: Test Network Connectivity

Before testing queries, verify that Databricks compute can reach your Neo4j instance.

##### Test 1.5.1: Basic TCP Connectivity (Network Layer)

Use this temporary UDF to test that the network path to Neo4j is open:

```sql
-- Create a temporary function to test TCP connectivity
CREATE OR REPLACE TEMPORARY FUNCTION connectionTest(host STRING, port STRING)
RETURNS STRING
LANGUAGE PYTHON AS $$
import subprocess
try:
    command = ['nc', '-zv', host, str(port)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = result.stdout.decode() + result.stderr.decode()

    if result.returncode == 0:
        status = "SUCCESS"
        message = f"Network connectivity to {host}:{port} is OPEN"
    else:
        status = "FAILURE"
        message = f"Cannot reach {host}:{port} - check firewall rules and network configuration"

    return f"{status} (return_code={result.returncode}) | {message} | Details: {output.strip()}"
except Exception as e:
    return f"FAILURE (exception) | Error running connectivity test: {str(e)}"
$$;

-- Test connectivity to your Neo4j instance
-- IMPORTANT: Use only the hostname, NOT the full JDBC URL
SELECT connectionTest('your-neo4j-host', '7687') AS connectivity_result;
```

**Important**: The `connectionTest` function requires only the **hostname**, not the JDBC URL scheme:

| Correct | Incorrect |
|---------|-----------|
| `connectionTest('3f1f827a.databases.neo4j.io', '7687')` | `connectionTest('neo4j+s://3f1f827a.databases.neo4j.io', '7687')` |
| `connectionTest('my-neo4j-server.company.com', '7687')` | `connectionTest('jdbc:neo4j://my-neo4j-server.company.com', '7687')` |

**Expected Results**:
- **Success**: Return code `0` (e.g., `0|Connection to host port 7687 [tcp/*] succeeded!`)
- **Failure**: Non-zero return code indicates network connectivity issues

**Note**: A warning like `inverse host lookup failed` is normal and does not indicate a problem - it just means reverse DNS lookup isn't configured for the IP address.

##### Test 1.5.2: Neo4j Driver Connectivity (Application Layer)

After confirming TCP connectivity, test the actual Neo4j driver connection. Run this in a Python notebook cell:

```python
# Test Neo4j driver connectivity (requires neo4j Python package installed on cluster)
from neo4j import GraphDatabase

# Replace with your Neo4j connection details
NEO4J_URI = "neo4j+s://xxxxxxxx.databases.neo4j.io"  # Use neo4j+s:// for Aura
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "your-password"  # Or use dbutils.secrets.get("neo4j-secrets", "password")

try:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # Verify connectivity
    driver.verify_connectivity()
    print("✓ Driver connectivity verified")

    # Test a simple query
    with driver.session() as session:
        result = session.run("RETURN 1 AS test")
        record = result.single()
        print(f"✓ Query executed successfully: {record['test']}")

        # Get database info
        result = session.run("CALL dbms.components() YIELD name, versions RETURN name, versions")
        for record in result:
            print(f"✓ Connected to: {record['name']} {record['versions']}")

    driver.close()
    print("\n✓ All connectivity tests passed!")

except Exception as e:
    print(f"✗ Connection failed: {e}")
```

**For Neo4j Aura**, use the `neo4j+s://` scheme (SSL required):
```python
NEO4J_URI = "neo4j+s://3f1f827a.databases.neo4j.io"
```

**For self-hosted Neo4j**, use the appropriate scheme:
```python
NEO4J_URI = "neo4j://my-server:7687"       # No encryption
NEO4J_URI = "neo4j+s://my-server:7687"     # SSL with CA-verified cert
NEO4J_URI = "neo4j+ssc://my-server:7687"   # SSL with self-signed cert
```

**Common Port Values**:
| Port | Protocol | Use Case |
|------|----------|----------|
| `7687` | Bolt | Default Neo4j connection port (recommended) |
| `7473` | HTTPS | Neo4j Browser/HTTP API with SSL |
| `7474` | HTTP | Neo4j Browser/HTTP API without SSL |

**Troubleshooting Connectivity Issues**:
- Verify firewall rules allow outbound connections from Databricks to Neo4j
- For private Neo4j instances, ensure VPC peering or Private Link is configured
- Check that the Neo4j instance is running and accepting connections
- For Aura, ensure you're using `neo4j+s://` (SSL is required)

#### Step 1.6: Test Basic Query Execution

The following examples use an aircraft operations database with nodes for Aircraft, Flight, Airport, Delay, MaintenanceEvent, System, Component, Sensor, and Reading.

**Important**: The primary goal of this integration is to execute **SQL queries** through Unity Catalog federation, which are automatically translated to Cypher by the Neo4j JDBC driver. This allows users familiar with SQL to query graph data without learning Cypher.

**Test 1: Simple SQL SELECT using `remote_query()`**

Run in the Databricks SQL editor or a notebook SQL cell:

```sql
-- Query aircraft data using standard SQL
-- The Neo4j JDBC driver translates this to: MATCH (a:Aircraft) RETURN a.aircraft_id, a.tail_number, a.model, a.manufacturer, a.operator LIMIT 10
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'SELECT aircraft_id, tail_number, model, manufacturer, operator FROM Aircraft LIMIT 10'
);
```

**Test 2: SQL SELECT with WHERE clause**

```sql
-- Query airports filtered by country
-- Translates to: MATCH (a:Airport) WHERE a.country = ''USA'' RETURN a.name, a.city, a.iata
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'SELECT name, city, iata FROM Airport WHERE country = ''USA'' LIMIT 20'
);
```

**Test 3: SQL SELECT with ORDER BY**

```sql
-- Query flights ordered by departure time
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'SELECT flight_number, origin, destination, scheduled_departure FROM Flight ORDER BY scheduled_departure DESC LIMIT 10'
);
```

**Test 4: SQL COUNT aggregate**

```sql
-- Count total flights in the database
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'SELECT COUNT(*) AS flight_count FROM Flight'
);
```

**Test 5: Query using `dbtable` option (Python)**

The Neo4j JDBC driver exposes node labels as tables, which can be read directly:

```python
# Read all Airport nodes as a table using Spark DataFrame API
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("dbtable", "Airport") \
    .load()

df.show()
df.printSchema()  # View the schema derived from Neo4j node properties
```

**Test 6: Verify available tables (node labels)**

```sql
-- List all available node labels (tables) in Neo4j
-- Note: This uses a Cypher procedure since it's a metadata query
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'CALL db.labels() YIELD label RETURN label ORDER BY label'
);
```

**Test 7: SQL SELECT with Python DataFrame API**

```python
# Query using SQL through the Spark DataFrame API
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("query", "SELECT tail_number, model, manufacturer FROM Aircraft WHERE manufacturer = 'Boeing' LIMIT 10") \
    .load()

df.show()
```

**Note on Complex Queries**: For queries involving relationship traversals, aggregations with GROUP BY, or complex graph patterns, see Phase 2 which covers SQL-to-Cypher translation capabilities and the use of native Cypher for advanced operations.

#### Step 1.7: Troubleshooting Common Issues

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| `UNSUPPORTED_FEATURE.ENVIRONMENT_NOT_ALLOWED` | Preview feature not enabled | Enable "Custom JDBC on UC Compute" in workspace Previews (see Step 1.0) |
| `ClassNotFoundException: org.neo4j.jdbc.Neo4jDriver` | JAR not loaded correctly | Verify volume path is correct and user has READ access |
| Connection timeout | Network connectivity | Check firewall rules, VPC peering, security groups; run connectivity test (Step 1.5) |
| Authentication failed | Wrong credentials | Verify username/password; check Neo4j user exists |
| SSL handshake failure | Certificate issue | Use `+ssc` suffix for self-signed certs, or configure trust |
| SQL query returns empty or error | SQL translation not enabled | For Phase 1, ensure `enableSQLTranslation=true` is in the connection URL (see Step 1.4) |

**Success Criteria**:
- Connection creation completes without errors
- A simple query returns data from Neo4j
- Results can be displayed in a Databricks notebook cell

**Estimated Effort**: One to two days for a technical proof-of-concept

---

### Phase 2: Advanced SQL Translation and Metadata Exploration

**Objective**: Explore advanced SQL-to-Cypher translation features including JOIN operations, metadata discovery, and native Cypher fallback for complex queries.

**Prerequisites**: Successful completion of Phase 1 (SQL translation is already enabled via `enableSQLTranslation=true` in the connection URL)

**Steps**:

#### Step 2.1: Optional Connection Tuning

The `neo4j_connection` created in Phase 1 already has SQL translation enabled. This step covers optional parameters to optimize translation performance.

**Additional SQL Translation Parameters** (per [Neo4j JDBC sql2cypher.adoc](https://github.com/neo4j/neo4j-jdbc/blob/main/docs/src/main/asciidoc/modules/ROOT/pages/sql2cypher.adoc)):

| Parameter | Description | Default |
|-----------|-------------|---------|
| `enableSQLTranslation` | Enable automatic SQL-to-Cypher translation | `false` |
| `cacheSQLTranslations` | Cache translated queries (LRU, 64 entries) | `false` |
| `s2c.prettyPrint` | Format generated Cypher for readability | `true` |
| `s2c.alwaysEscapeNames` | Always escape identifiers in Cypher | `true` |
| `s2c.sqlDialect` | SQL dialect for parser (POSTGRES, MYSQL, DEFAULT) | `DEFAULT` |

**To enable caching** (recommended for repeated queries), recreate the connection:
```sql
-- Optional: Recreate connection with caching for better performance
DROP CONNECTION IF EXISTS neo4j_connection;

CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '["/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar"]'
)
OPTIONS (
  url 'jdbc:neo4j://your-neo4j-host:7687/neo4j?enableSQLTranslation=true&cacheSQLTranslations=true',
  user SECRET('neo4j-secrets', 'username'),
  password SECRET('neo4j-secrets', 'password'),
  externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize'
);
```

#### Step 2.2: Test SQL JOIN Operations (Relationship Traversals)

SQL JOIN operations are translated to Cypher relationship patterns. Per the [Neo4j JDBC documentation](https://github.com/neo4j/neo4j-jdbc/blob/main/docs/src/main/asciidoc/modules/ROOT/pages/sql2cypher.adoc), only `INNER JOIN` and `NATURAL JOIN` are supported.

**Test 2.2.1: INNER JOIN on relationship**

```sql
-- Join Aircraft to Flight via relationship
-- The translator infers relationships from the join column pattern
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'SELECT a.tail_number, f.flight_number
            FROM Aircraft AS a
            JOIN Flight AS f ON (f.aircraft_id = a.aircraft_id)
            LIMIT 20'
);
```

**Test 2.2.2: Alternative JOIN syntax with relationship table pattern**

```sql
-- Using explicit relationship table naming pattern: Label_RELTYPE_Label
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'SELECT f.flight_number, a.name AS airport_name, a.city
            FROM Flight AS f
            JOIN Flight_DEPARTS_FROM_Airport AS r ON (f.flight_id = r.flight_id)
            JOIN Airport AS a ON (a.airport_id = r.airport_id)
            LIMIT 20'
);
```

**Important**: Relationship inference is heuristic-based. The translator uses these strategies (per sql2cypher.adoc):
1. Existing relationship template in the database
2. Table name pattern matching (`Label_RELTYPE_Label`)
3. Column name mappings configured via `s2c.joinColumnsToTypeMappings`

#### Step 2.3: Explore Neo4j Metadata as Tables

Per the [Neo4j JDBC metadata.adoc](https://github.com/neo4j/neo4j-jdbc/blob/main/docs/src/main/asciidoc/modules/ROOT/pages/metadata.adoc), the driver exposes Neo4j metadata through standard JDBC interfaces:

**Test 2.3.1: List all available "tables" (node labels)**

```sql
-- List all node labels available as tables
-- Note: This uses a Cypher procedure since it's a metadata query
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'CALL db.labels() YIELD label RETURN label ORDER BY label'
);
```

**Test 2.3.2: List properties for a label (columns for a table)**

```sql
-- Get schema information for Aircraft nodes (column definitions)
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'CALL db.schema.nodeTypeProperties()
            YIELD nodeLabels, propertyName, propertyTypes
            WHERE ''Aircraft'' IN nodeLabels
            RETURN propertyName, propertyTypes'
);
```

**Test 2.3.3: List relationship types**

```sql
-- Get available relationship types (for understanding JOIN possibilities)
SELECT * FROM remote_query(
  'neo4j_connection',
  query => 'CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType'
);
```

**Test 2.3.4: Using dbtable to read entire label as table (Python)**

```python
# Read all Aircraft using dbtable - useful for exploring schema
df = spark.read.format("jdbc") \
    .option("databricks.connection", "neo4j_connection") \
    .option("dbtable", "Aircraft") \
    .load()

print("Aircraft table schema:")
df.printSchema()

print("\nAircraft data:")
df.show()
```

#### Step 2.4: Native Cypher for Complex Operations

Some operations cannot be expressed in the supported SQL subset. Use the `/*+ NEO4J FORCE_CYPHER */` hint to bypass SQL translation and send Cypher directly. This is useful for:
- Multi-hop relationship traversals
- Aggregations with GROUP BY
- Path queries and graph algorithms

**Test 2.4.1: Complex graph traversal (multi-hop)**

```sql
-- Multi-hop traversal: Aircraft -> System -> Component -> MaintenanceEvent
-- Not expressible in standard SQL, requires native Cypher
SELECT * FROM remote_query(
  'neo4j_connection',
  query => '/*+ NEO4J FORCE_CYPHER */
            MATCH (a:Aircraft)-[:HAS_SYSTEM]->(s:System)-[:HAS_COMPONENT]->(c:Component)-[:HAS_EVENT]->(m:MaintenanceEvent)
            RETURN a.tail_number AS aircraft, s.name AS system, c.name AS component, m.event_type AS event
            LIMIT 20'
);
```

**Test 2.4.2: Aggregations with GROUP BY**

```sql
-- GROUP BY not supported in SQL translation - use native Cypher
SELECT * FROM remote_query(
  'neo4j_connection',
  query => '/*+ NEO4J FORCE_CYPHER */
            MATCH (a:Aircraft)-[:OPERATES_FLIGHT]->(f:Flight)-[:HAS_DELAY]->(d:Delay)
            RETURN a.tail_number AS aircraft, COUNT(d) AS delay_count, SUM(d.minutes) AS total_delay_minutes
            ORDER BY total_delay_minutes DESC
            LIMIT 10'
);
```

**Test 2.4.3: Path queries**

```sql
-- Find flight paths from JFK to other airports
SELECT * FROM remote_query(
  'neo4j_connection',
  query => '/*+ NEO4J FORCE_CYPHER */
            MATCH (origin:Airport {iata: ''JFK''})<-[:DEPARTS_FROM]-(f:Flight)-[:ARRIVES_AT]->(dest:Airport)
            RETURN origin.iata AS from_airport,
                   f.flight_number AS flight,
                   dest.iata AS to_airport,
                   f.scheduled_departure AS departure
            LIMIT 20'
);
```

#### Step 2.5: SQL Translation Compatibility Reference

Use this table as a quick reference for what SQL features are supported by the Neo4j JDBC driver's SQL-to-Cypher translation:

| SQL Feature | Supported | Notes |
|-------------|-----------|-------|
| `SELECT column1, column2` | Yes | Maps to Cypher RETURN |
| `SELECT *` | Yes | Expands to all properties when connected |
| `WHERE` with comparison operators | Yes | `=`, `<>`, `<`, `>`, `<=`, `>=` |
| `WHERE` with `LIKE` | Yes | Translates to Cypher `CONTAINS`/`STARTS WITH`/`ENDS WITH` |
| `WHERE` with `IN` | Yes | Translates to Cypher `IN` |
| `WHERE` with `AND`/`OR` | Yes | Standard boolean logic |
| `ORDER BY` | Yes | Maps directly to Cypher |
| `LIMIT` | Yes | Maps directly to Cypher |
| `COUNT(*)` | Yes | Supported aggregate |
| `INNER JOIN` | Yes | Maps to relationship pattern |
| `NATURAL JOIN` | Yes | Maps to relationship pattern |
| `LEFT/RIGHT/FULL OUTER JOIN` | **No** | Not supported |
| `GROUP BY` | **No** | Use native Cypher |
| `HAVING` | **No** | Use native Cypher |
| `SUM`, `AVG`, `MIN`, `MAX` | **No** | Use native Cypher |
| `UNION`, `EXCEPT`, `INTERSECT` | **No** | Use native Cypher |
| Window functions | **No** | Use native Cypher |
| Subqueries | **No** | Use native Cypher |
| `INSERT` | Yes | Creates nodes or relationships |
| `UPDATE` | Yes | Updates properties |
| `DELETE` | Yes | Deletes nodes or relationships |

**Success Criteria**:
- Basic SQL queries execute successfully via translation
- Join operations between related nodes work as expected
- Clear documentation of supported and unsupported query patterns

**Estimated Effort**: Two to three days

---

### Phase 3: Integration with Databricks Workflows

**Objective**: Validate practical usage scenarios with Databricks notebooks and Spark DataFrames.

**Prerequisites**: Successful completion of Phase 2

**Steps**:

1. **Spark DataFrame Integration**
   - Load Neo4j data into Spark DataFrames using the JDBC connection
   - Test performance with varying data volumes
   - Configure parallelization options (`numPartitions`, `partitionColumn`, etc.) where applicable

2. **Data Combination Scenarios**
   - Join Neo4j query results with data from Unity Catalog tables
   - Test combining graph traversal results with traditional tabular data

3. **Access Control Validation**
   - Grant connection access to test users
   - Verify that Unity Catalog governance restricts access appropriately
   - Confirm that users without connection access cannot query Neo4j

4. **Performance Baseline**
   - Document query execution times for representative query patterns
   - Note any timeout or memory issues with larger result sets
   - Identify queries that benefit from native Cypher versus SQL translation

**Success Criteria**:
- Neo4j data can be loaded into Spark DataFrames
- Results can be joined with other Databricks data sources
- Access control works as expected at the connection level

**Estimated Effort**: Three to five days

---

## Known Limitations and Workarounds

### Limitation 1: No Foreign Catalog Support

**Issue**: JDBC connections in Databricks do not support `CREATE FOREIGN CATALOG`. This means Neo4j tables cannot appear as browsable objects in the Unity Catalog explorer.

**Workaround**: Create documented views or saved queries that encapsulate common Neo4j access patterns. Users query Neo4j through explicit connection references rather than catalog navigation.

**Reference**: [Databricks Query Federation documentation](https://docs.databricks.com/aws/en/query-federation/index) notes that query federation "provides fine-grained access controls and governance at table-level using a foreign catalog" while JDBC connections provide "governance only at the connection level."

### Limitation 2: Limited SQL Translation

**Issue**: The Neo4j JDBC driver's SQL-to-Cypher translator does not support all SQL constructs (no outer joins, limited aggregations, no window functions).

**Workaround**: Use native Cypher queries for complex operations by prefixing queries with the `/*+ NEO4J FORCE_CYPHER */` hint. This bypasses SQL translation and sends Cypher directly to Neo4j.

**Reference**: [Neo4j JDBC sql2cypher documentation](https://github.com/neo4j/neo4j-jdbc/blob/main/docs/src/main/asciidoc/modules/ROOT/pages/sql2cypher.adoc) documents the `/*+ NEO4J FORCE_CYPHER */` hint for bypassing translation.

### Limitation 3: No Predicate Pushdown

**Issue**: Databricks notes that "neither JDBC nor PySpark data sources support predicate pushdown" for generic JDBC connections.

**Workaround**: Use the `query` option in Spark JDBC reads to push filtering logic into the connection query itself, reducing data transfer.

**Reference**: [Databricks JDBC connection documentation](https://docs.databricks.com/aws/en/connect/jdbc-connection) states this limitation explicitly.

### Limitation 4: Basic Authentication Only

**Issue**: Databricks JDBC connections support only username/password authentication. Neo4j SSO or OAuth tokens are not supported through this path.

**Workaround**: Create a dedicated Neo4j database user for the Databricks connection with appropriate read permissions. Store credentials using Databricks secrets rather than plaintext.

**Reference**: [Databricks documentation](https://docs.databricks.com/aws/en/connect/jdbc-connection) states "Only basic authentication is supported (username and password). There's no support for Unity Catalog credentials, OAuth, or service credentials."

---

## Requirements Summary

1. **R1**: The Neo4j JDBC driver JAR must be uploadable to a Unity Catalog volume
2. **R2**: A JDBC connection must be creatable with `TYPE JDBC` referencing the Neo4j driver
3. **R3**: Basic SQL queries must execute successfully against Neo4j node labels as tables
4. **R4**: Results must be loadable into Spark DataFrames for further processing
5. **R5**: Connection-level access control must restrict unauthorized users from querying Neo4j
6. **R6**: Native Cypher queries must be executable through the JDBC connection for complex operations

---

## Next Steps

1. **Approval**: Review this proposal and confirm alignment with project objectives
2. **Environment Setup**: Ensure Databricks and Neo4j environments meet the prerequisites
3. **Phase 1 Execution**: Begin with basic connectivity proof-of-concept
4. **Checkpoint Review**: After Phase 1, evaluate results before proceeding to Phase 2

---

## References

### Databricks Documentation
- [JDBC Unity Catalog Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) - Custom driver upload and connection creation
- [Query Federation Overview](https://docs.databricks.com/aws/en/query-federation/index) - Lakehouse Federation capabilities and supported sources
- [CREATE CONNECTION Syntax](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-connection) - SQL syntax reference
- [Manage Connections for Lakehouse Federation](https://docs.databricks.com/aws/en/query-federation/connections) - Permission and access management

### Neo4j JDBC Driver Documentation
- [Neo4j JDBC Driver Repository](https://github.com/neo4j/neo4j-jdbc) - Official driver source and releases
- [Driver README](https://github.com/neo4j/neo4j-jdbc/blob/main/README.adoc) - Quick start and feature overview
- SQL to Cypher Translation: `/docs/src/main/asciidoc/modules/ROOT/pages/sql2cypher.adoc` - Translation capabilities and limitations
- Metadata Handling: `/docs/src/main/asciidoc/modules/ROOT/pages/metadata.adoc` - Catalog, schema, and table mapping

### Databricks Community Discussions
- [Unity Catalog Limited Options for Connection Objects](https://community.databricks.com/t5/data-governance/unity-catalog-limited-options-for-connection-objects/td-p/56504) - Community feedback on connection limitations
