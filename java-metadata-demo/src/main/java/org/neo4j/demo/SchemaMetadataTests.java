/*
 * Copyright (c) 2023-2026 "Neo4j,"
 * Neo4j Sweden AB [https://neo4j.com]
 *
 * This file is part of Neo4j.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.neo4j.demo;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * Demonstrates Neo4j JDBC driver's DatabaseMetaData capabilities for schema discovery.
 * <p>
 * Shows how the driver exposes graph schema through standard JDBC metadata APIs,
 * enabling integration with tools like Unity Catalog.
 */
public class SchemaMetadataTests {

	private static final String SEPARATOR = "=".repeat(60);
	private static final String SECTION_SEPARATOR = "-".repeat(60);

	public void run(Connection connection) throws SQLException {
		var metadata = connection.getMetaData();

		printHeader("Neo4j Schema as Relational Metadata");

		// Connection info section
		printSectionHeader("Connection Information");
		System.out.printf("  Database:    %s %s%n",
				metadata.getDatabaseProductName(),
				metadata.getDatabaseProductVersion());
		System.out.printf("  Driver:      %s %s%n",
				metadata.getDriverName(),
				metadata.getDriverVersion());
		System.out.printf("  APOC:        %s%n", getApocStatus(connection));
		System.out.println();

		// Discover schema
		printSectionHeader("Discovering Schema via JDBC DatabaseMetaData");
		var schema = discoverSchema(metadata);
		System.out.printf("  Found %d node labels and %d relationship types%n",
				schema.tables().size(),
				schema.relationships().size());
		System.out.println();

		// Print discovered schema
		printSectionHeader("Node Labels (Tables)");
		printTables(schema);

		printSectionHeader("Relationships (Virtual Tables)");
		printRelationships(schema);

		printSectionHeader("Unity Catalog DDL");
		printUnityCatalogMapping(schema);

		printFooter();
	}

	/**
	 * Check APOC availability and return version or status string.
	 */
	private String getApocStatus(Connection connection) {
		try (var statement = connection.createStatement()) {
			var rs = statement.executeQuery("RETURN apoc.version() AS version");
			if (rs.next()) {
				return "Installed (" + rs.getString("version") + ")";
			}
		} catch (SQLException e) {
			// APOC not available
		}
		return "Not installed";
	}

	private void printHeader(String title) {
		System.out.println();
		System.out.println(SEPARATOR);
		System.out.println("  " + title);
		System.out.println(SEPARATOR);
		System.out.println();
	}

	private void printSectionHeader(String title) {
		System.out.println(SECTION_SEPARATOR);
		System.out.println("  " + title);
		System.out.println(SECTION_SEPARATOR);
	}

	private void printFooter() {
		System.out.println(SEPARATOR);
		System.out.println("  Schema discovery complete");
		System.out.println(SEPARATOR);
		System.out.println();
	}

	private Schema discoverSchema(DatabaseMetaData metadata) throws SQLException {
		var tables = new LinkedHashMap<String, TableInfo>();
		var relationships = new LinkedHashMap<String, TableInfo>();

		// Retrieve all tables
		try (var rs = metadata.getTables(null, null, null, null)) {
			while (rs.next()) {
				var tableName = rs.getString("TABLE_NAME");
				var tableType = rs.getString("TABLE_TYPE");
				var remarks = rs.getString("REMARKS");

				var info = new TableInfo(tableName, tableType, remarks);

				if ("RELATIONSHIP".equals(tableType)) {
					relationships.put(tableName, info);
				}
				else {
					tables.put(tableName, info);
				}
			}
		}

		// Retrieve columns for each table
		for (var entry : tables.entrySet()) {
			entry.getValue().columns.addAll(getColumns(metadata, entry.getKey()));
			entry.getValue().primaryKeys.addAll(getPrimaryKeys(metadata, entry.getKey()));
		}

		for (var entry : relationships.entrySet()) {
			entry.getValue().columns.addAll(getColumns(metadata, entry.getKey()));
		}

		return new Schema(tables, relationships);
	}

	private List<ColumnInfo> getColumns(DatabaseMetaData metadata, String tableName) throws SQLException {
		var columns = new ArrayList<ColumnInfo>();
		try (var rs = metadata.getColumns(null, null, tableName, null)) {
			while (rs.next()) {
				var columnName = rs.getString("COLUMN_NAME");
				var typeName = rs.getString("TYPE_NAME");
				var nullable = rs.getInt("NULLABLE") == DatabaseMetaData.columnNullable;
				var autoIncrement = "YES".equals(rs.getString("IS_AUTOINCREMENT"));
				var generated = "YES".equals(rs.getString("IS_GENERATEDCOLUMN"));

				columns.add(new ColumnInfo(columnName, typeName, nullable, autoIncrement || generated));
			}
		}
		return columns;
	}

	private List<String> getPrimaryKeys(DatabaseMetaData metadata, String tableName) throws SQLException {
		var keys = new ArrayList<String>();
		try (var rs = metadata.getPrimaryKeys(null, null, tableName)) {
			while (rs.next()) {
				keys.add(rs.getString("COLUMN_NAME"));
			}
		}
		return keys;
	}

	private void printTables(Schema schema) {
		if (schema.tables().isEmpty()) {
			System.out.println("  (none found)");
		} else {
			for (var entry : schema.tables().entrySet()) {
				var info = entry.getValue();
				System.out.println();
				System.out.printf("  %s%n", info.name);

				if (!info.columns.isEmpty()) {
					var columnNames = info.columns.stream().map(c -> c.name()).toList();
					System.out.printf("    Columns:     %s%n", String.join(", ", columnNames));
				}

				if (!info.primaryKeys.isEmpty()) {
					System.out.printf("    Primary Key: %s%n", String.join(", ", info.primaryKeys));
				}
			}
		}
		System.out.println();
	}

	private void printRelationships(Schema schema) {
		if (schema.relationships().isEmpty()) {
			System.out.println("  (none found)");
		} else {
			for (var entry : schema.relationships().entrySet()) {
				var info = entry.getValue();
				System.out.println();

				// Parse relationship name to extract start/end labels
				var parts = parseRelationshipName(info.name);
				if (parts != null) {
					System.out.printf("  (:%s)-[:%s]->(:%s)%n",
							parts.startLabel(), parts.relType(), parts.endLabel());
					System.out.printf("    Table Name:  %s%n", info.name);
				} else {
					System.out.printf("  %s%n", info.name);
				}

				if (!info.columns.isEmpty()) {
					var columnNames = info.columns.stream().map(c -> c.name()).toList();
					System.out.printf("    Columns:     %s%n", String.join(", ", columnNames));
				}
			}
		}
		System.out.println();
	}

	private void printUnityCatalogMapping(Schema schema) {
		System.out.println("  -- Generated DDL for Unity Catalog foreign tables");
		System.out.println();

		for (var entry : schema.tables().entrySet()) {
			var info = entry.getValue();
			System.out.printf("  CREATE FOREIGN TABLE %s (%n", info.name);
			printColumnDefinitions(info.columns, info.primaryKeys);
			System.out.println("  ) SERVER neo4j;");
			System.out.println();
		}

		if (!schema.relationships().isEmpty()) {
			System.out.println("  -- Relationship tables");
			System.out.println();
			for (var entry : schema.relationships().entrySet()) {
				var info = entry.getValue();
				System.out.printf("  CREATE FOREIGN TABLE %s (%n", sanitizeTableName(info.name));
				printColumnDefinitions(info.columns, List.of());
				System.out.println("  ) SERVER neo4j;");
				System.out.println();
			}
		}
	}

	private void printColumnDefinitions(List<ColumnInfo> columns, List<String> primaryKeys) {
		for (int i = 0; i < columns.size(); i++) {
			var col = columns.get(i);
			var sqlType = mapToSqlType(col.typeName());
			var nullConstraint = col.nullable() ? "" : " NOT NULL";
			var pkConstraint = primaryKeys.contains(col.name()) ? " PRIMARY KEY" : "";
			var comma = (i < columns.size() - 1) ? "," : "";

			System.out.printf("    %s %s%s%s%s%n", col.name(), sqlType, nullConstraint, pkConstraint, comma);
		}
	}

	private String mapToSqlType(String neo4jType) {
		if (neo4jType == null) {
			return "VARCHAR";
		}
		return switch (neo4jType.toUpperCase()) {
			case "STRING" -> "VARCHAR";
			case "INTEGER", "LONG" -> "BIGINT";
			case "FLOAT", "DOUBLE" -> "DOUBLE";
			case "BOOLEAN" -> "BOOLEAN";
			case "DATE" -> "DATE";
			case "LOCAL_DATETIME", "DATETIME" -> "TIMESTAMP";
			case "DURATION" -> "INTERVAL";
			case "POINT" -> "VARCHAR"; // Spatial types as string representation
			case "LIST" -> "ARRAY";
			default -> "VARCHAR";
		};
	}

	private String sanitizeTableName(String name) {
		// Replace characters that might be problematic in SQL identifiers
		return name.replace("-", "_");
	}

	private RelationshipParts parseRelationshipName(String name) {
		// Expected format: StartLabel_REL_TYPE_EndLabel
		// This is a heuristic - the actual pattern may vary
		var underscoreIdx = name.indexOf('_');
		var lastUnderscoreIdx = name.lastIndexOf('_');

		if (underscoreIdx > 0 && lastUnderscoreIdx > underscoreIdx) {
			var startLabel = name.substring(0, underscoreIdx);
			var relType = name.substring(underscoreIdx + 1, lastUnderscoreIdx);
			var endLabel = name.substring(lastUnderscoreIdx + 1);
			return new RelationshipParts(startLabel, relType, endLabel);
		}
		return null;
	}
}
