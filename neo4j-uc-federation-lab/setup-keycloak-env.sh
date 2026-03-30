#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <path-to-deployment.json> <neo4j-host>"
    echo ""
    echo "Generates .env.oauth from a Keycloak deployment.json for use with setup-oauth.sh."
    echo ""
    echo "Arguments:"
    echo "  deployment.json   Path to keycloak-infra/.deployment.json from the azure-ee-template"
    echo "  neo4j-host        Neo4j host (without protocol prefix)"
    echo "                    e.g. neo4j-vm.eastus.cloudapp.azure.com"
    echo ""
    echo "Example:"
    echo "  $0 /path/to/azure-ee-template/keycloak-infra/.deployment.json neo4j-vm.eastus.cloudapp.azure.com"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

DEPLOYMENT_JSON="$1"
NEO4J_HOST="$2"

if [ ! -f "$DEPLOYMENT_JSON" ]; then
    echo "Error: $DEPLOYMENT_JSON not found"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo "Error: jq is required. Install with: brew install jq"
    exit 1
fi

TOKEN_ENDPOINT=$(jq -r '.oidc.token_endpoint' "$DEPLOYMENT_JSON")
CLIENT_ID=$(jq -r '.oidc.client_id' "$DEPLOYMENT_JSON")
CLIENT_SECRET=$(jq -r '.oidc.client_secret' "$DEPLOYMENT_JSON")

if [ "$TOKEN_ENDPOINT" = "null" ] || [ "$CLIENT_ID" = "null" ] || [ "$CLIENT_SECRET" = "null" ]; then
    echo "Error: deployment.json is missing required oidc fields (token_endpoint, client_id, client_secret)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.oauth"

if [ -f "$ENV_FILE" ]; then
    backup="$ENV_FILE.backup.$(date +%Y%m%d%H%M%S)"
    cp "$ENV_FILE" "$backup"
    echo "Backed up existing .env.oauth to $(basename "$backup")"
fi

cat > "$ENV_FILE" << EOF
# Neo4j OAuth Connection Credentials
# Generated from: $DEPLOYMENT_JSON
# Used by setup-oauth.sh to create Databricks secrets

# Neo4j host (without protocol prefix)
NEO4J_HOST=$NEO4J_HOST

# Optional: database name (defaults to "neo4j")
NEO4J_DATABASE=neo4j

# Keycloak OAuth - from keycloak-infra/.deployment.json
OAUTH_TOKEN_ENDPOINT=$TOKEN_ENDPOINT
OAUTH_CLIENT_ID=$CLIENT_ID
OAUTH_CLIENT_SECRET=$CLIENT_SECRET

# Unity Catalog connection name
UC_CONNECTION_NAME=neo4j_oauth_connection

# Path to Neo4j Unity Catalog Connector JAR in Unity Catalog Volume
JDBC_JAR_PATH=/Volumes/main/jdbc_drivers/jars/neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar
EOF

echo "Created $ENV_FILE"
echo ""
echo "Configuration:"
echo "  NEO4J_HOST:             $NEO4J_HOST"
echo "  OAUTH_TOKEN_ENDPOINT:   $TOKEN_ENDPOINT"
echo "  OAUTH_CLIENT_ID:        $CLIENT_ID"
echo ""
echo "Next steps:"
echo "  1. Edit .env.oauth to set JDBC_JAR_PATH and UC_CONNECTION_NAME if needed"
echo "  2. Run: ./setup-oauth.sh"
