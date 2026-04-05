#!/usr/bin/env bash
# Submit a Python script as a one-time Databricks job run.
#
# Usage:
#   ./submit.sh                                    # runs test_hello.py (default)
#   ./submit.sh run_01_connect_test.py             # runs the connect test
#   ./submit.sh run_02_federated_queries.py        # runs federated queries
#   ./submit.sh run_01_connect_test.py --no-wait   # submit without waiting
#
# Scripts live in agent_modules/ on the remote workspace.
# Neo4j and UC credentials from .env are automatically injected as script parameters.
# Scripts that don't use argparse (like test_hello.py) safely ignore them.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env
set -a
source "$SCRIPT_DIR/.env"
set +a

PROFILE="$DATABRICKS_PROFILE"
REMOTE_DIR="$WORKSPACE_DIR"
CLUSTER_ID="$DATABRICKS_CLUSTER_ID"

SCRIPT_NAME="${1:-test_hello.py}"
NO_WAIT=""
if [[ "${2:-}" == "--no-wait" ]]; then
    NO_WAIT="--no-wait"
fi

REMOTE_PATH="$REMOTE_DIR/agent_modules/$SCRIPT_NAME"
RUN_NAME="sample_validation: $SCRIPT_NAME"

# shellcheck source=cluster_utils.sh
source "$SCRIPT_DIR/cluster_utils.sh"

echo "Submitting job (profile: $PROFILE)"
echo "  Script:   $REMOTE_PATH"
ensure_cluster_running "$PROFILE" "$CLUSTER_ID"
echo "  Run name: $RUN_NAME"

# Build parameters: inject credentials from .env.
# Uses Python to safely handle special characters in passwords.
# Prefers Databricks Secrets (--secret-scope) over plaintext --neo4j-password.
PARAMS=$(python3 -c "
import json, os
params = []
# Neo4j credentials
if os.environ.get('NEO4J_URI'):
    params += [
        '--neo4j-uri', os.environ['NEO4J_URI'],
        '--neo4j-username', os.environ.get('NEO4J_USERNAME', 'neo4j'),
    ]
    # Prefer secrets over plaintext password
    if os.environ.get('NEO4J_SECRET_SCOPE'):
        params += ['--secret-scope', os.environ['NEO4J_SECRET_SCOPE']]
        if os.environ.get('NEO4J_SECRET_KEY'):
            params += ['--secret-key', os.environ['NEO4J_SECRET_KEY']]
    elif os.environ.get('NEO4J_PASSWORD'):
        params += ['--neo4j-password', os.environ['NEO4J_PASSWORD']]
# Unity Catalog settings
if os.environ.get('UC_CATALOG'):
    params += ['--uc-catalog', os.environ['UC_CATALOG']]
if os.environ.get('UC_SCHEMA'):
    params += ['--uc-schema', os.environ['UC_SCHEMA']]
if os.environ.get('UC_VOLUME'):
    params += ['--uc-volume', os.environ['UC_VOLUME']]
if os.environ.get('JDBC_JAR_PATH'):
    params += ['--jdbc-jar-path', os.environ['JDBC_JAR_PATH']]
if os.environ.get('UC_CONNECTION_NAME'):
    params += ['--uc-connection-name', os.environ['UC_CONNECTION_NAME']]
print(json.dumps(params))
")

[[ -n "${NEO4J_URI:-}" ]] && echo "  Neo4j:    credentials injected from .env"
[[ -n "${UC_CATALOG:-}" ]] && echo "  UC:       catalog=$UC_CATALOG schema=$UC_SCHEMA"
echo "---"

# Build the job JSON.
# Uses an existing all-purpose cluster (started automatically if terminated).
JOB_JSON=$(cat <<EOF
{
  "run_name": "$RUN_NAME",
  "tasks": [
    {
      "task_key": "run_script",
      "spark_python_task": {
        "python_file": "$REMOTE_PATH",
        "parameters": $PARAMS
      },
      "existing_cluster_id": "$CLUSTER_ID"
    }
  ]
}
EOF
)

databricks jobs submit \
    --profile "$PROFILE" \
    --json "$JOB_JSON" \
    $NO_WAIT

echo ""
echo "Job submission complete."
