"""
Tests for known failing patterns in PySpark + Neo4j JDBC.

This module documents SQL patterns that are expected to fail due to
known limitations in the Spark JDBC integration or Neo4j SQL translation.

Understanding these limitations helps users:
    1. Avoid problematic patterns in production code
    2. Know when to use alternative approaches (remote_query, Spark Connector)
    3. Recognize if underlying issues have been fixed

Known Limitations:
    1. Column Projections (SELECT col1, col2)
       - Spark wraps query in subquery for schema inference
       - Neo4j translator uses subquery alias in Cypher output
       - Error: "spark_gen_subq_X" in generated Cypher

    2. GROUP BY
       - Same subquery wrapping issue as column projections
       - Aggregate columns are not properly exposed

    3. collect() Aggregate
       - Neo4j's LIST/ARRAY type is not recognized by Spark
       - Error: UNRECOGNIZED_SQL_TYPE

Workarounds:
    - Use SELECT * instead of column projections
    - Use aggregates without GROUP BY
    - Use Databricks remote_query() for full SQL control
    - Use Neo4j Spark Connector for native Cypher
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config
from .spark import get_jdbc_options
from .output import (
    print_subheader,
    print_test,
    print_expected_failure,
    print_unexpected_success,
    print_error,
)


def run_known_failure_tests(spark: SparkSession, config: Config) -> None:
    """
    Run tests for known failing patterns.

    These tests are expected to fail and help document the limitations
    of PySpark + Neo4j JDBC integration.

    Args:
        spark: Active SparkSession
        config: Configuration object
    """
    print_subheader("KNOWN FAILING PATTERNS")
    print("These tests document limitations in Spark/JDBC translation")

    opts = get_jdbc_options(config)

    # ---------------------------------------------------------------------
    # Test: Column projection (SELECT col1, col2)
    # ---------------------------------------------------------------------
    _test_column_projection(spark, opts)

    # ---------------------------------------------------------------------
    # Test: GROUP BY
    # ---------------------------------------------------------------------
    _test_group_by(spark, opts)

    # ---------------------------------------------------------------------
    # Test: collect() aggregate
    # ---------------------------------------------------------------------
    _test_collect_aggregate(spark, opts)


def _test_column_projection(spark: SparkSession, opts: dict) -> None:
    """
    Test column projection - expected to fail.

    Issue: Spark sends schema inference query as:
        SELECT * FROM (SELECT tail_number, model FROM Aircraft)
                      spark_gen_subq_X WHERE 1=0

    The Neo4j translator uses "spark_gen_subq_X" in the generated Cypher,
    causing a syntax error.

    Workaround: Use SELECT * or dbtable option instead.
    """
    sql = "SELECT tail_number, model FROM Aircraft LIMIT 5"
    print_test("[EXPECTED FAIL] Column projection", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "tail_number STRING, model STRING")
            .load()
        )
        df.show()
        print_unexpected_success()
    except Exception as e:
        err_str = str(e)
        if "spark_gen_subq" in err_str.lower():
            print_expected_failure("Spark subquery alias issue")
        else:
            print_error(f"UNEXPECTED ERROR: {err_str[:200]}")


def _test_group_by(spark: SparkSession, opts: dict) -> None:
    """
    Test GROUP BY - expected to fail.

    Issue: Same as column projection - Spark's subquery wrapping
    breaks the GROUP BY column references.

    Workaround: Use COUNT without GROUP BY, or use remote_query().
    """
    sql = "SELECT model, COUNT(*) AS cnt FROM Aircraft GROUP BY model"
    print_test("[EXPECTED FAIL] GROUP BY", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "model STRING, cnt LONG")
            .load()
        )
        df.show()
        print_unexpected_success()
    except Exception as e:
        err_str = str(e)
        if "spark_gen_subq" in err_str.lower():
            print_expected_failure("Spark subquery alias issue")
        else:
            print_error(f"UNEXPECTED ERROR: {err_str[:200]}")


def _test_collect_aggregate(spark: SparkSession, opts: dict) -> None:
    """
    Test collect() aggregate - expected to fail.

    Issue: Neo4j's collect() returns a LIST type, which Spark
    doesn't recognize as a valid SQL type.

    Error: UNRECOGNIZED_SQL_TYPE or LIST/ARRAY type error

    Workaround: Use Neo4j Spark Connector for native Cypher with lists,
    or process lists in application code.
    """
    sql = "SELECT collect(flight_number) AS flights FROM Flight LIMIT 10"
    print_test("[EXPECTED FAIL] collect() aggregate", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .load()
        )
        df.show(truncate=False)
        print_unexpected_success()
    except Exception as e:
        err_str = str(e)
        # Check for expected error patterns
        if any(
            pattern in err_str
            for pattern in ["UNRECOGNIZED_SQL_TYPE", "LIST", "ARRAY"]
        ):
            print_expected_failure("Spark doesn't support Neo4j LIST/ARRAY type")
        else:
            print_error(err_str[:200])
