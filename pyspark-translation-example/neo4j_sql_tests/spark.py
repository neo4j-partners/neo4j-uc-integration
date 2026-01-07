"""
Spark session and JDBC utilities.

This module provides functions for creating Spark sessions configured
for Neo4j JDBC connectivity and building JDBC option dictionaries.

The Spark session is configured with:
- Local master for testing
- Neo4j JDBC driver JAR on classpath
- UTC timezone to avoid timestamp issues
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession

from .config import Config


def create_spark_session(config: Config) -> SparkSession:
    """
    Create a SparkSession configured for Neo4j JDBC connectivity.

    The session is configured with:
    - Local master (local[*]) for parallel execution
    - Neo4j JDBC JAR added to Spark's classpath
    - UTC timezone for consistent timestamp handling

    Args:
        config: Configuration object containing JAR path

    Returns:
        Configured SparkSession

    Example:
        config = load_config()
        spark = create_spark_session(config)
        try:
            # Run tests
            ...
        finally:
            spark.stop()
    """
    return (
        SparkSession.builder
        .appName("Neo4j SQL Translation Test")
        .master("local[*]")
        .config("spark.jars", str(config.jar_path.absolute()))
        # Set timezone to avoid timestamp conversion issues
        .config("spark.driver.extraJavaOptions", "-Duser.timezone=UTC")
        .config("spark.executor.extraJavaOptions", "-Duser.timezone=UTC")
        # Reduce log verbosity for cleaner test output
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def get_jdbc_options(config: Config) -> dict:
    """
    Build JDBC connection options dictionary for Spark DataFrame reads.

    These options are passed to spark.read.format("jdbc").options(**opts).

    Args:
        config: Configuration object with connection details

    Returns:
        Dictionary of JDBC options

    Example:
        opts = get_jdbc_options(config)
        df = spark.read.format("jdbc").options(**opts).option("query", sql).load()
    """
    return {
        "url": config.jdbc_url,
        "driver": "org.neo4j.jdbc.Neo4jDriver",
        "user": config.username,
        "password": config.password,
    }


def execute_jdbc_query(
    spark: SparkSession,
    config: Config,
    query: str,
    custom_schema: str | None = None,
) -> DataFrame:
    """
    Execute a SQL query through Neo4j JDBC and return a DataFrame.

    This is a convenience function that handles the boilerplate of
    setting up JDBC options and executing a query.

    Args:
        spark: Active SparkSession
        config: Configuration object
        query: SQL query string to execute
        custom_schema: Optional Spark SQL schema string (e.g., "col1 LONG, col2 STRING")
                      Use this to bypass Spark's schema inference issues.

    Returns:
        DataFrame containing query results

    Raises:
        Exception: If query execution fails

    Example:
        df = execute_jdbc_query(
            spark, config,
            "SELECT COUNT(*) AS cnt FROM Flight",
            custom_schema="cnt LONG"
        )
        df.show()
    """
    opts = get_jdbc_options(config)

    reader = spark.read.format("jdbc").options(**opts).option("query", query)

    # Add custom schema if provided (important for Neo4j to avoid type inference issues)
    if custom_schema:
        reader = reader.option("customSchema", custom_schema)

    return reader.load()


def execute_jdbc_table(
    spark: SparkSession,
    config: Config,
    table_name: str,
) -> DataFrame:
    """
    Read a Neo4j label as a table and return a DataFrame.

    Uses the `dbtable` option which reads a Neo4j label directly.
    This avoids Spark's subquery wrapping that can break native Cypher.

    The schema is inferred from JDBC ResultSetMetaData, which allows
    Spark to discover column names and types from Neo4j properties.

    Args:
        spark: Active SparkSession
        config: Configuration object
        table_name: Neo4j label name to read as table

    Returns:
        DataFrame containing all nodes with the specified label

    Example:
        df = execute_jdbc_table(spark, config, "Aircraft")
        df.printSchema()  # Shows discovered columns
        df.show()
    """
    opts = get_jdbc_options(config)

    return (
        spark.read.format("jdbc")
        .options(**opts)
        .option("dbtable", table_name)
        .load()
    )
