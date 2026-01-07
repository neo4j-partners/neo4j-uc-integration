"""Neo4j Python Driver connectivity test."""

from __future__ import annotations

from typing import TYPE_CHECKING

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from tests.base import (
    BaseTest,
    TestResult,
    TestStatus,
    TestTimeoutError,
    run_with_timeout,
)

if TYPE_CHECKING:
    from config import Config


class Neo4jDriverTest(BaseTest):
    """Test Neo4j connectivity using the official Python driver."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Neo4j Python Driver Connectivity"

    def run(self) -> list[TestResult]:
        """Test Neo4j Python driver connectivity."""
        results: list[TestResult] = []
        timeout = self.config.test.timeout_seconds

        driver = None
        try:
            driver = GraphDatabase.driver(
                self.config.neo4j.bolt_uri,
                auth=(self.config.neo4j.user, self.config.neo4j.password),
            )

            # Test 1: Verify connectivity
            connectivity_result = run_with_timeout(
                self._test_connectivity, timeout, driver
            )
            results.append(connectivity_result)

            if connectivity_result.status != TestStatus.PASS:
                return results

            # Test 2: Execute simple query
            query_result = run_with_timeout(
                self._test_simple_query, timeout, driver
            )
            results.append(query_result)

            # Test 3: Get Neo4j version info
            version_result = run_with_timeout(
                self._get_neo4j_version, timeout, driver
            )
            results.append(version_result)

        except TestTimeoutError:
            results.append(
                TestResult(
                    name="timeout",
                    status=TestStatus.TIMEOUT,
                    message=f"Test timed out after {timeout}s",
                    details={"timeout_seconds": str(timeout)},
                )
            )
        except AuthError as e:
            results.append(
                TestResult(
                    name="authentication",
                    status=TestStatus.FAIL,
                    message="Authentication failed",
                    details={
                        "error": str(e),
                        "hint": "Check NEO4J_USER and NEO4J_PASSWORD in .env",
                    },
                )
            )
        except ServiceUnavailable as e:
            results.append(
                TestResult(
                    name="service_unavailable",
                    status=TestStatus.FAIL,
                    message="Neo4j service unavailable",
                    details={
                        "error": str(e),
                        "bolt_uri": self.config.neo4j.bolt_uri,
                        "hint": "Check NEO4J_HOST and network connectivity",
                    },
                )
            )
        except Exception as e:
            results.append(
                TestResult(
                    name="connection_error",
                    status=TestStatus.FAIL,
                    message=f"Connection failed: {type(e).__name__}",
                    details={"error": str(e)},
                )
            )
        finally:
            if driver:
                driver.close()

        return results

    def _test_connectivity(self, driver) -> TestResult:
        """Verify driver can connect to Neo4j."""
        try:
            driver.verify_connectivity()
            return TestResult(
                name="connectivity",
                status=TestStatus.PASS,
                message="Driver connectivity verified",
            )
        except Exception as e:
            return TestResult(
                name="connectivity",
                status=TestStatus.FAIL,
                message="Driver connectivity check failed",
                details={"error": str(e)},
            )

    def _test_simple_query(self, driver) -> TestResult:
        """Execute a simple test query."""
        try:
            with driver.session() as session:
                result = session.run("RETURN 1 AS test")
                record = result.single()
                value = record["test"]

                if value == 1:
                    return TestResult(
                        name="simple_query",
                        status=TestStatus.PASS,
                        message=f"Query executed: RETURN 1 = {value}",
                    )
                else:
                    return TestResult(
                        name="simple_query",
                        status=TestStatus.FAIL,
                        message=f"Unexpected query result: {value}",
                    )
        except Exception as e:
            return TestResult(
                name="simple_query",
                status=TestStatus.FAIL,
                message="Query execution failed",
                details={"error": str(e)},
            )

    def _get_neo4j_version(self, driver) -> TestResult:
        """Get Neo4j server version information."""
        try:
            with driver.session() as session:
                result = session.run(
                    "CALL dbms.components() YIELD name, versions RETURN name, versions"
                )
                records = list(result)

                if records:
                    components = {r["name"]: r["versions"] for r in records}
                    neo4j_versions = components.get("Neo4j Kernel", ["unknown"])
                    version_str = ", ".join(neo4j_versions)

                    return TestResult(
                        name="neo4j_version",
                        status=TestStatus.INFO,
                        message=f"Connected to Neo4j {version_str}",
                        details={k: str(v) for k, v in components.items()},
                    )
                else:
                    return TestResult(
                        name="neo4j_version",
                        status=TestStatus.INFO,
                        message="Could not determine Neo4j version",
                    )
        except Exception as e:
            return TestResult(
                name="neo4j_version",
                status=TestStatus.FAIL,
                message="Failed to get Neo4j version",
                details={"error": str(e)},
            )
