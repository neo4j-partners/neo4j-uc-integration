"""Unity Catalog JDBC connection tests.

These tests use an existing Unity Catalog JDBC connection to Neo4j.
The connection must be pre-configured in Unity Catalog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.base import (
    BaseTest,
    TestResult,
    TestStatus,
    TestTimeoutError,
    run_with_timeout,
)

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

    from config import Config


class UnityCatalogJdbcTest(BaseTest):
    """Test Neo4j JDBC through Unity Catalog connection."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Unity Catalog JDBC Connection"

    def run(self) -> list[TestResult]:
        """Run Unity Catalog JDBC tests."""
        results: list[TestResult] = []
        timeout = self.config.test.timeout_seconds

        try:
            from pyspark.sql import SparkSession

            spark = SparkSession.getActiveSession()
            if spark is None:
                results.append(
                    TestResult(
                        name="spark_session",
                        status=TestStatus.FAIL,
                        message="No active Spark session found",
                    )
                )
                return results

            connection_name = self.config.unity_catalog.connection_name

            # Test 1: Verify connection exists
            results.append(
                self._run_test_with_timeout(
                    "verify_connection",
                    lambda: self._test_verify_connection(spark, connection_name),
                    timeout,
                )
            )

            # Only continue if connection exists
            if results[-1].status != TestStatus.PASS:
                return results

            # Test 2: Simple query via DataFrame API
            results.append(
                self._run_test_with_timeout(
                    "dataframe_api",
                    lambda: self._test_dataframe_api(spark, connection_name),
                    timeout,
                )
            )

            # Test 3: Native Cypher with FORCE_CYPHER hint
            results.append(
                self._run_test_with_timeout(
                    "native_cypher",
                    lambda: self._test_native_cypher(spark, connection_name),
                    timeout,
                )
            )

            # Test 4: remote_query() function
            results.append(
                self._run_test_with_timeout(
                    "remote_query",
                    lambda: self._test_remote_query(spark, connection_name),
                    timeout,
                )
            )

        except Exception as e:
            results.append(
                TestResult(
                    name="uc_error",
                    status=TestStatus.FAIL,
                    message=f"Unity Catalog test error: {type(e).__name__}",
                    details={"error": str(e)},
                )
            )

        return results

    def _run_test_with_timeout(
        self,
        test_name: str,
        test_func,
        timeout: int,
    ) -> TestResult:
        """Run a test function with timeout handling."""
        try:
            return run_with_timeout(test_func, timeout)
        except TestTimeoutError:
            return TestResult(
                name=test_name,
                status=TestStatus.TIMEOUT,
                message=f"Test '{test_name}' timed out after {timeout}s",
                details={"timeout_seconds": str(timeout)},
            )
        except Exception as e:
            return TestResult(
                name=test_name,
                status=TestStatus.FAIL,
                message=f"Test '{test_name}' failed: {type(e).__name__}",
                details={"error": str(e)[:500]},
            )

    def _test_verify_connection(
        self,
        spark: SparkSession,
        connection_name: str,
    ) -> TestResult:
        """Verify the Unity Catalog connection exists."""
        try:
            # Connection names are workspace-level, not catalog.schema scoped
            # Just wrap in backticks if it contains special chars
            name = connection_name.strip()
            if "-" in name or " " in name:
                quoted_name = f"`{name}`"
            else:
                quoted_name = name

            sql = f"DESCRIBE CONNECTION {quoted_name}"
            print(f"[DEBUG] connection_name='{name}', SQL: {sql}")
            df = spark.sql(sql)

            # Extract connection info
            rows = df.collect()
            info = {row["info_name"]: row["info_value"] for row in rows}

            return TestResult(
                name="verify_connection",
                status=TestStatus.PASS,
                message=f"UC connection '{connection_name}' found",
                details={
                    "connection_name": info.get("Connection Name", connection_name),
                    "type": info.get("Type", "unknown"),
                    "owner": info.get("Owner", "unknown"),
                },
            )
        except Exception as e:
            error_str = str(e)
            if "CONNECTION_NOT_FOUND" in error_str:
                return TestResult(
                    name="verify_connection",
                    status=TestStatus.FAIL,
                    message=f"UC connection '{connection_name}' not found",
                    details={
                        "hint": "Create connection in Unity Catalog first",
                        "error": error_str[:300],
                    },
                )
            raise

    def _test_dataframe_api(
        self,
        spark: SparkSession,
        connection_name: str,
    ) -> TestResult:
        """Test UC connection via Spark DataFrame API."""
        try:
            df = (
                spark.read.format("jdbc")
                .option("databricks.connection", connection_name)
                .option("query", "SELECT 1 AS test")
                .load()
            )

            result = df.collect()[0]["test"]

            if result == 1:
                return TestResult(
                    name="dataframe_api",
                    status=TestStatus.PASS,
                    message="UC DataFrame API query succeeded",
                    details={"result": str(result)},
                )
            else:
                return TestResult(
                    name="dataframe_api",
                    status=TestStatus.FAIL,
                    message=f"Unexpected result: {result}",
                )
        except Exception as e:
            error_str = str(e)
            if "Connection was closed" in error_str:
                return TestResult(
                    name="dataframe_api",
                    status=TestStatus.FAIL,
                    message="SafeSpark connection closed prematurely",
                    details={
                        "error": error_str[:300],
                        "hint": "This may be a compatibility issue with SafeSpark wrapper",
                    },
                )
            raise

    def _test_native_cypher(
        self,
        spark: SparkSession,
        connection_name: str,
    ) -> TestResult:
        """Test UC connection with native Cypher using FORCE_CYPHER hint."""
        try:
            df = (
                spark.read.format("jdbc")
                .option("databricks.connection", connection_name)
                .option("query", "/*+ NEO4J FORCE_CYPHER */ RETURN 1 AS test")
                .load()
            )

            result = df.collect()[0]["test"]

            if result == 1:
                return TestResult(
                    name="native_cypher",
                    status=TestStatus.PASS,
                    message="UC with FORCE_CYPHER hint succeeded",
                    details={"result": str(result)},
                )
            else:
                return TestResult(
                    name="native_cypher",
                    status=TestStatus.FAIL,
                    message=f"Unexpected result: {result}",
                )
        except Exception as e:
            error_str = str(e)
            if "Connection was closed" in error_str:
                return TestResult(
                    name="native_cypher",
                    status=TestStatus.FAIL,
                    message="SafeSpark connection closed prematurely",
                    details={
                        "error": error_str[:300],
                        "hint": "FORCE_CYPHER may not work with SafeSpark wrapper",
                    },
                )
            raise

    def _test_remote_query(
        self,
        spark: SparkSession,
        connection_name: str,
    ) -> TestResult:
        """Test UC connection via remote_query() function."""
        try:
            # remote_query takes connection name as a string parameter
            name = connection_name.strip()
            df = spark.sql(f"""
                SELECT * FROM remote_query(
                    '{name}',
                    query => 'SELECT 1 AS test'
                )
            """)

            result = df.collect()[0]["test"]

            if result == 1:
                return TestResult(
                    name="remote_query",
                    status=TestStatus.PASS,
                    message="UC remote_query() function succeeded",
                    details={"result": str(result)},
                )
            else:
                return TestResult(
                    name="remote_query",
                    status=TestStatus.FAIL,
                    message=f"Unexpected result: {result}",
                )
        except Exception as e:
            error_str = str(e)
            if "Connection was closed" in error_str:
                return TestResult(
                    name="remote_query",
                    status=TestStatus.FAIL,
                    message="SafeSpark connection closed prematurely",
                    details={
                        "error": error_str[:300],
                        "hint": "remote_query() may not work with SafeSpark wrapper",
                    },
                )
            raise
