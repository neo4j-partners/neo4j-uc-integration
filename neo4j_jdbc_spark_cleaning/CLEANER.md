# Spark Cleaner: SparkSubqueryCleaningTranslator

## Overview

The **Spark Cleaner** (formally `SparkSubqueryCleaningTranslator`) is a specialized translator module in the Neo4j JDBC Driver designed to handle a specific pattern that Apache Spark generates when executing queries through JDBC connections.

When Apache Spark uses JDBC to query a database, it wraps the original query in a synthetic subquery structure to probe the result schema. This wrapper pattern can interfere with Cypher queries being passed through the Neo4j JDBC Driver. The Spark Cleaner detects these wrapper patterns and extracts the original Cypher query, allowing it to execute correctly against Neo4j.

**Module:** `org.neo4j:neo4j-jdbc-translator-sparkcleaner`
**Since:** Version 6.1.2
**Author:** Michael J. Simons

---

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

This wrapped structure is neither valid SQL nor valid Cypher. Without the Spark Cleaner, the query would fail because:
1. The standard SQL-to-Cypher translator cannot parse `MATCH` inside a SQL `SELECT` statement
2. Neo4j cannot execute the outer SQL wrapper

---

## How the Spark Cleaner Works

The `SparkSubqueryCleaningTranslator` follows a three-step process:

### Step 1: Detection

The translator first checks if the incoming statement **might be** a Spark-generated query by looking for the marker `SPARK_GEN_SUBQ` in the query text (case-insensitive):

```java
static boolean mightBeASparkQuery(String statement) {
    return statement != null && statement.toUpperCase(Locale.ROOT).contains("SPARK_GEN_SUBQ");
}
```

If this marker is not found, the translator returns `null`, signaling to the translator chain that it cannot handle this query and the next translator should try.

### Step 2: Extraction

If the Spark marker is detected, the translator attempts to extract the inner query using a regular expression pattern:

```java
private static final Pattern SUBQUERY_PATTERN = Pattern
    .compile("(?ims)SELECT\\s+\\*\\s+FROM\\s+\\((.*?)\\)\\s+SPARK_GEN_SUBQ_0.*");
```

This pattern matches the structure:
- `SELECT * FROM (` - The Spark wrapper prefix
- `(.*?)` - Captures the original query (non-greedy)
- `) SPARK_GEN_SUBQ_0.*` - The Spark wrapper suffix (including `WHERE 1=0`)

### Step 3: Cypher Validation

The extracted query is then validated to confirm it's actually Cypher (not SQL). This is done by parsing it with the official Neo4j Cypher 5 parser:

```java
boolean canParseAsCypher(String statement) {
    var tokens = new CommonTokenStream(new Cypher5Lexer(CharStreams.fromString(statement)));
    var parser = new Cypher5Parser(tokens);
    // ... parsing logic with SLL then LL prediction modes
}
```

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

This transformed query:
1. Is valid Cypher that Neo4j can execute
2. Uses a `CALL` subquery to preserve the original query structure
3. Returns only 1 row (for schema probing purposes)
4. Has the `FORCE_CYPHER` hint to prevent further translation

### Example 2: Simple Return Statement

**User's Original Query:**
```cypher
RETURN 1
```

**What Spark Sends:**
```sql
SELECT * FROM (RETURN 1) SPARK_GEN_SUBQ_0 WHERE 1=0
```

**Transformed Result:**
```cypher
/*+ NEO4J FORCE_CYPHER */
CALL {RETURN 1} RETURN * LIMIT 1
```

### Example 3: SQL Query (Not Transformed)

When Spark wraps an actual SQL query (not Cypher), the Spark Cleaner correctly identifies it and passes it through:

**User's SQL Query:**
```sql
SELECT * FROM Movie
```

**What Spark Sends:**
```sql
SELECT * FROM (SELECT * FROM Movie) SPARK_GEN_SUBQ_0 WHERE 1=0
```

**Spark Cleaner Action:** Returns `null` because `SELECT * FROM Movie` does not parse as valid Cypher. The query is then passed to the standard SQL-to-Cypher translator for handling.

---

## Configuration

### Required Dependency (Not Bundled by Default)

**Important:** The Spark Cleaner is **NOT included** in the standard or full Neo4j JDBC bundles. You must explicitly add it as a separate dependency:

```xml
<dependency>
    <groupId>org.neo4j</groupId>
    <artifactId>neo4j-jdbc-translator-sparkcleaner</artifactId>
    <version>6.10.4-SNAPSHOT</version>
</dependency>
```

Once on the classpath, the Spark Cleaner is automatically discovered via Java's Service Provider Interface (SPI) - no additional configuration is required. It will participate in the translator chain whenever:
1. The JAR is on the classpath
2. SQL translation is enabled (`enableSQLTranslation=true`) OR you call `connection.nativeSQL()`

### Precedence

The translator's precedence determines its position in the translator chain. By default, the Spark Cleaner has a precedence of `LOWEST_PRECEDENCE - 5` (meaning it runs **before** the default SQL translator but after higher-precedence custom translators).

You can configure the precedence via the `s2c.precedence` configuration property:

```java
Map<String, Object> config = Map.of("s2c.precedence", 100);
// The Spark Cleaner will use precedence 99 (value - 1)
```

---

## Architecture: Translator Chain

The Spark Cleaner participates in the Neo4j JDBC Driver's translator chain architecture:

```
[Incoming Query]
       │
       ▼
┌──────────────────────────────┐
│  Custom Translator (highest) │  ← Your domain-specific translator
└──────────────────────────────┘
       │ (returns null if can't handle)
       ▼
┌──────────────────────────────┐
│  SparkSubqueryCleaningTranslator │  ← Detects and unwraps Spark queries
└──────────────────────────────┘
       │ (returns null if not Spark/not Cypher)
       ▼
┌──────────────────────────────┐
│  Default SQL Translator      │  ← Standard SQL-to-Cypher translation
└──────────────────────────────┘
       │
       ▼
[Cypher Query to Neo4j]
```

Key behaviors:
- **Returns transformed Cypher:** When a Spark-wrapped Cypher query is detected and validated
- **Returns `null`:** When the query isn't a Spark query or the inner query isn't valid Cypher, allowing the next translator in the chain to handle it

---

## File Structure

```
neo4j-jdbc-translator/sparkcleaner/
├── pom.xml
└── src/
    ├── main/
    │   ├── java/org/neo4j/jdbc/translator/sparkcleaner/
    │   │   ├── SparkSubqueryCleaningTranslator.java      # Main translator logic
    │   │   └── SparkSubqueryCleaningTranslatorFactory.java  # SPI factory
    │   └── resources/META-INF/services/
    │       └── org.neo4j.jdbc.translator.spi.TranslatorFactory  # SPI registration
    └── test/
        └── java/org/neo4j/jdbc/translator/sparkcleaner/
            ├── SparkSubqueryCleaningTranslatorTests.java
            └── SparkSubqueryCleaningTranslatorFactoryTests.java
```

---

## Dependencies

The Spark Cleaner module uses:

- **Neo4j Cypher v5 ANTLR Parser** (`org.neo4j:cypher-v5-antlr-parser`): For validating that extracted queries are valid Cypher
- **Neo4j JDBC Translator SPI** (`org.neo4j:neo4j-jdbc-translator-spi`): The translator interface

The module uses Maven Shade Plugin to relocate the ANTLR runtime and Cypher parser classes to avoid conflicts with other versions that might be on the classpath.

---

## References

### Official Neo4j Documentation

- [SQL to Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/) - Overview of the translation feature and translator SPI
- [Neo4j JDBC Driver Configuration](https://neo4j.com/docs/jdbc-manual/current/configuration/) - Configuration options including SQL translation settings
- [Neo4j JDBC Driver](http://neo4j.github.io/neo4j-jdbc/6.0.0-M01/) - API documentation

### Related Topics

- [Neo4j Connector for Apache Spark](https://neo4j.com/docs/spark/current/) - Alternative integration approach for Spark
- [Announcing Neo4j JDBC Driver Version 6](https://neo4j.com/developer-blog/neo4j-jdbc-driver-v6/) - Feature overview of the JDBC driver

### Source Code References

| File | Description |
|------|-------------|
| `SparkSubqueryCleaningTranslator.java:44-111` | Main translator implementation |
| `SparkSubqueryCleaningTranslator.java:46-47` | Regex pattern for Spark subquery detection |
| `SparkSubqueryCleaningTranslator.java:73-75` | Quick detection method |
| `SparkSubqueryCleaningTranslator.java:85-108` | Cypher parsing validation |
| `SparkSubqueryCleaningTranslatorFactory.java:44-67` | Factory with precedence configuration |
| `Translator.java:56-144` | SPI interface definition |

---

## Summary

The Spark Cleaner (`SparkSubqueryCleaningTranslator`) solves a specific integration challenge when using Apache Spark with Neo4j via JDBC. By detecting Spark's auto-generated subquery wrappers, extracting the original Cypher query, validating it, and reformatting it for execution, it enables seamless Cypher query execution through Spark's JDBC infrastructure.

This module exemplifies the Neo4j JDBC Driver's extensible translator architecture, where specialized translators can be chained together to handle specific query patterns while delegating unrecognized patterns to other translators in the chain.
