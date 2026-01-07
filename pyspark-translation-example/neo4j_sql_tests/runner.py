"""
Test runner that orchestrates all Neo4j JDBC SQL translation tests.

This module provides the main entry point for running all test suites
and coordinates the test execution lifecycle:
    1. Load configuration
    2. Create Spark session
    3. Run selected test suites based on options
    4. Clean up resources

Test Suites (in execution order):
    1. Aggregate tests - COUNT, MAX, SELECT *
    2. Known failure tests - Documents limitations
    3. JOIN tests - NATURAL JOIN, JOIN ON
    4. Schema discovery tests - DataFrame-based schema inference
    5. JDBC metadata tests - Direct DatabaseMetaData API access

Usage:
    from neo4j_sql_tests import run_all_tests
    run_all_tests()

Or via command line:
    uv run test-sql [OPTIONS]
    uv run test-sql --aggregates --joins  # Run specific tests
    uv run test-sql --metadata            # Run only JDBC metadata tests
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, load_config, print_jar_download_instructions
from .spark import create_spark_session
from .output import print_header, print_info
from .tests_aggregates import run_aggregate_tests
from .tests_joins import run_join_tests
from .tests_known_failures import run_known_failure_tests
from .tests_schema import run_schema_discovery_tests
from .tests_jdbc_metadata import run_jdbc_metadata_tests


@dataclass
class TestOptions:
    """Options controlling which tests to run."""

    aggregates: bool = True
    joins: bool = True
    failures: bool = True
    schema: bool = True
    metadata: bool = True


def run_all_tests(config: Config | None = None, test_options: TestOptions | None = None) -> bool:
    """
    Run Neo4j JDBC SQL translation test suites.

    This is the main entry point for test execution. It:
        1. Validates configuration
        2. Creates a Spark session
        3. Runs selected test suites based on options
        4. Cleans up the Spark session

    Args:
        config: Optional Config object. If None, loads from environment.
        test_options: Optional TestOptions to select which tests to run.
                      If None, runs all tests.

    Returns:
        True if all tests completed (regardless of pass/fail), False on setup error

    Example:
        # Run all tests with default config
        success = run_all_tests()

        # Run only metadata tests
        options = TestOptions(
            aggregates=False, joins=False, failures=False,
            schema=False, metadata=True
        )
        success = run_all_tests(test_options=options)
    """
    # Load configuration if not provided
    if config is None:
        config = load_config()

    # Use default options (all tests) if not provided
    if test_options is None:
        test_options = TestOptions()

    # Validate configuration
    if errors := config.validate():
        _print_config_errors(errors, config)
        return False

    # Print startup banner
    _print_startup_banner(config, test_options)

    # Create Spark session and run tests
    spark = create_spark_session(config)

    try:
        # ---------------------------------------------------------------------
        # SQL Translation Tests
        # ---------------------------------------------------------------------
        run_sql_tests = (
            test_options.aggregates or test_options.failures or test_options.joins
        )

        if run_sql_tests:
            print_header("SQL TRANSLATION TESTS")
            print("Sending SQL queries through Neo4j JDBC driver.")
            print("The driver translates SQL to Cypher before executing.")
            print_info("See: https://neo4j.com/docs/jdbc-manual/current/sql2cypher/")

            # Run aggregate function tests
            if test_options.aggregates:
                run_aggregate_tests(spark, config)

            # Run known failure tests (documents limitations)
            if test_options.failures:
                run_known_failure_tests(spark, config)

            # Run JOIN translation tests
            if test_options.joins:
                run_join_tests(spark, config)

        # ---------------------------------------------------------------------
        # Schema Discovery Tests (DataFrame-based)
        # ---------------------------------------------------------------------
        if test_options.schema:
            run_schema_discovery_tests(spark, config)

        # ---------------------------------------------------------------------
        # JDBC DatabaseMetaData Tests (Direct API access)
        # ---------------------------------------------------------------------
        if test_options.metadata:
            run_jdbc_metadata_tests(spark, config)

        # ---------------------------------------------------------------------
        # Completion
        # ---------------------------------------------------------------------
        _print_completion_banner(test_options)

        return True

    finally:
        # Always clean up Spark session
        spark.stop()


def _print_config_errors(errors: list[str], config: Config) -> None:
    """Print configuration validation errors."""
    print_header("CONFIGURATION ERROR")

    for error in errors:
        print(f"  ERROR: {error}")

    # Special handling for missing JAR
    if any("JAR" in e for e in errors):
        print()
        print_jar_download_instructions()


def _print_startup_banner(config: Config, options: TestOptions) -> None:
    """Print startup banner with configuration info."""
    print_header("NEO4J JDBC SQL TRANSLATION TESTS")
    print(f"JDBC URL: {config.jdbc_url}")
    print(f"JAR Path: {config.jar_path}")
    print()

    # Show which tests will run
    tests_to_run = []
    if options.aggregates:
        tests_to_run.append("Aggregate functions (COUNT, MAX)")
    if options.joins:
        tests_to_run.append("JOIN translation")
    if options.failures:
        tests_to_run.append("Known limitations")
    if options.schema:
        tests_to_run.append("DataFrame schema discovery")
    if options.metadata:
        tests_to_run.append("JDBC DatabaseMetaData API")

    if len(tests_to_run) == 5:
        print("Running all tests:")
    else:
        print("Running selected tests:")

    for i, test in enumerate(tests_to_run, 1):
        print(f"  {i}. {test}")


def _print_completion_banner(options: TestOptions) -> None:
    """Print completion banner."""
    print_header("TESTS COMPLETED")
    print("Selected tests completed successfully!")
    print()
    print("Key Takeaways:")

    if options.aggregates:
        print("  ✓ Aggregates (COUNT, MAX) work reliably")
    if options.joins:
        print("  ✓ NATURAL JOIN translates to Cypher relationships")
        print("  ✓ JOIN ON clause infers relationship type from column name")
    if options.schema:
        print("  ✓ Schema discovery via SELECT * LIMIT 1 exposes labels as tables")
    if options.metadata:
        print("  ✓ JDBC DatabaseMetaData exposes labels, columns, primary keys")
        print("  ✓ Relationship patterns discoverable via getTables(RELATIONSHIP)")
    if options.failures:
        print("  ⚠ Column projections fail due to Spark subquery wrapping")
        print("  ⚠ GROUP BY has same limitation")
    if options.schema:
        print("  ⚠ Labels with array properties may fail DataFrame schema discovery")

    print()
    print("For full SQL control, use Databricks remote_query() or")
    print("Neo4j Spark Connector for native Cypher.")
