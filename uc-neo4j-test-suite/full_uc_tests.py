"""
Neo4j Unity Catalog JDBC Integration Test Suite

This script runs a comprehensive test suite for Neo4j JDBC connectivity through
Databricks Unity Catalog. All tests are wrapped in try/except to prevent crashes.

Usage in Databricks:
    %run ./full_uc_tests

Or execute directly:
    exec(open("/Workspace/path/to/full_uc_tests.py").read())

Prerequisites:
    1. Databricks Secrets configured in scope "neo4j-uc-creds"
    2. Neo4j JDBC JARs uploaded to UC Volume
    3. Cluster configured with SafeSpark memory settings:
       - spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128
       - spark.databricks.safespark.jdbcSandbox.jvm.xmx.mib 300
       - spark.databricks.safespark.jdbcSandbox.size.default.mib 512
"""

import time
from dataclasses import dataclass
from typing import Optional, Any

# =============================================================================
# CONFIGURATION
# =============================================================================

SCOPE_NAME = "neo4j-uc-creds"


def load_config() -> dict:
    """Load configuration from Databricks Secrets."""
    print("=" * 60)
    print("LOADING CONFIGURATION")
    print("=" * 60)

    config = {}

    try:
        config["host"] = dbutils.secrets.get(SCOPE_NAME, "host")
        print(f"  [OK] host: retrieved")
    except Exception as e:
        print(f"  [FAIL] host: {e}")
        raise

    try:
        config["user"] = dbutils.secrets.get(SCOPE_NAME, "user")
        print(f"  [OK] user: retrieved")
    except Exception as e:
        print(f"  [FAIL] user: {e}")
        raise

    try:
        config["password"] = dbutils.secrets.get(SCOPE_NAME, "password")
        print(f"  [OK] password: retrieved")
    except Exception as e:
        print(f"  [FAIL] password: {e}")
        raise

    try:
        config["connection_name"] = dbutils.secrets.get(SCOPE_NAME, "connection_name")
        print(f"  [OK] connection_name: {config['connection_name']}")
    except Exception as e:
        print(f"  [FAIL] connection_name: {e}")
        raise

    try:
        config["jdbc_jar_path"] = dbutils.secrets.get(SCOPE_NAME, "jdbc_jar_path")
        print(f"  [OK] jdbc_jar_path: retrieved")
    except Exception as e:
        print(f"  [FAIL] jdbc_jar_path: {e}")
        raise

    try:
        config["cleaner_jar_path"] = dbutils.secrets.get(SCOPE_NAME, "cleaner_jar_path")
        print(f"  [OK] cleaner_jar_path: retrieved")
    except Exception as e:
        print(f"  [FAIL] cleaner_jar_path: {e}")
        raise

    try:
        config["database"] = dbutils.secrets.get(SCOPE_NAME, "database")
    except Exception:
        config["database"] = "neo4j"
    print(f"  [OK] database: {config['database']}")

    # Derived values
    config["jdbc_url"] = f"jdbc:neo4j+s://{config['host']}:7687/{config['database']}?enableSQLTranslation=true"
    config["java_dependencies"] = f'["{config["jdbc_jar_path"]}", "{config["cleaner_jar_path"]}"]'

    print(f"\n  JDBC URL: {config['jdbc_url']}")
    print(f"  Connection: {config['connection_name']}")

    return config


# =============================================================================
# UC CONNECTION SETUP
# =============================================================================

def setup_connection(config: dict) -> bool:
    """Create or recreate the Unity Catalog JDBC connection."""
    print("\n" + "=" * 60)
    print("SETTING UP UC CONNECTION")
    print("=" * 60)

    connection_name = config["connection_name"]

    # Drop existing connection
    try:
        spark.sql(f"DROP CONNECTION IF EXISTS {connection_name}")
        print(f"  [OK] Dropped existing connection (if any)")
    except Exception as e:
        print(f"  [WARN] Drop connection: {e}")

    # Create connection
    create_sql = f"""
    CREATE CONNECTION {connection_name} TYPE JDBC
    ENVIRONMENT (
      java_dependencies '{config["java_dependencies"]}'
    )
    OPTIONS (
      url '{config["jdbc_url"]}',
      user '{config["user"]}',
      password '{config["password"]}',
      driver 'org.neo4j.jdbc.Neo4jDriver',
      externalOptionsAllowList 'dbtable,query,customSchema'
    )
    """

    try:
        start = time.time()
        spark.sql(create_sql)
        elapsed = (time.time() - start) * 1000
        print(f"  [OK] Connection '{connection_name}' created in {elapsed:.0f}ms")
        return True
    except Exception as e:
        print(f"  [FAIL] Create connection: {e}")
        return False


# =============================================================================
# TEST RESULT DATA CLASS
# =============================================================================

@dataclass
class TestResult:
    name: str
    success: bool
    time_ms: float
    error: Optional[str] = None
    result: Optional[Any] = None
    expected_fail: bool = False


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_test(
    config: dict,
    name: str,
    sql: str,
    schema: str,
    expected_cypher: Optional[str] = None,
    expected_fail: bool = False
) -> TestResult:
    """
    Run a single UC JDBC test with error handling.

    Args:
        config: Configuration dictionary with connection_name
        name: Test name for display
        sql: SQL query to execute
        schema: customSchema value (e.g., "cnt LONG")
        expected_cypher: Optional Cypher translation for documentation
        expected_fail: If True, test is expected to fail (documents limitation)

    Returns:
        TestResult with success status, timing, and any error
    """
    connection_name = config["connection_name"]

    try:
        start = time.time()
        df = spark.read.format("jdbc") \
            .option("databricks.connection", connection_name) \
            .option("query", sql) \
            .option("customSchema", schema) \
            .load()

        # Force execution
        results = df.collect()
        elapsed = (time.time() - start) * 1000

        # Extract first row result for display
        result_value = None
        if results:
            row = results[0]
            if len(row) == 1:
                result_value = row[0]
            else:
                result_value = row.asDict()

        return TestResult(
            name=name,
            success=True,
            time_ms=elapsed,
            result=result_value,
            expected_fail=expected_fail
        )

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        error_msg = str(e).split('\n')[0][:100]  # First line, truncated

        return TestResult(
            name=name,
            success=False,
            time_ms=elapsed,
            error=error_msg,
            expected_fail=expected_fail
        )


# =============================================================================
# TEST DEFINITIONS
# =============================================================================

def get_test_definitions() -> list:
    """Return list of all test definitions."""
    return [
        # =====================================================================
        # BASIC TESTS
        # =====================================================================
        {
            "name": "Basic Query",
            "sql": "SELECT 1 AS test",
            "schema": "test INT",
            "expected_cypher": "RETURN 1 AS test"
        },

        # =====================================================================
        # AGGREGATE TESTS
        # =====================================================================
        {
            "name": "COUNT Aggregate",
            "sql": "SELECT COUNT(*) AS flight_count FROM Flight",
            "schema": "flight_count LONG",
            "expected_cypher": "MATCH (n:Flight) RETURN count(n)"
        },
        {
            "name": "Multiple Aggregates (COUNT, MIN, MAX)",
            "sql": """SELECT COUNT(*) AS total,
                             MIN(aircraft_id) AS first_id,
                             MAX(aircraft_id) AS last_id
                      FROM Aircraft""",
            "schema": "total LONG, first_id STRING, last_id STRING"
        },
        {
            "name": "COUNT DISTINCT",
            "sql": "SELECT COUNT(DISTINCT manufacturer) AS unique_manufacturers FROM Aircraft",
            "schema": "unique_manufacturers LONG"
        },

        # =====================================================================
        # AGGREGATE WITH WHERE TESTS
        # =====================================================================
        {
            "name": "Aggregate with WHERE (equals)",
            "sql": """SELECT COUNT(*) AS boeing_count
                      FROM Aircraft
                      WHERE manufacturer = 'Boeing'""",
            "schema": "boeing_count LONG",
            "expected_cypher": "MATCH (n:Aircraft) WHERE n.manufacturer = 'Boeing' RETURN count(n)"
        },
        {
            "name": "Aggregate with WHERE (IN clause)",
            "sql": """SELECT COUNT(*) AS cnt
                      FROM Aircraft
                      WHERE manufacturer IN ('Boeing', 'Airbus')""",
            "schema": "cnt LONG"
        },
        {
            "name": "Aggregate with WHERE (AND)",
            "sql": """SELECT COUNT(*) AS cnt
                      FROM Aircraft
                      WHERE manufacturer = 'Boeing' AND model IS NOT NULL""",
            "schema": "cnt LONG"
        },
        {
            "name": "Aggregate with WHERE (IS NOT NULL)",
            "sql": """SELECT COUNT(*) AS cnt
                      FROM Aircraft
                      WHERE icao24 IS NOT NULL""",
            "schema": "cnt LONG"
        },

        # =====================================================================
        # JOIN TESTS (Graph Traversal)
        # =====================================================================
        {
            "name": "JOIN with Aggregate (2-hop)",
            "sql": """SELECT COUNT(*) AS relationship_count
                      FROM Flight f
                      NATURAL JOIN DEPARTS_FROM r
                      NATURAL JOIN Airport a""",
            "schema": "relationship_count LONG",
            "expected_cypher": "MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*)"
        },

        # =====================================================================
        # EXPECTED FAILURES (Document Limitations)
        # =====================================================================
        {
            "name": "GROUP BY (expected fail)",
            "sql": """SELECT manufacturer, COUNT(*) AS cnt
                      FROM Aircraft
                      GROUP BY manufacturer""",
            "schema": "manufacturer STRING, cnt LONG",
            "expected_fail": True
        },
        {
            "name": "Non-aggregate SELECT (expected fail)",
            "sql": """SELECT aircraft_id, manufacturer
                      FROM Aircraft""",
            "schema": "aircraft_id STRING, manufacturer STRING",
            "expected_fail": True
        },
        {
            "name": "ORDER BY (expected fail)",
            "sql": """SELECT COUNT(*) AS cnt
                      FROM Aircraft
                      ORDER BY cnt""",
            "schema": "cnt LONG",
            "expected_fail": True
        },
    ]


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_test_result(index: int, total: int, result: TestResult):
    """Print a single test result in formatted output."""
    status = "[PASS]" if result.success else "[FAIL]"
    if result.expected_fail:
        status = "[EXPECTED FAIL]" if not result.success else "[UNEXPECTED PASS]"

    # Pad name to align results
    name_padded = result.name[:40].ljust(40, '.')
    time_str = f"({result.time_ms:.0f}ms)"

    print(f"  [{index}/{total}] {name_padded} {status} {time_str}")

    if result.success and result.result is not None:
        result_str = str(result.result)
        if len(result_str) > 50:
            result_str = result_str[:50] + "..."
        print(f"          Result: {result_str}")
    elif not result.success and result.error:
        error_short = result.error[:60] + "..." if len(result.error) > 60 else result.error
        print(f"          Error: {error_short}")


def print_summary(results: list):
    """Print summary of all test results."""
    total = len(results)

    # Separate expected failures from real failures
    passed = [r for r in results if r.success and not r.expected_fail]
    failed = [r for r in results if not r.success and not r.expected_fail]
    expected_failed = [r for r in results if not r.success and r.expected_fail]
    unexpected_passed = [r for r in results if r.success and r.expected_fail]

    pass_count = len(passed)
    fail_count = len(failed)
    expected_fail_count = len(expected_failed)

    # Calculate success rate (excluding expected failures)
    testable = total - len([r for r in results if r.expected_fail])
    success_rate = (pass_count / testable * 100) if testable > 0 else 0

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"\nTotal Tests: {total}")
    print(f"  Passed: {pass_count}")
    print(f"  Failed: {fail_count}")
    print(f"  Expected Failures: {expected_fail_count}")
    if unexpected_passed:
        print(f"  Unexpected Passes: {len(unexpected_passed)}")
    print(f"\nSuccess Rate: {success_rate:.0f}% (excluding expected failures)")

    if passed:
        print("\n" + "-" * 40)
        print("PASSED TESTS:")
        for r in passed:
            print(f"  + {r.name}")

    if failed:
        print("\n" + "-" * 40)
        print("FAILED TESTS (Unexpected):")
        for r in failed:
            print(f"  - {r.name}")
            if r.error:
                print(f"    Error: {r.error[:80]}")

    if expected_failed:
        print("\n" + "-" * 40)
        print("EXPECTED FAILURES (Documents Limitations):")
        for r in expected_failed:
            print(f"  ~ {r.name}")

    if unexpected_passed:
        print("\n" + "-" * 40)
        print("UNEXPECTED PASSES (Previously failed, now works!):")
        for r in unexpected_passed:
            print(f"  ! {r.name}")

    # Total execution time
    total_time = sum(r.time_ms for r in results)
    print(f"\nTotal Execution Time: {total_time/1000:.1f}s")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Run the full UC JDBC test suite."""
    print("\n" + "=" * 60)
    print("NEO4J UNITY CATALOG JDBC TEST SUITE")
    print("=" * 60)
    print("\nThis test suite validates SQL patterns through UC JDBC connection.")
    print("All tests are wrapped in try/except to prevent crashes.\n")

    # Load configuration
    try:
        config = load_config()
    except Exception as e:
        print(f"\n[FATAL] Failed to load configuration: {e}")
        print("\nEnsure Databricks Secrets are configured in scope 'neo4j-uc-creds'")
        return

    # Setup connection
    if not setup_connection(config):
        print("\n[FATAL] Failed to create UC connection")
        return

    # Get test definitions
    tests = get_test_definitions()
    total = len(tests)

    # Run tests
    print("\n" + "=" * 60)
    print(f"RUNNING {total} TESTS")
    print("=" * 60 + "\n")

    results = []
    for i, test_def in enumerate(tests, 1):
        result = run_test(config, **test_def)
        results.append(result)
        print_test_result(i, total, result)

    # Print summary
    print_summary(results)

    print("\n" + "=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)


# =============================================================================
# EXECUTE
# =============================================================================

if __name__ == "__main__":
    main()
else:
    # When run via %run or exec(), also execute main
    main()
