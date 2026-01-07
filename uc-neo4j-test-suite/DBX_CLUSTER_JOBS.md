# Databricks Jobs Execution for UC Neo4j Test Suite

This document outlines how to use the Databricks Jobs API to automate the execution of the Unity Catalog Neo4j Test Suite (`uc-neo4j-test-suite`) on a Databricks cluster.

## Overview

The `dbx_job.py` script demonstrates how to programmatically create and trigger a Databricks Job using the [Databricks SDK for Python](https://docs.databricks.com/dev-tools/sdk-python.html). 

Unlike the interactive `dbx_main.py` (which uses the Command Execution API), this approach executes the test suite as a **Python Wheel Task**. This mimics a production-grade job setup where the package is installed and executed as a proper entry point.

## Prerequisites

1.  **Databricks Authentication**: The script uses `WorkspaceClient` which supports [Unified Authentication](https://docs.databricks.com/dev-tools/auth/index.html). Ensure you have one of the following configured:
    *   Environment variables: `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
    *   `~/.databrickscfg` profile
    *   Azure CLI or other supported methods.

2.  **Configuration**: Your `.env` file must define the target cluster:
    ```bash
    DATABRICKS_CLUSTER_ID=your-cluster-id
    ```

3.  **Build Artifacts**: Since this runs as a wheel task, your environment must be able to resolve the package `uc-neo4j-test-suite`. 
    *   *Note: In a real CI/CD pipeline, you would upload the `.whl` file to DBFS or a Unity Catalog Volume and reference it in the job definition. The current script assumes the library is available or installed on the cluster context.*

## How it Works

The `dbx_job.py` script performs the following steps:

1.  **Connect**: Initializes the `WorkspaceClient`.
2.  **Idempotency Check**: Searches for an existing job named **"UC Neo4j Test Suite (On-demand)"**.
    *   If found, it reuses the existing Job ID.
    *   If not found, it creates a new job.
3.  **Job Definition**:
    *   **Type**: `PythonWheelTask`
    *   **Package**: `uc-neo4j-test-suite` (defined in `pyproject.toml`)
    *   **Entry Point**: `uc-neo4j-test` (defined in `[project.scripts]`)
    *   **Compute**: Runs on the existing interactive cluster specified by `DATABRICKS_CLUSTER_ID`.
4.  **Trigger**: Calls `jobs.run_now()` to start a new run.
5.  **Monitor**: Polls the run lifecycle state until it reaches a terminal state (`TERMINATED`, `SKIPPED`, etc.) and reports the final result (`SUCCESS` or `FAILURE`).

## Usage

To run the job creation and trigger script:

```bash
uv run dbx_job.py
```

## References

*   **Databricks SDK for Python**: https://docs.databricks.com/aws/en/dev-tools/sdk-python
*   **Jobs API - Create**: https://docs.databricks.com/api/workspace/jobs/create
*   **Command Execution vs Jobs**: https://docs.databricks.com/api/workspace/commandexecution
*   **Automate Jobs**: https://docs.databricks.com/aws/en/jobs/automate
