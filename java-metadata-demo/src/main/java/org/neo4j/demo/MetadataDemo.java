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
import java.sql.DriverManager;
import java.sql.SQLException;

import io.github.cdimascio.dotenv.Dotenv;

/**
 * Demonstrates how the Neo4j JDBC driver exposes graph schema as relational metadata
 * through standard JDBC DatabaseMetaData APIs.
 * <p>
 * This capability is foundational for synchronizing Neo4j graph schema with relational
 * catalogs like Unity Catalog.
 *
 * @author Neo4j Drivers Team
 */
public final class MetadataDemo {

	private MetadataDemo() {
	}

	public static void main(String[] args) {
		var config = parseConfig(args);

		if (config.url == null) {
			printUsage();
			System.exit(1);
		}

		try (var connection = DriverManager.getConnection(config.url, config.username, config.password)) {
			
			if ("standard".equalsIgnoreCase(config.testMode) || "all".equalsIgnoreCase(config.testMode)) {
				new SchemaMetadataTests().run(connection);
			}
			
			if ("apoc".equalsIgnoreCase(config.testMode) || "all".equalsIgnoreCase(config.testMode)) {
				new ApocSchemaTests().run(connection);
			}
			
		}
		catch (SQLException ex) {
			System.err.println("Database error: " + ex.getMessage());
			System.exit(1);
		}
	}

	private static Config parseConfig(String[] args) {
		// Load from .env file (if present), falling back to system environment
		var dotenv = Dotenv.configure().ignoreIfMissing().load();

		var url = dotenv.get("NEO4J_URL");
		var username = dotenv.get("NEO4J_USERNAME");
		var password = dotenv.get("NEO4J_PASSWORD");
		var testMode = "standard"; // Default to standard JDBC metadata

		// Command-line arguments override .env and environment variables
		for (int i = 0; i < args.length; i++) {
			switch (args[i]) {
				case "--url", "-u" -> {
					if (i + 1 < args.length) {
						url = args[++i];
					}
				}
				case "--username", "--user" -> {
					if (i + 1 < args.length) {
						username = args[++i];
					}
				}
				case "--password", "--pass" -> {
					if (i + 1 < args.length) {
						password = args[++i];
					}
				}
				case "--test", "-t" -> {
					if (i + 1 < args.length) {
						testMode = args[++i];
					}
				}
				case "--help", "-h" -> {
					printUsage();
					System.exit(0);
				}
			}
		}

		return new Config(url, username, password, testMode);
	}

	private static void printUsage() {
		System.out.println("Neo4j JDBC Metadata Demo");
		System.out.println();
		System.out.println("Usage: java -jar metadata-demo.jar [options]");
		System.out.println();
		System.out.println("Options:");
		System.out.println("  --url, -u <url>       JDBC URL (e.g., jdbc:neo4j://localhost:7687)");
		System.out.println("  --username, --user    Database username");
		System.out.println("  --password, --pass    Database password");
		System.out.println("  --test, -t <mode>     Test mode: 'standard' (default), 'apoc', or 'all'");
		System.out.println("  --help, -h            Show this help message");
		System.out.println();
		System.out.println("Configuration (in order of precedence):");
		System.out.println("  1. Command-line arguments");
		System.out.println("  2. .env file in current directory");
		System.out.println("  3. System environment variables");
		System.out.println();
		System.out.println("Environment variables / .env keys:");
		System.out.println("  NEO4J_URL             JDBC URL");
		System.out.println("  NEO4J_USERNAME        Database username");
		System.out.println("  NEO4J_PASSWORD        Database password");
		System.out.println();
		System.out.println("Example using .env file:");
		System.out.println("  cp env.sample .env");
		System.out.println("  # Edit .env with your credentials");
		System.out.println("  java -jar metadata-demo.jar");
	}

	private record Config(String url, String username, String password, String testMode) {
	}

}