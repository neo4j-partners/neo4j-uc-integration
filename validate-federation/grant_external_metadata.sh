#!/usr/bin/env bash
# Grant CREATE EXTERNAL METADATA privilege on the metastore.
#
# Uses the account-admin profile to grant via the Unity Catalog grants API,
# then verifies by running run_05 on the workspace cluster.
#
# Usage:
#   ./grant_external_metadata.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env for workspace profile and user info
set -a
source "$SCRIPT_DIR/.env"
set +a

ADMIN_PROFILE="azure-account-admin"
WORKSPACE_PROFILE="$DATABRICKS_PROFILE"

# Get metastore ID from the workspace
echo "--- Discovering metastore ---"
METASTORE_ID=$(databricks api get /api/2.1/unity-catalog/metastore_summary \
    --profile "$WORKSPACE_PROFILE" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d['metastore_id'])
")
echo "  Metastore ID: $METASTORE_ID"

# Get current user
CURRENT_USER=$(databricks api get /api/2.0/preview/scim/v2/Me \
    --profile "$WORKSPACE_PROFILE" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('userName', d.get('emails', [{}])[0].get('value', 'unknown')))
")
echo "  User: $CURRENT_USER"

# Grant via account-level API
echo ""
echo "--- Granting CREATE_EXTERNAL_METADATA on metastore ---"
echo "  Profile: $ADMIN_PROFILE"
echo "  Metastore: $METASTORE_ID"
echo "  Principal: $CURRENT_USER"

GRANT_PAYLOAD=$(python3 -c "
import json
payload = {
    'changes': [{
        'principal': '$CURRENT_USER',
        'add': ['CREATE_EXTERNAL_METADATA']
    }]
}
print(json.dumps(payload))
")

databricks api patch "/api/2.1/unity-catalog/permissions/metastore/$METASTORE_ID" \
    --profile "$ADMIN_PROFILE" \
    --json "$GRANT_PAYLOAD" 2>&1

echo ""
echo "--- Verifying grant ---"
databricks api get "/api/2.1/unity-catalog/permissions/metastore/$METASTORE_ID" \
    --profile "$ADMIN_PROFILE" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for entry in d.get('privilege_assignments', []):
    principal = entry.get('principal', '')
    privs = [p.get('privilege') for p in entry.get('privileges', [])]
    if 'CREATE_EXTERNAL_METADATA' in privs:
        print(f'  [PASS] {principal} has CREATE_EXTERNAL_METADATA')
"

echo ""
echo "Done."
