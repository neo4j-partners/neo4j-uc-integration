"""Environment information test."""

from __future__ import annotations

import platform
import sys
from typing import TYPE_CHECKING

from tests.base import BaseTest, TestResult, TestStatus

if TYPE_CHECKING:
    from config import Config


class EnvironmentTest(BaseTest):
    """Collect environment information for support context."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Environment Information"

    def run(self) -> list[TestResult]:
        """Gather environment details."""
        results: list[TestResult] = []

        # Python version
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        results.append(
            TestResult(
                name="python_version",
                status=TestStatus.INFO,
                message=f"Python Version: {python_version}",
                details={"full_version": sys.version},
            )
        )

        # Platform info
        results.append(
            TestResult(
                name="platform",
                status=TestStatus.INFO,
                message=f"Platform: {platform.system()} {platform.release()}",
                details={
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                },
            )
        )

        # Neo4j Python driver version
        results.append(self._check_neo4j_driver())

        # Configuration summary
        results.append(
            TestResult(
                name="config",
                status=TestStatus.INFO,
                message="Configuration loaded from Databricks secrets",
                details={
                    "neo4j_host": self.config.neo4j.host,
                    "bolt_uri": self.config.neo4j.bolt_uri,
                    "jdbc_url": self.config.neo4j.jdbc_url,
                    "database": self.config.neo4j.database,
                    "uc_connection": self.config.unity_catalog.connection_name,
                    "jdbc_jar": self.config.unity_catalog.jdbc_jar_path,
                    "timeout": f"{self.config.test.timeout_seconds}s",
                },
            )
        )

        return results

    def _check_neo4j_driver(self) -> TestResult:
        """Check if Neo4j Python driver is installed."""
        try:
            import neo4j

            return TestResult(
                name="neo4j_driver",
                status=TestStatus.PASS,
                message=f"Neo4j Python Driver: {neo4j.__version__}",
            )
        except ImportError:
            return TestResult(
                name="neo4j_driver",
                status=TestStatus.FAIL,
                message="Neo4j Python Driver: NOT INSTALLED",
                details={"hint": "%pip install neo4j"},
            )
