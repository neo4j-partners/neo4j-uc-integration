"""Network connectivity test using TCP layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.base import BaseTest, TestResult, TestStatus

if TYPE_CHECKING:
    from config import Config


class NetworkConnectivityTest(BaseTest):
    """Test TCP connectivity to Neo4j host."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Network Connectivity (TCP)"

    def run(self) -> list[TestResult]:
        """Test TCP connectivity using Spark SQL UDF with netcat."""
        results: list[TestResult] = []

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

            results.append(self._test_tcp_connectivity(spark))

        except Exception as e:
            results.append(
                TestResult(
                    name="network_error",
                    status=TestStatus.FAIL,
                    message=f"Network test error: {type(e).__name__}",
                    details={"error": str(e)[:500]},
                )
            )

        return results

    def _test_tcp_connectivity(self, spark) -> TestResult:
        """Test TCP connectivity using netcat via Spark SQL UDF."""
        host = self.config.neo4j.host
        port = "7687"

        try:
            # Create temporary UDF for network testing
            spark.sql("""
                CREATE OR REPLACE TEMPORARY FUNCTION connectionTest(host STRING, port STRING)
                RETURNS STRING
                LANGUAGE PYTHON AS $$
                import subprocess
                try:
                    command = ['nc', '-zv', host, str(port)]
                    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    output = result.stdout.decode() + result.stderr.decode()
                    if result.returncode == 0:
                        status = "SUCCESS"
                        message = f"Network connectivity to {host}:{port} is OPEN"
                    else:
                        status = "FAILURE"
                        message = f"Cannot reach {host}:{port} - check firewall rules"
                    return f"{status} (return_code={result.returncode}) | {message} | Details: {output.strip()}"
                except Exception as e:
                    return f"FAILURE (exception) | Error: {str(e)}"
                $$
            """)

            result = spark.sql(
                f"SELECT connectionTest('{host}', '{port}') AS result"
            ).collect()[0]["result"]

            if "SUCCESS" in result:
                return TestResult(
                    name="tcp_connectivity",
                    status=TestStatus.PASS,
                    message=f"TCP connectivity to {host}:{port} successful",
                    details={"result": result},
                )
            else:
                return TestResult(
                    name="tcp_connectivity",
                    status=TestStatus.FAIL,
                    message=f"TCP connectivity to {host}:{port} failed",
                    details={
                        "result": result,
                        "hint": "Check firewall rules and network configuration",
                    },
                )

        except Exception as e:
            return TestResult(
                name="tcp_connectivity",
                status=TestStatus.FAIL,
                message=f"TCP test failed: {type(e).__name__}",
                details={"error": str(e)[:500]},
            )
