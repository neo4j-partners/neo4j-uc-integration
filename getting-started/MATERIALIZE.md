# Materialization: NullType Error and Fix Options

## Original Code

The notebook used `dbtable` + `customSchema` to read Neo4j node labels via the UC JDBC connection:

```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", UC_CONNECTION_NAME) \
    .option("dbtable", config["dbtable"]) \
    .option("customSchema", config["schema"]) \
    .load() \
    .drop("v$id")

df.write.format("delta").mode("overwrite").saveAsTable(fqn)
```

With `customSchema` set to:

```python
"`v$id` STRING, companyId STRING, name STRING, ticker STRING"
```

This is the same pattern used in `neo4j-uc-federation-lab/03_materialized_tables_for_agents.ipynb`.

## Error

```
Py4JJavaError: An error occurred while calling o567.saveAsTable.
: org.apache.spark.SparkException: Job aborted due to stage failure:
  Task 0 in stage 92.0 failed 4 times, most recent failure:
  java.sql.SQLException: INTERNAL: Unsupported JDBC type 0 (NULL) for column 'companyId'
```

The Neo4j JDBC driver returns JDBC type 0 (NULL) for columns during data reading, not just schema inference. `customSchema` overrides the inferred schema but does not change the JDBC type the driver reports when fetching rows from the `ResultSet`. Spark fails when it encounters type 0 at read time.

The connector JAR does not currently have a fix for this.

## Fix Option: `query` + `customSchema`

Replace `dbtable` with `query`, selecting only the columns we need (no `v$id`):

```python
df = spark.read.format("jdbc") \
    .option("databricks.connection", UC_CONNECTION_NAME) \
    .option("query", "SELECT companyId, name, ticker FROM Company") \
    .option("customSchema", "companyId STRING, name STRING, ticker STRING") \
    .load()

df.write.format("delta").mode("overwrite").saveAsTable(fqn)
```

Why this may fix it:

- **Avoids `v$id`** -- the internal Neo4j column is never requested, so Spark never encounters its NullType.
- **Explicit column selection** -- the SQL query tells the driver exactly which columns to return, which may cause it to report proper types.
- **SparkSubqueryCleaningTranslator handles wrapping** -- the `query` option was originally avoided because Spark wraps it in a subquery (`SELECT * FROM (...) SPARK_GEN_SUBQ_0 WHERE 1=0`) for schema inference. The connector's `SparkSubqueryCleaningTranslator` was built specifically to strip this wrapping before it reaches the Neo4j SQL translator.
- **`customSchema` still available** -- unlike `remote_query()`, the DataFrame JDBC API supports `customSchema` as a fallback for type inference.

## Next Steps

1. Update `03-materialized-tables.ipynb` to use `query` + `customSchema` instead of `dbtable` + `customSchema`.
2. Test on Databricks to confirm the NullType error is resolved.
3. If it works, apply the same fix to `neo4j-uc-federation-lab/03_materialized_tables_for_agents.ipynb`.
4. If it doesn't work (NullType persists even with `query`), fall back to `remote_query()` or the Python driver as the materialization method.
5. Revert the current Python driver changes in `03-materialized-tables.ipynb` back to JDBC.
