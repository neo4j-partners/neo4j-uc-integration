package org.neo4j.demo;

public record ColumnInfo(String name, String typeName, boolean nullable, boolean generated) {
}
