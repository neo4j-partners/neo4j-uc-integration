#!/usr/bin/env bash
# Submit a Python script as a one-time Databricks job run.
#
# Usage:
#   ./submit.sh                                       # runs test_hello.py (default)
#   ./submit.sh run_01_connection_validation.py        # runs connection validation
#   ./submit.sh run_01_connection_validation.py --no-wait
#
# Neo4j and UC credentials from .env are injected as script parameters.

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
RUN_NAME="validate_federation: $SCRIPT_NAME"

# shellcheck source=cluster_utils.sh
source "$SCRIPT_DIR/cluster_utils.sh"

echo "Submitting job (profile: $PROFILE)"
echo "  Script:   $REMOTE_PATH"
ensure_cluster_running "$PROFILE" "$CLUSTER_ID"
echo "  Run name: $RUN_NAME"

# Build parameters: inject credentials from .env.
PARAMS=$(python3 -c "
import json, os
params = []
# Neo4j credentials
if os.environ.get('NEO4J_HOST') and os.environ.get('NEO4J_PASSWORD'):
    params += [
        '--neo4j-host', os.environ['NEO4J_HOST'],
        '--neo4j-username', os.environ.get('NEO4J_USERNAME', 'neo4j'),
        '--neo4j-password', os.environ['NEO4J_PASSWORD'],
        '--neo4j-database', os.environ.get('NEO4J_DATABASE', 'neo4j'),
    ]
# UC JDBC settings
if os.environ.get('UC_CONNECTION_NAME'):
    params += ['--uc-connection-name', os.environ['UC_CONNECTION_NAME']]
if os.environ.get('JDBC_JAR_PATH'):
    params += ['--jdbc-jar-path', os.environ['JDBC_JAR_PATH']]
# Lakehouse settings
if os.environ.get('LAKEHOUSE_CATALOG'):
    params += ['--lakehouse-catalog', os.environ['LAKEHOUSE_CATALOG']]
if os.environ.get('LAKEHOUSE_SCHEMA'):
    params += ['--lakehouse-schema', os.environ['LAKEHOUSE_SCHEMA']]
# Metadata sync settings
if os.environ.get('METADATA_CATALOG'):
    params += ['--metadata-catalog', os.environ['METADATA_CATALOG']]
if os.environ.get('NODES_SCHEMA'):
    params += ['--nodes-schema', os.environ['NODES_SCHEMA']]
if os.environ.get('RELATIONSHIPS_SCHEMA'):
    params += ['--relationships-schema', os.environ['RELATIONSHIPS_SCHEMA']]
print(json.dumps(params))
")

[[ -n "${NEO4J_HOST:-}" ]] && echo "  Neo4j:    ${NEO4J_HOST}"
[[ -n "${UC_CONNECTION_NAME:-}" ]] && echo "  UC:       ${UC_CONNECTION_NAME}"
[[ -n "${LAKEHOUSE_CATALOG:-}" ]] && echo "  Lakehouse: ${LAKEHOUSE_CATALOG}.${LAKEHOUSE_SCHEMA}"
[[ -n "${METADATA_CATALOG:-}" ]] && echo "  Metadata: ${METADATA_CATALOG}"
echo "---"

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
