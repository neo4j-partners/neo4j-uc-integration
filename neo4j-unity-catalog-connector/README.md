# Neo4j Unity Catalog Connector

A single shaded (fat) JAR that bundles the Neo4j JDBC driver, the SQL-to-Cypher translator, and the Spark subquery cleaner for use with Databricks Unity Catalog federated queries.

Instead of downloading and uploading two separate JARs (`neo4j-jdbc-full-bundle` + `neo4j-jdbc-translator-sparkcleaner`), users upload this single JAR to a UC Volume and reference one path in their connection configuration.

## Prerequisites

- Java 17+

## Build

```bash
cd neo4j-unity-catalog-connector
./mvnw clean verify
```

The shaded JAR is produced at:

```
target/neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar
```

## Run Tests

Tests verify that the bundled translators are discoverable via SPI, the Spark subquery cleaner handles Databricks/Spark query patterns, and the JDBC driver class is loadable.

```bash
./mvnw test
```

## Test in Databricks

1. Build the JAR (see above).

2. Upload to a Unity Catalog Volume:

   ```python
   # In a Databricks notebook
   dbutils.fs.cp(
       "file:/path/to/neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar",
       "/Volumes/<catalog>/<schema>/jars/neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar"
   )
   ```

3. Create a JDBC connection referencing the single JAR:

   ```sql
   CREATE CONNECTION neo4j_connection TYPE JDBC
   ENVIRONMENT (
     java_dependencies '["/Volumes/<catalog>/<schema>/jars/neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar"]'
     safespark_memory '800m'
   )
   OPTIONS (
     host '<neo4j-host>',
     port '7687',
     user '<username>',
     password '<password>',
     jdbc_driver 'org.neo4j.jdbc.Neo4jDriver',
     jdbc_url 'jdbc:neo4j://<neo4j-host>:7687?database=neo4j&enableSQLTranslation=true'
   )
   ```

4. Run a federated query:

   ```sql
   SELECT * FROM IDENTIFIER(neo4j_connection.`/`) LIMIT 10;
   ```

## What's Inside

The shaded JAR bundles:

| Dependency | Purpose |
|---|---|
| `neo4j-jdbc` | Core JDBC driver for Neo4j |
| `neo4j-jdbc-translator-impl` | SQL-to-Cypher translation engine |
| `neo4j-jdbc-translator-sparkcleaner` | Cleans Spark subquery wrapping (`SPARK_GEN_SUBQ_0 WHERE 1=0`) |

All transitive dependencies (Jackson, Netty, jOOQ, Bolt protocol, Cypher DSL, Reactive Streams) are relocated under `org.neo4j.jdbc.internal.shaded.*` to avoid classpath conflicts with the Databricks runtime.

## Design

### Problem

Connecting Neo4j to Databricks Unity Catalog previously required users to download and upload **two separate JARs** to a Unity Catalog Volume:

1. `neo4j-jdbc-full-bundle-6.x.x.jar` — the main JDBC driver with SQL-to-Cypher translation
2. `neo4j-jdbc-translator-sparkcleaner-6.x.x.jar` — handles Spark's subquery wrapping (`SPARK_GEN_SUBQ_0 WHERE 1=0`)

Both had to be referenced individually in the `java_dependencies` array when creating a UC JDBC connection. This meant two manual downloads from Maven Central, two uploads to a Volume, two paths to manage, and two version numbers to keep in sync. If a user forgot the sparkcleaner JAR or used mismatched versions, the connection silently broke with confusing errors.

### Precedent: The AWS Glue Project

The `neo4j-aws-glue` project already does exactly this for AWS Glue. It is a small Maven project that:

- Depends on `neo4j-jdbc`, `neo4j-jdbc-translator-impl`, and `neo4j-jdbc-translator-sparkcleaner`
- Adds its own custom translator (`AwsGlueTranslator`) that rewrites `WHERE 1=0` to `LIMIT 1` for Glue's schema probing behavior
- Uses `maven-shade-plugin` to merge everything into a single JAR with relocated packages (Jackson, Netty, jOOQ, Bolt, Cypher DSL, etc.) under `org.neo4j.jdbc.internal.shaded.*` to avoid classpath conflicts
- Registers the custom translator via Java SPI (`META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory`)
- Produces a self-contained JAR that users drop into AWS Glue with zero additional setup

This project follows the same pattern.

### Custom Databricks Translator

The AWS Glue project has a custom `AwsGlueTranslator` because AWS Glue sends its own `WHERE 1=0` pattern for schema probing that differs from Spark's. Databricks uses standard Spark through SafeSpark, so the existing `neo4j-jdbc-translator-sparkcleaner` handles the subquery wrapping without any additional custom translator.

If testing reveals Databricks-specific SQL patterns that the existing translators don't handle (for example, SafeSpark may introduce its own query wrapping beyond what standard Spark does), a custom `DatabricksTranslator` can be added later following the same SPI pattern. The project structure accommodates this possibility even if the current version ships without one.

### SPI Service Registration

Unlike the AWS Glue project, there is no custom translator factory to register via SPI. The bundled `neo4j-jdbc-translator-sparkcleaner` and `neo4j-jdbc-translator-impl` JARs each include their own `META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory` files. The `ServicesResourceTransformer` in the maven-shade-plugin automatically merges these SPI registrations into the shaded JAR, so no custom services file is needed. If a `DatabricksTranslator` is added later, its factory would be registered via a new services file at that point.

### User-Agent Identification

The project includes a `META-INF/neo4j-jdbc-user-agent.txt` file containing:

```
neo4j-unity-catalog-connector/${project.version}
```

This string is sent by the Neo4j JDBC driver to the Neo4j server with every connection. The `${project.version}` placeholder is substituted by Maven at build time (via `<filtering>true</filtering>` in the pom.xml). This lets Neo4j (especially Aura) distinguish connections coming from the Databricks UC connector vs the plain JDBC driver vs the Glue connector — useful for support, usage analytics, and debugging.

### Package Relocation

All bundled dependencies are relocated to avoid conflicts with whatever JARs are already on the Databricks SafeSpark sandbox classpath. The relocation scheme from the AWS Glue project (`org.neo4j.jdbc.internal.shaded.*`) is reused as-is since it was designed by the Neo4j Connectors team for exactly this purpose.

### Impact on the User Experience

**Before (two JARs):**
```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '[
    "/Volumes/catalog/schema/jars/neo4j-jdbc-full-bundle-6.10.5.jar",
    "/Volumes/catalog/schema/jars/neo4j-jdbc-translator-sparkcleaner-6.10.5.jar"
  ]'
)
OPTIONS (...)
```

**After (one JAR):**
```sql
CREATE CONNECTION neo4j_connection TYPE JDBC
ENVIRONMENT (
  java_dependencies '["/Volumes/catalog/schema/jars/neo4j-unity-catalog-connector-1.0.0.jar"]'
)
OPTIONS (...)
```

### Decisions

1. **Repo location:** Subdirectory within `neo4j-uc-integration` (`neo4j-unity-catalog-connector/`).

2. **Artifact naming:** `neo4j-unity-catalog-connector` (groupId: `org.neo4j`, artifactId: `neo4j-unity-catalog-connector`).

3. **Version alignment:** Independent versioning (starting at `1.0.0-SNAPSHOT`), with the upstream `neo4j-jdbc` dependency version pinned separately (initially `6.10.5`).

4. **Custom translator:** Not needed initially. The existing `sparkcleaner` translator handles Databricks/Spark subquery wrapping. If testing reveals Databricks-specific SQL patterns, a `DatabricksTranslator` can be added following the `AwsGlueTranslator` SPI pattern.

### Implementation Progress

#### Phase 1: Create the Maven Project — COMPLETE

Built and verified locally. The `neo4j-unity-catalog-connector/` subdirectory contains:

```
neo4j-unity-catalog-connector/
├── .mvn/wrapper/
│   ├── maven-wrapper.jar
│   └── maven-wrapper.properties
├── src/
│   ├── main/resources/META-INF/
│   │   └── neo4j-jdbc-user-agent.txt
│   └── test/java/org/neo4j/uc/
│       └── BundledTranslatorsTest.java
├── mvnw
├── mvnw.cmd
├── pom.xml
└── README.md
```

**Build verification:**
- `./mvnw clean verify` succeeds (6 tests pass)
- Produces `neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar` (11MB)
- User-agent in JAR: `neo4j-unity-catalog-connector/1.0.0-SNAPSHOT`
- SPI services merged: `SqlToCypherTranslatorFactory` + `SparkSubqueryCleaningTranslatorFactory`
- 5952 classes relocated under `org.neo4j.jdbc.internal.shaded.*`

**Unit tests (`BundledTranslatorsTest`):**
- SPI discovery: verifies both `SqlToCypherTranslatorFactory` and `SparkSubqueryCleaningTranslatorFactory` are found via `ServiceLoader`
- Factory creation: verifies all discovered factories produce non-null `Translator` instances
- Pipeline integration: verifies the full translator pipeline (spark cleaner + SQL-to-Cypher) processes Spark-wrapped queries without error and removes `SPARK_GEN_SUBQ` wrapping
- Spark cleaner pass-through: verifies the cleaner handles plain Cypher without throwing
- JDBC driver loading: verifies `org.neo4j.jdbc.Neo4jDriver` is on the classpath

**CI/CD workflows added:**
- `.github/workflows/connector-build.yml` — builds on push to `main` and PRs, scoped to `neo4j-unity-catalog-connector/` path changes
- `.github/workflows/connector-release.yml` — publishes GitHub Release on `connector-*` tags

#### Phase 2: Validate with Databricks — NOT STARTED

#### Phase 3: Update Documentation — NOT STARTED

#### Phase 4: CI/CD and Release — PARTIAL
- GitHub Actions workflows created (build + release)
- Dependabot configuration not yet added
- Maven Central publishing decision deferred
