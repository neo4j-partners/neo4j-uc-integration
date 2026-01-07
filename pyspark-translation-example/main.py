#!/usr/bin/env python3
"""
Neo4j JDBC SQL Translation Test Suite - Entry Point

This script tests Neo4j JDBC SQL-to-Cypher translation using local PySpark.
It simulates the Databricks environment by sending SQL queries through
the Neo4j JDBC driver with enableSQLTranslation=true.

Usage:
    uv run test-sql [OPTIONS]

Options:
    --all           Run all tests (default)
    --aggregates    Run aggregate function tests (COUNT, MAX, SELECT *)
    --joins         Run JOIN translation tests
    --failures      Run known failure tests (documents limitations)
    --schema        Run DataFrame-based schema discovery tests
    --metadata      Run direct JDBC DatabaseMetaData tests
    --sql           Run SQL translation tests only (aggregates + joins + failures)
    --discovery     Run schema discovery tests only (schema + metadata)

Examples:
    uv run test-sql                    # Run all tests
    uv run test-sql --aggregates       # Run only aggregate tests
    uv run test-sql --metadata         # Run only JDBC metadata tests
    uv run test-sql --sql              # Run SQL translation tests
    uv run test-sql --aggregates --joins  # Run aggregates and joins
"""

import argparse

from neo4j_sql_tests import run_all_tests, TestOptions


def parse_args() -> TestOptions:
    """
    Parse command-line arguments.

    Returns:
        TestOptions with flags for which tests to run
    """
    parser = argparse.ArgumentParser(
        description="Neo4j JDBC SQL Translation Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run test-sql                    Run all tests
  uv run test-sql --aggregates       Run only aggregate tests
  uv run test-sql --metadata         Run only JDBC metadata tests
  uv run test-sql --sql              Run SQL translation tests only
  uv run test-sql --discovery        Run schema discovery tests only
  uv run test-sql --aggregates --joins  Run aggregates and joins
        """,
    )

    # Individual test flags
    parser.add_argument(
        "--aggregates",
        action="store_true",
        help="Run aggregate function tests (COUNT, MAX, SELECT *)",
    )
    parser.add_argument(
        "--joins",
        action="store_true",
        help="Run JOIN translation tests (NATURAL JOIN, JOIN ON)",
    )
    parser.add_argument(
        "--failures",
        action="store_true",
        help="Run known failure tests (documents limitations)",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Run DataFrame-based schema discovery tests",
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="Run direct JDBC DatabaseMetaData tests",
    )

    # Group flags
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests (default if no flags specified)",
    )
    parser.add_argument(
        "--sql",
        action="store_true",
        help="Run SQL translation tests only (aggregates + joins + failures)",
    )
    parser.add_argument(
        "--discovery",
        action="store_true",
        help="Run schema discovery tests only (schema + metadata)",
    )

    args = parser.parse_args()

    # Determine which tests to run
    # If --all or no specific flags, run everything
    individual_flags = [
        args.aggregates,
        args.joins,
        args.failures,
        args.schema,
        args.metadata,
    ]
    group_flags = [args.sql, args.discovery]

    if args.all or (not any(individual_flags) and not any(group_flags)):
        # Run all tests
        return TestOptions()

    # Start with all False and enable based on flags
    options = TestOptions(
        aggregates=False,
        joins=False,
        failures=False,
        schema=False,
        metadata=False,
    )

    # Apply group flags
    if args.sql:
        options.aggregates = True
        options.joins = True
        options.failures = True

    if args.discovery:
        options.schema = True
        options.metadata = True

    # Apply individual flags (override groups)
    if args.aggregates:
        options.aggregates = True
    if args.joins:
        options.joins = True
    if args.failures:
        options.failures = True
    if args.schema:
        options.schema = True
    if args.metadata:
        options.metadata = True

    return options


def main():
    """
    Main entry point for the test suite.

    Parses command-line arguments, loads configuration from environment,
    and runs selected test suites.

    Exit code 0 on success, 1 on configuration error.
    """
    options = parse_args()
    success = run_all_tests(test_options=options)
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
