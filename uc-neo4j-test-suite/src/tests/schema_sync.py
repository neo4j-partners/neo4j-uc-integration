"""Schema Synchronization tests for Neo4j with Unity Catalog.

These tests demonstrate discovering Neo4j graph schema via JDBC DatabaseMetaData
and creating Unity Catalog objects backed by the JDBC connection.

Tests are split to allow independent execution:
- SchemaDiscoveryTest: Discovers schema via JDBC DatabaseMetaData
- SchemaSyncOptionATest: Views with inferred schema
- SchemaSyncOptionCTest: Hybrid approach with schema registry
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

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


# Module-level cache for discovered schema.
# This is intentionally module-level to share state between test classes
# that run sequentially in the same process.
_discovered_schema: dict[str, Any] | None = None


def get_discovered_schema() -> dict[str, Any] | None:
    """Get the cached discovered schema."""
    return _discovered_schema


def set_discovered_schema(schema: dict[str, Any]) -> None:
    """Set the cached discovered schema."""
    global _discovered_schema
    _discovered_schema = schema


def _run_test_with_timeout(
    test_name: str,
    test_func: Callable[[], TestResult],
    timeout: int,
) -> TestResult:
    """
    Run a test function with timeout handling.

    Args:
        test_name: Name for error reporting.
        test_func: Zero-argument callable returning TestResult.
        timeout: Timeout in seconds.

    Returns:
        TestResult from test_func, or error/timeout result.
    """
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


class SchemaDiscoveryTest(BaseTest):
    """Test schema discovery via JDBC DatabaseMetaData API."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "Schema Discovery (JDBC DatabaseMetaData)"

    def run(self) -> list[TestResult]:
        """Run schema discovery tests."""
        results: list[TestResult] = []
        timeout = self.config.test.timeout_seconds

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

        # Test 1: Trigger driver loading
        results.append(
            _run_test_with_timeout(
                "driver_load",
                lambda: self._test_driver_load(spark),
                timeout,
            )
        )

        if results[-1].status != TestStatus.PASS:
            return results

        # Test 2: Schema discovery via DatabaseMetaData
        results.append(
            _run_test_with_timeout(
                "schema_discovery",
                lambda: self._test_schema_discovery(spark),
                timeout,
            )
        )

        return results

    def _test_driver_load(self, spark: SparkSession) -> TestResult:
        """Trigger Neo4j JDBC driver loading with a minimal query."""
        jdbc_url = self.config.neo4j.jdbc_url_sql
        user = self.config.neo4j.user
        password = self.config.neo4j.password

        df = (
            spark.read.format("jdbc")
            .option("url", jdbc_url)
            .option("driver", "org.neo4j.jdbc.Neo4jDriver")
            .option("user", user)
            .option("password", password)
            .option("query", "SELECT 1 AS test")
            .option("customSchema", "test INT")
            .load()
        )
        result = df.take(1)

        if result and result[0]["test"] == 1:
            return TestResult(
                name="driver_load",
                status=TestStatus.PASS,
                message="Neo4j JDBC driver loaded successfully",
            )
        return TestResult(
            name="driver_load",
            status=TestStatus.FAIL,
            message="Driver loaded but query returned unexpected result",
        )

    def _test_schema_discovery(self, spark: SparkSession) -> TestResult:
        """Discover Neo4j schema using JDBC DatabaseMetaData API."""
        schema = self._discover_schema_via_jdbc(spark)
        set_discovered_schema(schema)

        label_count = len(schema.get("labels", {}))
        rel_count = len(schema.get("relationships", []))
        total_columns = sum(
            len(label["columns"]) for label in schema.get("labels", {}).values()
        )

        if label_count > 0:
            labels_list = list(schema["labels"].keys())[:5]
            return TestResult(
                name="schema_discovery",
                status=TestStatus.PASS,
                message=f"Discovered {label_count} labels, {rel_count} relationships",
                details={
                    "labels": ", ".join(labels_list),
                    "total_columns": str(total_columns),
                    "relationships": str(rel_count),
                },
            )
        return TestResult(
            name="schema_discovery",
            status=TestStatus.FAIL,
            message="No labels discovered from Neo4j",
        )

    def _discover_schema_via_jdbc(self, spark: SparkSession) -> dict[str, Any]:
        """
        Discover Neo4j schema using JDBC DatabaseMetaData API.

        Uses spark._jvm (Py4J gateway) to access JDBC DatabaseMetaData directly.
        """
        schema: dict[str, Any] = {"labels": {}, "relationships": []}

        jvm = spark._jvm
        gateway = spark._sc._gateway

        # Create JDBC connection
        props = jvm.java.util.Properties()
        props.setProperty("user", self.config.neo4j.user)
        props.setProperty("password", self.config.neo4j.password)

        jdbc_url = self.config.neo4j.jdbc_url_sql
        connection = None

        try:
            connection = jvm.java.sql.DriverManager.getConnection(jdbc_url, props)
            metadata = connection.getMetaData()

            # Store driver info
            schema["driver_info"] = {
                "driver_name": metadata.getDriverName(),
                "driver_version": metadata.getDriverVersion(),
                "database_product": metadata.getDatabaseProductName(),
                "database_version": metadata.getDatabaseProductVersion(),
            }

            # Discover Labels via getTables(TABLE)
            types_array = gateway.new_array(gateway.jvm.java.lang.String, 1)
            types_array[0] = "TABLE"

            rs = metadata.getTables(None, None, None, types_array)
            while rs.next():
                label_name = rs.getString("TABLE_NAME")
                schema["labels"][label_name] = {"columns": [], "primary_key": None}
            rs.close()

            # Discover Columns for each Label
            for label_name in schema["labels"]:
                rs = metadata.getColumns(None, None, label_name, None)
                while rs.next():
                    col_info = {
                        "name": rs.getString("COLUMN_NAME"),
                        "type_name": rs.getString("TYPE_NAME"),
                        "sql_type": rs.getInt("DATA_TYPE"),
                        "nullable": rs.getString("IS_NULLABLE") == "YES",
                        "is_generated": rs.getString("IS_GENERATEDCOLUMN") == "YES",
                    }
                    schema["labels"][label_name]["columns"].append(col_info)
                rs.close()

                # Get primary key
                rs = metadata.getPrimaryKeys(None, None, label_name)
                while rs.next():
                    schema["labels"][label_name]["primary_key"] = rs.getString(
                        "COLUMN_NAME"
                    )
                rs.close()

            # Discover Relationships via getTables(RELATIONSHIP)
            types_array[0] = "RELATIONSHIP"
            rs = metadata.getTables(None, None, None, types_array)
            while rs.next():
                rel_name = rs.getString("TABLE_NAME")
                remarks = rs.getString("REMARKS") or ""
                parts = remarks.split("\n") if remarks else []
                if len(parts) >= 3:
                    schema["relationships"].append(
                        {
                            "from_label": parts[0],
                            "type": parts[1],
                            "to_label": parts[2],
                            "table_name": rel_name,
                        }
                    )
                else:
                    schema["relationships"].append(
                        {
                            "from_label": None,
                            "type": rel_name,
                            "to_label": None,
                            "table_name": rel_name,
                        }
                    )
            rs.close()

        finally:
            if connection:
                connection.close()

        return schema


class SchemaSyncOptionATest(BaseTest):
    """Test Option A: Views with Inferred Schema.

    Creates Unity Catalog views that query through JDBC connection.
    Schema is inferred from JDBC ResultSetMetaData at query time.
    """

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._view_name: str | None = None

    @property
    def name(self) -> str:
        return "Schema Sync Option A (Inferred Schema Views)"

    def run(self) -> list[TestResult]:
        """Run Option A tests."""
        results: list[TestResult] = []
        timeout = self.config.test.timeout_seconds

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

        # Check if schema was discovered
        schema = get_discovered_schema()
        if not schema or not schema.get("labels"):
            results.append(
                TestResult(
                    name="schema_check",
                    status=TestStatus.SKIP,
                    message="No schema discovered - run SchemaDiscoveryTest first",
                )
            )
            return results

        # Get first label for testing
        test_label = list(schema["labels"].keys())[0]
        self._view_name = f"neo4j_view_{test_label.lower()}"

        # Test 1: Create view via DataFrame registration
        results.append(
            _run_test_with_timeout(
                "create_view",
                lambda: self._test_create_view(spark, test_label),
                timeout,
            )
        )

        if results[-1].status != TestStatus.PASS:
            return results

        # Test 2: Query the view
        results.append(
            _run_test_with_timeout(
                "query_view",
                lambda: self._test_query_view(spark),
                timeout,
            )
        )

        # Test 3: Verify schema via DESCRIBE
        results.append(
            _run_test_with_timeout(
                "describe_view",
                lambda: self._test_describe_view(spark),
                timeout,
            )
        )

        return results

    def _test_create_view(
        self, spark: SparkSession, test_label: str
    ) -> TestResult:
        """Create view via DataFrame registration."""
        connection_name = self.config.unity_catalog.connection_name

        df = (
            spark.read.format("jdbc")
            .option("databricks.connection", connection_name)
            .option("dbtable", test_label)
            .load()
        )

        # Register as temp view
        df.createOrReplaceTempView(self._view_name)

        return TestResult(
            name="create_view",
            status=TestStatus.PASS,
            message=f"Created temp view '{self._view_name}' for label '{test_label}'",
            details={
                "view_name": self._view_name,
                "source_label": test_label,
                "column_count": str(len(df.columns)),
            },
        )

    def _test_query_view(self, spark: SparkSession) -> TestResult:
        """Query the created view."""
        df = spark.sql(f"SELECT * FROM {self._view_name} LIMIT 3")
        rows = df.collect()
        row_count = len(rows)

        return TestResult(
            name="query_view",
            status=TestStatus.PASS,
            message=f"View query returned {row_count} rows",
            details={"row_count": str(row_count)},
        )

    def _test_describe_view(self, spark: SparkSession) -> TestResult:
        """Verify schema via DESCRIBE."""
        df = spark.sql(f"DESCRIBE {self._view_name}")
        columns = df.collect()
        col_count = len(columns)
        col_names = [row["col_name"] for row in columns[:5]]

        return TestResult(
            name="describe_view",
            status=TestStatus.PASS,
            message=f"DESCRIBE returned {col_count} columns",
            details={"columns": ", ".join(col_names)},
        )


class SchemaSyncOptionCTest(BaseTest):
    """Test Option C: Hybrid Approach with Schema Registry.

    Creates a schema registry table storing discovered metadata
    plus views for data access.

    Note: Relationship pattern tests are separated to avoid hangs.
    """

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._registry_table = "neo4j_schema_registry"
        self._view_name: str | None = None

    @property
    def name(self) -> str:
        return "Schema Sync Option C (Hybrid with Schema Registry)"

    def run(self) -> list[TestResult]:
        """Run Option C tests."""
        results: list[TestResult] = []
        timeout = self.config.test.timeout_seconds

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

        # Check if schema was discovered
        schema = get_discovered_schema()
        if not schema or not schema.get("labels"):
            results.append(
                TestResult(
                    name="schema_check",
                    status=TestStatus.SKIP,
                    message="No schema discovered - run SchemaDiscoveryTest first",
                )
            )
            return results

        # Get a label for testing (use 3rd if available, else first)
        labels_list = list(schema["labels"].keys())
        test_label = labels_list[2] if len(labels_list) > 2 else labels_list[0]
        self._view_name = f"neo4j_hybrid_{test_label.lower()}"

        # Test 1: Create schema registry table
        results.append(
            _run_test_with_timeout(
                "create_registry",
                lambda: self._test_create_registry(spark, schema),
                timeout,
            )
        )

        if results[-1].status != TestStatus.PASS:
            return results

        # Test 2: Query registry for labels
        results.append(
            _run_test_with_timeout(
                "query_registry_labels",
                lambda: self._test_query_registry_labels(spark),
                timeout,
            )
        )

        # Test 3: Create view for data access
        results.append(
            _run_test_with_timeout(
                "create_hybrid_view",
                lambda: self._test_create_hybrid_view(spark, test_label),
                timeout,
            )
        )

        # Test 4: Query the view
        if results[-1].status == TestStatus.PASS:
            results.append(
                _run_test_with_timeout(
                    "query_hybrid_view",
                    lambda: self._test_query_hybrid_view(spark),
                    timeout,
                )
            )

        return results

    def _test_create_registry(
        self, spark: SparkSession, schema: dict[str, Any]
    ) -> TestResult:
        """Create schema registry table from discovered schema."""
        registry_rows = []
        discovered_at = datetime.now().isoformat()

        # Add label columns
        for label_name, label_info in schema.get("labels", {}).items():
            for col in label_info["columns"]:
                registry_rows.append(
                    {
                        "label_name": label_name,
                        "column_name": col["name"],
                        "column_type": col["type_name"],
                        "is_nullable": col["nullable"],
                        "is_generated": col["is_generated"],
                        "is_primary_key": col["name"]
                        == label_info.get("primary_key"),
                        "discovered_at": discovered_at,
                    }
                )

        # Add relationship patterns (but don't query them - causes hangs)
        for rel in schema.get("relationships", []):
            registry_rows.append(
                {
                    "label_name": f"[REL] {rel['type']}",
                    "column_name": f"({rel.get('from_label', '?')})->({rel.get('to_label', '?')})",
                    "column_type": "RELATIONSHIP",
                    "is_nullable": False,
                    "is_generated": False,
                    "is_primary_key": False,
                    "discovered_at": discovered_at,
                }
            )

        if registry_rows:
            df_registry = spark.createDataFrame(registry_rows)
            df_registry.createOrReplaceTempView(self._registry_table)

            return TestResult(
                name="create_registry",
                status=TestStatus.PASS,
                message=f"Created schema registry with {len(registry_rows)} entries",
                details={
                    "registry_table": self._registry_table,
                    "entry_count": str(len(registry_rows)),
                },
            )
        return TestResult(
            name="create_registry",
            status=TestStatus.FAIL,
            message="No schema data to populate registry",
        )

    def _test_query_registry_labels(self, spark: SparkSession) -> TestResult:
        """Query registry for label columns (NOT relationships - causes hangs)."""
        df = spark.sql(f"""
            SELECT label_name, column_name, column_type, is_primary_key
            FROM {self._registry_table}
            WHERE column_type != 'RELATIONSHIP'
            LIMIT 10
        """)
        rows = df.collect()
        row_count = len(rows)

        labels = set(row["label_name"] for row in rows)

        return TestResult(
            name="query_registry_labels",
            status=TestStatus.PASS,
            message=f"Registry query returned {row_count} column entries",
            details={"labels_sample": ", ".join(list(labels)[:3])},
        )

    def _test_create_hybrid_view(
        self, spark: SparkSession, test_label: str
    ) -> TestResult:
        """Create view for data access."""
        connection_name = self.config.unity_catalog.connection_name

        df = (
            spark.read.format("jdbc")
            .option("databricks.connection", connection_name)
            .option("dbtable", test_label)
            .load()
        )

        df.createOrReplaceTempView(self._view_name)

        return TestResult(
            name="create_hybrid_view",
            status=TestStatus.PASS,
            message=f"Created hybrid view '{self._view_name}'",
            details={
                "view_name": self._view_name,
                "source_label": test_label,
            },
        )

    def _test_query_hybrid_view(self, spark: SparkSession) -> TestResult:
        """Query the hybrid view."""
        df = spark.sql(f"SELECT * FROM {self._view_name} LIMIT 3")
        rows = df.collect()
        row_count = len(rows)

        return TestResult(
            name="query_hybrid_view",
            status=TestStatus.PASS,
            message=f"Hybrid view query returned {row_count} rows",
            details={"row_count": str(row_count)},
        )
