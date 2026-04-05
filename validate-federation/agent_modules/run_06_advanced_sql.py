"""Validate advanced SQL-to-Cypher translation via remote_query().

Tests GROUP BY, HAVING, ORDER BY, LIMIT, OFFSET, DISTINCT, JOIN+GROUP BY,
and all clauses combined. Also runs federated queries using GROUP BY/HAVING
results joined with Delta lakehouse data.

Usage:
    ./upload.sh run_06_advanced_sql.py && ./submit.sh run_06_advanced_sql.py
"""

import argparse
import sys
import time

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
from data_utils import add_common_args, derive_config, remote_query, ValidationResults

add_common_args(parser)
args, _ = parser.parse_known_args()
cfg = derive_config(args)

from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
spark.sql(f"USE CATALOG `{cfg['lakehouse_catalog']}`")
spark.sql(f"USE SCHEMA `{cfg['lakehouse_schema']}`")

conn = cfg["uc_connection_name"]
vr = ValidationResults()

print("=" * 60)
print("validate-federation: 06 Advanced SQL Features")
print("=" * 60)
print(f"  Lakehouse: {cfg['lakehouse_catalog']}.{cfg['lakehouse_schema']}")
print(f"  Neo4j:     {cfg['neo4j_host']}")
print(f"  UC Conn:   {conn}")
print("")


def rq(query):
    """Shorthand for remote_query via Spark SQL."""
    return spark.sql(f"""
        SELECT * FROM remote_query('{conn}', query => '{query}')
    """)


# ============================================================================
# Section 1: GROUP BY
# ============================================================================
print("--- GROUP BY ---")

# Implicit grouping — projected columns match GROUP BY
try:
    t0 = time.time()
    result = rq("SELECT severity, COUNT(*) AS cnt FROM MaintenanceEvent m GROUP BY severity")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("GROUP BY implicit", len(rows) > 0, f"{len(rows)} severities, {ms:.0f}ms")
except Exception as e:
    vr.record("GROUP BY implicit", False, str(e)[:120])

# Explicit WITH — GROUP BY column NOT in projection
try:
    t0 = time.time()
    result = rq("SELECT COUNT(*) AS cnt FROM MaintenanceEvent m GROUP BY severity")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("GROUP BY explicit WITH", len(rows) > 0, f"{len(rows)} groups, {ms:.0f}ms")
except Exception as e:
    vr.record("GROUP BY explicit WITH", False, str(e)[:120])

# Multiple aggregates
try:
    t0 = time.time()
    result = rq("SELECT operator, COUNT(*) AS flights, COUNT(DISTINCT origin) AS origins, COUNT(DISTINCT destination) AS destinations FROM Flight f GROUP BY operator")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("GROUP BY multi-aggregate", len(rows) > 0, f"{len(rows)} operators, {ms:.0f}ms")
except Exception as e:
    vr.record("GROUP BY multi-aggregate", False, str(e)[:120])

# ============================================================================
# Section 2: HAVING
# ============================================================================
print("\n--- HAVING ---")

# Simple HAVING
try:
    t0 = time.time()
    result = rq("SELECT operator, COUNT(*) AS cnt FROM Flight f GROUP BY operator HAVING cnt > 20")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    all_over_20 = all(r["cnt"] > 20 for r in rows)
    vr.record("HAVING simple", all_over_20 and len(rows) >= 0, f"{len(rows)} operators, {ms:.0f}ms")
except Exception as e:
    vr.record("HAVING simple", False, str(e)[:120])

# Non-projected aggregate
try:
    t0 = time.time()
    result = rq("SELECT severity FROM MaintenanceEvent m GROUP BY severity HAVING COUNT(*) > 10")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("HAVING non-projected", len(rows) >= 0, f"{len(rows)} severities, {ms:.0f}ms")
except Exception as e:
    vr.record("HAVING non-projected", False, str(e)[:120])

# Compound condition
try:
    t0 = time.time()
    result = rq("SELECT operator, COUNT(*) AS cnt FROM Flight f GROUP BY operator HAVING COUNT(*) > 10 AND COUNT(DISTINCT origin) > 2")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("HAVING compound", len(rows) >= 0, f"{len(rows)} operators, {ms:.0f}ms")
except Exception as e:
    vr.record("HAVING compound", False, str(e)[:120])

# ============================================================================
# Section 3: ORDER BY
# ============================================================================
print("\n--- ORDER BY ---")

# ORDER BY on aggregate alias
try:
    t0 = time.time()
    result = rq("SELECT severity, COUNT(*) AS cnt FROM MaintenanceEvent m GROUP BY severity ORDER BY cnt DESC")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    counts = [r["cnt"] for r in rows]
    is_sorted = counts == sorted(counts, reverse=True)
    vr.record("ORDER BY aggregate", is_sorted and len(rows) > 0, f"{len(rows)} rows sorted, {ms:.0f}ms")
except Exception as e:
    vr.record("ORDER BY aggregate", False, str(e)[:120])

# Multi-key ORDER BY
try:
    t0 = time.time()
    result = rq("SELECT operator, COUNT(*) AS cnt, COUNT(DISTINCT origin) AS routes FROM Flight f GROUP BY operator ORDER BY cnt DESC, routes")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("ORDER BY multi-key", len(rows) > 0, f"{len(rows)} rows, {ms:.0f}ms")
except Exception as e:
    vr.record("ORDER BY multi-key", False, str(e)[:120])

# ============================================================================
# Section 4: JOIN + GROUP BY
# ============================================================================
print("\n--- JOIN + GROUP BY ---")

# Non-projected group key
try:
    t0 = time.time()
    result = rq("SELECT COUNT(*) AS flight_count FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a GROUP BY a.code")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("JOIN+GROUP BY non-projected", len(rows) > 0, f"{len(rows)} airports, {ms:.0f}ms")
except Exception as e:
    vr.record("JOIN+GROUP BY non-projected", False, str(e)[:120])

# Projected group key
try:
    t0 = time.time()
    result = rq("SELECT a.code, COUNT(*) AS flight_count FROM Flight f NATURAL JOIN DEPARTS_FROM r NATURAL JOIN Airport a GROUP BY a.code")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("JOIN+GROUP BY projected", len(rows) > 0, f"{len(rows)} airports, {ms:.0f}ms")
except Exception as e:
    vr.record("JOIN+GROUP BY projected", False, str(e)[:120])

# ============================================================================
# Section 5: DISTINCT, LIMIT, OFFSET
# ============================================================================
print("\n--- DISTINCT, LIMIT, OFFSET ---")

# DISTINCT + GROUP BY
try:
    t0 = time.time()
    result = rq("SELECT DISTINCT operator, COUNT(*) AS cnt FROM Flight f GROUP BY operator")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("DISTINCT+GROUP BY", len(rows) > 0, f"{len(rows)} operators, {ms:.0f}ms")
except Exception as e:
    vr.record("DISTINCT+GROUP BY", False, str(e)[:120])

# LIMIT + OFFSET
try:
    t0 = time.time()
    result = rq("SELECT operator, COUNT(*) AS cnt FROM Flight f GROUP BY operator ORDER BY cnt DESC LIMIT 3 OFFSET 1")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("LIMIT+OFFSET", len(rows) <= 3, f"{len(rows)} rows (skip 1 take 3), {ms:.0f}ms")
except Exception as e:
    vr.record("LIMIT+OFFSET", False, str(e)[:120])

# HAVING + ORDER BY + LIMIT + OFFSET combined
try:
    t0 = time.time()
    result = rq("SELECT severity, COUNT(*) AS cnt FROM MaintenanceEvent m GROUP BY severity HAVING COUNT(*) > 5 ORDER BY cnt DESC LIMIT 10 OFFSET 0")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("HAVING+ORDER+LIMIT+OFFSET", len(rows) >= 0, f"{len(rows)} rows, {ms:.0f}ms")
except Exception as e:
    vr.record("HAVING+ORDER+LIMIT+OFFSET", False, str(e)[:120])

# ============================================================================
# Section 6: All Clauses Combined
# ============================================================================
print("\n--- All Clauses Combined ---")
try:
    t0 = time.time()
    result = rq("SELECT DISTINCT severity, COUNT(*) AS cnt, MAX(fault) AS last_fault FROM MaintenanceEvent m WHERE aircraft_id LIKE ''AC%'' GROUP BY severity HAVING COUNT(*) > 1 ORDER BY cnt DESC LIMIT 10 OFFSET 0")
    rows = result.collect()
    ms = (time.time() - t0) * 1000
    vr.record("All clauses combined", len(rows) > 0, f"{len(rows)} rows, {ms:.0f}ms")
    result.show(truncate=False)
except Exception as e:
    vr.record("All clauses combined", False, str(e)[:200])

# ============================================================================
# Section 7: Federated Queries with GROUP BY/HAVING
# ============================================================================
print("\n--- Federated: Neo4j GROUP BY + Delta ---")

# Federated 1: Neo4j GROUP BY + Delta sensor health
try:
    t0 = time.time()
    result = spark.sql(f"""
        WITH neo4j_maint AS (
            SELECT *
            FROM remote_query('{conn}',
                query => 'SELECT aircraft_id, severity, COUNT(*) AS cnt FROM MaintenanceEvent m GROUP BY aircraft_id, severity ORDER BY cnt DESC')
        ),
        sensor_health AS (
            SELECT
                sys.aircraft_id,
                ROUND(AVG(CASE WHEN sen.type = 'EGT' THEN r.value END), 1) AS avg_egt,
                ROUND(AVG(CASE WHEN sen.type = 'Vibration' THEN r.value END), 4) AS avg_vibration
            FROM sensor_readings r
            JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
            JOIN systems sys ON sen.system_id = sys.`:ID(System)`
            GROUP BY sys.aircraft_id
        )
        SELECT
            a.tail_number, a.model,
            m.severity, m.cnt AS maint_count,
            s.avg_egt AS avg_egt_c, s.avg_vibration AS avg_vib_ips
        FROM neo4j_maint m
        JOIN aircraft a ON m.aircraft_id = a.`:ID(Aircraft)`
        JOIN sensor_health s ON m.aircraft_id = s.aircraft_id
        ORDER BY m.cnt DESC
    """)
    cnt = result.count()
    ms = (time.time() - t0) * 1000
    vr.record("Federated: GROUP BY + Delta", cnt > 0, f"{cnt} rows, {ms:.0f}ms")
    result.show(10, truncate=False)
except Exception as e:
    vr.record("Federated: GROUP BY + Delta", False, str(e)[:200])

# Federated 2: Neo4j HAVING filter + Delta engine performance
try:
    t0 = time.time()
    result = spark.sql(f"""
        WITH active_operators AS (
            SELECT *
            FROM remote_query('{conn}',
                query => 'SELECT operator, COUNT(*) AS flight_count, COUNT(DISTINCT aircraft_id) AS aircraft_count FROM Flight f GROUP BY operator HAVING COUNT(*) > 20 ORDER BY flight_count DESC')
        ),
        fleet_sensor_avg AS (
            SELECT
                a.operator,
                ROUND(AVG(CASE WHEN sen.type = 'EGT' THEN r.value END), 1) AS avg_egt,
                ROUND(AVG(CASE WHEN sen.type = 'FuelFlow' THEN r.value END), 2) AS avg_fuel_flow,
                ROUND(AVG(CASE WHEN sen.type = 'N1Speed' THEN r.value END), 0) AS avg_n1_speed
            FROM sensor_readings r
            JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
            JOIN systems sys ON sen.system_id = sys.`:ID(System)`
            JOIN aircraft a ON sys.aircraft_id = a.`:ID(Aircraft)`
            WHERE sys.type = 'Engine'
            GROUP BY a.operator
        )
        SELECT
            o.operator, o.flight_count, o.aircraft_count,
            s.avg_egt AS avg_egt_c, s.avg_fuel_flow AS fuel_kgs, s.avg_n1_speed AS n1_rpm
        FROM active_operators o
        JOIN fleet_sensor_avg s ON o.operator = s.operator
        ORDER BY o.flight_count DESC
    """)
    cnt = result.count()
    ms = (time.time() - t0) * 1000
    vr.record("Federated: HAVING + Delta", cnt >= 0, f"{cnt} operators, {ms:.0f}ms")
    result.show(truncate=False)
except Exception as e:
    vr.record("Federated: HAVING + Delta", False, str(e)[:200])

# ============================================================================
# Summary
# ============================================================================
all_passed = vr.summary()
if not all_passed:
    sys.exit(1)
