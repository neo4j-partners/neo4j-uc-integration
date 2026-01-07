"""
Neo4j JDBC SQL Translation Test Suite

This package provides tests for Neo4j JDBC SQL-to-Cypher translation using PySpark.
It simulates the Databricks environment by sending SQL queries through the Neo4j
JDBC driver with enableSQLTranslation=true.

Package Structure:
    config.py           - Configuration and environment management
    spark.py            - Spark session and JDBC utilities
    output.py           - Output formatting helpers
    jdbc_metadata.py    - Direct JDBC DatabaseMetaData access
    tests_*.py          - Individual test modules
    runner.py           - Test orchestration

Usage:
    uv run test-sql

Reference:
    https://neo4j.com/docs/jdbc-manual/current/sql2cypher/
"""

from .config import Config, load_config
from .spark import create_spark_session, get_jdbc_options
from .output import print_header, print_test, print_success, print_error
from .runner import run_all_tests, TestOptions
from .jdbc_metadata import (
    get_tables,
    get_columns,
    get_primary_keys,
    get_driver_info,
    get_full_schema,
)

__all__ = [
    # Configuration
    "Config",
    "load_config",
    # Spark utilities
    "create_spark_session",
    "get_jdbc_options",
    # Output formatting
    "print_header",
    "print_test",
    "print_success",
    "print_error",
    # Test runner
    "run_all_tests",
    "TestOptions",
    # JDBC metadata access
    "get_tables",
    "get_columns",
    "get_primary_keys",
    "get_driver_info",
    "get_full_schema",
]
