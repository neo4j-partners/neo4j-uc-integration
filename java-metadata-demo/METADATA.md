# Neo4j Schema Metadata Demo

## Proposal: Standalone Java Program for Neo4j Schema Synchronization

### Overview

This document proposes a simple standalone Java program that demonstrates how the Neo4j JDBC driver exposes graph schema as relational metadata through standard JDBC DatabaseMetaData APIs. This capability is foundational for synchronizing Neo4j graph schema with relational catalogs like Unity Catalog.

### Purpose

The goal is to create a minimal, self-contained Java application that:

1. Connects to a Neo4j database using the JDBC driver
2. Retrieves schema information using standard JDBC metadata APIs
3. Displays the mapping between graph concepts and relational concepts
4. Outputs schema information suitable for Unity Catalog foreign table generation

### Background: How Neo4j JDBC Exposes Graph Schema

The Neo4j JDBC driver implements the standard `java.sql.DatabaseMetaData` interface and maps graph concepts to relational concepts as follows:

**Node Labels as Tables**

When you call `getTables()`, the driver returns node labels as tables with type "TABLE". For example, a Neo4j database with Person and Movie labels would return these as tables named "Person" and "Movie".

**Relationships as Virtual Tables**

Relationships are exposed as virtual tables using an encoded naming convention: `startLabel_relationshipType_endLabel`. For example, a KNOWS relationship between Person nodes appears as "Person_KNOWS_Person". These have table type "RELATIONSHIP".

**Properties as Columns**

When you call `getColumns()`, the driver returns node and relationship properties as columns. The driver queries `db.schema.nodeTypeProperties()` and `db.schema.relTypeProperties()` to discover property names and types, then maps Neo4j types to SQL types.

**Virtual Element ID Columns**

The driver adds virtual columns for element IDs:
- `v$id` on all tables (the internal element identifier)
- `v$startlabel_id` and `v$endlabel_id` on relationship tables (references to connected nodes)

**Primary Keys**

The driver exposes unique constraints and element IDs as primary keys through `getPrimaryKeys()`.

### Proposed Program Structure

The demo program will be organized as a single-directory Maven project with one main class.

**Directory Layout**

```
examples/metadata-demo/
  pom.xml                    - Maven build file with JDBC driver dependency
  METADATA.md                - This document
  src/main/java/
    org/neo4j/demo/
      MetadataDemo.java      - Main program
```

**Program Flow**

The program will perform the following steps in sequence:

1. Accept database connection parameters from command line or environment variables (URL, username, password)

2. Establish a JDBC connection to Neo4j using the driver

3. Obtain DatabaseMetaData from the connection

4. Retrieve and display all tables by calling getTables with no filters, then print each table name, table type (TABLE, RELATIONSHIP, or CBV), and remarks

5. For each table, retrieve and display columns by calling getColumns, then print column name, SQL type name, nullability, and whether it is auto-generated

6. Retrieve and display primary keys by calling getPrimaryKeys for each table, then print key column names

7. Print a summary showing the mapping from graph schema to relational schema in a format suitable for Unity Catalog foreign table definitions

**Output Format**

The program will produce human-readable output showing:

```
=== Neo4j Schema as Relational Metadata ===

TABLES (Node Labels):
  Person (TABLE)
    Columns: v$id, name, age, email
    Primary Key: v$id
  Movie (TABLE)
    Columns: v$id, title, released, tagline
    Primary Key: v$id

RELATIONSHIPS (Virtual Tables):
  Person_ACTED_IN_Movie (RELATIONSHIP)
    Start Node: Person
    End Node: Movie
    Columns: v$id, roles, v$Person_id, v$Movie_id

UNITY CATALOG MAPPING:
  CREATE FOREIGN TABLE Person (...) SERVER neo4j;
  CREATE FOREIGN TABLE Movie (...) SERVER neo4j;
```

### Dependencies

The program requires only:

- Java 17 or later
- Neo4j JDBC Driver (org.neo4j:neo4j-jdbc)
- A running Neo4j database (can use Neo4j Aura free tier or local Docker instance)

No additional libraries are needed. The JDBC driver handles all SQL translation and metadata operations internally.

### How This Supports Unity Catalog Integration

Unity Catalog requires relational schema definitions to register external data sources. This program demonstrates how to:

1. Discover what tables exist by querying getTables
2. Determine table structure by querying getColumns for each table
3. Identify primary keys for join operations by querying getPrimaryKeys
4. Understand relationship patterns through the virtual table naming convention

With this information, an integration tool can automatically generate Unity Catalog foreign table definitions that map to Neo4j graph data.

### Running the Demo

The user will build and run the program as follows:

```
cd examples/metadata-demo
mvn package
java -jar target/metadata-demo.jar \
  --url jdbc:neo4j://localhost:7687 \
  --username neo4j \
  --password secret
```

Alternatively, connection parameters can be set via environment variables NEO4J_URL, NEO4J_USERNAME, and NEO4J_PASSWORD.

### Limitations and Notes

**Sampling Behavior**

The driver samples a limited number of nodes and relationships when discovering schema. This means properties that exist only on a small subset of nodes may not appear in the metadata.

**APOC Dependency**

When APOC is available in the Neo4j database, the driver uses `apoc.meta.schema()` for more efficient and accurate schema discovery. Without APOC, it falls back to core database procedures.

**Property Type Inference**

Neo4j is schema-optional, so property types are inferred from sampled data. The same property name on different nodes may have different types.

**Cypher Procedures via Spark JDBC**

Direct Cypher procedure calls like `CALL db.labels()` cannot be executed through Spark JDBC because Spark wraps queries in subqueries. The JDBC DatabaseMetaData API provides the workaround by encapsulating these calls internally.

### Success Criteria

The demo is successful when it:

1. Connects to any Neo4j database with the standard movie dataset
2. Lists all node labels as tables
3. Lists all relationship types as virtual tables with proper naming
4. Shows column definitions including types for all tables
5. Produces output that clearly maps graph concepts to relational concepts

### Next Steps After Demo

Once this demo validates the metadata capabilities, the next steps would be:

1. Extend to generate actual Unity Catalog DDL statements
2. Add support for incremental schema synchronization
3. Integrate with Databricks SDK for direct catalog registration
4. Add schema change detection and drift reporting

This demo serves as the foundation for proving that Neo4j graph schema can be reliably exposed through standard JDBC APIs and synchronized with relational catalog systems.
