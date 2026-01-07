"""
Aggregate function tests for Neo4j JDBC SQL translation.

This module tests SQL aggregate functions that are reliably translated
to Cypher by the Neo4j JDBC driver. These are the most robust patterns
for PySpark + Neo4j JDBC integration.

Supported Aggregates:
    - COUNT(*), COUNT(column)
    - MAX, MIN, SUM, AVG
    - SELECT * (with caveats for float/double columns)

SQL to Cypher Translation Examples:
    SQL:    SELECT COUNT(*) AS cnt FROM Flight
    Cypher: MATCH (n:Flight) RETURN count(n) AS cnt

    SQL:    SELECT MAX(flight_number) AS max_fn FROM Flight
    Cypher: MATCH (n:Flight) RETURN max(n.flight_number) AS max_fn

Best Practices:
    - Always use customSchema to avoid Spark type inference issues
    - Use column aliases (AS) for predictable column names
    - Prefer aggregates over SELECT * for large datasets
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config
from .spark import get_jdbc_options
from .output import print_subheader, print_test, print_success, print_error


def run_aggregate_tests(spark: SparkSession, config: Config) -> None:
    """
    Run all aggregate function tests.

    These tests demonstrate SQL aggregate functions that work reliably
    with Neo4j JDBC SQL translation.

    Args:
        spark: Active SparkSession
        config: Configuration object
    """
    print_subheader("WORKING PATTERNS - Aggregate Functions")

    opts = get_jdbc_options(config)

    # ---------------------------------------------------------------------
    # Test: COUNT(*) - Most reliable aggregate
    # ---------------------------------------------------------------------
    _test_count_star(spark, opts)

    # ---------------------------------------------------------------------
    # Test: COUNT on different table
    # ---------------------------------------------------------------------
    _test_count_different_table(spark, opts)

    # ---------------------------------------------------------------------
    # Test: MAX aggregate
    # ---------------------------------------------------------------------
    _test_max_aggregate(spark, opts)

    # ---------------------------------------------------------------------
    # Test: SELECT * with LIMIT
    # ---------------------------------------------------------------------
    _test_select_star(spark, opts)


def _test_count_star(spark: SparkSession, opts: dict) -> None:
    """
    Test COUNT(*) aggregate - the most reliable pattern.

    COUNT(*) translates cleanly to Cypher's count() function and
    returns a single row with a single column.
    """
    sql = "SELECT COUNT(*) AS flight_count FROM Flight"
    print_test("COUNT(*)", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            # customSchema ensures correct type - avoids NullType issues
            .option("customSchema", "flight_count LONG")
            .load()
        )
        df.show()
        print_success()
    except Exception as e:
        print_error(str(e))


def _test_count_different_table(spark: SparkSession, opts: dict) -> None:
    """
    Test COUNT on a different label/table.

    Verifies aggregate works across different Neo4j labels.
    """
    sql = "SELECT COUNT(*) AS cnt FROM Aircraft"
    print_test("COUNT on different table", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "cnt LONG")
            .load()
        )
        df.show()
        print_success()
    except Exception as e:
        print_error(str(e))


def _test_max_aggregate(spark: SparkSession, opts: dict) -> None:
    """
    Test MAX aggregate function.

    MAX translates to Cypher's max() function. Works with strings,
    numbers, and dates.
    """
    sql = "SELECT MAX(flight_number) AS max_fn FROM Flight"
    print_test("MAX aggregate", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            # Result type depends on the column type in Neo4j
            .option("customSchema", "max_fn STRING")
            .load()
        )
        df.show()
        print_success()
    except Exception as e:
        print_error(str(e))


def _test_select_star(spark: SparkSession, opts: dict) -> None:
    """
    Test SELECT * with LIMIT.

    SELECT * works when all columns have compatible types. Can fail if
    Neo4j float/double values exceed Java's range.

    Note: The schema is inferred from JDBC ResultSetMetaData, which
    exposes Neo4j property types as SQL types.
    """
    sql = "SELECT * FROM Flight LIMIT 5"
    print_test("SELECT * (with LIMIT)", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .load()
        )
        # Show schema to demonstrate metadata discovery
        df.printSchema()
        df.show(5, truncate=False)
        print_success()
    except Exception as e:
        print_error(str(e))
