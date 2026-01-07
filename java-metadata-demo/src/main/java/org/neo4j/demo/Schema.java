package org.neo4j.demo;

import java.util.Map;

public record Schema(Map<String, TableInfo> tables, Map<String, TableInfo> relationships) {
}
