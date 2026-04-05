"""Load data into both systems and run federated queries.

Converts getting-started/02-federated-queries.ipynb into a standalone
script for batch execution on a Databricks cluster.

Sections:
  1. Create schema, volume, and Delta tables from CSV
  2. Load graph data into Neo4j (companies, products, competitors, risk factors)
  3. Run three federated queries joining Neo4j (via UC JDBC) with Delta tables

Prerequisites:
  - run_01_connect_test.py must have run first (creates UC JDBC connection)
  - CSV files must be in getting-started/data/ on the workspace

Usage:
    ./upload.sh run_02_federated_queries.py && ./submit.sh run_02_federated_queries.py
"""

import argparse
import os
import sys
from data_utils import add_common_args, derive_config, get_neo4j_driver, read_neo4j, ValidationResults


def main():
    parser = argparse.ArgumentParser(description="Load data and run federated queries")
    add_common_args(parser)
    args, _ = parser.parse_known_args()
    cfg = derive_config(args)

    from pyspark.sql import SparkSession
    from pyspark.sql.functions import col
    spark = SparkSession.builder.getOrCreate()

    results = ValidationResults()
    fqn = cfg["fqn"]

    print("=" * 60)
    print("run_02_federated_queries: Data Load + Federated Queries")
    print("=" * 60)
    print(f"  Neo4j URI:   {cfg['neo4j_uri']}")
    print(f"  Schema:      {fqn}")
    print(f"  Volume:      {cfg['volume_path']}")
    print("")

    # ------------------------------------------------------------------
    # Section 1: Create schema, volume, and Delta tables
    # ------------------------------------------------------------------
    print("--- Section 1: Delta Lakehouse Setup ---")
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {fqn}")
        spark.sql(f"CREATE VOLUME IF NOT EXISTS {fqn}.{cfg['uc_volume']}")
        print(f"  Schema: {fqn}")
        print(f"  Volume: {cfg['volume_path']}")

        # Verify CSV files are in the UC Volume (uploaded by upload.sh --all)
        data_files = [
            "companies.csv",
            "financial_metrics.csv",
            "asset_managers.csv",
            "asset_manager_holdings.csv",
        ]
        missing = [f for f in data_files if not os.path.exists(os.path.join(cfg["volume_path"], f))]
        if missing:
            raise FileNotFoundError(
                f"CSV files missing from {cfg['volume_path']}: {', '.join(missing)}. "
                f"Run: ./upload.sh --all"
            )
        print(f"  CSV files verified in {cfg['volume_path']}")

        # Create Delta tables from CSV files
        tables = {
            "companies": "companies.csv",
            "financial_metrics": "financial_metrics.csv",
            "asset_managers": "asset_managers.csv",
            "asset_manager_holdings": "asset_manager_holdings.csv",
        }

        for table_name, csv_file in tables.items():
            table_fqn = f"{fqn}.{table_name}"
            spark.sql(f"""
                CREATE OR REPLACE TABLE {table_fqn} AS
                SELECT * EXCEPT (_rescued_data)
                FROM read_files('{cfg['volume_path']}/{csv_file}',
                    format => 'csv',
                    header => true,
                    inferColumnTypes => true)
            """)
            count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {table_fqn}").collect()[0]["cnt"]
            print(f"  {table_fqn}: {count} rows")

        results.record("Delta tables created", True, f"{len(tables)} tables")

        # Verify expected row counts
        companies_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {fqn}.companies").collect()[0]["cnt"]
        metrics_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {fqn}.financial_metrics").collect()[0]["cnt"]
        managers_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {fqn}.asset_managers").collect()[0]["cnt"]
        holdings_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {fqn}.asset_manager_holdings").collect()[0]["cnt"]

        results.record("companies table", companies_count == 6, f"{companies_count} rows")
        results.record("financial_metrics table", metrics_count == 90, f"{metrics_count} rows")
        results.record("asset_managers table", managers_count == 15, f"{managers_count} rows")
        results.record("asset_manager_holdings table", holdings_count == 72, f"{holdings_count} rows")

    except Exception as e:
        results.record("Delta lakehouse setup", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 2: Load graph data into Neo4j
    # ------------------------------------------------------------------
    print("\n--- Section 2: Load Graph Data into Neo4j ---")
    try:
        driver = get_neo4j_driver(cfg)
        with driver.session() as session:
            # Clear existing data
            session.run("MATCH (n) WHERE n:Company OR n:Product OR n:RiskFactor DETACH DELETE n")

            # Company nodes
            companies = [
                {"companyId": "C001", "name": "Amazon.com, Inc.", "ticker": "AMZN"},
                {"companyId": "C002", "name": "Apple Inc.", "ticker": "AAPL"},
                {"companyId": "C003", "name": "Microsoft Corporation", "ticker": "MSFT"},
                {"companyId": "C004", "name": "NVIDIA Corporation", "ticker": "NVDA"},
                {"companyId": "C005", "name": "PG&E Corporation", "ticker": "PCG"},
                {"companyId": "C006", "name": "PayPal Holdings, Inc.", "ticker": "PYPL"},
            ]
            session.run(
                "UNWIND $companies AS c CREATE (:Company {companyId: c.companyId, name: c.name, ticker: c.ticker})",
                companies=companies,
            )
            print(f"  Created {len(companies)} Company nodes")

            # Product nodes + OFFERS relationships
            products = [
                {"productId": "P001", "name": "A-to-z Guarantee", "companyId": "C001"},
                {"productId": "P011", "name": "AWS", "companyId": "C001"},
                {"productId": "P018", "name": "Amazon Prime", "companyId": "C001"},
                {"productId": "P019", "name": "Amazon Stores", "companyId": "C001"},
                {"productId": "P045", "name": "Blink", "companyId": "C001"},
                {"productId": "P015", "name": "AirPods", "companyId": "C002"},
                {"productId": "P020", "name": "App Store", "companyId": "C002"},
                {"productId": "P021", "name": "Apple Arcade", "companyId": "C002"},
                {"productId": "P022", "name": "Apple Card", "companyId": "C002"},
                {"productId": "P030", "name": "Apple Vision Pro", "companyId": "C002"},
                {"productId": "P009", "name": "AI Services", "companyId": "C003"},
                {"productId": "P010", "name": "AI-powered Productivity Services", "companyId": "C003"},
                {"productId": "P036", "name": "Azure", "companyId": "C003"},
                {"productId": "P037", "name": "Azure AI", "companyId": "C003"},
                {"productId": "P038", "name": "Azure AI Platform", "companyId": "C003"},
                {"productId": "P002", "name": "A100 Integrated Circuit", "companyId": "C004"},
                {"productId": "P003", "name": "A100X", "companyId": "C004"},
                {"productId": "P004", "name": "A800", "companyId": "C004"},
                {"productId": "P005", "name": "AGX", "companyId": "C004"},
                {"productId": "P006", "name": "AI Cloud Services", "companyId": "C004"},
                {"productId": "P050", "name": "Bundled Customer Electricity Supply", "companyId": "C005"},
                {"productId": "P051", "name": "Bundled Electric Service", "companyId": "C005"},
                {"productId": "P052", "name": "Bundled Gas Sales", "companyId": "C005"},
                {"productId": "P082", "name": "Diablo Canyon Nuclear Power Plant", "companyId": "C005"},
                {"productId": "P083", "name": "Diablo Canyon Unit 1", "companyId": "C005"},
                {"productId": "P046", "name": "Braintree", "companyId": "C006"},
                {"productId": "P047", "name": "Braintree (Unbranded Card Processing)", "companyId": "C006"},
                {"productId": "P048", "name": "Branded Credit Card", "companyId": "C006"},
                {"productId": "P049", "name": "Branded Debit Card", "companyId": "C006"},
                {"productId": "P053", "name": "Buy Now, Pay Later", "companyId": "C006"},
            ]
            session.run("""
                UNWIND $products AS p
                CREATE (prod:Product {productId: p.productId, name: p.name})
                WITH prod, p
                MATCH (c:Company {companyId: p.companyId})
                CREATE (c)-[:OFFERS]->(prod)
            """, products=products)
            print(f"  Created {len(products)} Product nodes with OFFERS relationships")

            # Competitor relationships (internal + external targets)
            competitors = [
                {"source": "C001", "targetId": None, "targetName": "Alibaba Group"},
                {"source": "C001", "targetId": None, "targetName": "Alphabet"},
                {"source": "C001", "targetId": "C003", "targetName": "Microsoft Corporation"},
                {"source": "C001", "targetId": None, "targetName": "Shopify Inc."},
                {"source": "C001", "targetId": None, "targetName": "Walmart Inc."},
                {"source": "C002", "targetId": None, "targetName": "Google"},
                {"source": "C002", "targetId": "C003", "targetName": "Microsoft Corporation"},
                {"source": "C002", "targetId": None, "targetName": "Nintendo"},
                {"source": "C002", "targetId": None, "targetName": "Samsung Electronics Co. Ltd"},
                {"source": "C002", "targetId": None, "targetName": "Sony"},
                {"source": "C003", "targetId": None, "targetName": "Adobe"},
                {"source": "C003", "targetId": "C001", "targetName": "Amazon.com, Inc."},
                {"source": "C003", "targetId": "C002", "targetName": "Apple Inc."},
                {"source": "C003", "targetId": None, "targetName": "BMC"},
                {"source": "C003", "targetId": None, "targetName": "CA Technologies"},
                {"source": "C003", "targetId": None, "targetName": "Cisco Systems, Inc."},
                {"source": "C003", "targetId": None, "targetName": "Dell"},
                {"source": "C003", "targetId": None, "targetName": "Google"},
                {"source": "C003", "targetId": None, "targetName": "Hewlett-Packard"},
                {"source": "C003", "targetId": None, "targetName": "IBM"},
                {"source": "C003", "targetId": None, "targetName": "Intel Security Group"},
                {"source": "C003", "targetId": None, "targetName": "Lenovo"},
                {"source": "C003", "targetId": None, "targetName": "McAfee, LLC"},
                {"source": "C003", "targetId": None, "targetName": "Meta"},
                {"source": "C003", "targetId": None, "targetName": "Netflix, Inc."},
                {"source": "C003", "targetId": None, "targetName": "Nintendo"},
                {"source": "C003", "targetId": None, "targetName": "Nokia"},
                {"source": "C003", "targetId": None, "targetName": "Okta"},
                {"source": "C003", "targetId": None, "targetName": "OpenAI"},
                {"source": "C003", "targetId": None, "targetName": "Oracle"},
                {"source": "C003", "targetId": None, "targetName": "Proofpoint"},
                {"source": "C003", "targetId": None, "targetName": "Red Hat"},
                {"source": "C003", "targetId": None, "targetName": "SAP"},
                {"source": "C003", "targetId": None, "targetName": "Salesforce"},
                {"source": "C003", "targetId": None, "targetName": "Slack"},
                {"source": "C003", "targetId": None, "targetName": "Snowflake"},
                {"source": "C003", "targetId": None, "targetName": "Sony"},
                {"source": "C003", "targetId": None, "targetName": "Symantec"},
                {"source": "C003", "targetId": None, "targetName": "Tencent"},
                {"source": "C003", "targetId": None, "targetName": "VMware"},
                {"source": "C003", "targetId": None, "targetName": "Yahoo"},
                {"source": "C003", "targetId": None, "targetName": "Zoom"},
                {"source": "C004", "targetId": None, "targetName": "Advanced Micro Devices, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Advantest America Inc."},
                {"source": "C004", "targetId": None, "targetName": "Alibaba Group"},
                {"source": "C004", "targetId": None, "targetName": "Alphabet"},
                {"source": "C004", "targetId": "C001", "targetName": "Amazon.com, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Ambarella, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Arista Networks"},
                {"source": "C004", "targetId": None, "targetName": "Arm"},
                {"source": "C004", "targetId": None, "targetName": "BYD Auto"},
                {"source": "C004", "targetId": None, "targetName": "Baidu, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Broadcom Inc."},
                {"source": "C004", "targetId": None, "targetName": "Cisco Systems, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Hewlett Packard Enterprise Company"},
                {"source": "C004", "targetId": None, "targetName": "Hewlett-Packard"},
                {"source": "C004", "targetId": None, "targetName": "Intel Corporation"},
                {"source": "C004", "targetId": None, "targetName": "Juniper Networks, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Marvell Technology Group"},
                {"source": "C004", "targetId": None, "targetName": "Micron Technology"},
                {"source": "C004", "targetId": "C003", "targetName": "Microsoft Corporation"},
                {"source": "C004", "targetId": None, "targetName": "Qualcomm Incorporated"},
                {"source": "C004", "targetId": None, "targetName": "Quantum Corp."},
                {"source": "C004", "targetId": None, "targetName": "Renesas Electronics Corporation"},
                {"source": "C004", "targetId": None, "targetName": "SK Hynix"},
                {"source": "C004", "targetId": None, "targetName": "Samsung Electronics Co. Ltd"},
                {"source": "C004", "targetId": None, "targetName": "SoftBank Group Corp."},
                {"source": "C004", "targetId": None, "targetName": "Tesla, Inc."},
                {"source": "C004", "targetId": None, "targetName": "Texas Instruments Incorporated"},
                {"source": "C005", "targetId": None, "targetName": "CAISO"},
                {"source": "C005", "targetId": None, "targetName": "Pacific Power"},
                {"source": "C005", "targetId": None, "targetName": "San Diego Gas & Electric Company"},
                {"source": "C005", "targetId": None, "targetName": "Sempra Energy"},
                {"source": "C005", "targetId": None, "targetName": "Southern California Edison"},
                {"source": "C006", "targetId": None, "targetName": "Adyen N.V."},
                {"source": "C006", "targetId": None, "targetName": "Block, Inc."},
                {"source": "C006", "targetId": None, "targetName": "Stripe Inc."},
                {"source": "C006", "targetId": None, "targetName": "eBay"},
            ]
            session.run("""
                UNWIND $competitors AS comp
                MATCH (source:Company {companyId: comp.source})
                CALL (source, comp) {
                    WITH source, comp
                    WHERE comp.targetId IS NOT NULL
                    MATCH (target:Company {companyId: comp.targetId})
                    CREATE (source)-[:COMPETES_WITH]->(target)
                    UNION
                    WITH source, comp
                    WHERE comp.targetId IS NULL
                    MERGE (target:Company {name: comp.targetName})
                    CREATE (source)-[:COMPETES_WITH]->(target)
                }
            """, competitors=competitors)
            print(f"  Created {len(competitors)} COMPETES_WITH relationships")

            # Risk Factor nodes + HAS_RISK relationships
            risk_factors = [
                {"riskId": "R006", "name": "A-to-z Guarantee Cost Risk", "companyId": "C001"},
                {"riskId": "R016", "name": "AWS Revenue Growth Impact", "companyId": "C001"},
                {"riskId": "R023", "name": "Acquisition and Investment Risk", "companyId": "C001"},
                {"riskId": "R024", "name": "Acquisition and Merger Risks", "companyId": "C001"},
                {"riskId": "R026", "name": "Additional Tax Liabilities and Collection Obligations", "companyId": "C001"},
                {"riskId": "R051", "name": "COVID-19 Pandemic Uncertainty", "companyId": "C001"},
                {"riskId": "R080", "name": "Claims, Litigation, and Government Investigations", "companyId": "C001"},
                {"riskId": "R094", "name": "Commercial Agreements and Strategic Alliances Risk", "companyId": "C001"},
                {"riskId": "R036", "name": "Antitrust Investigation Risk", "companyId": "C002"},
                {"riskId": "R037", "name": "App Store Regulatory Risk", "companyId": "C002"},
                {"riskId": "R043", "name": "Business Interruption", "companyId": "C002"},
                {"riskId": "R064", "name": "Carrier and Reseller Dependency Risk", "companyId": "C002"},
                {"riskId": "R118", "name": "Component Availability Risk", "companyId": "C002"},
                {"riskId": "R119", "name": "Component Shortage", "companyId": "C002"},
                {"riskId": "R121", "name": "Component Supply and Pricing Risk", "companyId": "C002"},
                {"riskId": "R140", "name": "Credit Risk", "companyId": "C002"},
                {"riskId": "R008", "name": "AI Data Usage Regulatory Risk", "companyId": "C003"},
                {"riskId": "R009", "name": "AI Development and Use Risk", "companyId": "C003"},
                {"riskId": "R011", "name": "AI Harm and Liability", "companyId": "C003"},
                {"riskId": "R012", "name": "AI Market Competition", "companyId": "C003"},
                {"riskId": "R013", "name": "AI Regulation Risk", "companyId": "C003"},
                {"riskId": "R015", "name": "AI Regulatory and Legal Liability", "companyId": "C003"},
                {"riskId": "R017", "name": "Abuse of Platforms", "companyId": "C003"},
                {"riskId": "R025", "name": "Acquisitions and Strategic Alliances Risk", "companyId": "C003"},
                {"riskId": "R007", "name": "AI Cloud Services Risk", "companyId": "C004"},
                {"riskId": "R010", "name": "AI Ethics and Regulation Risk", "companyId": "C004"},
                {"riskId": "R013b", "name": "AI Regulation Risk", "companyId": "C004"},
                {"riskId": "R014", "name": "AI Regulatory Restriction Risk", "companyId": "C004"},
                {"riskId": "R019", "name": "Acquisition Financing Risk", "companyId": "C004"},
                {"riskId": "R020", "name": "Acquisition Integration Risk", "companyId": "C004"},
                {"riskId": "R021", "name": "Acquisition Regulatory Risk", "companyId": "C004"},
                {"riskId": "R022", "name": "Acquisition Termination Risk", "companyId": "C004"},
                {"riskId": "R001", "name": "2017 Northern California Wildfire Claims", "companyId": "C005"},
                {"riskId": "R002", "name": "2019 Kincade Fire Liability", "companyId": "C005"},
                {"riskId": "R003", "name": "2020 Zogg Fire Liability", "companyId": "C005"},
                {"riskId": "R004", "name": "2021 Dixie Fire Liability", "companyId": "C005"},
                {"riskId": "R005", "name": "2022 Mosquito Fire Liability", "companyId": "C005"},
                {"riskId": "R028", "name": "Aging Infrastructure Risk", "companyId": "C005"},
                {"riskId": "R029", "name": "Air Quality and Climate Change Regulation", "companyId": "C005"},
                {"riskId": "R030", "name": "Annual Rate Update Protests", "companyId": "C005"},
                {"riskId": "R018", "name": "Account Holder Default Risk", "companyId": "C006"},
                {"riskId": "R031", "name": "Anti-Corruption Risk", "companyId": "C006"},
                {"riskId": "R033", "name": "Anti-Money Laundering Compliance Risk", "companyId": "C006"},
                {"riskId": "R034", "name": "Anti-Money Laundering and Counter-Terrorist Financing Risk", "companyId": "C006"},
                {"riskId": "R035", "name": "Anti-Money Laundering and Sanctions Risk", "companyId": "C006"},
                {"riskId": "R039", "name": "Authentication Requirements Risk", "companyId": "C006"},
                {"riskId": "R040", "name": "Banking Regulation Risk", "companyId": "C006"},
                {"riskId": "R041", "name": "Brexit Risk", "companyId": "C006"},
            ]
            session.run("""
                UNWIND $risks AS r
                CREATE (rf:RiskFactor {riskId: r.riskId, name: r.name})
                WITH rf, r
                MATCH (c:Company {companyId: r.companyId})
                CREATE (c)-[:HAS_RISK]->(rf)
            """, risks=risk_factors)
            print(f"  Created {len(risk_factors)} RiskFactor nodes with HAS_RISK relationships")

            # Verify graph counts
            company_count = session.run(
                "MATCH (c:Company) WHERE c.companyId IS NOT NULL RETURN count(c) AS cnt"
            ).single()["cnt"]
            product_count = session.run("MATCH (p:Product) RETURN count(p) AS cnt").single()["cnt"]
            risk_count = session.run("MATCH (r:RiskFactor) RETURN count(r) AS cnt").single()["cnt"]
            offers_count = session.run("MATCH ()-[r:OFFERS]->() RETURN count(r) AS cnt").single()["cnt"]
            competes_count = session.run("MATCH ()-[r:COMPETES_WITH]->() RETURN count(r) AS cnt").single()["cnt"]
            has_risk_count = session.run("MATCH ()-[r:HAS_RISK]->() RETURN count(r) AS cnt").single()["cnt"]

        driver.close()

        results.record("Company nodes (tracked)", company_count == 6, f"{company_count} nodes")
        results.record("Product nodes", product_count == 30, f"{product_count} nodes")
        results.record("RiskFactor nodes", risk_count == 48, f"{risk_count} nodes")
        results.record("OFFERS relationships", offers_count == 30, f"{offers_count} rels")
        results.record("COMPETES_WITH relationships", competes_count == 78, f"{competes_count} rels")
        results.record("HAS_RISK relationships", has_risk_count == 48, f"{has_risk_count} rels")

    except Exception as e:
        results.record("Neo4j graph data load", False, str(e))
        results.summary()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Section 3: Federated Queries
    # ------------------------------------------------------------------
    print("\n--- Section 3: Federated Queries ---")

    # Query 1: Products (Neo4j) + Financial Metrics (Delta)
    print("\n  Query 1: Products (Neo4j) + Metrics (Delta)")
    try:
        neo4j_products = read_neo4j(spark, cfg,
            custom_schema="product_count LONG",
            query="SELECT COUNT(*) AS product_count FROM Product",
        )
        product_total = neo4j_products.collect()[0]["product_count"]

        neo4j_companies = read_neo4j(spark, cfg,
            custom_schema="`v$id` STRING, companyId STRING, name STRING, ticker STRING",
            dbtable="Company",
        ).select("companyId", "name", "ticker").filter("companyId IS NOT NULL")

        delta_metrics = spark.sql(f"""
            SELECT companyId, COUNT(*) AS metric_count
            FROM {fqn}.financial_metrics
            GROUP BY companyId
        """)

        result = neo4j_companies.join(delta_metrics, "companyId", "left")
        result.orderBy("companyId").show(truncate=False)

        row_count = result.count()
        has_metrics = result.filter("metric_count IS NOT NULL").count()

        results.record("Query 1: company+metrics join", row_count == 6 and has_metrics == 6,
                       f"{row_count} rows, {has_metrics} with metrics, {product_total} total products")

    except Exception as e:
        results.record("Query 1: company+metrics join", False, str(e))

    # Query 2: Competitors (Neo4j) + Holdings (Delta)
    print("\n  Query 2: Competitors (Neo4j) + Holdings (Delta)")
    try:
        holdings = spark.sql(f"""
            SELECT
                c.name AS competitor,
                c.ticker,
                am.name AS asset_manager,
                h.shares AS shares_held
            FROM {fqn}.asset_manager_holdings h
            JOIN {fqn}.companies c ON h.companyId = c.companyId
            JOIN {fqn}.asset_managers am ON h.managerId = am.managerId
            WHERE h.companyId IN ('C001', 'C003')
            ORDER BY c.name, h.shares DESC
        """)
        holdings.show(10, truncate=False)
        holdings_count = holdings.count()

        results.record("Query 2: competitor holdings", holdings_count > 0,
                       f"{holdings_count} holdings rows")

    except Exception as e:
        results.record("Query 2: competitor holdings", False, str(e))

    # Query 3: Risk Factors (Neo4j) + Financial Metrics (Delta)
    print("\n  Query 3: Risk Factors (Neo4j) + Financials (Delta)")
    try:
        neo4j_risks = read_neo4j(spark, cfg,
            custom_schema="risk_count LONG",
            query="SELECT COUNT(*) AS risk_count FROM RiskFactor",
        )
        total_risks = neo4j_risks.collect()[0]["risk_count"]

        neo4j_companies = read_neo4j(spark, cfg,
            custom_schema="`v$id` STRING, companyId STRING, name STRING, ticker STRING",
            dbtable="Company",
        ).select("companyId", "name", "ticker").filter("companyId IS NOT NULL")

        delta_summary = spark.sql(f"""
            SELECT
                c.companyId,
                c.name AS company,
                c.ticker,
                COUNT(fm.metricId) AS financial_metrics_count
            FROM {fqn}.companies c
            JOIN {fqn}.financial_metrics fm ON c.companyId = fm.companyId
            GROUP BY c.companyId, c.name, c.ticker
            ORDER BY c.companyId
        """)

        result = neo4j_companies.alias("neo4j") \
            .join(delta_summary.alias("delta"), "companyId") \
            .select(
                col("neo4j.companyId"),
                col("neo4j.name"),
                col("neo4j.ticker"),
                col("delta.financial_metrics_count"),
            )
        result.show(truncate=False)
        row_count = result.count()

        results.record("Query 3: risk+financial view", row_count == 6,
                       f"{row_count} rows, {total_risks} total risk factors")

    except Exception as e:
        results.record("Query 3: risk+financial view", False, str(e))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if not results.summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
