"""Shared utilities for sample-validation scripts.

Provides:
- Common argparse arguments for Neo4j and UC configuration
- Neo4j connection helper
- UC JDBC read helper
- PASS/FAIL reporting and summary
"""

import argparse


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def add_common_args(parser):
    """Add the standard Neo4j + UC arguments that submit.sh injects."""
    parser.add_argument("--neo4j-uri", required=True, help="Neo4j Aura URI (neo4j+s://...)")
    parser.add_argument("--neo4j-username", default="neo4j", help="Neo4j username")
    parser.add_argument("--neo4j-password", default=None, help="Neo4j password (prefer --secret-scope)")
    parser.add_argument("--secret-scope", default=None, help="Databricks secret scope containing Neo4j credentials")
    parser.add_argument("--secret-key", default="neo4j-password", help="Secret key for Neo4j password within the scope")
    parser.add_argument("--uc-catalog", required=True, help="Unity Catalog catalog name")
    parser.add_argument("--uc-schema", default="neo4j_getting_started", help="UC schema name")
    parser.add_argument("--uc-volume", default="data", help="UC volume name for CSV data")
    parser.add_argument("--jdbc-jar-path", required=True, help="Path to connector JAR in UC Volume")
    parser.add_argument("--uc-connection-name", default="sample_neo4j_jdbc_connection", help="UC JDBC connection name")
    return parser


def _resolve_password(args):
    """Resolve Neo4j password from Databricks Secrets or CLI argument."""
    if args.secret_scope:
        from pyspark.sql import SparkSession
        from pyspark.dbutils import DBUtils
        spark = SparkSession.builder.getOrCreate()
        dbutils = DBUtils(spark)
        return dbutils.secrets.get(scope=args.secret_scope, key=args.secret_key)
    if args.neo4j_password:
        return args.neo4j_password
    raise ValueError("Either --secret-scope or --neo4j-password must be provided")


def derive_config(args):
    """Compute derived values from parsed args. Returns a dict with all config."""
    uc_catalog = args.uc_catalog
    uc_schema = args.uc_schema
    neo4j_host = args.neo4j_uri.replace("neo4j+s://", "")
    neo4j_password = _resolve_password(args)

    return {
        "neo4j_uri": args.neo4j_uri,
        "neo4j_username": args.neo4j_username,
        "neo4j_password": neo4j_password,
        "neo4j_host": neo4j_host,
        "uc_catalog": uc_catalog,
        "uc_schema": uc_schema,
        "uc_volume": args.uc_volume,
        "jdbc_jar_path": args.jdbc_jar_path,
        "uc_connection_name": args.uc_connection_name,
        # Backtick-quoted fully qualified name (handles hyphens in catalog names)
        "fqn": f"`{uc_catalog}`.`{uc_schema}`",
        "volume_path": f"/Volumes/{uc_catalog}/{uc_schema}/{args.uc_volume}",
        "neo4j_jdbc_url": f"jdbc:neo4j+s://{neo4j_host}:7687/neo4j",
        "neo4j_jdbc_url_sql": f"jdbc:neo4j+s://{neo4j_host}:7687/neo4j?enableSQLTranslation=true",
        "java_dependencies": f'["{args.jdbc_jar_path}"]',
    }


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def get_neo4j_driver(cfg):
    """Create and return a Neo4j driver from config dict."""
    from neo4j import GraphDatabase
    return GraphDatabase.driver(cfg["neo4j_uri"], auth=(cfg["neo4j_username"], cfg["neo4j_password"]))


# ---------------------------------------------------------------------------
# UC JDBC helpers
# ---------------------------------------------------------------------------

def read_neo4j(spark, cfg, custom_schema, query=None, dbtable=None):
    """Read from Neo4j through the UC JDBC connection.

    Use `query` for aggregates (COUNT, GROUP BY). Use `dbtable` for
    non-aggregate reads — it avoids Spark's subquery wrapping which the
    Neo4j SQL-to-Cypher translator cannot handle for non-aggregate SELECT.
    """
    reader = spark.read.format("jdbc") \
        .option("databricks.connection", cfg["uc_connection_name"]) \
        .option("customSchema", custom_schema)
    if query:
        reader = reader.option("query", query)
    else:
        reader = reader.option("dbtable", dbtable)
    return reader.load()


# ---------------------------------------------------------------------------
# PASS/FAIL reporting
# ---------------------------------------------------------------------------

class ValidationResults:
    """Collects PASS/FAIL results and prints a summary."""

    def __init__(self):
        self.results = []

    def record(self, name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        self.results.append((name, passed, detail))
        msg = f"  [{status}] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def summary(self):
        passed = sum(1 for _, p, _ in self.results if p)
        total = len(self.results)
        print("")
        print("=" * 60)
        print(f"RESULTS: {passed}/{total} passed")
        print("=" * 60)
        for name, p, detail in self.results:
            status = "PASS" if p else "FAIL"
            line = f"  [{status}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)
        print("")
        if passed == total:
            print("STATUS: ALL PASSED")
        else:
            print(f"STATUS: {total - passed} FAILED")
        return passed == total
