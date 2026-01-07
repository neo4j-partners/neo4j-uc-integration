"""Neo4j Spark Connector test."""

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


class SparkConnectorTest(BaseTest):
    """Test Neo4j Spark Connector (org.neo4j.spark.DataSource)."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Neo4j Spark Connector"

    def run(self) -> list[TestResult]:
        """Test Neo4j Spark Connector connectivity."""
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

            results.append(
                self._run_test_with_timeout(
                    "spark_connector",
                    lambda: self._test_spark_connector(spark),
                    timeout,
                )
            )

        except Exception as e:
            results.append(
                TestResult(
                    name="spark_connector_error",
                    status=TestStatus.FAIL,
                    message=f"Spark Connector test error: {type(e).__name__}",
                    details={"error": str(e)[:500]},
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

    def _test_spark_connector(self, spark: SparkSession) -> TestResult:
        """Test Neo4j Spark Connector with a simple query."""
        try:
            df = (
                spark.read.format("org.neo4j.spark.DataSource")
                .option("url", self.config.neo4j.bolt_uri)
                .option("authentication.type", "basic")
                .option("authentication.basic.username", self.config.neo4j.user)
                .option("authentication.basic.password", self.config.neo4j.password)
                .option("query", "RETURN 'Spark Connector Works!' AS message, 1 AS value")
                .load()
            )

            rows = df.collect()
            if rows and rows[0]["value"] == 1:
                return TestResult(
                    name="spark_connector",
                    status=TestStatus.PASS,
                    message="Neo4j Spark Connector query succeeded",
                    details={
                        "message": rows[0]["message"],
                        "value": str(rows[0]["value"]),
                    },
                )
            else:
                return TestResult(
                    name="spark_connector",
                    status=TestStatus.FAIL,
                    message="Unexpected result from Spark Connector",
                    details={"rows": str(rows)[:300]},
                )

        except Exception as e:
            error_str = str(e)
            if "ClassNotFoundException" in error_str or "neo4j.spark" in error_str:
                return TestResult(
                    name="spark_connector",
                    status=TestStatus.FAIL,
                    message="Neo4j Spark Connector not installed",
                    details={
                        "error": error_str[:300],
                        "hint": "Install neo4j-connector-apache-spark from Maven Central",
                    },
                )
            raise
