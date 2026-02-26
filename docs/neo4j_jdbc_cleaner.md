# Spark Cleaner: SparkSubqueryCleaningTranslator

## Overview

The **Spark Cleaner** (`SparkSubqueryCleaningTranslator`) is a specialized translator module for the Neo4j JDBC Driver that handles a specific pattern Apache Spark generates when executing queries through JDBC connections.

When Apache Spark uses JDBC to query a database, it wraps the original query in a synthetic subquery structure to probe the result schema. This wrapper pattern can interfere with Cypher queries being passed through the Neo4j JDBC Driver. The Spark Cleaner detects these wrapper patterns and extracts the original Cypher query, allowing it to execute correctly against Neo4j.

## The Problem: Spark's Subquery Wrapping

When Apache Spark connects to a database via JDBC, it often needs to determine the schema of query results before executing the actual query. To accomplish this, Spark wraps the user's query in a synthetic structure like:

```sql
SELECT * FROM (
    <original_query>
) SPARK_GEN_SUBQ_0 WHERE 1=0
```

The `WHERE 1=0` clause ensures no data is returned during schema probing, and `SPARK_GEN_SUBQ_0` is Spark's auto-generated subquery alias.

### Why This Is Problematic for Neo4j

When users want to execute Cypher queries through Spark, they might write:

```cypher
MATCH (m:Movie)<-[:ACTED_IN]-(p:Person)
RETURN m.title AS title, collect(p.name) AS actors
ORDER BY m.title
```

Spark transforms this into:

```sql
SELECT * FROM (
    MATCH (m:Movie)<-[:ACTED_IN]-(p:Person)
    RETURN m.title AS title, collect(p.name) AS actors
    ORDER BY m.title
) SPARK_GEN_SUBQ_0 WHERE 1=0
```

This wrapped structure is neither valid SQL nor valid Cypher. Without the Spark Cleaner, the query would fail.

---

## How the Spark Cleaner Works

The `SparkSubqueryCleaningTranslator` follows a three-step process:

### Step 1: Detection

The translator checks if the incoming statement might be a Spark-generated query by looking for the marker `SPARK_GEN_SUBQ` in the query text (case-insensitive).

### Step 2: Extraction

If the Spark marker is detected, the translator extracts the inner query using a regular expression pattern that matches the Spark wrapper structure.

### Step 3: Cypher Validation

The extracted query is validated to confirm it's actually Cypher (not SQL) by parsing it with the Neo4j Cypher 5 parser.

If the query parses successfully as Cypher, the translator wraps it in a format that Neo4j can execute:

```cypher
/*+ NEO4J FORCE_CYPHER */
CALL {<extracted_cypher>} RETURN * LIMIT 1
```

The `/*+ NEO4J FORCE_CYPHER */` hint tells the Neo4j JDBC Driver to bypass any further SQL translation and send the query directly to Neo4j.

---

## Usage Examples

### Example 1: Basic Movie Query

**User's Original Cypher Query:**
```cypher
MATCH (m:Movie)<-[:ACTED_IN]-(p:Person)
RETURN m.title AS title, collect(p.name) AS actors
ORDER BY m.title
```

**What Spark Sends to JDBC:**
```sql
SELECT * FROM (
MATCH (m:Movie)<-[:ACTED_IN]-(p:Person)
RETURN m.title AS title, collect(p.name) AS actors
ORDER BY m.title
) SPARK_GEN_SUBQ_0 WHERE 1=0
```

**What the Spark Cleaner Produces:**
```cypher
/*+ NEO4J FORCE_CYPHER */
CALL {MATCH (m:Movie)<-[:ACTED_IN]-(p:Person)
RETURN m.title AS title, collect(p.name) AS actors
ORDER BY m.title} RETURN * LIMIT 1
```

### Example 2: SQL Query (Not Transformed)

When Spark wraps an actual SQL query (not Cypher), the Spark Cleaner correctly identifies it and passes it through to the standard SQL-to-Cypher translator.

---

## References

- [SQL to Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) - Overview of the translation feature and translator SPI
- [Neo4j JDBC Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) - Configuration options including SQL translation settings
- [Neo4j Connector for Apache Spark](https://neo4j.com/docs/spark/current/) - Alternative integration approach for Spark
