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
import java.sql.SQLException;
import java.util.Collections;
import java.util.List;
import java.util.Map;

public class ApocSchemaTests {

	public void run(Connection connection) throws SQLException {
		System.out.println("=== APOC Schema Discovery Tests ===");
		System.out.println();

		// 1. APOC Availability Check
		var apocVersion = getApocVersion(connection);
		if (apocVersion == null) {
			System.out.println("APOC is NOT installed or unavailable. Skipping APOC tests.");
			return;
		}
		System.out.printf("APOC Version: %s%n", apocVersion);
		System.out.println();

		// 2. Node Type Properties Discovery
		System.out.println("--- Node Type Properties (apoc.meta.nodeTypeProperties) ---");
		discoverNodeTypeProperties(connection);
		System.out.println();

		// 3. Relationship Type Properties Discovery
		System.out.println("--- Relationship Type Properties (apoc.meta.relTypeProperties) ---");
		discoverRelTypeProperties(connection);
		System.out.println();
	}

	private String getApocVersion(Connection connection) {
		try (var statement = connection.createStatement()) {
			var rs = statement.executeQuery("RETURN apoc.version() AS version");
			if (rs.next()) {
				return rs.getString("version");
			}
		}
		catch (SQLException e) {
			// APOC not available or other error
		}
		return null;
	}

	private void discoverNodeTypeProperties(Connection connection) throws SQLException {
		// Demonstrate configuration: sampling
		// We use a PreparedStatement to pass the map if possible, but JDBC driver might not support map params easily in standard SQL
		// Actually, Neo4j JDBC supports passing maps as parameters if we use Cypher syntax
		// or we can stringify it. For simplicity, we'll just execute the statement with a literal map for demo.
		
		String query = "CALL apoc.meta.nodeTypeProperties({sample: 100})";
		
		try (var stmt = connection.createStatement();
			 var rs = stmt.executeQuery(query)) {
			
			System.out.printf("%-20s %-20s %-20s %-10s%n", "NodeType", "PropertyName", "PropertyTypes", "Mandatory");
			System.out.println("-------------------------------------------------------------------------");
			
			while (rs.next()) {
				// The result columns from apoc.meta.nodeTypeProperties are:
				// nodeType, nodeLabels, propertyName, propertyTypes, mandatory, cardinality, ...
				
				String nodeType = rs.getString("nodeType");
				String propertyName = rs.getString("propertyName");
				// propertyTypes is a List, but JDBC might return it as Array or Object (List)
				Object propertyTypesObj = rs.getObject("propertyTypes");
				boolean mandatory = rs.getBoolean("mandatory");

				System.out.printf("%-20s %-20s %-20s %-10b%n", 
						truncate(nodeType, 20), 
						truncate(propertyName, 20), 
						truncate(String.valueOf(propertyTypesObj), 20), 
						mandatory);
			}
		}
	}

	private void discoverRelTypeProperties(Connection connection) throws SQLException {
		String query = "CALL apoc.meta.relTypeProperties({sample: 100})";
		
		try (var stmt = connection.createStatement();
			 var rs = stmt.executeQuery(query)) {
			
			System.out.printf("%-30s %-20s %-20s %-20s%n", "RelType", "Source", "Target", "PropertyName");
			System.out.println("------------------------------------------------------------------------------------------------");
			
			while (rs.next()) {
				// Columns: relType, sourceNodeLabels, targetNodeLabels, propertyName, propertyTypes, ...
				
				String relType = rs.getString("relType");
				// sourceNodeLabels is List
				Object sourceObj = rs.getObject("sourceNodeLabels");
				Object targetObj = rs.getObject("targetNodeLabels");
				String propertyName = rs.getString("propertyName");

				System.out.printf("%-30s %-20s %-20s %-20s%n", 
						truncate(relType, 30),
						truncate(String.valueOf(sourceObj), 20),
						truncate(String.valueOf(targetObj), 20),
						truncate(propertyName, 20));
			}
		}
	}

	private String truncate(String s, int maxLen) {
		if (s == null) return "null";
		if (s.length() <= maxLen) return s;
		return s.substring(0, maxLen - 3) + "...";
	}
}
