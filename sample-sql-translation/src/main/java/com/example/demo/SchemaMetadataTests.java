package com.example.demo;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Demonstrates Neo4j JDBC Driver's DatabaseMetaData capabilities for schema discovery.
 *
 * The Neo4j JDBC driver exposes graph schema through standard JDBC metadata APIs:
 * - Labels → Tables (TABLE type)
 * - Relationships → Virtual Tables (RELATIONSHIP type) in format {Label1}_{RelType}_{Label2}
 * - Properties → Columns with SQL type mapping
 * - Element IDs → Primary Keys (v$id artificial column)
 *
 * This enables Unity Catalog and other SQL tools to discover Neo4j graph schema
 * without requiring native Cypher queries.
 *
 * @see <a href="https://neo4j.com/docs/jdbc-manual/current/">Neo4j JDBC Driver Manual</a>
 */
public class SchemaMetadataTests {

    /**
     * Run all schema metadata tests against the provided connection.
     *
     * @param connection Active JDBC connection to Neo4j
     */
    public static void runAllTests(Connection connection) {
        System.out.println("\n" + "=".repeat(70));
        System.out.println("SCHEMA METADATA TESTS - Neo4j JDBC DatabaseMetaData API");
        System.out.println("=".repeat(70));

        try {
            DatabaseMetaData metaData = connection.getMetaData();

            // Print driver info
            printDriverInfo(metaData);

            // Test 1: Discover catalogs (databases)
            testGetCatalogs(metaData);

            // Test 2: Discover schemas
            testGetSchemas(metaData);

            // Test 3: Discover tables (labels and relationships)
            List<String> labels = testGetTables(metaData);

            // Test 4: Discover columns for discovered labels
            if (!labels.isEmpty()) {
                testGetColumns(metaData, labels.get(0)); // Test with first label
            }

            // Test 5: Discover primary keys
            if (!labels.isEmpty()) {
                testGetPrimaryKeys(metaData, labels.get(0));
            }

            // Test 6: Show relationship virtual tables
            testGetRelationshipTables(metaData);

            // Test 7: Print schema summary
            printSchemaSummary(metaData);

        } catch (SQLException e) {
            System.err.println("[FAIL] Schema metadata tests failed: " + e.getMessage());
            e.printStackTrace();
        }
    }

    /**
     * Print JDBC driver information.
     */
    private static void printDriverInfo(DatabaseMetaData metaData) throws SQLException {
        System.out.println("\n--- [INFO] JDBC Driver Information ---");
        System.out.println("Driver Name: " + metaData.getDriverName());
        System.out.println("Driver Version: " + metaData.getDriverVersion());
        System.out.println("Database Product: " + metaData.getDatabaseProductName());
        System.out.println("Database Version: " + metaData.getDatabaseProductVersion());
        System.out.println("Catalog Term: " + metaData.getCatalogTerm());
        System.out.println("Schema Term: " + metaData.getSchemaTerm());
    }

    /**
     * Test getCatalogs() - Returns Neo4j databases.
     *
     * Neo4j supports multiple databases (e.g., "neo4j", "system").
     * Each database appears as a catalog in JDBC terms.
     */
    private static void testGetCatalogs(DatabaseMetaData metaData) throws SQLException {
        System.out.println("\n--- [TEST] getCatalogs() - Neo4j Databases ---");

        try (ResultSet rs = metaData.getCatalogs()) {
            List<String> catalogs = new ArrayList<>();
            while (rs.next()) {
                String catalog = rs.getString("TABLE_CAT");
                catalogs.add(catalog);
            }

            if (catalogs.isEmpty()) {
                System.out.println("[INFO] No catalogs returned (may require elevated privileges)");
            } else {
                System.out.println("[PASS] Found " + catalogs.size() + " catalog(s): " + catalogs);
            }
        }
    }

    /**
     * Test getSchemas() - Returns the default "public" schema.
     *
     * Neo4j uses a single "public" schema for all objects.
     * This is a simplification from the graph model.
     */
    private static void testGetSchemas(DatabaseMetaData metaData) throws SQLException {
        System.out.println("\n--- [TEST] getSchemas() - Database Schemas ---");

        try (ResultSet rs = metaData.getSchemas()) {
            while (rs.next()) {
                String schema = rs.getString("TABLE_SCHEM");
                String catalog = rs.getString("TABLE_CATALOG");
                System.out.println("[PASS] Schema: " + schema + " (Catalog: " + catalog + ")");
            }
        }
    }

    /**
     * Test getTables() - Returns labels as TABLE type and relationships as RELATIONSHIP type.
     *
     * The Neo4j JDBC driver maps:
     * - Node labels → TABLE type
     * - Relationships → RELATIONSHIP type (virtual tables in format Label1_RelType_Label2)
     * - Cypher-backed views → CBV type
     *
     * @return List of discovered label names (TABLE type only)
     */
    private static List<String> testGetTables(DatabaseMetaData metaData) throws SQLException {
        System.out.println("\n--- [TEST] getTables() - Labels as Tables ---");

        List<String> labels = new ArrayList<>();

        // Query only TABLE type (node labels)
        try (ResultSet rs = metaData.getTables(null, null, null, new String[]{"TABLE"})) {
            System.out.println("\nNode Labels (TABLE type):");
            int count = 0;
            while (rs.next()) {
                String tableName = rs.getString("TABLE_NAME");
                String tableType = rs.getString("TABLE_TYPE");
                String remarks = rs.getString("REMARKS");

                labels.add(tableName);
                count++;
                if (count <= 10) {
                    System.out.println("  - " + tableName + " [" + tableType + "]" +
                        (remarks != null ? " - " + remarks : ""));
                }
            }

            if (count > 10) {
                System.out.println("  ... and " + (count - 10) + " more labels");
            }

            System.out.println("\n[PASS] Discovered " + count + " node labels as tables");
        }

        return labels;
    }

    /**
     * Test getTables() for RELATIONSHIP type - Virtual tables for relationships.
     *
     * Relationships are exposed as virtual tables in format: {SourceLabel}_{RelType}_{TargetLabel}
     * The REMARKS column contains relationship metadata.
     */
    private static void testGetRelationshipTables(DatabaseMetaData metaData) throws SQLException {
        System.out.println("\n--- [TEST] getTables(RELATIONSHIP) - Relationship Virtual Tables ---");

        try (ResultSet rs = metaData.getTables(null, null, null, new String[]{"RELATIONSHIP"})) {
            System.out.println("\nRelationship Patterns (RELATIONSHIP type):");
            int count = 0;
            while (rs.next()) {
                String tableName = rs.getString("TABLE_NAME");
                String remarks = rs.getString("REMARKS");

                count++;
                if (count <= 10) {
                    // Parse remarks to show pattern nicely
                    if (remarks != null) {
                        String[] parts = remarks.split("\n");
                        if (parts.length >= 3) {
                            System.out.println("  - (:" + parts[0] + ")-[:" + parts[1] + "]->(:" + parts[2] + ")");
                        } else {
                            System.out.println("  - " + tableName);
                        }
                    } else {
                        System.out.println("  - " + tableName);
                    }
                }
            }

            if (count > 10) {
                System.out.println("  ... and " + (count - 10) + " more relationships");
            }

            if (count == 0) {
                System.out.println("  (No relationships found - graph may be empty or disconnected)");
            } else {
                System.out.println("\n[PASS] Discovered " + count + " relationship patterns");
            }
        }
    }

    /**
     * Test getColumns() - Returns properties as columns for a given label.
     *
     * The Neo4j JDBC driver maps:
     * - Properties → Columns with appropriate SQL types
     * - v$id → Artificial column for element ID (IS_GENERATEDCOLUMN=YES)
     *
     * Type mapping: STRING→VARCHAR, INTEGER→BIGINT, FLOAT→DOUBLE, BOOLEAN→BOOLEAN, etc.
     */
    private static void testGetColumns(DatabaseMetaData metaData, String tableName) throws SQLException {
        System.out.println("\n--- [TEST] getColumns('" + tableName + "') - Properties as Columns ---");

        try (ResultSet rs = metaData.getColumns(null, null, tableName, null)) {
            System.out.println("\nColumns for label '" + tableName + "':");

            int count = 0;
            while (rs.next()) {
                String columnName = rs.getString("COLUMN_NAME");
                String typeName = rs.getString("TYPE_NAME");
                int dataType = rs.getInt("DATA_TYPE");
                String isNullable = rs.getString("IS_NULLABLE");
                String isGenerated = rs.getString("IS_GENERATEDCOLUMN");
                int ordinal = rs.getInt("ORDINAL_POSITION");

                count++;
                String generated = "YES".equals(isGenerated) ? " [generated]" : "";
                System.out.println("  " + ordinal + ". " + columnName + " : " + typeName +
                    " (SQL type " + dataType + ", nullable=" + isNullable + ")" + generated);
            }

            if (count == 0) {
                System.out.println("  (No columns found for this label)");
            } else {
                System.out.println("\n[PASS] Discovered " + count + " columns (properties) for '" + tableName + "'");
            }
        }
    }

    /**
     * Test getPrimaryKeys() - Returns primary key information.
     *
     * Neo4j JDBC returns:
     * - Unique constraint columns if exactly one UNIQUE constraint exists
     * - Otherwise, the artificial v$id column (element ID)
     */
    private static void testGetPrimaryKeys(DatabaseMetaData metaData, String tableName) throws SQLException {
        System.out.println("\n--- [TEST] getPrimaryKeys('" + tableName + "') ---");

        try (ResultSet rs = metaData.getPrimaryKeys(null, null, tableName)) {
            System.out.println("\nPrimary Key for '" + tableName + "':");

            int count = 0;
            while (rs.next()) {
                String columnName = rs.getString("COLUMN_NAME");
                String pkName = rs.getString("PK_NAME");
                int keySeq = rs.getInt("KEY_SEQ");

                count++;
                System.out.println("  - Column: " + columnName + ", Key Seq: " + keySeq + ", PK Name: " + pkName);
            }

            if (count == 0) {
                System.out.println("  (No primary key defined)");
            } else {
                System.out.println("\n[PASS] Found " + count + " primary key column(s)");
            }
        }
    }

    /**
     * Print a summary of the discovered schema suitable for UC foreign table generation.
     */
    private static void printSchemaSummary(DatabaseMetaData metaData) throws SQLException {
        System.out.println("\n" + "=".repeat(70));
        System.out.println("SCHEMA DISCOVERY SUMMARY");
        System.out.println("=".repeat(70));

        // Collect all tables with their columns
        Map<String, List<String>> schema = new LinkedHashMap<>();

        try (ResultSet tables = metaData.getTables(null, null, null, new String[]{"TABLE"})) {
            while (tables.next()) {
                String tableName = tables.getString("TABLE_NAME");
                List<String> columns = new ArrayList<>();

                try (ResultSet cols = metaData.getColumns(null, null, tableName, null)) {
                    while (cols.next()) {
                        String colName = cols.getString("COLUMN_NAME");
                        String typeName = cols.getString("TYPE_NAME");
                        columns.add(colName + " " + typeName);
                    }
                }

                schema.put(tableName, columns);
            }
        }

        // Print summary
        System.out.println("\nDiscovered " + schema.size() + " labels with their properties:\n");

        int labelCount = 0;
        for (Map.Entry<String, List<String>> entry : schema.entrySet()) {
            labelCount++;
            if (labelCount <= 5) {
                System.out.println(entry.getKey() + ":");
                for (String col : entry.getValue()) {
                    System.out.println("  - " + col);
                }
                System.out.println();
            }
        }

        if (labelCount > 5) {
            System.out.println("... and " + (labelCount - 5) + " more labels\n");
        }

        // Count relationships
        int relCount = 0;
        try (ResultSet rels = metaData.getTables(null, null, null, new String[]{"RELATIONSHIP"})) {
            while (rels.next()) {
                relCount++;
            }
        }

        System.out.println("Relationship patterns discovered: " + relCount);
        System.out.println("\n[INFO] This schema can be used to generate Unity Catalog foreign tables");
        System.out.println("=".repeat(70));
    }
}
