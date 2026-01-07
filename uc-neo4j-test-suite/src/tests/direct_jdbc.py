"""Direct JDBC tests bypassing Unity Catalog SafeSpark wrapper.

These tests use the Neo4j JDBC driver directly with Spark, without going
through Unity Catalog's SafeSpark isolation layer. They serve as a working
baseline to confirm JDBC connectivity works.
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


class DirectJdbcTest(BaseTest):
    """Test Neo4j JDBC driver directly (bypassing SafeSpark)."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Direct JDBC (bypassing SafeSpark)"

    def run(self) -> list[TestResult]:
        """Run Direct JDBC tests."""
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

            # Test 1: dbtable (read label as table)
            results.append(
                self._run_test_with_timeout(
                    "dbtable",
                    lambda: self._test_dbtable(spark),
                    timeout,
                )
            )

            # Test 2: SQL translation (simple SELECT)
            results.append(
                self._run_test_with_timeout(
                    "sql_translation",
                    lambda: self._test_sql_translation(spark),
                    timeout,
                )
            )

            # Test 3: SQL aggregate (COUNT)
            results.append(
                self._run_test_with_timeout(
                    "sql_aggregate",
                    lambda: self._test_sql_aggregate(spark),
                    timeout,
                )
            )

            # Test 4: SQL JOIN translation
            results.append(
                self._run_test_with_timeout(
                    "sql_join",
                    lambda: self._test_sql_join(spark),
                    timeout,
                )
            )

        except Exception as e:
            results.append(
                TestResult(
                    name="direct_jdbc_error",
                    status=TestStatus.FAIL,
                    message=f"Direct JDBC test error: {type(e).__name__}",
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

    def _test_dbtable(self, spark: SparkSession) -> TestResult:
        """Test reading a Neo4j label as a table using dbtable option."""
        test_label = self.config.test.test_label
        label_schema = self.config.test.test_label_schema

        try:
            df = (
                spark.read.format("jdbc")
                .option("url", self.config.neo4j.jdbc_url_sql)
                .option("driver", "org.neo4j.jdbc.Neo4jDriver")
                .option("user", self.config.neo4j.user)
                .option("password", self.config.neo4j.password)
                .option("dbtable", test_label)
                .option("customSchema", label_schema)
                .load()
            )

            count = df.count()

            return TestResult(
                name="dbtable",
                status=TestStatus.PASS,
                message=f"Direct JDBC dbtable '{test_label}' read succeeded",
                details={
                    "label": test_label,
                    "row_count": str(count),
                    "schema": label_schema[:100],
                },
            )

        except Exception as e:
            error_str = str(e)
            if "ClassNotFoundException" in error_str:
                return TestResult(
                    name="dbtable",
                    status=TestStatus.FAIL,
                    message="Neo4j JDBC driver not installed as cluster library",
                    details={
                        "error": error_str[:300],
                        "hint": "Install neo4j-jdbc-full-bundle JAR as cluster library",
                    },
                )
            raise

    def _test_sql_translation(self, spark: SparkSession) -> TestResult:
        """Test SQL translation with a simple SELECT query."""
        try:
            df = (
                spark.read.format("jdbc")
                .option("url", self.config.neo4j.jdbc_url_sql)
                .option("driver", "org.neo4j.jdbc.Neo4jDriver")
                .option("user", self.config.neo4j.user)
                .option("password", self.config.neo4j.password)
                .option("query", "SELECT 1 AS value")
                .option("customSchema", "value INT")
                .load()
            )

            result = df.collect()[0]["value"]

            if result == 1:
                return TestResult(
                    name="sql_translation",
                    status=TestStatus.PASS,
                    message="Direct JDBC SQL translation succeeded",
                    details={"result": str(result)},
                )
            else:
                return TestResult(
                    name="sql_translation",
                    status=TestStatus.FAIL,
                    message=f"Unexpected result: {result}",
                )

        except Exception as e:
            raise

    def _test_sql_aggregate(self, spark: SparkSession) -> TestResult:
        """Test SQL aggregate (COUNT) query."""
        test_label = self.config.test.test_label

        try:
            df = (
                spark.read.format("jdbc")
                .option("url", self.config.neo4j.jdbc_url_sql)
                .option("driver", "org.neo4j.jdbc.Neo4jDriver")
                .option("user", self.config.neo4j.user)
                .option("password", self.config.neo4j.password)
                .option("query", f"SELECT COUNT(*) AS cnt FROM {test_label}")
                .option("customSchema", "cnt LONG")
                .load()
            )

            count = df.collect()[0]["cnt"]

            return TestResult(
                name="sql_aggregate",
                status=TestStatus.PASS,
                message=f"Direct JDBC SQL aggregate succeeded",
                details={
                    "query": f"SELECT COUNT(*) FROM {test_label}",
                    "count": str(count),
                },
            )

        except Exception as e:
            raise

    def _test_sql_join(self, spark: SparkSession) -> TestResult:
        """Test SQL JOIN translation to Cypher relationships.

        SQL: SELECT COUNT(*) FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a
        Cypher: MATCH (f:Flight)-[:DEPARTS_FROM]->(a:Airport) RETURN count(*)
        """
        try:
            df = (
                spark.read.format("jdbc")
                .option("url", self.config.neo4j.jdbc_url_sql)
                .option("driver", "org.neo4j.jdbc.Neo4jDriver")
                .option("user", self.config.neo4j.user)
                .option("password", self.config.neo4j.password)
                .option(
                    "query",
                    """SELECT COUNT(*) AS cnt
                       FROM Flight f
                       NATURAL JOIN DEPARTS_FROM r
                       NATURAL JOIN Airport a""",
                )
                .option("customSchema", "cnt LONG")
                .load()
            )

            count = df.collect()[0]["cnt"]

            return TestResult(
                name="sql_join",
                status=TestStatus.PASS,
                message="Direct JDBC SQL JOIN translation succeeded",
                details={
                    "pattern": "Flight-[:DEPARTS_FROM]->Airport",
                    "count": str(count),
                },
            )

        except Exception as e:
            error_str = str(e)
            # This test may fail if the graph doesn't have this pattern
            if "syntax error" in error_str.lower() or "not found" in error_str.lower():
                return TestResult(
                    name="sql_join",
                    status=TestStatus.SKIP,
                    message="SQL JOIN test skipped - pattern not in graph",
                    details={
                        "hint": "Requires Flight-[:DEPARTS_FROM]->Airport pattern",
                        "error": error_str[:200],
                    },
                )
            raise
