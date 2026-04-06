# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Neo4j + Databricks Lakehouse Federation Integration — enables SQL queries against Neo4j graph databases from Databricks via Unity Catalog's JDBC connection support. The core component is the Neo4j JDBC Lakehouse Federation Connector, a shaded (fat) JAR that bundles the Neo4j JDBC driver with SQL-to-Cypher translators.

## Connector JAR

The Neo4j JDBC Lakehouse Federation Connector JAR is built and released from a separate repo: [neo4j-unity-catalog-connector](https://github.com/neo4j-labs/neo4j-unity-catalog-connector). Download the latest release from [releases](https://github.com/neo4j-labs/neo4j-unity-catalog-connector/tags).

## Architecture

### Translator Pipeline (SPI-based)

Translators are discovered via Java ServiceLoader (`META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory`). The pipeline chains translators by `Translator.getOrder()`:

1. **SparkSubqueryCleaningTranslator** (highest precedence) — strips Spark's `SPARK_GEN_SUBQ_0 WHERE 1=0` wrapping that Databricks adds to JDBC queries
2. **SqlToCypherTranslator** — converts cleaned SQL into Cypher

Each translator returns `null` for queries it doesn't handle, passing to the next in the chain.

### Shaded JAR Strategy

The Maven shade plugin merges `neo4j-jdbc`, `neo4j-jdbc-translator-impl`, and `neo4j-jdbc-translator-sparkcleaner` into a single JAR. All dependencies are relocated under `org.neo4j.jdbc.internal.shaded.*` to avoid classpath conflicts with Databricks SafeSpark's isolated JVM. The `ServicesResourceTransformer` merges SPI registration files across the bundled JARs — this is critical for translator discovery.

### SafeSpark Compatibility

Databricks runs custom JDBC drivers in an isolated JVM sandbox. The connector requires metaspace tuning:
`spark.databricks.safespark.jdbcSandbox.jvm.maxMetaspace.mib 128`

### Project Layout

- `neo4j-unity-catalog-connector/` — Maven project (Java 17), the connector JAR
- `neo4j-uc-federation-lab/` — Databricks notebooks (5 numbered notebooks demonstrating patterns)
- `site/` — Antora documentation site (AsciiDoc, published to GitHub Pages)
- `docs/` — Markdown reference documentation

## Code Style

- **Formatter:** Palantir Java Format via Spotless Maven Plugin (enforced at compile phase)
- Run `./mvnw spotless:apply` before committing Java changes

## Testing

JUnit 5 tests in `neo4j-unity-catalog-connector/src/test/java/`. Key test (`BundledTranslatorsTest.java`) verifies:
- SPI discovery of both translator factories
- Spark subquery cleaning pipeline
- Cypher passthrough behavior
- Neo4j JDBC driver class loading

## Release Process

Tag with `connector-*` pattern triggers GitHub Actions to build and publish a release:
```bash
git tag connector-1.0.0
git push origin connector-1.0.0
```

## SQL-to-Cypher Support via UC JDBC

Supported: `SELECT COUNT(*)`, aggregates with `WHERE`, `COUNT DISTINCT`, `NATURAL JOIN` (graph traversals), subqueries with aggregates, `GROUP BY` (implicit and explicit WITH-clause generation), `HAVING` (simple, compound, mixed aggregates, without GROUP BY), `ORDER BY` (including on aggregate aliases and after WITH clauses), `DISTINCT` with GROUP BY/HAVING, `LIMIT`/`OFFSET` with WITH clauses, `WHERE` + `GROUP BY` combinations, `JOIN` + `GROUP BY`, `COUNT(DISTINCT)` in HAVING, additional aggregate functions (`percentileCont`, `percentileDisc`, `stDev`, `stDevP`), full clause combinations.

Not supported (use Spark Connector instead): non-aggregate `SELECT`, relationship property aggregation.
