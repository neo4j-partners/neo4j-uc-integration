# validate-federation: Test Failures

## Environment

- **Databricks Runtime:** 4.1.0 (Spark 4.1.0, Python 3.12.3)
- **Connector JAR:** neo4j-unity-catalog-connector-1.3.1.jar
- **Neo4j Host:** e3790fca.databases.neo4j.io
- **UC Connection:** sample_neo4j_jdbc_connection (created by run_01)
- **Workspace:** Azure (adb-1098933906466604)
- **Date:** 2026-04-03

## Results Summary

| Script | Result |
|--------|--------|
| run_01_connection_validation.py | 15/15 PASSED |
| run_02_federated_queries.py | 14/14 PASSED |
| run_03_materialized_tables.py | 26/26 PASSED |
| run_06_advanced_sql.py | 3/16 FAILED (13 failures) |

## run_06 Failures: GROUP BY via remote_query()

### Root Cause

Spark wraps every `remote_query()` query in a subquery for schema inference:

```sql
SELECT * FROM (
  <original query>
) SPARK_GEN_SUBQ_0 WHERE 1=0
```

The SparkSubqueryCleaningTranslator strips this wrapping for simple queries (aggregates, JOINs). But when the original query contains `GROUP BY` with projected grouping columns, `ORDER BY`, `HAVING`, `DISTINCT`, `LIMIT`, or `OFFSET`, the cleaner does not handle the wrapped form. The JDBC driver receives the wrapped SQL, fails to translate it to Cypher, and returns `JDBC_EXTERNAL_ENGINE_SYNTAX_ERROR.DURING_OUTPUT_SCHEMA_RESOLUTION`.

### What Passes (3/16)

| Test | Query Pattern | Why It Works |
|------|--------------|--------------|
| GROUP BY explicit WITH | `SELECT COUNT(*) ... GROUP BY severity` | GROUP BY column not projected; Cypher uses WITH clause that survives wrapping |
| JOIN+GROUP BY non-projected | `SELECT COUNT(*) ... NATURAL JOIN ... GROUP BY a.code` | Same: non-projected GROUP BY |
| JOIN+GROUP BY projected | `SELECT a.code, COUNT(*) ... GROUP BY a.code` | JOIN traversal path may get different treatment |

### What Fails (13/16)

All share the same error: `JDBC_EXTERNAL_ENGINE_SYNTAX_ERROR.DURING_OUTPUT_SCHEMA_RESOLUTION`

| Test | Query Pattern |
|------|--------------|
| GROUP BY implicit | `SELECT severity, COUNT(*) ... GROUP BY severity` |
| GROUP BY multi-aggregate | `SELECT operator, COUNT(*), COUNT(DISTINCT origin) ... GROUP BY operator` |
| HAVING simple | `... GROUP BY operator HAVING cnt > 20` |
| HAVING non-projected | `... GROUP BY severity HAVING COUNT(*) > 10` |
| HAVING compound | `... HAVING COUNT(*) > 10 AND COUNT(DISTINCT origin) > 2` |
| ORDER BY aggregate | `... GROUP BY severity ORDER BY cnt DESC` |
| ORDER BY multi-key | `... GROUP BY operator ORDER BY cnt DESC, routes` |
| DISTINCT+GROUP BY | `SELECT DISTINCT operator, COUNT(*) ... GROUP BY operator` |
| LIMIT+OFFSET | `... GROUP BY operator ORDER BY cnt DESC LIMIT 3 OFFSET 1` |
| HAVING+ORDER+LIMIT+OFFSET | Combined clauses |
| All clauses combined | WHERE + GROUP BY + HAVING + ORDER BY + DISTINCT + LIMIT + OFFSET |
| Federated: GROUP BY + Delta | CTE with remote_query GROUP BY joined to Delta tables |
| Federated: HAVING + Delta | CTE with remote_query HAVING joined to Delta tables |

### Separate Issue: LIKE Quoting

The "All clauses combined" test also hit a quoting error:

```
Token ')' expected: [1:141] ...WHERE aircraft_id LIKE AC% GROUP [*]BY severity HAVING
```

The doubled single quotes `''AC%''` (SQL escape for literal quotes inside `remote_query()`) were stripped at the wrong level, producing `LIKE AC%` instead of `LIKE 'AC%'`.

This is the same class of bug as the WHERE string literal issue: `WHERE severity = 'CRITICAL'` returns 0 rows via `remote_query()` but 101 via direct JDBC.

## Context

Notebook 06 was developed and validated interactively on the AWS workspace using the `aircraft_connection_v2` UC connection. The batch scripts use `sample_neo4j_jdbc_connection` created fresh by run_01 with the same connector JAR (1.3.1). The difference in behavior may stem from:

1. **Runtime version:** The AWS workspace may run a different Databricks Runtime that handles `remote_query()` schema inference differently.
2. **Connector JAR version:** Notebook 06 references neo4j-jdbc PR #1310 features. The connector JAR at 1.3.1 may not include the SparkSubqueryCleaningTranslator updates needed for GROUP BY wrapping.
3. **Interactive vs. batch execution:** Unlikely to cause differences, but worth ruling out.

## Proposed Next Steps

1. **Verify connector version:** Check which neo4j-jdbc version is bundled in the 1.3.1 connector JAR. The GROUP BY features require neo4j-jdbc 6.12.0+ with PR #1310. If the JAR bundles an older driver, the cleaner won't handle GROUP BY wrapping.

2. **Test with aircraft_connection_v2:** Change `UC_CONNECTION_NAME` in .env to `aircraft_connection_v2` and re-run run_06 to see if the pre-existing connection (which was used to validate notebook 06) behaves differently.

3. **Test on AWS workspace:** Run the batch scripts on the AWS workspace where notebook 06 was originally validated, to isolate whether the issue is workspace/runtime-specific or connector-specific.

4. **Update SparkSubqueryCleaningTranslator:** If the connector JAR's cleaner doesn't handle GROUP BY wrapping, this is a connector bug to fix in neo4j-unity-catalog-connector. The cleaner needs to strip the `SPARK_GEN_SUBQ WHERE 1=0` wrapper even when the inner query contains GROUP BY, HAVING, ORDER BY, DISTINCT, LIMIT, or OFFSET.

5. **Workaround for run_06:** For queries that fail via `remote_query()`, fall back to UC JDBC DataFrame API (`read_neo4j_jdbc` with `query` option) which may handle schema inference differently. If that also fails, use the Spark Connector as run_02 does for row-level data.
