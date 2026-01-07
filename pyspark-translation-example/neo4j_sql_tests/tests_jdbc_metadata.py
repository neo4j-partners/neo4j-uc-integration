"""
Tests for direct JDBC DatabaseMetaData access.

This module demonstrates accessing Neo4j JDBC driver's DatabaseMetaData API
directly through PySpark's Py4J gateway, mirroring the Java SchemaMetadataTests.

Tests included:
    1. Driver information - JDBC driver and database metadata
    2. Get tables (labels) - getTables() with TABLE type
    3. Get columns - getColumns() for properties as columns
    4. Get primary keys - getPrimaryKeys() for element IDs
    5. Get relationships - getTables() with RELATIONSHIP type
    6. Schema summary - Complete schema discovery

This demonstrates that Neo4j JDBC exposes graph schema through standard
JDBC metadata APIs, enabling Unity Catalog and other SQL tools to discover
Neo4j graph schema without requiring native Cypher queries.

Reference:
    https://neo4j.com/docs/jdbc-manual/current/
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config
from .jdbc_metadata import (
    get_driver_info,
    get_catalogs,
    get_schemas,
    get_tables,
    get_columns,
    get_primary_keys,
    get_full_schema,
)
from .output import (
    print_header,
    print_subheader,
    print_test,
    print_success,
    print_error,
    print_info,
)


def run_jdbc_metadata_tests(spark: SparkSession, config: Config) -> None:
    """
    Run JDBC DatabaseMetaData tests mirroring Java SchemaMetadataTests.

    Demonstrates direct access to Neo4j JDBC metadata using PySpark's
    Py4J gateway (spark._jvm).

    Args:
        spark: Active SparkSession
        config: Configuration object
    """
    print_header("JDBC DATABASEMETADATA TESTS")
    print("Direct access to Neo4j JDBC metadata via spark._jvm")
    print("Equivalent to Java DatabaseMetaData API calls")
    print_info("See: https://neo4j.com/docs/jdbc-manual/current/")

    # Test 1: Driver information
    _test_driver_info(spark, config)

    # Test 2: Get catalogs (databases)
    _test_get_catalogs(spark, config)

    # Test 3: Get schemas
    _test_get_schemas(spark, config)

    # Test 4: Get tables (labels)
    labels = _test_get_tables(spark, config)

    # Test 5: Get columns for first label
    if labels:
        _test_get_columns(spark, config, labels[0])

    # Test 6: Get primary keys
    if labels:
        _test_get_primary_keys(spark, config, labels[0])

    # Test 7: Get relationship tables
    _test_get_relationships(spark, config)

    # Test 8: Print schema summary
    _print_schema_summary(spark, config)


def _test_driver_info(spark: SparkSession, config: Config) -> None:
    """Test getting JDBC driver information."""
    print_subheader("JDBC Driver Information")

    try:
        info = get_driver_info(spark, config)

        print(f"  Driver Name: {info['driver_name']}")
        print(f"  Driver Version: {info['driver_version']}")
        print(f"  Database Product: {info['database_product']}")
        print(f"  Database Version: {info['database_version']}")
        print(f"  Catalog Term: {info['catalog_term']}")
        print(f"  Schema Term: {info['schema_term']}")
        print_success("Driver info retrieved")

    except Exception as e:
        print_error(str(e)[:200])


def _test_get_catalogs(spark: SparkSession, config: Config) -> None:
    """Test getCatalogs() - returns Neo4j databases."""
    print_test("getCatalogs()", "Neo4j databases")

    try:
        catalogs = get_catalogs(spark, config)

        if catalogs:
            print(f"  Found {len(catalogs)} catalog(s): {catalogs}")
            print_success(f"{len(catalogs)} catalogs")
        else:
            print("  No catalogs returned (may require elevated privileges)")
            print_success("getCatalogs() completed")

    except Exception as e:
        print_error(str(e)[:200])


def _test_get_schemas(spark: SparkSession, config: Config) -> None:
    """Test getSchemas() - returns database schemas."""
    print_test("getSchemas()", "Database schemas")

    try:
        schemas = get_schemas(spark, config)

        for schema in schemas:
            print(f"  Schema: {schema['schema_name']} (Catalog: {schema['catalog_name']})")

        if schemas:
            print_success(f"{len(schemas)} schema(s)")
        else:
            print_success("No schemas returned")

    except Exception as e:
        print_error(str(e)[:200])


def _test_get_tables(spark: SparkSession, config: Config) -> list[str]:
    """
    Test getTables(TABLE) - returns labels as tables.

    Returns:
        List of label names for use in subsequent tests
    """
    print_test("getTables(TABLE)", "Labels as tables")

    try:
        tables = get_tables(spark, config, table_type="TABLE")

        print("  Node Labels (TABLE type):")
        labels = []
        for i, table in enumerate(tables):
            labels.append(table["name"])
            if i < 10:  # Show first 10
                remarks = f" - {table['remarks']}" if table["remarks"] else ""
                print(f"    - {table['name']} [{table['type']}]{remarks}")

        if len(tables) > 10:
            print(f"    ... and {len(tables) - 10} more labels")

        print_success(f"{len(tables)} labels discovered")
        return labels

    except Exception as e:
        print_error(str(e)[:200])
        return []


def _test_get_columns(
    spark: SparkSession,
    config: Config,
    table_name: str,
) -> None:
    """Test getColumns() - returns properties as columns."""
    print_test(f"getColumns('{table_name}')", "Properties as columns")

    try:
        columns = get_columns(spark, config, table_name)

        print(f"  Columns for label '{table_name}':")
        for col in columns:
            generated = " [generated]" if col["is_generated"] == "YES" else ""
            print(
                f"    {col['ordinal']}. {col['name']} : {col['type_name']} "
                f"(SQL type {col['data_type']}, nullable={col['nullable']}){generated}"
            )

        print_success(f"{len(columns)} columns discovered")

    except Exception as e:
        print_error(str(e)[:200])


def _test_get_primary_keys(
    spark: SparkSession,
    config: Config,
    table_name: str,
) -> None:
    """Test getPrimaryKeys() - returns primary key columns."""
    print_test(f"getPrimaryKeys('{table_name}')", "Primary key columns")

    try:
        keys = get_primary_keys(spark, config, table_name)

        print(f"  Primary Key for '{table_name}':")
        for key in keys:
            print(
                f"    - Column: {key['column_name']}, "
                f"Key Seq: {key['key_seq']}, "
                f"PK Name: {key['pk_name']}"
            )

        if keys:
            print_success(f"{len(keys)} primary key column(s)")
        else:
            print("  (No primary key defined)")
            print_success("getPrimaryKeys() completed")

    except Exception as e:
        print_error(str(e)[:200])


def _test_get_relationships(spark: SparkSession, config: Config) -> None:
    """Test getTables(RELATIONSHIP) - returns relationship virtual tables."""
    print_test("getTables(RELATIONSHIP)", "Relationship patterns")

    try:
        relationships = get_tables(spark, config, table_type="RELATIONSHIP")

        print("  Relationship Patterns (RELATIONSHIP type):")
        for i, rel in enumerate(relationships):
            if i < 10:  # Show first 10
                # Parse remarks to show pattern nicely
                if rel["remarks"]:
                    parts = rel["remarks"].split("\n")
                    if len(parts) >= 3:
                        print(f"    - (:{parts[0]})-[:{parts[1]}]->(:{parts[2]})")
                    else:
                        print(f"    - {rel['name']}")
                else:
                    print(f"    - {rel['name']}")

        if len(relationships) > 10:
            print(f"    ... and {len(relationships) - 10} more relationships")

        if relationships:
            print_success(f"{len(relationships)} relationship patterns discovered")
        else:
            print("  (No relationships found - graph may be empty)")
            print_success("getTables(RELATIONSHIP) completed")

    except Exception as e:
        print_error(str(e)[:200])


def _print_schema_summary(spark: SparkSession, config: Config) -> None:
    """Print complete schema summary."""
    print_header("JDBC METADATA SCHEMA SUMMARY")

    try:
        schema = get_full_schema(spark, config)

        print(f"Discovered {len(schema)} labels with their properties:\n")

        for i, (table_name, columns) in enumerate(schema.items()):
            if i < 5:  # Show first 5 tables in detail
                print(f"  {table_name}:")
                for col in columns[:5]:  # Show first 5 columns
                    print(f"    - {col['name']} : {col['type_name']}")
                if len(columns) > 5:
                    print(f"    ... and {len(columns) - 5} more columns")
                print()

        if len(schema) > 5:
            print(f"  ... and {len(schema) - 5} more labels\n")

        # Count relationships
        relationships = get_tables(spark, config, table_type="RELATIONSHIP")

        print(f"Labels discovered: {len(schema)}")
        print(f"Relationship patterns discovered: {len(relationships)}")
        print()
        print_info("This schema can be used to generate Unity Catalog foreign tables")
        print_info("Schema discovery uses standard JDBC DatabaseMetaData API")

    except Exception as e:
        print_error(str(e)[:200])
