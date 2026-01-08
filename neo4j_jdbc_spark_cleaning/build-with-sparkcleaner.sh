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
    ./mvnw test -pl neo4j-jdbc-translator/sparkcleaner

    echo ""
    echo "Running full bundle integration tests..."
    ./mvnw verify -pl bundles/neo4j-jdbc-full-bundle
fi
