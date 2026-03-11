# Python UDF + Genie Approach for Neo4j Integration: Analysis

Research conducted 2026-03-10 against official Databricks documentation.

---

## Executive Summary

A proposal was evaluated that positions a Python UDF registered in Unity Catalog as a "secret weapon" for integrating Neo4j with Databricks Genie. The idea is to bypass the JDBC connector's SQL-to-Cypher translation by hardcoding Cypher queries inside Python functions and letting Genie invoke them.

After thorough research against official Databricks documentation, **this approach is unlikely to work reliably, and even if it could be made to work, it would be fragile and unscalable.**

The core problem is a fundamental design mismatch. Genie was built from the ground up as a natural language to SQL engine for business intelligence against tabular data. It was not built to route queries to external systems, call arbitrary functions with extracted parameters, or reason about non-relational data models like graphs. Its entire architecture, from the metadata it ingests to the queries it generates to the results it renders, is oriented around SQL and tables. Trying to repurpose it as a dispatch layer for Neo4j Cypher queries works against every design decision Databricks made when building the product.

The existing Neo4j JDBC connector in this repository takes a more architecturally sound approach for the Genie use case. It lets Genie do what it was designed to do (generate SQL from natural language) and then hands that SQL off to the Neo4j JDBC driver's mature, well-tested SQL-to-Cypher translator. This pipeline plays to Genie's strengths rather than fighting against them.

For agentic graph query use cases that go beyond what SQL translation can express, Databricks' own documentation points toward Mosaic AI Agent Bricks with MCP servers, not Genie with Python UDFs. Databricks built an entire AI platform with purpose-built services for different integration patterns. The right tool for connecting agents to external databases like Neo4j is the agent framework with MCP, not the BI tool with a workaround.

---

## 1. The Fundamental Design Mismatch

Before getting into specific technical blockers, it is worth understanding why this approach fails at the architectural level.

### What Genie was built to do

Genie is a compound AI system purpose-built for one job: turning natural language questions from business users into SQL queries against tabular data. Databricks describes it as enabling business teams to "interact with their data using natural language" through "generative AI tailored to your organization's terminology and data."

Everything about Genie's design serves this mission:

- **Its inputs are tabular metadata.** Genie ingests table names, column descriptions, primary and foreign key relationships, SQL expressions, and example SQL queries. These are all relational/tabular concepts. There is no mechanism to feed it node labels, relationship types, property keys, or graph traversal patterns.
- **Its reasoning is SQL reasoning.** When Genie processes a user question, it generates a read-only SQL query against Unity Catalog tables. It thinks in terms of joins, aggregates, filters, and GROUP BY clauses. It does not and cannot reason about graph hops, path traversals, or variable-length relationships.
- **Its outputs are tabular results.** Genie renders results as tables and charts on a SQL warehouse. It expects rows and columns, not JSON blobs from a scalar function.
- **Its context window is SQL-oriented.** Genie references table metadata, column information, example SQL queries, SQL functions, instructions, and chat history when generating queries. Every piece of context is designed to help it write better SQL, not to help it decide whether a question is "graphy" or "tabular."

### What Genie was not built to do

Genie was not designed to be a general-purpose tool router or function dispatcher. Specifically:

- **It was not built to call external systems.** Genie generates SQL and runs it on a SQL warehouse. It does not make HTTP calls, open database connections, or invoke arbitrary code on external services. The Python UDF approach tries to smuggle an external Neo4j connection inside a function call, but Genie has no awareness that this is happening and no ability to handle failures, timeouts, or connection issues gracefully.
- **It was not built to reason about non-SQL data models.** Genie has no training data, no context mechanisms, and no UI affordances for graph databases, document stores, key-value stores, or any other non-relational model. You cannot teach it graph semantics through a function COMMENT string.
- **It was not built for dynamic tool selection.** The proposal imagines Genie acting like an agent that recognizes a question requires graph traversal and then routes it to the right Neo4j function. But Genie's function matching is based on COMMENT text pattern matching against user questions. It is not performing intent classification or reasoning about which backend can best answer a given question.
- **It was not built for complex parameter extraction.** The documented examples of Genie calling trusted asset functions show simple parameter passing: a region name, a product ID. Extracting graph-specific parameters (variable-length path depths, multiple node types, relationship filters) from natural language is well beyond what the COMMENT-based matching system was designed to handle.
- **It was not built for agentic workflows.** Even Genie's Agent mode (currently in Beta) is about running multiple SQL queries iteratively, not about calling external tools. The [Agent mode docs](https://docs.databricks.com/aws/en/genie/research-agent) describe it as "creating research plans, running multiple SQL queries, learning from each result." It adds depth of SQL analysis, not breadth of tool access.

### Why this matters

The Python UDF proposal asks Genie to do all five of the things listed above: call an external system, reason about a graph data model, select the right tool for a graph question, extract graph-relevant parameters, and orchestrate this in an agentic way. Each of these individually falls outside what Genie was designed for. Together, they represent a fundamental misalignment between the tool and the task.

---

## 2. Why the Python UDF + Genie Approach Most Likely Will Not Work

Beyond the design mismatch, there are specific technical reasons this approach is unlikely to succeed.

### Python UDFs are not documented as Genie trusted assets

Genie spaces support "trusted assets," which are predefined functions that provide verified answers. The [trusted assets documentation](https://docs.databricks.com/aws/en/genie/trusted-assets) describes two supported types:

1. Parameterized SQL queries with example values
2. User-defined **table functions** registered in Unity Catalog

The docs only show SQL function examples. Python UDFs are never mentioned. This matters because:

- The [CREATE FUNCTION reference](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-sql-function) confirms Python functions are **scalar only** and cannot be table functions (`RETURNS TABLE` is SQL-only)
- Genie trusted assets reference "user-defined table functions" specifically
- The UI to add functions to a Genie space is under **Configure > Context > SQL Queries**

There is no official documentation showing a `LANGUAGE PYTHON` function being added to a Genie space or Genie invoking one.

### Parameter extraction is fragile

Even if Genie could invoke a Python UDF, it would need to extract the right parameters from natural language. The docs show this is unreliable:

- Genie decides when to call a function and what parameters to pass based on the function's **COMMENT text** alone
- There is no documented mechanism for sophisticated parameter extraction. The examples show simple cases like region names or product IDs.
- The [best practices docs](https://docs.databricks.com/aws/en/genie/best-practices) warn that "without proper guidance, Genie may misinterpret data, questions, or business jargon"
- Genie "does not consider the SQL content of your trusted assets" and matches on comments and descriptions only

### Agent mode does not change this

Genie's Agent mode (Beta) adds multi-step SQL reasoning, running multiple SQL queries iteratively. It does **not** add tool-calling, function routing, or the ability to invoke external systems. The [Agent mode docs](https://docs.databricks.com/aws/en/genie/research-agent) describe it as creating "research plans, running multiple SQL queries, learning from each result." It uses the same context and data as normal Genie.

### The Cypher is hardcoded, not translated

The "query is known ahead of time" constraint from [Databricks' own recommendation](https://docs.databricks.com/aws/en/generative-ai/agent-framework/create-custom-tool) means the Cypher is hardcoded in the function with a parameter slot. This is not natural language to Cypher translation. It is a pre-written Cypher query that takes a product ID. Every new graph question pattern requires a new function with new hardcoded Cypher, and Genie must correctly route to each one based on a COMMENT string.

| What the writeup wants | What Genie actually does |
|------------------------|--------------------------|
| Natural language to Cypher translation | Natural language to SQL translation |
| Graph-aware reasoning (traversals, paths, hops) | Tabular reasoning (joins, aggregates, filters) |
| Dynamic parameter extraction for graph queries | Simple parameter matching via COMMENT text |
| Agent-style tool selection ("use Neo4j for this") | SQL generation against configured tables |

### Even if it worked, it would not be reliable

The combination of undocumented Python UDF support in Genie, fragile COMMENT-based routing, scalar-only return types, and zero graph awareness means that even a working prototype would be unreliable for anything beyond a tightly scripted single-question demo.

---

## 3. The JDBC Connector Approach Plays to Genie's Strengths

The Neo4j JDBC connector in this repository takes a fundamentally different and more sound approach. It works with Genie's strengths rather than against them.

Genie excels at natural language to SQL translation. It is trained for it, optimized for it, and every component of its architecture supports it. The JDBC connector leverages this by:

1. **Letting Genie do what it is good at.** Genie generates SQL from natural language, which is its core competency.
2. **Using a well-tested SQL-to-Cypher translation layer.** The Neo4j JDBC driver's `SqlToCypherTranslator` converts that SQL into Cypher at the driver level.
3. **Handling Databricks-specific quirks.** The `SparkSubqueryCleaningTranslator` strips Spark's wrapper queries before translation.
4. **Running through Unity Catalog's standard JDBC federation.** No experimental features, no preview APIs, no workarounds.

The Neo4j JDBC driver's SQL-to-Cypher translator is a mature, extensively tested component maintained by Neo4j. It handles translation at the right layer, after Genie has already done its job of understanding the user's intent and expressing it as SQL. This is a well-understood pipeline: natural language to SQL (Genie's strength) to Cypher (the JDBC driver's strength).

The JDBC approach has known SQL-to-Cypher limitations (documented in CLAUDE.md). Not all SQL patterns translate cleanly to Cypher. But these are well-characterized, predictable limitations, not the kind of undocumented, untested failure modes that the Python UDF approach introduces.

---

## 4. Square Peg, Round Hole: Forcing Everything Through Genie

The Python UDF proposal tries to force everything through Genie, making a SQL-focused BI tool act as a graph query router. This is not how Databricks recommends building AI integrations with external systems.

Databricks has an entire AI suite called **Mosaic AI** with purpose-built services for different tasks:

- **Genie (AI/BI)** is for natural language to SQL, serving business intelligence against tabular data
- **Agent Bricks** is for building and deploying production AI agents with tool-calling capabilities
- **Agent Framework** is for custom agents with MCP server integrations, external API connections, and multi-agent orchestration
- **MCP (Model Context Protocol)** is the open standard for connecting agents to tools, resources, and external services

These services exist because different integration patterns require different architectures. Genie is for BI analysts asking questions about tables. Agent Bricks and MCP are for building agents that call external tools and APIs. Trying to make Genie do the job of Agent Bricks is working against the platform, not with it.

### Mosaic AI Agent Bricks + MCP: The documented path for external tool integration

Databricks' own documentation explicitly recommends MCP servers over UC functions for most agent tool use cases:

> "In most other use cases, Databricks recommends **MCP servers or defining the logic directly in agent code** for faster execution, per-user authentication support, and additional flexibility."
> [Create AI agent tools using Unity Catalog functions](https://docs.databricks.com/aws/en/generative-ai/agent-framework/create-custom-tool)

Using [Agent Bricks](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/) to call Neo4j via an [MCP server](https://docs.databricks.com/aws/en/generative-ai/mcp/) is a well-documented pattern that aligns with how Databricks designed these systems to work:

- **Agent Bricks agents can use MCP tools.** The agent discovers available tools at runtime and the LLM decides which to call based on tool descriptions and the user's question.
- **Custom MCP servers can be hosted on Databricks Apps.** A [Neo4j MCP server](https://docs.databricks.com/aws/en/generative-ai/mcp/custom-mcp) could expose graph schema information and Cypher execution as tools.
- **The LLM driving the agent can reason about graph schemas.** Unlike Genie, which is locked to SQL generation, an agent's LLM can learn Cypher patterns from tool descriptions and schema context.
- **External MCP servers are supported.** Databricks allows [connecting to MCP servers outside of Databricks](https://docs.databricks.com/aws/en/generative-ai/mcp/external-mcp) through managed proxy connections.
- **Supervisor agents can orchestrate across backends.** A [Supervisor Agent](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/multi-agent-supervisor) can combine a Genie space for tabular questions with a Neo4j MCP tool for graph questions, routing to the right backend based on the question.

This is the architecture Databricks built for exactly this kind of external integration. It uses the right tool for the right job rather than trying to shoehorn graph queries through a SQL BI interface.

---

## 5. Potential Blockers Even If the Python UDF Approach Could Be Made to Work

- **Port 7687 blocked on serverless compute.** Python UDFs on serverless only allow TCP/UDP over ports 80, 443, and 53. The Neo4j Bolt protocol uses port 7687. The UDF would fail to connect unless running on a non-serverless cluster.
- **No `dbutils.secrets` access.** Python UDFs execute in an isolated sandbox without access to `dbutils`. The proposed `dbutils.secrets.get()` call for credential management will not work.
- **Python UDFs are Public Preview, not GA.** The original writeup's comparison table claiming "GA" status is incorrect per the [UC UDF docs](https://docs.databricks.com/aws/en/udf/unity-catalog).
- **Genie Agent mode is Beta.** It is UI-only during Beta with no API access. Workspace admins must enable it via the previews page per the [Agent mode docs](https://docs.databricks.com/aws/en/genie/research-agent).
- **Scalar return type only.** Python UDFs can only return scalar values such as a JSON string, not tables. Genie is designed to display tabular results. A JSON string blob is a poor experience for BI users.
- **Cold start latency.** Serverless compute has cold start overhead for UDF execution, undermining the "serverless speed" claim.
- **No graph schema awareness.** Genie has no mechanism to understand node labels, relationship types, or property keys. It cannot help users formulate graph-aware questions or validate that parameters make sense in a graph context.
- **COMMENT-based routing is brittle.** Adding multiple Neo4j functions to a Genie space means Genie must correctly route based on comment text alone. With many functions, "Genie might struggle to prioritize" per the [best practices docs](https://docs.databricks.com/aws/en/genie/best-practices).
- **No error handling visibility.** If the Neo4j connection fails or Cypher errors occur inside the UDF, the error surfaces as a generic function failure. There is no mechanism for Genie to understand or explain graph database errors to the user.
- **Security model mismatch.** UC functions run as the function owner, not the calling user. There is no per-user authentication to Neo4j, creating both security and audit trail gaps.

---

## References

- [Use trusted assets in AI/BI Genie spaces](https://docs.databricks.com/aws/en/genie/trusted-assets)
- [Set up and manage an AI/BI Genie space](https://docs.databricks.com/aws/en/genie/set-up)
- [What is an AI/BI Genie space](https://docs.databricks.com/aws/en/genie/)
- [Agent mode in Genie spaces](https://docs.databricks.com/aws/en/genie/research-agent)
- [Curate an effective Genie space](https://docs.databricks.com/aws/en/genie/best-practices)
- [CREATE FUNCTION (SQL and Python)](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-sql-function)
- [User-defined functions (UDFs) in Unity Catalog](https://docs.databricks.com/aws/en/udf/unity-catalog)
- [Create AI agent tools using Unity Catalog functions](https://docs.databricks.com/aws/en/generative-ai/agent-framework/create-custom-tool)
- [Model Context Protocol (MCP) on Databricks](https://docs.databricks.com/aws/en/generative-ai/mcp/)
- [Host custom MCP servers using Databricks apps](https://docs.databricks.com/aws/en/generative-ai/mcp/custom-mcp)
- [Use Databricks managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [Use external MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/external-mcp)
- [Agent Bricks](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/)
- [Supervisor Agent](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/multi-agent-supervisor)
