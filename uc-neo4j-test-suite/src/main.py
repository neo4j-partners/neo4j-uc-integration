"""Neo4j connectivity test suite for Databricks."""

from config import DEFAULT_AIRCRAFT_SCHEMA, load_config
from tests import (
    DirectJdbcTest,
    EnvironmentTest,
    Neo4jDriverTest,
    NetworkConnectivityTest,
    SchemaDiscoveryTest,
    SchemaSyncOptionATest,
    SchemaSyncOptionCTest,
    SparkConnectorTest,
    UnityCatalogJdbcTest,
)
from tests.base import BaseTest, TestStatus


def create_test_suite(config) -> list[BaseTest]:
    """Create the ordered list of tests to run."""
    return [
        EnvironmentTest(config),
        NetworkConnectivityTest(config),
        Neo4jDriverTest(config),
        SparkConnectorTest(config),
        DirectJdbcTest(config),
        # Schema Sync tests (Section 8 equivalents)
        SchemaDiscoveryTest(config),
        SchemaSyncOptionATest(config),  # Views with inferred schema
        SchemaSyncOptionCTest(config),  # Hybrid with schema registry
        # Unity Catalog tests
        UnityCatalogJdbcTest(config),  # Expected to fail (SafeSpark issue)
    ]


def run_tests(tests: list[BaseTest]) -> bool:
    """Execute all tests and print results."""
    all_passed = True
    all_results = []

    for test in tests:
        test.print_header()
        print()

        results = test.run()
        all_results.extend(results)

        for result in results:
            result.print()
            if result.status in (TestStatus.FAIL, TestStatus.TIMEOUT):
                all_passed = False

        print()

    print_summary(all_results)
    return all_passed


def print_summary(results: list) -> None:
    """Print a summary of all test results."""
    print("=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)

    pass_count = sum(1 for r in results if r.status == TestStatus.PASS)
    fail_count = sum(1 for r in results if r.status == TestStatus.FAIL)
    timeout_count = sum(1 for r in results if r.status == TestStatus.TIMEOUT)
    info_count = sum(1 for r in results if r.status == TestStatus.INFO)
    skip_count = sum(1 for r in results if r.status == TestStatus.SKIP)

    print(f"\nPassed:   {pass_count}")
    print(f"Failed:   {fail_count}")
    print(f"Timeout:  {timeout_count}")
    print(f"Skipped:  {skip_count}")
    print(f"Info:     {info_count}")

    if fail_count > 0 or timeout_count > 0:
        print("\nFailed/Timeout tests:")
        for r in results:
            if r.status in (TestStatus.FAIL, TestStatus.TIMEOUT):
                print(f"  - {r.name}: {r.message}")

    print()


def run(
    secret_scope: str = "neo4j-uc-creds",
    jdbc_jar_path: str = "/Volumes/main/jdbc_drivers/jars/neo4j-jdbc-translator-sparkcleaner-6.10.3.jar",
    test_label: str = "Aircraft",
    test_label_schema: str = DEFAULT_AIRCRAFT_SCHEMA,
    timeout_seconds: int = 30,
) -> bool:
    """
    Run the test suite.

    Args:
        secret_scope: Databricks secret scope containing neo4j credentials
                      and connection_name.
        jdbc_jar_path: Path to Neo4j JDBC JAR (for reference only).
        test_label: Neo4j node label for test queries.
        test_label_schema: Spark schema for the test label (required for Direct JDBC).
        timeout_seconds: Timeout for each test.
    """
    print()
    print("=" * 60)
    print("Neo4j Unity Catalog Connection Test Suite")
    print("=" * 60)
    print()

    config = load_config(
        secret_scope=secret_scope,
        jdbc_jar_path=jdbc_jar_path,
        test_label=test_label,
        test_label_schema=test_label_schema,
        timeout_seconds=timeout_seconds,
    )
    tests = create_test_suite(config)
    return run_tests(tests)


if __name__ == "__main__":
    run()
