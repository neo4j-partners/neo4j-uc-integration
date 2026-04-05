"""Materialize Neo4j graph data as Delta tables and run SQL validation queries.

Converts getting-started/03-materialized-tables.ipynb into a standalone
script for batch execution on a Databricks cluster.

Sections:
  1. Verify data sources (Delta tables from notebook 02, Neo4j graph via JDBC)
  2. Materialize Neo4j nodes and relationships as Delta tables via UC JDBC
  3. SQL validation tests (GROUP BY, WHERE, aggregations, DISTINCT)
  4. Federated queries on materialized + lakehouse data

Prerequisites:
  - run_01_connect_test.py must have run (creates UC JDBC connection)
  - run_02_federated_queries.py must have run (creates Delta tables and Neo4j graph)

Usage:
    ./upload.sh run_03_materialized_tables.py && ./submit.sh run_03_materialized_tables.py
"""

import argparse
import sys
import time
from data_utils import add_common_args, derive_config, read_neo4j, ValidationResults


def main():
    parser = argparse.ArgumentParser(description="Materialize Neo4j data and run SQL validation")
    add_common_args(parser)
    args, _ = parser.parse_known_args()
    cfg = derive_config(args)

    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()

    results = ValidationResults()
    fqn = cfg["fqn"]

    print("=" * 60)
    print("run_03_materialized_tables: Materialize + SQL Validation")
    print("=" * 60)
    print(f"  Neo4j URI:   {cfg['neo4j_uri']}")
    print(f"  Schema:      {fqn}")
    print("")

    # ------------------------------------------------------------------
    # Section 1: Verify data sources
    # ------------------------------------------------------------------
    print("--- Section 1: Verify Data Sources ---")
    try:
        # Verify Delta tables from notebook 02
        delta_tables = {
            "companies": 6,
            "financial_metrics": 90,
            "asset_managers": 15,
            "asset_manager_holdings": 72,
        }
        for table_name, expected in delta_tables.items():
            count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {fqn}.{table_name}").collect()[0]["cnt"]
            results.record(f"Delta: {table_name}", count == expected, f"{count} rows (expected {expected})")

        # Verify Neo4j graph via UC JDBC
        neo4j_labels = {
            "Company": 0,   # variable due to external competitors; just check > 0
            "Product": 30,
            "RiskFactor": 48,
        }
        for label, expected in neo4j_labels.items():
            df = read_neo4j(spark, cfg,
                custom_schema="cnt LONG",
                query=f"SELECT COUNT(*) AS cnt FROM {label}",
            )
            count = df.collect()[0]["cnt"]
            if expected == 0:
                results.record(f"Neo4j JDBC: {label}", count > 0, f"{count} nodes")
            else:
                results.record(f"Neo4j JDBC: {label}", count == expected, f"{count} nodes (expected {expected})")

    except Exception as e:
        results.record("Verify data sources", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 2: Materialize Neo4j graph data via UC JDBC
    # ------------------------------------------------------------------
    # Uses GROUP BY aggregate queries via UC JDBC for nodes (avoids both
    # dbtable NullType errors and direct JDBC schema resolution errors).
    # COMPETES_WITH uses the Neo4j Python driver since the SQL-to-Cypher
    # translator cannot handle same-label joins.
    print("\n--- Section 2: Materialize Neo4j Data ---")

    from pyspark.sql.types import StringType, StructType, StructField

    def materialize_table(table_name, df, description, expected=None):
        """Write a DataFrame as a Delta table with STRING casting for JDBC CHAR(0) fix."""
        table_fqn = f"{fqn}.{table_name}"

        t0 = time.time()
        # Cast all columns to STRING to avoid JDBC CHAR(0) Delta write errors
        for c in df.columns:
            df = df.withColumn(c, df[c].cast(StringType()))
        df.write.format("delta").mode("overwrite").saveAsTable(table_fqn)
        ms = (time.time() - t0) * 1000

        cnt = spark.sql(f"SELECT COUNT(*) AS cnt FROM {table_fqn}").collect()[0]["cnt"]
        if expected:
            results.record(f"Materialized: {table_name}", cnt == expected,
                          f"{cnt} rows ({description}), {ms:.0f}ms")
        else:
            results.record(f"Materialized: {table_name}", cnt > 0,
                          f"{cnt} rows ({description}), {ms:.0f}ms")

    # --- Node tables (Neo4j Python driver + createDataFrame) ---
    # Single-table GROUP BY queries fail with JDBC_EXTERNAL_ENGINE_SYNTAX_ERROR
    # during Spark schema resolution. Use the Python driver like COMPETES_WITH.
    # Company filters by companyId IS NOT NULL to exclude external competitor nodes.
    from data_utils import get_neo4j_driver

    try:
        driver = get_neo4j_driver(cfg)
        with driver.session() as session:
            records = session.run(
                "MATCH (c:Company) WHERE c.companyId IS NOT NULL "
                "RETURN c.companyId AS companyId, c.name AS name, c.ticker AS ticker"
            )
            rows = [(r["companyId"], r["name"], r["ticker"]) for r in records]
        driver.close()

        schema = StructType([
            StructField("companyId", StringType()),
            StructField("name", StringType()),
            StructField("ticker", StringType()),
        ])
        df = spark.createDataFrame(rows, schema)
        materialize_table("neo4j_companies", df, "Company nodes (tracked)")
    except Exception as e:
        results.record("Materialized: neo4j_companies", False, str(e)[:200])

    try:
        driver = get_neo4j_driver(cfg)
        with driver.session() as session:
            records = session.run("MATCH (p:Product) RETURN p.productId AS productId, p.name AS name")
            rows = [(r["productId"], r["name"]) for r in records]
        driver.close()

        schema = StructType([
            StructField("productId", StringType()),
            StructField("name", StringType()),
        ])
        df = spark.createDataFrame(rows, schema)
        materialize_table("neo4j_products", df, "Product nodes")
    except Exception as e:
        results.record("Materialized: neo4j_products", False, str(e)[:200])

    try:
        driver = get_neo4j_driver(cfg)
        with driver.session() as session:
            records = session.run("MATCH (r:RiskFactor) RETURN r.riskId AS riskId, r.name AS name")
            rows = [(r["riskId"], r["name"]) for r in records]
        driver.close()

        schema = StructType([
            StructField("riskId", StringType()),
            StructField("name", StringType()),
        ])
        df = spark.createDataFrame(rows, schema)
        materialize_table("neo4j_risk_factors", df, "RiskFactor nodes")
    except Exception as e:
        results.record("Materialized: neo4j_risk_factors", False, str(e)[:200])

    # --- Relationship tables (NATURAL JOIN + GROUP BY via UC JDBC) ---
    # The connector only supports aggregate SELECT through the query path,
    # so we GROUP BY all columns with COUNT(*) to get the relationship pairs.
    try:
        df = read_neo4j(spark, cfg,
            custom_schema="companyId STRING, companyName STRING, productId STRING, productName STRING, cnt LONG",
            query="""SELECT c.companyId AS companyId, c.name AS companyName,
                            p.productId AS productId, p.name AS productName, COUNT(*) AS cnt
                     FROM Company c NATURAL JOIN OFFERS r NATURAL JOIN Product p
                     GROUP BY c.companyId, c.name, p.productId, p.name""",
        ).select("companyId", "companyName", "productId", "productName")
        materialize_table("neo4j_company_products", df, "Company-[:OFFERS]->Product", expected=30)
    except Exception as e:
        results.record("Materialized: neo4j_company_products", False, str(e)[:200])

    # COMPETES_WITH: same label on both sides is not supported by the SQL-to-Cypher
    # translator. Use Neo4j Python driver + spark.createDataFrame instead.
    try:
        driver = get_neo4j_driver(cfg)
        with driver.session() as session:
            records = session.run(
                "MATCH (c:Company)-[:COMPETES_WITH]->(comp:Company) "
                "WHERE c.companyId IS NOT NULL "
                "RETURN c.companyId AS companyId, c.name AS companyName, "
                "comp.name AS competitorName, comp.companyId AS competitorId"
            )
            rows = [(r["companyId"], r["companyName"], r["competitorName"], r["competitorId"]) for r in records]
        driver.close()

        schema = StructType([
            StructField("companyId", StringType()),
            StructField("companyName", StringType()),
            StructField("competitorName", StringType()),
            StructField("competitorId", StringType()),
        ])
        df = spark.createDataFrame(rows, schema)
        materialize_table("neo4j_competitors", df, "Company-[:COMPETES_WITH]->Company", expected=78)
    except Exception as e:
        results.record("Materialized: neo4j_competitors", False, str(e)[:200])

    try:
        df = read_neo4j(spark, cfg,
            custom_schema="companyId STRING, companyName STRING, riskId STRING, riskName STRING, cnt LONG",
            query="""SELECT c.companyId AS companyId, c.name AS companyName,
                            rf.riskId AS riskId, rf.name AS riskName, COUNT(*) AS cnt
                     FROM Company c NATURAL JOIN HAS_RISK rel NATURAL JOIN RiskFactor rf
                     GROUP BY c.companyId, c.name, rf.riskId, rf.name""",
        ).select("companyId", "companyName", "riskId", "riskName")
        materialize_table("neo4j_company_risks", df, "Company-[:HAS_RISK]->RiskFactor", expected=48)
    except Exception as e:
        results.record("Materialized: neo4j_company_risks", False, str(e)[:200])

    # ------------------------------------------------------------------
    # Section 3: SQL Validation Tests
    # ------------------------------------------------------------------
    print("\n--- Section 3: SQL Validation Tests ---")

    # TEST 1: GROUP BY — Products per company
    print("\n  TEST 1: GROUP BY — Products per company")
    try:
        df = spark.sql(f"""
            SELECT companyName, COUNT(*) AS product_count
            FROM {fqn}.neo4j_company_products
            GROUP BY companyName
            ORDER BY product_count DESC
        """)
        df.show(truncate=False)
        row_count = df.count()
        results.record("SQL: GROUP BY", row_count == 6, f"{row_count} companies")
    except Exception as e:
        results.record("SQL: GROUP BY", False, str(e))

    # TEST 2: WHERE + ORDER BY — Microsoft risk factors
    print("\n  TEST 2: WHERE + ORDER BY — Microsoft risk factors")
    try:
        df = spark.sql(f"""
            SELECT riskId, riskName
            FROM {fqn}.neo4j_company_risks
            WHERE companyName = 'Microsoft Corporation'
            ORDER BY riskName
        """)
        df.show(truncate=False)
        row_count = df.count()
        results.record("SQL: WHERE + ORDER BY", row_count == 8, f"{row_count} risk factors")
    except Exception as e:
        results.record("SQL: WHERE + ORDER BY", False, str(e))

    # TEST 3: Aggregations — Risk + competitor counts per company
    print("\n  TEST 3: Aggregations — Risk + competitor counts")
    try:
        df = spark.sql(f"""
            SELECT
                r.companyName,
                COUNT(DISTINCT r.riskId) AS risk_count,
                c.competitor_count
            FROM {fqn}.neo4j_company_risks r
            JOIN (
                SELECT companyId, COUNT(*) AS competitor_count
                FROM {fqn}.neo4j_competitors
                GROUP BY companyId
            ) c ON r.companyId = c.companyId
            GROUP BY r.companyName, c.competitor_count
            ORDER BY risk_count DESC
        """)
        df.show(truncate=False)
        row_count = df.count()
        results.record("SQL: Aggregations + JOIN", row_count == 6, f"{row_count} companies")
    except Exception as e:
        results.record("SQL: Aggregations + JOIN", False, str(e))

    # TEST 4: DISTINCT — Unique external competitors
    print("\n  TEST 4: DISTINCT — Unique external competitors")
    try:
        df = spark.sql(f"""
            SELECT DISTINCT competitorName
            FROM {fqn}.neo4j_competitors
            WHERE competitorId IS NULL
            ORDER BY competitorName
        """)
        count = df.count()
        results.record("SQL: DISTINCT", count > 0, f"{count} unique external competitors")
    except Exception as e:
        results.record("SQL: DISTINCT", False, str(e))

    # ------------------------------------------------------------------
    # Section 4: Federated Queries on Materialized Data
    # ------------------------------------------------------------------
    print("\n--- Section 4: Federated Queries ---")

    # Federated Query 1: Company Overview Dashboard
    print("\n  Federated Query 1: Company Overview Dashboard")
    try:
        df = spark.sql(f"""
            SELECT
                c.name AS company,
                c.ticker,
                p.product_count,
                comp.competitor_count,
                r.risk_count,
                fm.metric_count
            FROM {fqn}.companies c
            LEFT JOIN (
                SELECT companyId, COUNT(*) AS product_count
                FROM {fqn}.neo4j_company_products
                GROUP BY companyId
            ) p ON c.companyId = p.companyId
            LEFT JOIN (
                SELECT companyId, COUNT(*) AS competitor_count
                FROM {fqn}.neo4j_competitors
                GROUP BY companyId
            ) comp ON c.companyId = comp.companyId
            LEFT JOIN (
                SELECT companyId, COUNT(*) AS risk_count
                FROM {fqn}.neo4j_company_risks
                GROUP BY companyId
            ) r ON c.companyId = r.companyId
            LEFT JOIN (
                SELECT companyId, COUNT(*) AS metric_count
                FROM {fqn}.financial_metrics
                GROUP BY companyId
            ) fm ON c.companyId = fm.companyId
            ORDER BY c.companyId
        """)
        df.show(truncate=False)
        row_count = df.count()
        has_products = df.filter("product_count IS NOT NULL").count()
        results.record("Federated Q1: company overview", row_count == 6 and has_products == 6,
                       f"{row_count} rows")
    except Exception as e:
        results.record("Federated Q1: company overview", False, str(e))

    # Federated Query 2: Competitor Exposure Analysis
    print("\n  Federated Query 2: Competitor Exposure Analysis")
    try:
        df = spark.sql(f"""
            SELECT
                am.name AS asset_manager,
                comp.competitorName AS nvidia_competitor,
                h.shares AS shares_held
            FROM {fqn}.neo4j_competitors comp
            JOIN {fqn}.asset_manager_holdings h
                ON comp.competitorId = h.companyId
            JOIN {fqn}.asset_managers am
                ON h.managerId = am.managerId
            WHERE comp.companyId = 'C004'
              AND comp.competitorId IS NOT NULL
            ORDER BY comp.competitorName, h.shares DESC
        """)
        df.show(10, truncate=False)
        row_count = df.count()
        results.record("Federated Q2: competitor exposure", row_count > 0,
                       f"{row_count} rows")
    except Exception as e:
        results.record("Federated Q2: competitor exposure", False, str(e))

    # Federated Query 3: Risk-Weighted Investment View
    print("\n  Federated Query 3: Risk-Weighted Investment View")
    try:
        df = spark.sql(f"""
            SELECT
                am.name AS asset_manager,
                COUNT(DISTINCT h.companyId) AS companies_held,
                SUM(h.shares) AS total_shares,
                SUM(r.risk_count) AS total_risk_factors
            FROM {fqn}.asset_manager_holdings h
            JOIN {fqn}.asset_managers am ON h.managerId = am.managerId
            LEFT JOIN (
                SELECT companyId, COUNT(*) AS risk_count
                FROM {fqn}.neo4j_company_risks
                GROUP BY companyId
            ) r ON h.companyId = r.companyId
            GROUP BY am.name
            ORDER BY total_risk_factors DESC
        """)
        df.show(truncate=False)
        row_count = df.count()
        results.record("Federated Q3: risk-weighted view", row_count > 0,
                       f"{row_count} asset managers")
    except Exception as e:
        results.record("Federated Q3: risk-weighted view", False, str(e))

    # Federated Query 4: Product Portfolio + Financial Metrics
    print("\n  Federated Query 4: Product Portfolio + Financial Metrics")
    try:
        df = spark.sql(f"""
            WITH product_summary AS (
                SELECT companyId, CONCAT_WS(', ', COLLECT_LIST(productName)) AS products
                FROM {fqn}.neo4j_company_products
                GROUP BY companyId
            ),
            metric_sample AS (
                SELECT companyId,
                       FIRST(name) AS sample_metric,
                       FIRST(value) AS sample_value,
                       FIRST(period) AS sample_period
                FROM {fqn}.financial_metrics
                GROUP BY companyId
            )
            SELECT
                c.name AS company,
                c.ticker,
                p.products,
                m.sample_metric,
                m.sample_value,
                m.sample_period
            FROM {fqn}.companies c
            JOIN product_summary p ON c.companyId = p.companyId
            JOIN metric_sample m ON c.companyId = m.companyId
            ORDER BY c.companyId
        """)
        df.show(truncate=False)
        row_count = df.count()
        results.record("Federated Q4: product+financial", row_count == 6,
                       f"{row_count} rows")
    except Exception as e:
        results.record("Federated Q4: product+financial", False, str(e))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if not results.summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
