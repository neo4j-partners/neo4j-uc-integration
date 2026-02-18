# Request for Reference Customers: Neo4j + Databricks Unity Catalog Integration

**To:** Neo4j Field Team
**From:** Ryan Knight
**Subject:** Need reference customers for Neo4j JDBC + Databricks Unity Catalog integration

---

Hi team,

We need your help surfacing customers who run both Neo4j and Databricks. We have a working integration that lets Databricks users query Neo4j through Unity Catalog using the Neo4j JDBC driver, and we are requesting Databricks to add official support. They prioritize based on customer demand, so even a brief email from a customer to their Databricks account team expressing interest would move the needle. Ideal candidates are organizations that currently move data between the two platforms manually, or teams with graph data in Neo4j that their Databricks analysts cannot access today. Any assistance would be greatly appreciated.

## What the integration does

The Neo4j JDBC driver plugs into Databricks Unity Catalog's custom JDBC support to enable federated queries against Neo4j from inside Databricks. SQL queries get translated to Cypher automatically, so analysts can query graph data without learning a new language. Results come back as standard Spark DataFrames and can be joined with Delta tables, Iceberg tables, or any other UC data source. All connections run under Unity Catalog governance with access controls, audit logging, and credentials stored in Databricks Secrets.

## What this means in practice

Consider a fraud detection team with transaction data in Delta tables and entity relationships (accounts, devices, shared identifiers) in Neo4j. Today, combining those datasets requires custom ETL or duplicate copies. With this integration, a single Databricks notebook joins Neo4j graph traversal results with Delta table aggregations in one query. No data movement, no pipeline to maintain. The integration supports aggregates, filtered queries, COUNT DISTINCT, and multi-hop traversals expressed as SQL JOINs, with aggregation pushed down to Neo4j so only results travel over the network.

Thanks for any leads you can surface.

Best,
Ryan
