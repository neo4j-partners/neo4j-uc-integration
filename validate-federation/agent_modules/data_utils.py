"""Shared utilities for validate-federation scripts.

Provides:
- Common argparse arguments for Neo4j and lakehouse configuration
- Neo4j connection helpers
- UC JDBC read helpers (DataFrame API and remote_query)
- PASS/FAIL reporting and summary
"""

import argparse


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def add_common_args(parser):
    """Add the standard Neo4j + lakehouse arguments that submit.sh injects."""
    parser.add_argument("--neo4j-host", required=True, help="Neo4j host (without protocol)")
    parser.add_argument("--neo4j-username", default="neo4j", help="Neo4j username")
    parser.add_argument("--neo4j-password", required=True, help="Neo4j password")
    parser.add_argument("--neo4j-database", default="neo4j", help="Neo4j database name")
    parser.add_argument("--uc-connection-name", required=True, help="UC JDBC connection name")
    parser.add_argument("--jdbc-jar-path", required=True, help="Path to connector JAR in UC Volume")
    parser.add_argument("--lakehouse-catalog", required=True, help="Lakehouse catalog name")
    parser.add_argument("--lakehouse-schema", default="lakehouse", help="Lakehouse schema name")
    return parser


def derive_config(args):
    """Compute derived values from parsed args. Returns a dict with all config."""
    return {
        "neo4j_host": args.neo4j_host,
        "neo4j_username": args.neo4j_username,
        "neo4j_password": args.neo4j_password,
        "neo4j_database": args.neo4j_database,
        "neo4j_bolt_uri": f"neo4j+s://{args.neo4j_host}",
        "neo4j_jdbc_url": f"jdbc:neo4j+s://{args.neo4j_host}:7687/{args.neo4j_database}",
        "neo4j_jdbc_url_sql": f"jdbc:neo4j+s://{args.neo4j_host}:7687/{args.neo4j_database}?enableSQLTranslation=true",
        "uc_connection_name": args.uc_connection_name,
        "jdbc_jar_path": args.jdbc_jar_path,
        "java_dependencies": f'["{args.jdbc_jar_path}"]',
        "lakehouse_catalog": args.lakehouse_catalog,
        "lakehouse_schema": args.lakehouse_schema,
        "lakehouse_fqn": f"`{args.lakehouse_catalog}`.`{args.lakehouse_schema}`",
    }


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def get_neo4j_driver(cfg):
    """Create and return a Neo4j driver from config dict."""
    from neo4j import GraphDatabase
    return GraphDatabase.driver(cfg["neo4j_bolt_uri"], auth=(cfg["neo4j_username"], cfg["neo4j_password"]))


# ---------------------------------------------------------------------------
# UC JDBC helpers
# ---------------------------------------------------------------------------

def read_neo4j_jdbc(spark, cfg, custom_schema, query=None, dbtable=None):
    """Read from Neo4j through the UC JDBC connection (DataFrame API).

    Use `query` for aggregates (COUNT, GROUP BY). Use `dbtable` for
    non-aggregate reads of node labels with customSchema.
    """
    reader = spark.read.format("jdbc") \
        .option("databricks.connection", cfg["uc_connection_name"]) \
        .option("customSchema", custom_schema)
    if query:
        reader = reader.option("query", query)
    else:
        reader = reader.option("dbtable", dbtable)
    return reader.load()


def remote_query(spark, cfg, query):
    """Execute a query via remote_query() SQL function."""
    return spark.sql(f"""
        SELECT * FROM remote_query('{cfg["uc_connection_name"]}',
            query => '{query}')
    """)


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
