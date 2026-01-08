# Building Neo4j JDBC Driver with Spark Cleaner

This document describes the steps required to build a custom Neo4j JDBC Full Bundle that includes the Spark Cleaner (`SparkSubqueryCleaningTranslator`) module.

## Prerequisites

### Java Version

The Neo4j JDBC Driver requires **Java 25** to build (though the output targets Java 17 runtime).

```bash
# Check available Java 25 versions with SDKMAN
sdk list java | grep -i "25"

# Install Temurin 25 (recommended)
sdk install java 25.0.1-tem

# Switch to Java 25
sdk use java 25.0.1-tem

# Verify
java -version
# Expected output: openjdk version "25.0.1" ...
```

**Note:** The project uses `java-build.version=25` for building but `java.version=17` for bytecode compatibility. The resulting JAR runs on Java 17+.

### Maven

Maven 3.9.11+ is required. The project includes a Maven wrapper (`./mvnw`).

---

## POM File Modifications

Two changes were made to `bundles/neo4j-jdbc-full-bundle/pom.xml`:

### 1. Add Dependency (lines 63-66)

Add the sparkcleaner dependency alongside the existing translator:

```xml
<dependencies>
    <dependency>
        <groupId>org.neo4j</groupId>
        <artifactId>neo4j-jdbc</artifactId>
    </dependency>
    <dependency>
        <groupId>org.neo4j</groupId>
        <artifactId>neo4j-jdbc-translator-impl</artifactId>
    </dependency>
    <!-- ADD THIS DEPENDENCY -->
    <dependency>
        <groupId>org.neo4j</groupId>
        <artifactId>neo4j-jdbc-translator-sparkcleaner</artifactId>
    </dependency>
    <!-- ... other dependencies ... -->
</dependencies>
```

### 2. Add to Shade Plugin Includes (line 173)

Add the sparkcleaner to the Maven Shade Plugin's artifact set so it gets bundled into the uber-JAR:

```xml
<artifactSet>
    <includes>
        <!-- ... existing includes ... -->
        <include>org.neo4j:neo4j-jdbc-translator-spi:*</include>
        <include>org.neo4j:neo4j-jdbc-translator-impl:*</include>
        <!-- ADD THIS LINE -->
        <include>org.neo4j:neo4j-jdbc-translator-sparkcleaner:*</include>
        <include>org.neo4j:neo4j-jdbc:*</include>
        <!-- ... other includes ... -->
    </includes>
</artifactSet>
```

---

## Build Script

A build script `build-with-sparkcleaner.sh` was created to automate the build and verification:

```bash
#!/bin/bash
#
# Copyright (c) 2023-2026 "Neo4j,"
# Neo4j Sweden AB [https://neo4j.com]
#
# This file is part of Neo4j.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Build and test the Neo4j JDBC Full Bundle with Spark Cleaner included
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================="
echo "Building Neo4j JDBC with Spark Cleaner"
echo "=============================================="

# Step 1: Build the sparkcleaner module first (and its dependencies)
echo ""
echo "[1/3] Building sparkcleaner module..."
./mvnw -Dfast package -pl neo4j-jdbc-translator/sparkcleaner -am -DskipTests

# Step 2: Build the full bundle (which now includes sparkcleaner)
echo ""
echo "[2/3] Building full bundle with sparkcleaner..."
./mvnw -Dfast package -pl bundles/neo4j-jdbc-full-bundle -am -DskipTests

# Step 3: Verify the sparkcleaner is included in the bundle
echo ""
echo "[3/3] Verifying sparkcleaner is included in bundle..."
BUNDLE_JAR=$(ls bundles/neo4j-jdbc-full-bundle/target/neo4j-jdbc-full-bundle-*.jar | grep -v sources | head -1)

echo "Bundle JAR: $BUNDLE_JAR"

if jar tf "$BUNDLE_JAR" | grep -q "SparkSubqueryCleaningTranslator.class"; then
    echo "SUCCESS: SparkSubqueryCleaningTranslator.class found in bundle!"
    jar tf "$BUNDLE_JAR" | grep "sparkcleaner.*\.class" | head -5
else
    echo "WARNING: SparkSubqueryCleaningTranslator NOT found in bundle"
    echo "Checking JAR contents..."
    jar tf "$BUNDLE_JAR" | grep -i spark || echo "No spark-related classes found"
fi

# Check for SPI service file
echo ""
echo "Checking for SPI service registration..."
if jar tf "$BUNDLE_JAR" | grep -q "META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory"; then
    echo "SPI service file found. Contents:"
    unzip -p "$BUNDLE_JAR" META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory
    echo ""
    if unzip -p "$BUNDLE_JAR" META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory | grep -q "SparkSubqueryCleaningTranslatorFactory"; then
        echo "SUCCESS: SparkSubqueryCleaningTranslatorFactory is registered in SPI!"
    else
        echo "WARNING: SparkSubqueryCleaningTranslatorFactory NOT in SPI file"
    fi
else
    echo "WARNING: SPI service file not found"
fi

echo ""
echo "=============================================="
echo "Build complete!"
echo "Bundle location: $BUNDLE_JAR"
echo "=============================================="

# Optional: Run tests
if [ "$1" == "--test" ]; then
    echo ""
    echo "Running sparkcleaner tests..."
    ./mvnw test -pl neo4j-jdbc-translator/sparkcleaner -am -Dlicense.skip=true

    echo ""
    echo "Running full bundle integration tests..."
    ./mvnw verify -pl bundles/neo4j-jdbc-full-bundle -Dlicense.skip=true
fi
```

### Usage

```bash
# Build only
./build-with-sparkcleaner.sh

# Build and run tests
./build-with-sparkcleaner.sh --test
```

---

## Verification Steps

### 1. Verify Classes Are Included

Check that the Spark Cleaner classes are in the bundle JAR:

```bash
jar tf bundles/neo4j-jdbc-full-bundle/target/neo4j-jdbc-full-bundle-*.jar | grep sparkcleaner
```

Expected output:
```
org/neo4j/jdbc/translator/sparkcleaner/
org/neo4j/jdbc/translator/sparkcleaner/package-info.class
org/neo4j/jdbc/translator/sparkcleaner/SparkSubqueryCleaningTranslator.class
org/neo4j/jdbc/translator/sparkcleaner/SparkSubqueryCleaningTranslatorFactory.class
org/neo4j/jdbc/translator/sparkcleaner/internal/shaded/...
```

### 2. Verify SPI Registration

Check that the translator factory is registered in the SPI service file:

```bash
unzip -p bundles/neo4j-jdbc-full-bundle/target/neo4j-jdbc-full-bundle-*.jar \
    META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory
```

Expected output:
```
org.neo4j.jdbc.translator.impl.SqlToCypherTranslatorFactory
org.neo4j.jdbc.translator.sparkcleaner.SparkSubqueryCleaningTranslatorFactory
```

Both factories must be present for the translator chain to work correctly.

### 3. Run Unit Tests

```bash
./mvnw test -pl neo4j-jdbc-translator/sparkcleaner -am -Dlicense.skip=true
```

Expected output:
```
[INFO] Tests run: 19, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS
```

---

## Build Output

After a successful build, the bundle JAR is located at:

```
bundles/neo4j-jdbc-full-bundle/target/neo4j-jdbc-full-bundle-6.10.4-SNAPSHOT.jar
```

This JAR contains:
- Core Neo4j JDBC Driver
- SQL-to-Cypher Translator (`SqlToCypherTranslatorFactory`)
- Spark Cleaner (`SparkSubqueryCleaningTranslatorFactory`)
- All shaded dependencies (Netty, jOOQ, Cypher DSL, etc.)

---

## Quick Reference Commands

| Task | Command |
|------|---------|
| Install Java 25 | `sdk install java 25.0.1-tem` |
| Switch to Java 25 | `sdk use java 25.0.1-tem` |
| Build with script | `./build-with-sparkcleaner.sh` |
| Build and test | `./build-with-sparkcleaner.sh --test` |
| Manual fast build | `./mvnw -Dfast package -pl bundles/neo4j-jdbc-full-bundle -am -DskipTests` |
| Run sparkcleaner tests | `./mvnw test -pl neo4j-jdbc-translator/sparkcleaner -am -Dlicense.skip=true` |
| Verify JAR contents | `jar tf bundles/neo4j-jdbc-full-bundle/target/neo4j-jdbc-full-bundle-*.jar \| grep sparkcleaner` |
| Check SPI file | `unzip -p bundles/neo4j-jdbc-full-bundle/target/neo4j-jdbc-full-bundle-*.jar META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory` |

---

## Troubleshooting

### Wrong Java Version

```
[ERROR] Detected JDK is version X which is not in the allowed range [25,).
```

**Solution:** Install and switch to Java 25:
```bash
sdk install java 25.0.1-tem
sdk use java 25.0.1-tem
```

### License Header Errors

```
[ERROR] Some files do not have the expected license header.
```

**Solution:** Add `-Dlicense.skip=true` to skip license checks, or run:
```bash
./mvnw license:format
```

### Missing Dependencies

```
[ERROR] Could not find artifact org.neo4j:neo4j-jdbc-translator-spi:jar
```

**Solution:** Use `-am` (also make) to build dependencies:
```bash
./mvnw package -pl neo4j-jdbc-translator/sparkcleaner -am
```

---

## Files Modified/Created

| File | Change |
|------|--------|
| `bundles/neo4j-jdbc-full-bundle/pom.xml` | Added sparkcleaner dependency and shade plugin include |
| `build-with-sparkcleaner.sh` | Created - build automation script |
| `CLEANER.md` | Created - Spark Cleaner documentation |
| `CLEANING_BUILD.md` | Created - This build guide |
