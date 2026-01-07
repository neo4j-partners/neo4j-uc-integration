"""
JOIN translation tests for Neo4j JDBC SQL-to-Cypher.

This module tests how SQL JOIN syntax is translated to Cypher
relationship patterns by the Neo4j JDBC driver.

JOIN Translation Rules:
    1. NATURAL JOIN → Anonymous relationship (untyped)
       SQL:    FROM Flight f NATURAL JOIN Airport a
       Cypher: MATCH (f:Flight)-->(a:Airport)

    2. JOIN with ON clause → Typed relationship from column name
       SQL:    FROM Flight f JOIN Airport a ON (a.id = f.DEPARTS_FROM)
       Cypher: MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport)

    3. Three-way NATURAL JOIN → Explicit relationship type
       SQL:    FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a
       Cypher: MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport)

Limitations:
    - OUTER JOINs (LEFT, RIGHT, FULL) are NOT supported
    - Relationship direction is always outgoing (-->)
    - Multi-hop traversals require explicit relationship types

Reference:
    https://neo4j.com/docs/jdbc-manual/current/sql2cypher/
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config
from .spark import get_jdbc_options
from .output import print_subheader, print_test, print_success, print_error, print_info


def run_join_tests(spark: SparkSession, config: Config) -> None:
    """
    Run all JOIN translation tests.

    These tests demonstrate how SQL JOINs are translated to Cypher
    relationship patterns.

    Args:
        spark: Active SparkSession
        config: Configuration object
    """
    print_subheader("JOIN SYNTAX TESTS")
    print_info("Testing Neo4j JDBC's SQL-to-Cypher JOIN translation")
    print_info("See: https://neo4j.com/docs/jdbc-manual/current/sql2cypher/")

    opts = get_jdbc_options(config)

    # ---------------------------------------------------------------------
    # Test: NATURAL JOIN with COUNT
    # ---------------------------------------------------------------------
    _test_natural_join_count(spark, opts)

    # ---------------------------------------------------------------------
    # Test: JOIN with ON clause
    # ---------------------------------------------------------------------
    _test_join_on_clause(spark, opts)

    # ---------------------------------------------------------------------
    # Test: Multi-hop NATURAL JOIN
    # ---------------------------------------------------------------------
    _test_multi_hop_join(spark, opts)

    # ---------------------------------------------------------------------
    # Test: Domain-specific JOINs
    # ---------------------------------------------------------------------
    _test_maintenance_join(spark, opts)
    _test_delays_join(spark, opts)


def _test_natural_join_count(spark: SparkSession, opts: dict) -> None:
    """
    Test NATURAL JOIN with COUNT aggregate.

    Three-way NATURAL JOIN explicitly names the relationship type:
    SQL:    Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a
    Cypher: MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport)

    Using COUNT avoids potential float overflow from Airport lat/lon columns.
    """
    sql = """SELECT COUNT(*) AS cnt
             FROM Flight f
             NATURAL JOIN DEPARTS_FROM r
             NATURAL JOIN Airport a"""

    print_test("NATURAL JOIN with COUNT", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "cnt LONG")
            .load()
        )
        df.show()
        print_success("NATURAL JOIN translated to Cypher relationship pattern")
    except Exception as e:
        print_error(str(e))


def _test_join_on_clause(spark: SparkSession, opts: dict) -> None:
    """
    Test JOIN with ON clause.

    The join column name (uppercase) becomes the relationship type:
    SQL:    JOIN Airport a ON (a.airport_id = f.DEPARTS_FROM)
    Cypher: MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport)

    This is useful when you want explicit control over relationship inference.
    """
    sql = """SELECT COUNT(*) AS cnt
             FROM Flight f
             JOIN Airport a ON (a.airport_id = f.DEPARTS_FROM)"""

    print_test("JOIN with ON clause", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "cnt LONG")
            .load()
        )
        df.show()
        print_success("JOIN ON translated to relationship pattern")
    except Exception as e:
        print_error(str(e))


def _test_multi_hop_join(spark: SparkSession, opts: dict) -> None:
    """
    Test multi-hop NATURAL JOIN.

    Connects Aircraft to Flight through the OPERATES_FLIGHT relationship:
    SQL:    Aircraft ac NATURAL JOIN OPERATES_FLIGHT r NATURAL JOIN Flight f
    Cypher: MATCH (ac:Aircraft)-[:OPERATES_FLIGHT]->(f:Flight)
    """
    sql = """SELECT * FROM Aircraft ac
             NATURAL JOIN OPERATES_FLIGHT r
             NATURAL JOIN Flight f
             LIMIT 5"""

    print_test("Multi-hop NATURAL JOIN", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .load()
        )
        df.printSchema()
        df.show(5, truncate=False)
        print_success("Multi-hop JOIN translated")
    except Exception as e:
        print_error(str(e))


def _test_maintenance_join(spark: SparkSession, opts: dict) -> None:
    """
    Test domain-specific JOIN: Aircraft maintenance events.

    Demonstrates traversing Aircraft → MaintenanceEvent relationship.
    """
    sql = """SELECT COUNT(*) AS event_count
             FROM Aircraft ac
             NATURAL JOIN HAS_EVENT r
             NATURAL JOIN MaintenanceEvent m"""

    print_test("Aircraft maintenance JOIN", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "event_count LONG")
            .load()
        )
        df.show()
        print_success("Maintenance events JOIN")
    except Exception as e:
        print_error(str(e))


def _test_delays_join(spark: SparkSession, opts: dict) -> None:
    """
    Test domain-specific JOIN: Flight delays.

    Demonstrates traversing Flight → Delay relationship.
    """
    sql = """SELECT COUNT(*) AS delay_count
             FROM Flight f
             NATURAL JOIN HAS_DELAY r
             NATURAL JOIN Delay d"""

    print_test("Flight delays JOIN", sql)

    try:
        df = (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", sql)
            .option("customSchema", "delay_count LONG")
            .load()
        )
        df.show()
        print_success("Flight delays JOIN")
    except Exception as e:
        print_error(str(e))
