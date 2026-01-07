# Spring Boot Neo4j Demo

A basic Spring Boot 4.0.1 application that connects to Neo4j and prints the database schema on startup.

## Prerequisites

- Java 21 or higher.
- A running Neo4j instance.

## Configuration

Update the Neo4j connection details in `src/main/resources/application.properties`:

```properties
spring.neo4j.uri=bolt://localhost:7687
spring.neo4j.authentication.username=neo4j
spring.neo4j.authentication.password=password
```

## Running the Application

You can run the application using the included Maven Wrapper:

```bash
./mvnw spring-boot:run
```

## Features

- **Spring Boot 4.0.1**: Utilizing the latest stable version of Spring Boot.
- **Neo4j Integration**: Uses `spring-boot-starter-data-neo4j`.
- **Schema Inspection**: Automatically executes `CALL db.schema.visualization()` and prints the result to the console upon startup using a `CommandLineRunner`.
