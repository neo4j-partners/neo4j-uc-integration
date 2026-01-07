# Neo4j JDBC Metadata Demo

This project demonstrates how the Neo4j JDBC driver exposes Neo4j graph schema as relational metadata through standard JDBC `DatabaseMetaData` APIs. This capability is useful for synchronizing Neo4j graph schema with relational catalogs like Unity Catalog.

It also includes demonstrations of using APOC procedures (`apoc.meta.nodeTypeProperties` and `apoc.meta.relTypeProperties`) for advanced schema discovery.

## Prerequisites

- Java 17 or higher
- A running Neo4j instance
- (Optional) Neo4j APOC Library installed (standard in Neo4j Aura)

## Quick Start

### 1. Configure Connection

Copy the sample environment file and edit it with your Neo4j credentials:

```bash
cp env.sample .env
```

Alternatively, you can use command-line arguments or environment variables.

### 2. Build the Project

Use the Maven wrapper to build the executable JAR:

```bash
./mvnw package
```

### 3. Run the Application

Run the generated JAR file:

```bash
java -jar target/metadata-demo-1.0.0-SNAPSHOT.jar
```

By default, this runs the **Standard JDBC Metadata** discovery.

## Running Specific Tests

You can select which schema discovery method to run using the `--test` (or `-t`) option.

### Run APOC Schema Discovery
This demonstrates finding detailed property type information using APOC.

```bash
java -jar target/metadata-demo-1.0.0-SNAPSHOT.jar --test apoc
```

### Run All Tests

```bash
java -jar target/metadata-demo-1.0.0-SNAPSHOT.jar --test all
```

## Configuration Options

The application supports configuration via command-line arguments, a `.env` file, or system environment variables (in that order of precedence).

### Command-line Arguments

| Option | Description |
|--------|-------------|
| `--url`, `-u` | JDBC URL (e.g., `jdbc:neo4j://localhost:7687`) |
| `--username`, `--user` | Database username |
| `--password`, `--pass` | Database password |
| `--test`, `-t` | Test mode: `standard` (default), `apoc`, or `all` |

### Environment Variables / .env Keys

- `NEO4J_URL`: JDBC URL
- `NEO4J_USERNAME`: Database username
- `NEO4J_PASSWORD`: Database password