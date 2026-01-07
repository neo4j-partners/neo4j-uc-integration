package org.neo4j.demo;

import java.util.ArrayList;
import java.util.List;

public final class TableInfo {

	public final String name;

	public final String type;

	public final String remarks;

	public final List<ColumnInfo> columns = new ArrayList<>();

	public final List<String> primaryKeys = new ArrayList<>();

	public TableInfo(String name, String type, String remarks) {
		this.name = name;
		this.type = type;
		this.remarks = remarks;
	}

}
