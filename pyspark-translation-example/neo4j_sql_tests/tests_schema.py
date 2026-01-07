"""
Schema discovery tests for Neo4j JDBC metadata.

This module demonstrates how the Neo4j JDBC driver exposes graph schema
as relational metadata, enabling SQL tools to discover:
    - Labels as tables
    - Properties as columns
    - Property types as SQL types

How It Works:
    1. Execute SELECT * FROM Label LIMIT 1 via JDBC query option
    2. Spark infers schema from JDBC ResultSetMetaData
    3. The DataFrame schema contains discovered columns and types

Note: The `query` option is preferred over `dbtable` because it handles
Neo4j's type mapping more reliably. The `dbtable` option can fail with
UNRECOGNIZED_SQL_TYPE errors when labels have array/list properties.

This is the foundation for Unity Catalog schema synchronization:
    - Discover Neo4j labels and properties via JDBC
    - Generate Unity Catalog foreign table definitions
    - Keep UC schema in sync with Neo4j graph schema

Type Mapping (Neo4j → Spark SQL):
    STRING    → StringType
    INTEGER   → LongType (64-bit)
    FLOAT     → DoubleType
    BOOLEAN   → BooleanType
    DATE      → DateType
    DATETIME  → TimestampType
    LIST      → NOT SUPPORTED (causes UNRECOGNIZED_SQL_TYPE)

Limitations:
    - Labels with array/list properties may fail schema discovery
    - Column projections fail due to Spark subquery wrapping
    - Use Java JDBC DatabaseMetaData for comprehensive schema discovery

Reference:
    https://neo4j.com/docs/jdbc-manual/current/
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config
from .spark import get_jdbc_options
from .output import (
    print_header,
    print_test,
    print_success,
    print_error,
    print_info,
    print_columns,
    print_schema_summary,
)


# Labels to discover schema for
# These should match labels that exist in your Neo4j database
DEFAULT_LABELS = ["Aircraft", "Airport", "Flight", "Delay", "MaintenanceEvent"]


def run_schema_discovery_tests(
    spark: SparkSession,
    config: Config,
    labels: list[str] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """
    Run schema discovery tests for specified labels.

    Demonstrates that Neo4j JDBC exposes graph schema as relational
    metadata through standard JDBC APIs.

    Args:
        spark: Active SparkSession
        config: Configuration object
        labels: List of Neo4j labels to discover. Defaults to DEFAULT_LABELS.

    Returns:
        Dictionary mapping label names to list of (column_name, column_type) tuples

    Example:
        schemas = run_schema_discovery_tests(spark, config)
        for label, columns in schemas.items():
            print(f"{label}: {len(columns)} columns")
    """
    if labels is None:
        labels = DEFAULT_LABELS

    print_header("SCHEMA DISCOVERY TESTS")
    print("Demonstrating Neo4j JDBC metadata discovery via SELECT * LIMIT 1")
    print("Labels are exposed as tables, properties as columns")
    print_info("See: https://neo4j.com/docs/jdbc-manual/current/")

    opts = get_jdbc_options(config)
    discovered_schemas = {}

    for label in labels:
        schema_info = _discover_label_schema(spark, opts, label)
        if schema_info:
            discovered_schemas[label] = schema_info

    # Print summary
    _print_summary(discovered_schemas)

    return discovered_schemas


def _discover_label_schema(
    spark: SparkSession,
    opts: dict,
    label: str,
) -> list[tuple[str, str]] | None:
    """
    Discover schema for a single Neo4j label.

    Uses SELECT * with LIMIT 1 to read a single row from the label.
    Spark infers the schema from JDBC ResultSetMetaData. The query
    approach handles Neo4j type mapping better than dbtable option.

    Args:
        spark: Active SparkSession
        opts: JDBC connection options
        label: Neo4j label name

    Returns:
        List of (column_name, column_type) tuples, or None if discovery failed
    """
    # Use query option - handles type mapping better than dbtable
    sql = f"SELECT * FROM {label} LIMIT 1"
    print_test(f"Schema for '{label}'", sql)

    try:
        # Read a single row to discover schema
        # The query option with LIMIT 1 is efficient and works reliably
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .load()
        )

        # Extract schema information from the DataFrame
        schema_info = [
            (field.name, str(field.dataType))
            for field in df.schema.fields
        ]

        # Display discovered columns
        print("  Columns discovered:")
        print_columns(schema_info)
        print_success(f"{len(schema_info)} columns")

        return schema_info

    except Exception as e:
        # Truncate error for readability
        err_msg = str(e)
        if "UNRECOGNIZED_SQL_TYPE" in err_msg:
            print_error("Label has properties with unsupported types (arrays/lists)")
        else:
            print_error(err_msg[:200])
        return None


def _print_summary(schemas: dict[str, list[tuple[str, str]]]) -> None:
    """
    Print schema discovery summary.

    Args:
        schemas: Dictionary of discovered schemas
    """
    print_header("SCHEMA DISCOVERY SUMMARY")
    print_schema_summary(schemas)

    print()
    print_info("This demonstrates Neo4j JDBC exposes graph schema as relational metadata")
    print_info("Schema can be used to generate Unity Catalog foreign tables")


def generate_uc_foreign_table_ddl(
    label: str,
    columns: list[tuple[str, str]],
    connection_name: str,
) -> str:
    """
    Generate Unity Catalog foreign table DDL from discovered schema.

    This is a prototype showing how discovered schema could be used
    to create UC foreign tables.

    Args:
        label: Neo4j label name
        columns: List of (column_name, spark_type) tuples
        connection_name: UC JDBC connection name

    Returns:
        SQL DDL statement for creating the foreign table

    Example:
        ddl = generate_uc_foreign_table_ddl(
            "Aircraft",
            [("aircraft_id", "StringType"), ("model", "StringType")],
            "neo4j_connection"
        )
        print(ddl)
    """
    # Map Spark types to SQL types
    type_mapping = {
        "StringType": "STRING",
        "LongType": "BIGINT",
        "DoubleType": "DOUBLE",
        "BooleanType": "BOOLEAN",
        "DateType": "DATE",
        "TimestampType": "TIMESTAMP",
    }

    # Build column definitions
    col_defs = []
    for col_name, spark_type in columns:
        # Handle complex type names like StringType()
        base_type = spark_type.replace("()", "")
        sql_type = type_mapping.get(base_type, "STRING")
        col_defs.append(f"    {col_name} {sql_type}")

    columns_sql = ",\n".join(col_defs)

    return f"""-- Foreign table for Neo4j label: {label}
CREATE FOREIGN TABLE IF NOT EXISTS neo4j_{label.lower()} (
{columns_sql}
)
USING JDBC
CONNECTION {connection_name}
OPTIONS (
    dbtable '{label}'
);"""
