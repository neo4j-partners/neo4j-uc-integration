"""Validate Neo4j connectivity and UC JDBC connection setup.

Converts getting-started/01-simple-connect-test.ipynb into a standalone
script for batch execution on a Databricks cluster.

Sections:
  1. Neo4j Python driver connectivity
  2. Create sample test data in Neo4j
  3. Create UC JDBC connection
  4. Query sample data via UC JDBC

Usage:
    ./upload.sh run_01_connect_test.py && ./submit.sh run_01_connect_test.py
"""

import argparse
import sys
import time
from data_utils import add_common_args, derive_config, get_neo4j_driver, read_neo4j, ValidationResults


def main():
    parser = argparse.ArgumentParser(description="Validate Neo4j connectivity and UC JDBC setup")
    add_common_args(parser)
    args, _ = parser.parse_known_args()
    cfg = derive_config(args)

    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()

    results = ValidationResults()

    print("=" * 60)
    print("run_01_connect_test: Neo4j + UC JDBC Validation")
    print("=" * 60)
    print(f"  Neo4j URI:       {cfg['neo4j_uri']}")
    print(f"  UC Connection:   {cfg['uc_connection_name']}")
    print(f"  JDBC JAR:        {cfg['jdbc_jar_path']}")
    print("")

    # ------------------------------------------------------------------
    # Section 1: Neo4j Python driver connectivity
    # ------------------------------------------------------------------
    print("--- Section 1: Neo4j Python Driver ---")
    try:
        start = time.time()
        driver = get_neo4j_driver(cfg)
        driver.verify_connectivity()
        elapsed = (time.time() - start) * 1000

        with driver.session() as session:
            record = session.run("RETURN 1 AS test").single()
            assert record["test"] == 1

        results.record("Python driver connectivity", True, f"{elapsed:.0f}ms")
        driver.close()
    except Exception as e:
        results.record("Python driver connectivity", False, str(e))
        # Cannot continue without Neo4j
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 2: Create sample test data
    # ------------------------------------------------------------------
    print("\n--- Section 2: Create Sample Test Data ---")
    try:
        driver = get_neo4j_driver(cfg)
        with driver.session() as session:
            # Clear existing test data
            session.run("MATCH (n) WHERE n:Company OR n:Product DETACH DELETE n")

            # Create Company nodes
            session.run("""
                CREATE (:Company {companyId: 'C001', name: 'Amazon.com, Inc.', ticker: 'AMZN'})
                CREATE (:Company {companyId: 'C002', name: 'Apple Inc.', ticker: 'AAPL'})
                CREATE (:Company {companyId: 'C003', name: 'Microsoft Corporation', ticker: 'MSFT'})
                CREATE (:Company {companyId: 'C004', name: 'NVIDIA Corporation', ticker: 'NVDA'})
            """)

            # Create Product nodes
            session.run("""
                CREATE (:Product {productId: 'P011', name: 'AWS'})
                CREATE (:Product {productId: 'P018', name: 'Amazon Prime'})
                CREATE (:Product {productId: 'P020', name: 'App Store'})
                CREATE (:Product {productId: 'P030', name: 'Apple Vision Pro'})
                CREATE (:Product {productId: 'P036', name: 'Azure'})
                CREATE (:Product {productId: 'P037', name: 'Azure AI'})
                CREATE (:Product {productId: 'P002', name: 'A100 Integrated Circuit'})
                CREATE (:Product {productId: 'P006', name: 'AI Cloud Services'})
            """)

            # Create OFFERS relationships
            offers = [
                ("C001", "P011"), ("C001", "P018"),
                ("C002", "P020"), ("C002", "P030"),
                ("C003", "P036"), ("C003", "P037"),
                ("C004", "P002"), ("C004", "P006"),
            ]
            for company_id, product_id in offers:
                session.run(
                    "MATCH (c:Company {companyId: $cid}), (p:Product {productId: $pid}) CREATE (c)-[:OFFERS]->(p)",
                    cid=company_id, pid=product_id,
                )

            # Create COMPETES_WITH relationships
            competes = [
                ("C001", "C003"), ("C002", "C003"),
                ("C003", "C001"), ("C003", "C002"),
                ("C004", "C001"), ("C004", "C003"),
            ]
            for src, tgt in competes:
                session.run(
                    "MATCH (a:Company {companyId: $src}), (b:Company {companyId: $tgt}) CREATE (a)-[:COMPETES_WITH]->(b)",
                    src=src, tgt=tgt,
                )

            # Verify counts
            company_count = session.run("MATCH (c:Company) RETURN count(c) AS cnt").single()["cnt"]
            product_count = session.run("MATCH (p:Product) RETURN count(p) AS cnt").single()["cnt"]
            offers_count = session.run("MATCH ()-[r:OFFERS]->() RETURN count(r) AS cnt").single()["cnt"]
            competes_count = session.run("MATCH ()-[r:COMPETES_WITH]->() RETURN count(r) AS cnt").single()["cnt"]

        driver.close()

        results.record("Company nodes created", company_count == 4, f"{company_count} nodes")
        results.record("Product nodes created", product_count == 8, f"{product_count} nodes")
        results.record("OFFERS relationships", offers_count == 8, f"{offers_count} rels")
        results.record("COMPETES_WITH relationships", competes_count == 6, f"{competes_count} rels")

    except Exception as e:
        results.record("Create sample test data", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 3: Create UC JDBC connection
    # ------------------------------------------------------------------
    print("\n--- Section 3: UC JDBC Connection ---")
    try:
        spark.sql(f"DROP CONNECTION IF EXISTS {cfg['uc_connection_name']}")

        create_sql = f"""
            CREATE CONNECTION {cfg['uc_connection_name']} TYPE JDBC
            ENVIRONMENT (
                java_dependencies '{cfg['java_dependencies']}'
            )
            OPTIONS (
                url '{cfg['neo4j_jdbc_url_sql']}',
                user '{cfg['neo4j_username']}',
                password '{cfg['neo4j_password']}',
                driver 'org.neo4j.jdbc.Neo4jDriver',
                externalOptionsAllowList 'dbtable,query,partitionColumn,lowerBound,upperBound,numPartitions,fetchSize,customSchema'
            )
        """
        start = time.time()
        spark.sql(create_sql)
        elapsed = (time.time() - start) * 1000

        # Test with SELECT 1
        df = spark.read.format("jdbc") \
            .option("databricks.connection", cfg["uc_connection_name"]) \
            .option("query", "SELECT 1 AS test") \
            .option("customSchema", "test INT") \
            .load()
        test_val = df.collect()[0]["test"]

        results.record("UC JDBC connection created", True, f"{elapsed:.0f}ms")
        results.record("UC JDBC SELECT 1", test_val == 1, f"returned {test_val}")

    except Exception as e:
        results.record("UC JDBC connection", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 4: Query sample data via UC JDBC
    # ------------------------------------------------------------------
    print("\n--- Section 4: Query via UC JDBC ---")
    try:
        # Count companies (aggregate — uses query option)
        df = read_neo4j(spark, cfg,
            custom_schema="company_count LONG",
            query="SELECT COUNT(*) AS company_count FROM Company",
        )
        company_jdbc_count = df.collect()[0]["company_count"]
        results.record("JDBC count companies", company_jdbc_count == 4, f"{company_jdbc_count} companies")

        # List companies (non-aggregate — uses dbtable option)
        df = read_neo4j(spark, cfg,
            custom_schema="`v$id` STRING, companyId STRING, name STRING, ticker STRING",
            dbtable="Company",
        ).drop("v$id").filter("companyId IS NOT NULL")
        company_rows = df.count()
        results.record("JDBC list companies", company_rows == 4, f"{company_rows} rows")

        # Count products (aggregate)
        df = read_neo4j(spark, cfg,
            custom_schema="product_count LONG",
            query="SELECT COUNT(*) AS product_count FROM Product",
        )
        product_jdbc_count = df.collect()[0]["product_count"]
        results.record("JDBC count products", product_jdbc_count == 8, f"{product_jdbc_count} products")

        # List products (non-aggregate)
        df = read_neo4j(spark, cfg,
            custom_schema="`v$id` STRING, productId STRING, name STRING",
            dbtable="Product",
        ).drop("v$id")
        product_rows = df.count()
        results.record("JDBC list products", product_rows == 8, f"{product_rows} rows")

    except Exception as e:
        results.record("JDBC queries", False, str(e))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if not results.summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
