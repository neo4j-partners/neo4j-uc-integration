# Databricks Unity Catalog & Neo4j JDBC Federation

This project tests the integration of Neo4j as a federated data source within Databricks Unity Catalog using the Neo4j JDBC driver, based on the approach defined in [ Neo4j as a Federated Data Source for Databricks Unity Catalog](./neo4j_databricks_jdbc_federation_proposal.md). The goal is to validate SQL-to-Cypher translation through Unity Catalog's JDBC federation and document what works and what is currently broken.

Two Spark notebooks demonstrate the current issue with using the Neo4j JDBC driver through [Unity Catalog JDBC connections](https://docs.databricks.com/aws/en/connect/jdbc-connection). The notebooks show that the Neo4j JDBC driver works when loaded directly into Spark, but fails when routed through Unity Catalog's isolated sandbox environment (SafeSpark). Databricks uses this isolation layer to "install the JDBC driver in an isolated sandbox accessible by Spark compute to ensure Spark security and Unity Catalog governance." The sandbox appears to be breaking the integration because it intercepts JDBC calls through a gRPC wrapper that is incompatible with the Neo4j driver's connection handling. The next step is to work with Databricks to troubleshoot this incompatibility.

## Current Status Summary

### Databricks Notebook Status - Primary Demonstration of Current Blockers

The following two notebooks are the primary demonstration of the current blockers with Unity Catalog JDBC integration:

| Notebook | Status | Description |
|----------|--------|-------------|
| [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) | **FAIL** | Full test suite (Sections 1-8) covering network connectivity, Neo4j Python driver, Spark Connector, Direct JDBC, and Unity Catalog JDBC tests. **UC JDBC tests fail due to SafeSpark incompatibility.** |
| [`neo4j_schema_test.ipynb`](uc-neo4j-test-suite/neo4j_schema_test.ipynb) | **FAIL** | Focused schema testing (Sections 1, 3, 8) demonstrating JDBC DatabaseMetaData schema discovery and Unity Catalog object creation. **Fails when using UC JDBC connection.** |

The rest of the samples and code in this repository demonstrate how Neo4j JDBC works for SQL-to-Cypher translation and schema discovery of graph-to-relational mapping when used outside of Unity Catalog's SafeSpark wrapper.

## SafeSpark and the Unity Catalog Neo4j JDBC Blocker

### Current Status Summary

SafeSpark appears to be what is blocking the JDBC Unity Catalog connection from working with the Neo4j driver. Based on my investigation of the error stack traces and testing, this is what I understand is happening.

### What is SafeSpark?

**SafeSpark** is Databricks' internal isolation layer for running custom JDBC drivers in Unity Catalog. When you create a UC JDBC connection with a custom driver, SafeSpark:

1. **Runs JDBC drivers in a sandboxed process** - The driver JAR executes in an isolated container/process, not directly in the Spark executor
2. **Communicates via gRPC** - Spark talks to the isolated driver through a gRPC bridge
3. **Enforces security boundaries** - Prevents custom drivers from accessing cluster resources, secrets, or other data directly

This architecture provides security isolation but introduces a layer that can cause compatibility issues with certain JDBC drivers.

### Evidence that SafeSpark Is Causing the Errors

The SafeSpark components are visible in error messages when Unity Catalog JDBC connections fail:

```
java.lang.RuntimeException: Connection was closed before the operation completed.
    at com.databricks.safespark.jdbc.grpc_client.JdbcConnectClient.awaitWhileConnected
    at com.databricks.safespark.jdbc.grpc_client.JdbcGetRowsClient.fetchMetadata
    at com.databricks.safespark.jdbc.driver.GrpcResultSet.metadata$lzycompute
```

### Why I Believe SafeSpark Breaks Neo4j JDBC

The Neo4j JDBC driver works  when loaded directly into Spark (all Direct JDBC tests pass), but fails when routed through SafeSpark:

| Scenario | Works? | Reason |
|----------|--------|--------|
| Direct JDBC (driver in Spark classpath) | Yes | Driver runs in-process with Spark |
| Unity Catalog JDBC Connection | No | SafeSpark gRPC wrapper intercepts calls |

**Failure points:**
- SafeSpark's gRPC wrapper intercepts all JDBC calls
- The metadata/schema resolution phase fails before any query executes
- The sandboxed process may timeout or crash during Neo4j's connection handshake
- Even with `customSchema` to bypass schema inference, SafeSpark still attempts its own resolution


## Project Overview

### Component Test Results

| Component | Status | Description |
|-----------|--------|-------------|
| Network Connectivity | PASS | TCP connectivity to Neo4j verified |
| Neo4j Python Driver | PASS | Bolt protocol connectivity works |
| Neo4j Spark Connector | PASS | `org.neo4j.spark.DataSource` fully functional |
| **Neo4j JDBC SQL-to-Cypher** | **PASS** | **Tested & verified** - SQL translated to Cypher |
| Direct JDBC | PASS | Works with `customSchema` workaround |
| **Unity Catalog JDBC** | **FAIL** | **SafeSpark incompatibility - blocked** |
| **Unity Catalog JDBC Schema** | **FAIL** | **Schema discovery fails through SafeSpark isolation** |

**What Works:**
- **Neo4j JDBC SQL-to-Cypher translation** - Fully tested and verified with Spark
- **Direct JDBC with Spark** - Works when bypassing Unity Catalog (requires `customSchema`)
- **Neo4j Spark Connector** - `org.neo4j.spark.DataSource` works perfectly
- **Network & Driver Connectivity** - TCP, Bolt protocol, and credentials all verified

**What is Broken:**
- **Unity Catalog JDBC connections** - Blocked by SafeSpark incompatibility
- **`remote_query()` function** - Fails due to same SafeSpark issue
- **Any query routed through a UC Connection** - SafeSpark fails during metadata resolution

**Root Cause:** Databricks **SafeSpark** (the isolation layer for custom JDBC drivers) is incompatible with the Neo4j JDBC driver. See [Technical Deep Dive](#technical-deep-dive-safespark-and-the-unity-catalog-jdbc-blocker) below.

For detailed test results and best practices, see [**UC_INTEGRATION_STATUS.md**](./UC_INTEGRATION_STATUS.md).

---

## Neo4j JDBC SQL-to-Cypher Translation (Verified Working)

The Neo4j JDBC driver's SQL-to-Cypher translation capability has been **fully verified and works with Spark**. This enables querying graph data using familiar SQL syntax, which the driver automatically translates to Cypher.

### How It Works

The Neo4j JDBC driver with `enableSQLTranslation=true` translates SQL queries to Cypher:

```python
# SQL query sent to Neo4j JDBC driver
df = spark.read.format("jdbc") \
    .option("url", "jdbc:neo4j+s://host:7687/db?enableSQLTranslation=true") \
    .option("driver", "org.neo4j.jdbc.Neo4jDriver") \
    .option("query", "SELECT COUNT(*) AS cnt FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a") \
    .option("customSchema", "cnt LONG") \
    .load()

# Driver translates to Cypher: MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*) AS cnt
```

### Supported SQL Patterns

| SQL Pattern | Cypher Translation | Status |
|-------------|-------------------|--------|
| `SELECT COUNT(*) FROM Label` | `MATCH (n:Label) RETURN count(*)` | PASS |
| `SELECT * FROM Label LIMIT n` | `MATCH (n:Label) RETURN n LIMIT n` | PASS |
| `NATURAL JOIN` | Relationship pattern `()-[:REL]->()` | PASS |
| `JOIN ... ON` | Typed relationship from column name | PASS |
| `MAX`, `MIN`, `SUM`, `AVG` | Native Cypher aggregates | PASS |

### Projects Demonstrating SQL Translation

| Project | Description | How to Run |
|---------|-------------|------------|
| [`pyspark-translation-example/`](./pyspark-translation-example/) | Local PySpark tests for SQL-to-Cypher translation | `uv run test-sql` |
| [`sample-sql-translation/`](./sample-sql-translation/) | Spring Boot app for JDBC connectivity testing | `./mvnw spring-boot:run` |
| [`neo4j_databricks_sql_translation.ipynb`](uc-neo4j-test-suite/neo4j_databricks_sql_translation.ipynb) | Full Databricks notebook with comprehensive tests (Sections 1-8) | Import to Databricks |
| [`neo4j_schema_test.ipynb`](uc-neo4j-test-suite/neo4j_schema_test.ipynb) | Focused notebook for schema testing (Sections 1, 3, 8) | Import to Databricks |

See the [Neo4j JDBC SQL2Cypher documentation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) for full translation rules.

## Repository Structure

This repository contains multiple components to demonstrate, test, and validate this integration:

### 1. Spring Boot SQL Translation Demo
**Directory**: `sample-sql-translation/`

A lightweight Spring Boot application that serves as a baseline for testing Neo4j connectivity and schema inspection.
- **Purpose**: Verifies basic JDBC connectivity and allows you to inspect the Neo4j database schema (`CALL db.schema.visualization()`).
- **Key Features**: Spring Boot 4.0.1, `spring-boot-starter-data-neo4j`.

### 2. PySpark SQL Translation Example
**Directory**: `pyspark-translation-example/`

A local PySpark environment that simulates the Databricks runtime to test the JDBC driver's SQL-to-Cypher translation capabilities.
- **Purpose**: To validate how specific SQL queries (JOINs, Aggregates) are translated to Cypher by the driver before deploying to Databricks.
- **Key File**: `test_sql_translation.py` - Runs a suite of SQL queries against Neo4j via Spark JDBC and reports success/failure of translation patterns.

### 3. Unity Catalog Test Suite
**Directory**: `uc-neo4j-test-suite/`

A comprehensive Python test suite designed to validate the environment and connectivity requirements for the Unity Catalog integration.
- **Purpose**: Automated verification of network connectivity, driver availability, and basic Neo4j access.

### 4. Databricks Notebooks
**Directory**: `uc-neo4j-test-suite/`

Databricks notebooks implementing the steps defined in the proposal:
- `neo4j_databricks_sql_translation.ipynb` - Full test suite with all sections (1-8)
- `neo4j_schema_test.ipynb` - Focused schema testing (Sections 1, 3, 8)

## Getting Started

To fully understand the functionality and set up the integration, follow these steps:

1.  **Review the Spring Project**: Check `sample-sql-translation` to understand the basics of connecting to Neo4j via JDBC.
2.  **Explore SQL Translation**: Run the `pyspark-translation-example` to see the SQL-to-Cypher translation in action. This will show you which SQL patterns (like `NATURAL JOIN` vs `INNER JOIN`) are supported and how they map to graph relationships.
3.  **Read the Proposal**: Review `neo4j_databricks_jdbc_federation_proposal.md` to understand the architectural goals, limitations, and the "Custom JDBC on UC Compute" feature.
4.  **Execute the Notebooks**: Import notebooks from `uc-neo4j-test-suite/` into your Databricks workspace. Use `neo4j_databricks_sql_translation.ipynb` for full testing or `neo4j_schema_test.ipynb` for focused schema tests.

---

### Next Steps

Work with Databricks to troubleshoot the incompatibility between the internal SafeSpark layer and the Neo4j JDBC driver.

### References

- [Databricks JDBC Unity Catalog Connection](https://docs.databricks.com/aws/en/connect/jdbc-connection) - Official documentation
- [Databricks Community - Java SQL Driver Manager in UC Shared Mode](https://community.databricks.com/t5/data-engineering/java-sql-driver-manager-not-working-in-unity-catalog-shared-mode/td-p/75326) - Related isolation issues
- [Databricks Runtime 17.3+ Release Notes](https://docs.databricks.com/aws/en/release-notes/product/2025/november) - JDBC connection feature availability