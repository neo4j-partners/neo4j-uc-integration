"""Materialize Neo4j graph data into Delta tables via UC JDBC dbtable.

Creates managed Delta tables from Neo4j node labels (MaintenanceEvent, Flight,
Airport) plus a Spark SQL join table (flight_airports). Then validates the
materialized tables with SQL queries and federated queries against Delta sensor data.

Usage:
    ./upload.sh run_03_materialized_tables.py && ./submit.sh run_03_materialized_tables.py
"""

import argparse
import sys
import time

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
from data_utils import add_common_args, derive_config, read_neo4j_jdbc, remote_query, ValidationResults

add_common_args(parser)
args, _ = parser.parse_known_args()
cfg = derive_config(args)

from pyspark.sql import SparkSession
from pyspark.sql.functions import col
spark = SparkSession.builder.getOrCreate()
spark.sql(f"USE CATALOG `{cfg['lakehouse_catalog']}`")
spark.sql(f"USE SCHEMA `{cfg['lakehouse_schema']}`")

FQN = cfg["lakehouse_fqn"]
vr = ValidationResults()

print("=" * 60)
print("validate-federation: 03 Materialized Tables")
print("=" * 60)
print(f"  Lakehouse: {cfg['lakehouse_catalog']}.{cfg['lakehouse_schema']}")
print(f"  Neo4j:     {cfg['neo4j_host']}")
print(f"  UC Conn:   {cfg['uc_connection_name']}")
print("")

# ============================================================================
# Section 1: Verify Data Sources
# ============================================================================
print("--- Verify Data Sources ---")

for table in ["aircraft", "systems", "sensors", "sensor_readings"]:
    try:
        cnt = spark.sql(f"SELECT COUNT(*) AS cnt FROM {table}").collect()[0]["cnt"]
        vr.record(f"Delta: {table}", cnt > 0, f"{cnt:,} rows")
    except Exception as e:
        vr.record(f"Delta: {table}", False, str(e)[:120])

for label in ["Aircraft", "MaintenanceEvent", "Flight", "Airport"]:
    try:
        cnt = remote_query(spark, cfg, f"SELECT COUNT(*) AS cnt FROM {label}").collect()[0]["cnt"]
        vr.record(f"Neo4j: {label}", cnt > 0, f"{cnt:,} nodes")
    except Exception as e:
        vr.record(f"Neo4j: {label}", False, str(e)[:120])

# ============================================================================
# Section 2: Materialize Neo4j Tables
# ============================================================================
print("\n--- Materialize: neo4j_maintenance_events ---")
TABLE_MAINT = f"{FQN}.neo4j_maintenance_events"
try:
    spark.sql(f"DROP TABLE IF EXISTS {TABLE_MAINT}")
    spark.sql(f"DROP VIEW IF EXISTS {TABLE_MAINT}")

    MAINT_SCHEMA = """`v$id` STRING, aircraft_id STRING, system_id STRING, component_id STRING,
        event_id STRING, severity STRING, fault STRING, corrective_action STRING, reported_at STRING"""

    t0 = time.time()
    df = read_neo4j_jdbc(spark, cfg, MAINT_SCHEMA, dbtable="MaintenanceEvent") \
        .select("aircraft_id", "fault", "severity", "corrective_action", "reported_at")
    df.write.mode("overwrite").saveAsTable(TABLE_MAINT)
    ms = (time.time() - t0) * 1000

    cnt = spark.sql("SELECT COUNT(*) AS cnt FROM neo4j_maintenance_events").collect()[0]["cnt"]
    vr.record("Materialize: maintenance_events", cnt > 0, f"{cnt} rows, {ms:.0f}ms")
except Exception as e:
    vr.record("Materialize: maintenance_events", False, str(e)[:200])

print("\n--- Materialize: neo4j_flights ---")
TABLE_FLIGHTS = f"{FQN}.neo4j_flights"
try:
    spark.sql(f"DROP TABLE IF EXISTS {TABLE_FLIGHTS}")
    spark.sql(f"DROP VIEW IF EXISTS {TABLE_FLIGHTS}")

    FLIGHT_SCHEMA = """`v$id` STRING, aircraft_id STRING, flight_id STRING, operator STRING,
        flight_number STRING, origin STRING, destination STRING,
        scheduled_departure STRING, scheduled_arrival STRING"""

    t0 = time.time()
    df = read_neo4j_jdbc(spark, cfg, FLIGHT_SCHEMA, dbtable="Flight") \
        .select("aircraft_id", "flight_number", "operator", "origin", "destination",
                "scheduled_departure", "scheduled_arrival")
    df.write.mode("overwrite").saveAsTable(TABLE_FLIGHTS)
    ms = (time.time() - t0) * 1000

    cnt = spark.sql("SELECT COUNT(*) AS cnt FROM neo4j_flights").collect()[0]["cnt"]
    vr.record("Materialize: flights", cnt > 0, f"{cnt} rows, {ms:.0f}ms")
except Exception as e:
    vr.record("Materialize: flights", False, str(e)[:200])

print("\n--- Materialize: neo4j_airports ---")
TABLE_AIRPORTS = f"{FQN}.neo4j_airports"
TABLE_FLIGHT_AIRPORTS = f"{FQN}.neo4j_flight_airports"
try:
    spark.sql(f"DROP TABLE IF EXISTS {TABLE_FLIGHT_AIRPORTS}")
    spark.sql(f"DROP VIEW IF EXISTS {TABLE_FLIGHT_AIRPORTS}")
    spark.sql(f"DROP TABLE IF EXISTS {TABLE_AIRPORTS}")
    spark.sql(f"DROP VIEW IF EXISTS {TABLE_AIRPORTS}")

    AIRPORT_SCHEMA = """`v$id` STRING, airport_id STRING, name STRING, city STRING,
        country STRING, iata STRING, icao STRING, lat STRING, lon STRING"""

    t0 = time.time()
    airports_df = read_neo4j_jdbc(spark, cfg, AIRPORT_SCHEMA, dbtable="Airport") \
        .select("iata", col("name").alias("airport_name"), "city", "country", "icao", "lat", "lon")
    airports_df.write.mode("overwrite").saveAsTable(TABLE_AIRPORTS)
    ms = (time.time() - t0) * 1000

    cnt = spark.sql("SELECT COUNT(*) AS cnt FROM neo4j_airports").collect()[0]["cnt"]
    vr.record("Materialize: airports", cnt > 0, f"{cnt} rows, {ms:.0f}ms")
except Exception as e:
    vr.record("Materialize: airports", False, str(e)[:200])

print("\n--- Create: neo4j_flight_airports (Spark SQL JOIN) ---")
try:
    t0 = time.time()
    spark.sql(f"""
        CREATE OR REPLACE TABLE {TABLE_FLIGHT_AIRPORTS} AS
        SELECT f.flight_number, f.aircraft_id, a.iata AS airport_code, a.airport_name
        FROM {FQN}.neo4j_flights f
        JOIN {FQN}.neo4j_airports a ON f.origin = a.iata
    """)
    ms = (time.time() - t0) * 1000

    cnt = spark.sql("SELECT COUNT(*) AS cnt FROM neo4j_flight_airports").collect()[0]["cnt"]
    vr.record("Create: flight_airports", cnt > 0, f"{cnt} rows, {ms:.0f}ms")
except Exception as e:
    vr.record("Create: flight_airports", False, str(e)[:200])

# ============================================================================
# Section 3: Verify All Materialized Tables
# ============================================================================
print("\n--- Verify Materialized Tables ---")
neo4j_tables = {
    "neo4j_maintenance_events": "MaintenanceEvent nodes",
    "neo4j_flights": "Flight nodes",
    "neo4j_airports": "Airport nodes",
    "neo4j_flight_airports": "flights JOIN airports",
}
for table_name, desc in neo4j_tables.items():
    try:
        cnt = spark.sql(f"SELECT COUNT(*) AS cnt FROM {table_name}").collect()[0]["cnt"]
        vr.record(f"Verify: {table_name}", cnt > 0, f"{cnt:,} rows ({desc})")
    except Exception as e:
        vr.record(f"Verify: {table_name}", False, str(e)[:120])

# ============================================================================
# Section 4: SQL Tests on Materialized Tables
# ============================================================================
print("\n--- SQL Tests on Materialized Tables ---")

# Test 1: GROUP BY
try:
    result = spark.sql("""
        SELECT severity, COUNT(*) AS event_count
        FROM neo4j_maintenance_events
        GROUP BY severity ORDER BY event_count DESC
    """)
    cnt = result.count()
    vr.record("SQL: GROUP BY severity", cnt > 0, f"{cnt} severity levels")
except Exception as e:
    vr.record("SQL: GROUP BY severity", False, str(e)[:120])

# Test 2: ORDER BY
try:
    result = spark.sql("""
        SELECT flight_number, aircraft_id, operator, origin, destination
        FROM neo4j_flights ORDER BY flight_number LIMIT 10
    """)
    rows = result.collect()
    fns = [r["flight_number"] for r in rows]
    vr.record("SQL: ORDER BY flight_number", fns == sorted(fns), f"{len(rows)} rows sorted")
except Exception as e:
    vr.record("SQL: ORDER BY flight_number", False, str(e)[:120])

# Test 3: WHERE filter
try:
    result = spark.sql("""
        SELECT aircraft_id, fault, severity, corrective_action
        FROM neo4j_maintenance_events WHERE severity = 'CRITICAL'
    """)
    rows = result.collect()
    all_critical = all(r["severity"] == "CRITICAL" for r in rows)
    vr.record("SQL: WHERE severity=CRITICAL", all_critical and len(rows) > 0, f"{len(rows)} events")
except Exception as e:
    vr.record("SQL: WHERE severity=CRITICAL", False, str(e)[:120])

# Test 4: Aggregations
try:
    result = spark.sql("""
        SELECT aircraft_id, COUNT(*) AS total,
               SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical
        FROM neo4j_maintenance_events GROUP BY aircraft_id ORDER BY total DESC LIMIT 10
    """)
    vr.record("SQL: aggregations per aircraft", result.count() > 0)
except Exception as e:
    vr.record("SQL: aggregations per aircraft", False, str(e)[:120])

# Test 5: DISTINCT on graph traversal
try:
    result = spark.sql("""
        SELECT DISTINCT airport_code, airport_name
        FROM neo4j_flight_airports ORDER BY airport_code
    """)
    cnt = result.count()
    vr.record("SQL: DISTINCT airports", cnt > 0, f"{cnt} unique airports")
except Exception as e:
    vr.record("SQL: DISTINCT airports", False, str(e)[:120])

# Test 6: GROUP BY on graph traversal
try:
    result = spark.sql("""
        SELECT airport_code, airport_name, COUNT(*) AS departure_count
        FROM neo4j_flight_airports GROUP BY airport_code, airport_name ORDER BY departure_count DESC
    """)
    vr.record("SQL: GROUP BY airport departures", result.count() > 0)
except Exception as e:
    vr.record("SQL: GROUP BY airport departures", False, str(e)[:120])

# ============================================================================
# Section 5: Federated Queries (materialized tables + Delta)
# ============================================================================
print("\n--- Federated Queries ---")

# Federated 1: Fleet summary
try:
    t0 = time.time()
    result = spark.sql("""
        SELECT
            maint.total_maintenance_events, maint.critical_events,
            flights.total_flights, airports.unique_airports,
            ROUND(sensor.avg_egt, 1) AS avg_egt_celsius,
            ROUND(sensor.avg_vibration, 4) AS avg_vibration_ips,
            sensor.total_readings
        FROM (
            SELECT COUNT(*) AS total_maintenance_events,
                   SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_events
            FROM neo4j_maintenance_events
        ) maint
        CROSS JOIN (SELECT COUNT(*) AS total_flights FROM neo4j_flights) flights
        CROSS JOIN (SELECT COUNT(DISTINCT airport_code) AS unique_airports FROM neo4j_flight_airports) airports
        CROSS JOIN (
            SELECT
                AVG(CASE WHEN sen.type = 'EGT' THEN r.value END) AS avg_egt,
                AVG(CASE WHEN sen.type = 'Vibration' THEN r.value END) AS avg_vibration,
                COUNT(*) AS total_readings
            FROM sensor_readings r
            JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
        ) sensor
    """)
    row = result.collect()[0]
    ms = (time.time() - t0) * 1000
    vr.record("Federated: fleet summary (views)",
              row["total_maintenance_events"] > 0 and row["total_readings"] > 0, f"{ms:.0f}ms")
except Exception as e:
    vr.record("Federated: fleet summary (views)", False, str(e)[:200])

# Federated 2: Sensor health + maintenance
try:
    t0 = time.time()
    result = spark.sql("""
        WITH aircraft_ref AS (
            SELECT `:ID(Aircraft)` AS aircraft_id, tail_number, model, operator FROM aircraft
        ),
        sensor_health AS (
            SELECT sys.aircraft_id,
                   ROUND(AVG(CASE WHEN sen.type = 'EGT' THEN r.value END), 1) AS avg_egt,
                   ROUND(AVG(CASE WHEN sen.type = 'Vibration' THEN r.value END), 4) AS avg_vibration
            FROM sensor_readings r
            JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
            JOIN systems sys ON sen.system_id = sys.`:ID(System)`
            GROUP BY sys.aircraft_id
        ),
        maintenance_summary AS (
            SELECT aircraft_id, COUNT(*) AS total_events,
                   SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical
            FROM neo4j_maintenance_events GROUP BY aircraft_id
        )
        SELECT a.tail_number, a.model,
               COALESCE(m.total_events, 0) AS maint_events,
               COALESCE(m.critical, 0) AS critical,
               s.avg_egt, s.avg_vibration
        FROM aircraft_ref a
        LEFT JOIN maintenance_summary m ON a.aircraft_id = m.aircraft_id
        LEFT JOIN sensor_health s ON a.aircraft_id = s.aircraft_id
        ORDER BY m.total_events DESC NULLS LAST
    """)
    ms = (time.time() - t0) * 1000
    vr.record("Federated: sensor+maintenance (views)", result.count() > 0, f"{ms:.0f}ms")
except Exception as e:
    vr.record("Federated: sensor+maintenance (views)", False, str(e)[:200])

# Federated 3: High EGT + critical maintenance
try:
    t0 = time.time()
    result = spark.sql("""
        WITH aircraft_egt AS (
            SELECT sys.aircraft_id,
                   ROUND(AVG(r.value), 1) AS avg_egt, ROUND(MAX(r.value), 1) AS max_egt
            FROM sensor_readings r
            JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
            JOIN systems sys ON sen.system_id = sys.`:ID(System)`
            WHERE sen.type = 'EGT'
            GROUP BY sys.aircraft_id
        ),
        critical_maint AS (
            SELECT aircraft_id, COUNT(*) AS critical_count, COLLECT_LIST(fault) AS faults
            FROM neo4j_maintenance_events WHERE severity = 'CRITICAL'
            GROUP BY aircraft_id
        )
        SELECT a.tail_number, a.model, e.avg_egt, e.max_egt,
               cm.critical_count, cm.faults
        FROM aircraft a
        JOIN aircraft_egt e ON a.`:ID(Aircraft)` = e.aircraft_id
        JOIN critical_maint cm ON a.`:ID(Aircraft)` = cm.aircraft_id
        ORDER BY e.avg_egt DESC
    """)
    ms = (time.time() - t0) * 1000
    vr.record("Federated: high EGT + critical maint", result.count() > 0, f"{ms:.0f}ms")
except Exception as e:
    vr.record("Federated: high EGT + critical maint", False, str(e)[:200])

# Federated 4: Route coverage + engine health
try:
    t0 = time.time()
    result = spark.sql("""
        WITH airport_aircraft AS (
            SELECT DISTINCT airport_code, airport_name, aircraft_id
            FROM neo4j_flight_airports
        ),
        aircraft_egt AS (
            SELECT sys.aircraft_id, ROUND(AVG(r.value), 1) AS avg_egt
            FROM sensor_readings r
            JOIN sensors sen ON r.sensor_id = sen.`:ID(Sensor)`
            JOIN systems sys ON sen.system_id = sys.`:ID(System)`
            WHERE sen.type = 'EGT'
            GROUP BY sys.aircraft_id
        )
        SELECT aa.airport_code, aa.airport_name,
               COUNT(DISTINCT aa.aircraft_id) AS aircraft_count,
               ROUND(AVG(e.avg_egt), 1) AS avg_fleet_egt_c
        FROM airport_aircraft aa
        JOIN aircraft_egt e ON aa.aircraft_id = e.aircraft_id
        GROUP BY aa.airport_code, aa.airport_name
        ORDER BY avg_fleet_egt_c DESC
    """)
    ms = (time.time() - t0) * 1000
    vr.record("Federated: route coverage + EGT", result.count() > 0, f"{ms:.0f}ms")
except Exception as e:
    vr.record("Federated: route coverage + EGT", False, str(e)[:200])

# ============================================================================
# Summary
# ============================================================================
all_passed = vr.summary()
if not all_passed:
    sys.exit(1)
