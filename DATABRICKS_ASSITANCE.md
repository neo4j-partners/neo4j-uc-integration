# Request for Reference Customers: Neo4j + Databricks Unity Catalog Integration

**To:** Neo4j Field Team
**From:** Ryan Knight
**Subject:** Need reference customers for Neo4j JDBC + Databricks Unity Catalog integration

---

Hi team,

I need your help surfacing customers who run both Neo4j and Databricks and would be interested in Neo4j integration into Unity Catalog. We have a working integration that lets Databricks users query Neo4j through Unity Catalog using the Neo4j JDBC driver, and we're requesting Databricks to add official support. They prioritize based on customer demand, so even a brief description of the use case would help. Customer names can be anonymous. More details on the integration can be found here: https://neo4j-partners.github.io/neo4j-uc-integration/neo4j-uc-integration-docs/1.0/index.html

For example, one customer in the defense industry needs unified security enforcement across all data sources through Unity Catalog. Another wants to join Neo4j graph data with lakehouse tables without building custom pipelines for each source. Another has graph data their Databricks analysts need alongside lakehouse data. Any customers expressing interest would move the needle so any assistance would be greatly appreciated.


Some background: the Neo4j JDBC driver plugs into Unity Catalog's custom JDBC support for federated queries against Neo4j from inside Databricks. SQL queries get translated to Cypher automatically, and results come back as standard Spark DataFrames that can be joined with Delta tables, Iceberg tables, or any other UC data source. All connections run under Unity Catalog governance with access controls and audit logging.

## Example Use Cases

- **Natural language queries with Genie** — Neo4j graph data can be materialized as Delta tables and added to a Genie space alongside lakehouse tables. Users ask plain-English questions and Genie generates federated SQL that joins across both sources automatically, with no SQL or Cypher required.

- **Fraud detection** — Join transaction data in Delta tables with entity relationships in Neo4j in a single notebook query. No data movement, no pipeline to maintain.

- **Knowledge graph-enriched ML** — Pull graph-derived features (centrality, community scores, relationship counts) directly from Neo4j into model training without separate ETL.

- **Supply chain visibility** — Join supplier network data in Neo4j with inventory and logistics in Delta tables for risk assessment and disruption analysis.

- **Ad hoc exploration** — Prototype cross-system queries joining Neo4j with lakehouse tables before committing to a full ingestion pipeline.

Thanks for any leads you can surface.

Best,
Ryan

