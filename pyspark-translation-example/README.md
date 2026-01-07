# Neo4j SQL Translation Test Suite

Test Neo4j JDBC SQL-to-Cypher translation locally with PySpark.

## Quick Start

1. Copy env.sample to .env and add your Neo4j credentials:
   ```bash
   cp env.sample .env
   # Edit .env with your credentials
   ```

2. Download the JDBC driver:
   ```bash
   curl -L -o neo4j-jdbc-full-bundle-6.0.0.jar \
       "https://repo1.maven.org/maven2/org/neo4j/neo4j-jdbc-full-bundle/6.0.0/neo4j-jdbc-full-bundle-6.0.0.jar"
   ```

3. Run the tests:
   ```bash
   uv run test-sql
   ```

## Command Line Options

Run all tests or select specific test suites:

```bash
uv run test-sql [OPTIONS]
```

### Individual Test Flags

| Flag | Description |
|------|-------------|
| `--aggregates` | Run aggregate function tests (COUNT, MAX, SELECT *) |
| `--joins` | Run JOIN translation tests (NATURAL JOIN, JOIN ON) |
| `--failures` | Run known failure tests (documents limitations) |
| `--schema` | Run DataFrame-based schema discovery tests |
| `--metadata` | Run direct JDBC DatabaseMetaData tests |

### Group Flags

| Flag | Description |
|------|-------------|
| `--all` | Run all tests (default if no flags specified) |
| `--sql` | Run SQL translation tests only (aggregates + joins + failures) |
| `--discovery` | Run schema discovery tests only (schema + metadata) |

### Examples

```bash
# Run all tests (default)
uv run test-sql

# Run only aggregate tests
uv run test-sql --aggregates

# Run only JDBC metadata tests
uv run test-sql --metadata

# Run SQL translation tests (no schema discovery)
uv run test-sql --sql

# Run schema discovery tests only
uv run test-sql --discovery

# Run specific combination
uv run test-sql --aggregates --joins

# Show help
uv run test-sql --help
```

## Test Suites

### 1. Aggregate Tests (`--aggregates`)
- COUNT(*), COUNT(column)
- MAX, MIN, SUM, AVG
- SELECT * with LIMIT
- Demonstrates reliable SQL patterns that translate correctly

### 2. JOIN Tests (`--joins`)
- NATURAL JOIN - translates to Cypher relationship patterns
- JOIN ON - infers relationship type from column name
- Multi-hop JOINs across multiple labels
- Shows how SQL JOINs translate to Cypher relationships

### 3. Known Failure Tests (`--failures`)
- Column projections (SELECT col1, col2)
- GROUP BY queries
- collect() aggregate
- Documents Spark subquery wrapping limitations

### 4. Schema Discovery Tests (`--schema`)
- Uses SELECT * LIMIT 1 via DataFrame
- Discovers labels as tables, properties as columns
- Type mapping from Neo4j to Spark SQL types
- Foundation for Unity Catalog schema synchronization

### 5. JDBC Metadata Tests (`--metadata`)
- Direct access to JDBC DatabaseMetaData API via `spark._jvm`
- getTables() - discovers labels and relationship patterns
- getColumns() - discovers properties with SQL types
- getPrimaryKeys() - discovers primary key columns
- Mirrors Java SchemaMetadataTests functionality

## Package Structure

```
pyspark-translation-example/
├── main.py                    # Entry point with CLI argument parsing
├── neo4j_sql_tests/           # Test package
│   ├── __init__.py            # Package exports
│   ├── config.py              # Configuration management
│   ├── spark.py               # Spark utilities
│   ├── output.py              # Output formatting
│   ├── jdbc_metadata.py       # Direct JDBC DatabaseMetaData access
│   ├── tests_aggregates.py    # Aggregate function tests
│   ├── tests_joins.py         # JOIN translation tests
│   ├── tests_known_failures.py # Known limitation tests
│   ├── tests_schema.py        # DataFrame schema discovery tests
│   ├── tests_jdbc_metadata.py # JDBC metadata tests
│   └── runner.py              # Test orchestration
├── pyproject.toml
└── .env                       # Your credentials (not in git)
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `NEO4J_URI` | Neo4j connection URI | `neo4j+s://xxx.databases.neo4j.io` |
| `NEO4J_USERNAME` | Database username | `neo4j` |
| `NEO4J_PASSWORD` | Database password | `your-password` |
| `NEO4J_DATABASE` | Database name | `neo4j` |
| `NEO4J_JDBC_JAR` | Path to JDBC JAR | `./neo4j-jdbc-full-bundle-6.0.0.jar` |

## Programmatic Usage

You can also run tests programmatically:

```python
from neo4j_sql_tests import run_all_tests, TestOptions

# Run all tests
run_all_tests()

# Run only metadata tests
options = TestOptions(
    aggregates=False,
    joins=False,
    failures=False,
    schema=False,
    metadata=True
)
run_all_tests(test_options=options)

# Access JDBC metadata directly
from neo4j_sql_tests import (
    create_spark_session,
    load_config,
    get_tables,
    get_columns,
    get_primary_keys,
)

config = load_config()
spark = create_spark_session(config)

tables = get_tables(spark, config, table_type="TABLE")
columns = get_columns(spark, config, "Aircraft")
```

## References

- [Neo4j JDBC Manual](https://neo4j.com/docs/jdbc-manual/current/)
- [SQL to Cypher Translation](https://neo4j.com/docs/jdbc-manual/current/sql2cypher/)
