# Request for Reference Customers: Neo4j + Databricks Unity Catalog Integration

**To:** Neo4j Field Team
**From:** Ryan Knight
**Subject:** Need reference customers for Neo4j JDBC + Databricks Unity Catalog integration

---

Hi team,

I need your help surfacing customers who run both Neo4j and Databricks. We have a working integration that lets Databricks users query Neo4j through Unity Catalog using the Neo4j JDBC driver, and we are requesting Databricks to add official support. They prioritize based on customer demand, so even a brief snippet of the customer use case would be helpful. The customer name can be anonymous. For example, one customer in the defense industry needs to enforce fine-grained security across all their data sources through Unity Catalog rather than managing access controls separately in each system. Another customer has dozens of data sources and wants to use Unity Catalog to create unified views that join graph data from Neo4j with their lakehouse tables without building custom pipelines for each source. There are a lot of use cases for federated Unity Catalog. Another is for teams with graph data in Neo4j that their Databricks analysts want to access, combining lakehouse data with knowledge graph data. Any customers expressing interest would move the needle. Any assistance would be greatly appreciated.


Some background on how the integration works: the Neo4j JDBC driver plugs into Databricks Unity Catalog's custom JDBC support to enable federated queries against Neo4j from inside Databricks. SQL queries get translated to Cypher automatically, so analysts can query graph data without learning a new language. Results come back as standard Spark DataFrames and can be joined with Delta tables, Iceberg tables, lakehouse relational data, or any other UC data source. All connections run under Unity Catalog governance with access controls, audit logging, and credentials stored in Databricks Secrets.

## What this means in practice

Consider a fraud detection team with transaction data in Delta tables and entity relationships (accounts, devices, shared identifiers) in Neo4j. Today, combining those datasets requires custom ETL or duplicate copies. With this integration, a single Databricks notebook joins Neo4j graph traversal results with Delta table aggregations in one query. No data movement, no pipeline to maintain. The integration supports aggregates, filtered queries, COUNT DISTINCT, and multi-hop traversals expressed as SQL JOINs, with aggregation pushed down to Neo4j so only results travel over the network.

## Other use cases

- **Knowledge graph-enriched ML pipelines** — Data science teams training models on lakehouse data can pull graph-derived features (node centrality, community detection scores, relationship counts) directly from Neo4j without building separate ETL to extract and materialize those features into Delta tables.

- **Supply chain visibility** — Organizations modeling supplier networks and dependencies in Neo4j can join that graph data with inventory and logistics data in Delta tables for real-time risk assessment and disruption analysis, all from a single Databricks notebook.

- **Ad hoc exploration before ETL investment** — Analysts can prototype cross-system queries joining Neo4j graph data with lakehouse tables before committing to building a full ingestion pipeline. This is exactly the proof-of-concept scenario Databricks recommends federation for.

Thanks for any leads you can surface.

Best,
Ryan

