"""Validate Neo4j connectivity and create the UC JDBC connection.

Prerequisites:
  - run_00_load_graph.py must have run (loads Neo4j graph data)
  - CSV files must be in the UC Volume (run upload_data.sh first)

Sections:
  1. Load Delta sensor_readings table from CSV
  2. Create UC JDBC connection
  3. Query Aircraft and Airport counts via UC JDBC

Usage (via runner):
    uv run python -m cli upload run_01_connect_test.py
    uv run python -m cli submit run_01_connect_test.py
"""

import sys
import time

from data_utils import inject_params, get_config, read_neo4j, ValidationResults


def main():
    inject_params()
    cfg = get_config()

    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()

    results = ValidationResults()

    print("=" * 60)
    print("run_01_connect_test: Neo4j + UC JDBC Validation")
    print("=" * 60)
    print(f"  Neo4j URI:       {cfg['neo4j_uri']}")
    print(f"  UC Connection:   {cfg['uc_connection_name']}")
    print(f"  JDBC JAR:        {cfg['jdbc_jar_path']}")
    print(f"  Volume:          {cfg['volume_path']}")
    print("")

    # ------------------------------------------------------------------
    # Section 1: Load Delta sensor_readings table
    # ------------------------------------------------------------------
    print("--- Section 1: Delta sensor_readings ---")
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {cfg['fqn']}")
        spark.sql(f"CREATE VOLUME IF NOT EXISTS {cfg['fqn']}.`{cfg['uc_volume']}`")

        spark.sql(f"""
            CREATE OR REPLACE TABLE {cfg['fqn']}.sensor_readings AS
            SELECT * EXCEPT (_rescued_data)
            FROM read_files('{cfg['volume_path']}/nodes_readings.csv',
                format => 'csv',
                header => true,
                inferColumnTypes => true)
        """)

        reading_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {cfg['fqn']}.sensor_readings").collect()[0]["cnt"]
        results.record("sensor_readings table", reading_count == 172800, f"{reading_count:,} rows")

    except Exception as e:
        results.record("Delta sensor_readings", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 2: Create UC JDBC connection
    # ------------------------------------------------------------------
    print("\n--- Section 2: UC JDBC Connection ---")
    try:
        spark.sql(f"DROP CONNECTION IF EXISTS {cfg['uc_connection_name']}")

        esc = lambda s: s.replace("'", "\\'")

        create_sql = f"""
            CREATE CONNECTION {cfg['uc_connection_name']} TYPE JDBC
            ENVIRONMENT (
                java_dependencies '{cfg['java_dependencies']}'
            )
            OPTIONS (
                url '{esc(cfg['neo4j_jdbc_url_sql'])}',
                user '{esc(cfg['neo4j_username'])}',
                password '{esc(cfg['neo4j_password'])}',
                driver 'org.neo4j.jdbc.Neo4jDriver',
                externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize,customSchema'
            )
        """
        start = time.time()
        spark.sql(create_sql)
        elapsed = (time.time() - start) * 1000

        df = (
            spark.read.format("jdbc")
            .option("databricks.connection", cfg["uc_connection_name"])
            .option("query", "SELECT 1 AS test")
            .option("customSchema", "test INT")
            .load()
        )
        test_val = df.collect()[0]["test"]

        results.record("UC JDBC connection created", True, f"{elapsed:.0f}ms")
        results.record("UC JDBC SELECT 1", test_val == 1, f"returned {test_val}")

    except Exception as e:
        results.record("UC JDBC connection", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 3: Query Aircraft and Airport counts via UC JDBC
    # ------------------------------------------------------------------
    print("\n--- Section 3: Query via UC JDBC ---")
    try:
        df = read_neo4j(spark, cfg,
            custom_schema="aircraft_count LONG",
            query="SELECT COUNT(*) AS aircraft_count FROM Aircraft",
        )
        aircraft_jdbc_count = df.collect()[0]["aircraft_count"]
        results.record("JDBC count Aircraft", aircraft_jdbc_count == 20, f"{aircraft_jdbc_count} aircraft")

        df = read_neo4j(spark, cfg,
            custom_schema="airport_count LONG",
            query="SELECT COUNT(*) AS airport_count FROM Airport",
        )
        airport_jdbc_count = df.collect()[0]["airport_count"]
        results.record("JDBC count Airport", airport_jdbc_count == 12, f"{airport_jdbc_count} airports")

    except Exception as e:
        results.record("JDBC queries", False, str(e))

    if not results.summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
