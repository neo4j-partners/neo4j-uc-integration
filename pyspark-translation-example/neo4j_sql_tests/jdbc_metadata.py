"""
Direct JDBC DatabaseMetaData access using PySpark's JVM gateway.

This module provides functions to access Neo4j JDBC driver's DatabaseMetaData
API directly through PySpark's Py4J gateway, without requiring additional
Python dependencies.

This replicates the functionality of Java's SchemaMetadataTests.java:
    - getTables() - Discover labels (TABLE) and relationships (RELATIONSHIP)
    - getColumns() - Discover properties as columns for a label
    - getPrimaryKeys() - Discover primary key columns
    - Driver info - Get JDBC driver metadata

How it works:
    1. Access Java classes through spark._jvm (Py4J gateway)
    2. Create JDBC connection using java.sql.DriverManager
    3. Call connection.getMetaData() to get DatabaseMetaData
    4. Use standard JDBC metadata methods

The Neo4j JDBC driver exposes graph schema as relational metadata:
    - Labels -> Tables (TABLE type)
    - Relationships -> Virtual Tables (RELATIONSHIP type)
    - Properties -> Columns with SQL types
    - Element IDs -> Primary keys (v$id artificial column)

Reference:
    https://neo4j.com/docs/jdbc-manual/current/
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config


_driver_loaded = False


def _ensure_driver_loaded(spark: SparkSession, config: Config) -> None:
    """
    Ensure the Neo4j JDBC driver is loaded and registered.

    Spark's JDBC connector uses a custom classloader for driver JARs.
    We trigger driver loading by performing a minimal Spark JDBC operation,
    which loads the driver through Spark's mechanism.

    This is necessary when running metadata tests standalone without
    prior DataFrame operations.
    """
    global _driver_loaded
    if _driver_loaded:
        return

    # Import here to avoid circular imports
    from .spark import get_jdbc_options

    try:
        # Perform a minimal query to trigger driver loading
        # This uses Spark's JDBC infrastructure which handles classloading
        opts = get_jdbc_options(config)
        (
            spark.read.format("jdbc")
            .options(**opts)
            .option("query", "SELECT 1")
            .option("customSchema", "result INT")
            .load()
            .take(1)
        )
        _driver_loaded = True
    except Exception:
        # Even if the query fails, the driver should be loaded
        _driver_loaded = True


def get_jdbc_connection(spark: SparkSession, config: Config):
    """
    Create a JDBC connection using Spark's JVM gateway.

    Uses java.sql.DriverManager to create the connection. The Neo4j JDBC
    driver JAR must be on the classpath (configured via spark.jars).

    Args:
        spark: Active SparkSession with JVM gateway
        config: Configuration with JDBC URL and credentials

    Returns:
        java.sql.Connection object (accessed via Py4J)

    Note:
        The returned connection MUST be closed by the caller to avoid
        resource leaks. Use try/finally pattern.
    """
    # Ensure driver is loaded via Spark's JDBC infrastructure
    _ensure_driver_loaded(spark, config)

    jvm = spark._jvm

    # Create Properties object for credentials
    props = jvm.java.util.Properties()
    props.setProperty("user", config.username)
    props.setProperty("password", config.password)

    # Get connection using DriverManager
    return jvm.java.sql.DriverManager.getConnection(config.jdbc_url, props)


def get_driver_info(spark: SparkSession, config: Config) -> dict:
    """
    Get JDBC driver and database information.

    Equivalent Java:
        DatabaseMetaData metaData = connection.getMetaData();
        metaData.getDriverName();
        metaData.getDriverVersion();
        metaData.getDatabaseProductName();
        metaData.getDatabaseProductVersion();

    Args:
        spark: Active SparkSession
        config: Configuration object

    Returns:
        Dictionary with driver_name, driver_version, database_product,
        database_version, catalog_term, schema_term
    """
    connection = get_jdbc_connection(spark, config)
    try:
        metadata = connection.getMetaData()
        return {
            "driver_name": metadata.getDriverName(),
            "driver_version": metadata.getDriverVersion(),
            "database_product": metadata.getDatabaseProductName(),
            "database_version": metadata.getDatabaseProductVersion(),
            "catalog_term": metadata.getCatalogTerm(),
            "schema_term": metadata.getSchemaTerm(),
        }
    finally:
        connection.close()


def get_catalogs(spark: SparkSession, config: Config) -> list[str]:
    """
    Get list of catalogs (Neo4j databases).

    Equivalent Java:
        DatabaseMetaData metaData = connection.getMetaData();
        ResultSet rs = metaData.getCatalogs();

    Neo4j supports multiple databases (e.g., "neo4j", "system").
    Each database appears as a catalog in JDBC terms.

    Args:
        spark: Active SparkSession
        config: Configuration object

    Returns:
        List of catalog (database) names
    """
    connection = get_jdbc_connection(spark, config)
    try:
        metadata = connection.getMetaData()
        rs = metadata.getCatalogs()

        catalogs = []
        while rs.next():
            catalogs.append(rs.getString("TABLE_CAT"))
        rs.close()
        return catalogs
    finally:
        connection.close()


def get_schemas(spark: SparkSession, config: Config) -> list[dict]:
    """
    Get list of schemas.

    Equivalent Java:
        DatabaseMetaData metaData = connection.getMetaData();
        ResultSet rs = metaData.getSchemas();

    Neo4j uses a single "public" schema for all objects.

    Args:
        spark: Active SparkSession
        config: Configuration object

    Returns:
        List of dicts with schema_name and catalog_name
    """
    connection = get_jdbc_connection(spark, config)
    try:
        metadata = connection.getMetaData()
        rs = metadata.getSchemas()

        schemas = []
        while rs.next():
            schemas.append({
                "schema_name": rs.getString("TABLE_SCHEM"),
                "catalog_name": rs.getString("TABLE_CATALOG"),
            })
        rs.close()
        return schemas
    finally:
        connection.close()


def get_tables(
    spark: SparkSession,
    config: Config,
    table_type: str = "TABLE",
) -> list[dict]:
    """
    Get tables using DatabaseMetaData.getTables().

    Equivalent Java:
        DatabaseMetaData metaData = connection.getMetaData();
        ResultSet rs = metaData.getTables(null, null, null, new String[]{"TABLE"});

    The Neo4j JDBC driver maps:
        - Node labels -> TABLE type
        - Relationships -> RELATIONSHIP type (virtual tables)
        - Cypher-backed views -> CBV type

    Relationship table names use format: {Label1}_{RelType}_{Label2}
    The REMARKS column contains the relationship pattern.

    Args:
        spark: Active SparkSession
        config: Configuration object
        table_type: Type filter - "TABLE" for labels, "RELATIONSHIP" for
                    relationship patterns, None for all types

    Returns:
        List of dicts with name, type, and remarks
    """
    connection = get_jdbc_connection(spark, config)
    try:
        metadata = connection.getMetaData()

        # Create Java String array using Py4J gateway
        # This is the proper way to create Java arrays from PySpark
        if table_type:
            gateway = spark._sc._gateway
            types_array = gateway.new_array(gateway.jvm.java.lang.String, 1)
            types_array[0] = table_type
        else:
            types_array = None

        # getTables(catalog, schemaPattern, tableNamePattern, types)
        rs = metadata.getTables(None, None, None, types_array)

        tables = []
        while rs.next():
            tables.append({
                "name": rs.getString("TABLE_NAME"),
                "type": rs.getString("TABLE_TYPE"),
                "remarks": rs.getString("REMARKS"),
            })
        rs.close()
        return tables
    finally:
        connection.close()


def get_columns(
    spark: SparkSession,
    config: Config,
    table_name: str,
) -> list[dict]:
    """
    Get columns for a table using DatabaseMetaData.getColumns().

    Equivalent Java:
        DatabaseMetaData metaData = connection.getMetaData();
        ResultSet rs = metaData.getColumns(null, null, tableName, null);

    The Neo4j JDBC driver maps:
        - Properties -> Columns with appropriate SQL types
        - v$id -> Artificial column for element ID (IS_GENERATEDCOLUMN=YES)

    Type mapping: STRING->VARCHAR, INTEGER->BIGINT, FLOAT->DOUBLE, etc.

    Args:
        spark: Active SparkSession
        config: Configuration object
        table_name: Name of the table (Neo4j label)

    Returns:
        List of dicts with column metadata (name, type_name, data_type,
        nullable, ordinal, is_generated)
    """
    connection = get_jdbc_connection(spark, config)
    try:
        metadata = connection.getMetaData()

        # getColumns(catalog, schemaPattern, tableNamePattern, columnNamePattern)
        rs = metadata.getColumns(None, None, table_name, None)

        columns = []
        while rs.next():
            columns.append({
                "name": rs.getString("COLUMN_NAME"),
                "type_name": rs.getString("TYPE_NAME"),
                "data_type": rs.getInt("DATA_TYPE"),
                "column_size": rs.getInt("COLUMN_SIZE"),
                "nullable": rs.getString("IS_NULLABLE"),
                "ordinal": rs.getInt("ORDINAL_POSITION"),
                "is_generated": rs.getString("IS_GENERATEDCOLUMN"),
            })
        rs.close()
        return columns
    finally:
        connection.close()


def get_primary_keys(
    spark: SparkSession,
    config: Config,
    table_name: str,
) -> list[dict]:
    """
    Get primary keys for a table using DatabaseMetaData.getPrimaryKeys().

    Equivalent Java:
        DatabaseMetaData metaData = connection.getMetaData();
        ResultSet rs = metaData.getPrimaryKeys(null, null, tableName);

    Neo4j JDBC returns:
        - Unique constraint columns if exactly one UNIQUE constraint exists
        - Otherwise, the artificial v$id column (element ID)

    Args:
        spark: Active SparkSession
        config: Configuration object
        table_name: Name of the table (Neo4j label)

    Returns:
        List of dicts with column_name, key_seq, and pk_name
    """
    connection = get_jdbc_connection(spark, config)
    try:
        metadata = connection.getMetaData()

        # getPrimaryKeys(catalog, schema, table)
        rs = metadata.getPrimaryKeys(None, None, table_name)

        keys = []
        while rs.next():
            keys.append({
                "column_name": rs.getString("COLUMN_NAME"),
                "key_seq": rs.getShort("KEY_SEQ"),
                "pk_name": rs.getString("PK_NAME"),
            })
        rs.close()
        return keys
    finally:
        connection.close()


def get_full_schema(
    spark: SparkSession,
    config: Config,
) -> dict[str, list[dict]]:
    """
    Get complete schema for all tables (labels).

    Combines getTables() and getColumns() to build a complete schema map.

    Args:
        spark: Active SparkSession
        config: Configuration object

    Returns:
        Dictionary mapping table names to lists of column metadata
    """
    tables = get_tables(spark, config, table_type="TABLE")

    schema = {}
    for table in tables:
        table_name = table["name"]
        columns = get_columns(spark, config, table_name)
        schema[table_name] = columns

    return schema
