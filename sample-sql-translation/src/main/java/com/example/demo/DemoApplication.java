package com.example.demo;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.data.neo4j.core.Neo4jClient;
import org.springframework.beans.factory.annotation.Value;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Map;
import java.util.Collection;

@SpringBootApplication
public class DemoApplication {

    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }

    @Bean
    CommandLineRunner demo(Neo4jClient neo4jClient,
                           @Value("${spring.neo4j.uri}") String uri,
                           @Value("${spring.neo4j.authentication.username}") String username,
                           @Value("${spring.neo4j.authentication.password}") String password) {
        return args -> {
            System.out.println("Connecting to Neo4j with SDN...");
            try {
                // Executing a schema visualization query
                Collection<Map<String, Object>> results = neo4jClient
                        .query("CALL db.schema.visualization()")
                        .fetch()
                        .all();
                
                System.out.println("Schema Query Result Count: " + results.size());
                results.forEach(System.out::println);
            } catch (Exception e) {
                System.err.println("Error executing query: " + e.getMessage());
                e.printStackTrace();
            }

            System.out.println("\n--- Starting JDBC SQL Translation Example ---");
            runJdbcExample(uri, username, password);
        };
    }

    private void runJdbcExample(String uri, String username, String password) {
        // Construct JDBC URL
        // Expected format: jdbc:neo4j+s://host:port/database?enableSQLTranslation=true
        // We assume 'uri' is something like "neo4j+s://hostname"
        String jdbcUrl = "jdbc:" + uri + "/neo4j?enableSQLTranslation=true";
        
        System.out.println("JDBC URL: " + jdbcUrl);
        
        try (Connection con = DriverManager.getConnection(jdbcUrl, username, password)) {
            
            // Test 1: Simple Select
            executeJdbcQuery(con, "Simple Select Limit 5", 
                "SELECT * FROM Flight LIMIT 5");

            // Test 2: Aggregates
            executeJdbcQuery(con, "Count Aggregates", 
                "SELECT COUNT(*) AS total_flights FROM Flight");

            // Test 3: Natural Join
            executeJdbcQuery(con, "Natural Join (Flight -> Airport)", 
                "SELECT * FROM Flight f NATURAL JOIN Airport a LIMIT 5");

            // Test 4: Join with ON clause
            executeJdbcQuery(con, "Join with ON clause", 
                "SELECT * FROM Flight f JOIN Airport a ON (a.airport_id = f.DEPARTS_FROM) LIMIT 5");

             // Test 5: Multi-hop Join
            executeJdbcQuery(con, "Multi-hop Join (Aircraft -> Flight)",
                "SELECT * FROM Aircraft ac JOIN Flight f ON (ac.id = f.ASSIGNED_AIRCRAFT) LIMIT 5");

            // Schema Metadata Tests - Demonstrates JDBC DatabaseMetaData API
            // for Neo4j schema discovery (labels as tables, properties as columns)
            SchemaMetadataTests.runAllTests(con);

        } catch (Exception e) {
            System.err.println("JDBC Connection Error: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private void executeJdbcQuery(Connection con, String testName, String sql) {
        System.out.println("\n--- [TEST] " + testName + " ---");
        System.out.println("SQL: " + sql);
        
        try (Statement stmt = con.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            
            int columns = rs.getMetaData().getColumnCount();
            int rowCount = 0;
            while (rs.next()) {
                rowCount++;
                StringBuilder row = new StringBuilder();
                for (int i = 1; i <= columns; i++) {
                    String colName = rs.getMetaData().getColumnName(i);
                    Object val = rs.getObject(i);
                    row.append(colName).append("=").append(val).append(", ");
                }
                // Print only first 5 rows to avoid spamming
                if (rowCount <= 5) {
                    System.out.println("Row " + rowCount + ": " + row.toString());
                }
            }
            if (rowCount > 5) {
                System.out.println("... (Total rows: " + rowCount + ")");
            } else if (rowCount == 0) {
                 System.out.println("(No results found)");
            }
            
        } catch (Exception e) {
            System.err.println("Query Execution Failed: " + e.getMessage());
            // We don't throw here to allow other tests to proceed
        }
    }
}
