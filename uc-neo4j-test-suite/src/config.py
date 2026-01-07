"""Configuration management using Databricks secrets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Neo4jConfig:
    """Neo4j connection configuration."""

    host: str
    user: str
    password: str
    database: str = "neo4j"

    @property
    def bolt_uri(self) -> str:
        """Bolt protocol URI for Neo4j Python driver."""
        return f"neo4j+s://{self.host}"

    @property
    def jdbc_url(self) -> str:
        """JDBC URL for Neo4j JDBC driver."""
        return f"jdbc:neo4j+s://{self.host}:7687/{self.database}"

    @property
    def jdbc_url_sql(self) -> str:
        """JDBC URL with SQL translation enabled."""
        return f"{self.jdbc_url}?enableSQLTranslation=true"


@dataclass(frozen=True)
class UnityCatalogConfig:
    """Unity Catalog JDBC configuration."""

    jdbc_jar_path: str
    connection_name: str = "neo4j_connection"


# Default schema for Aircraft label (from notebook)
# Use backticks around column names with special characters (like $)
DEFAULT_AIRCRAFT_SCHEMA = (
    "`v$id` STRING, aircraft_id STRING, tail_number STRING, "
    "icao24 STRING, model STRING, operator STRING, manufacturer STRING"
)


@dataclass(frozen=True)
class TestConfig:
    """Test execution configuration."""

    timeout_seconds: int = 30
    test_label: str = "Aircraft"
    test_label_schema: str = DEFAULT_AIRCRAFT_SCHEMA


@dataclass(frozen=True)
class Config:
    """Complete test suite configuration."""

    neo4j: Neo4jConfig
    unity_catalog: UnityCatalogConfig
    test: TestConfig


class ConfigurationError(Exception):
    """Raised when required configuration is missing."""


def get_dbutils():
    """Get dbutils in Databricks environment."""
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.getActiveSession()
        from pyspark.dbutils import DBUtils
        return DBUtils(spark)
    except ImportError:
        # Fallback for older Databricks runtimes
        import IPython
        return IPython.get_ipython().user_ns["dbutils"]


def load_config(
    secret_scope: str = "neo4j-uc-creds",
    jdbc_jar_path: str = "/Volumes/main/default/neo4j/neo4j-jdbc-full-bundle-6.0.0.jar",
    test_label: str = "Aircraft",
    test_label_schema: str = DEFAULT_AIRCRAFT_SCHEMA,
    timeout_seconds: int = 30,
) -> Config:
    """
    Load configuration from Databricks secrets.

    Args:
        secret_scope: Databricks secret scope name.
                      Expected keys: host, user, password, connection_name, database (optional)
        jdbc_jar_path: Path to Neo4j JDBC JAR in Unity Catalog Volume.
        test_label: Neo4j node label to use for test queries.
        test_label_schema: Spark schema for the test label (required for Direct JDBC).
        timeout_seconds: Test timeout in seconds.

    Returns:
        Populated Config instance.
    """
    dbutils = get_dbutils()

    def get_secret(key: str, default: str | None = None) -> str:
        try:
            return dbutils.secrets.get(scope=secret_scope, key=key)
        except Exception as e:
            if default is not None:
                return default
            raise ConfigurationError(
                f"Secret '{key}' not found in scope '{secret_scope}'. "
                f"Create it with: databricks secrets put-secret {secret_scope} {key}"
            ) from e

    neo4j = Neo4jConfig(
        host=get_secret("host"),
        user=get_secret("user"),
        password=get_secret("password"),
        database=get_secret("database", "neo4j"),
    )

    unity_catalog = UnityCatalogConfig(
        jdbc_jar_path=jdbc_jar_path,
        connection_name=get_secret("connection_name"),
    )

    test = TestConfig(
        timeout_seconds=timeout_seconds,
        test_label=test_label,
        test_label_schema=test_label_schema,
    )

    return Config(
        neo4j=neo4j,
        unity_catalog=unity_catalog,
        test=test,
    )
