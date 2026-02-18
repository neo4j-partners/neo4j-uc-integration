#!/bin/bash
#
# Enable Unity Catalog system tables (audit logs, query history, lineage)
#
# Usage:
#   ./enable_system_tables.sh <databricks-profile>
#
# Example:
#   ./enable_system_tables.sh my-workspace-profile
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Validate args
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <databricks-profile>"
    echo ""
    echo "  databricks-profile   Profile name from ~/.databrickscfg"
    echo ""
    echo "Example:"
    echo "  $0 my-workspace-profile"
    exit 1
fi

PROFILE="$1"
DB="databricks --profile $PROFILE"

# Check for databricks CLI
if ! command -v databricks &> /dev/null; then
    log_error "Databricks CLI not found"
    echo "Install with: pip install databricks-cli"
    echo "Or: brew install databricks"
    exit 1
fi

# Get metastore ID
log_info "Looking up metastore for profile: $PROFILE"
METASTORE_ID=$($DB metastores summary 2>/dev/null | jq -r '.metastore_id // empty')

if [[ -z "$METASTORE_ID" ]]; then
    log_error "Could not determine metastore ID"
    echo "Ensure your profile has account admin or metastore admin permissions."
    echo "You can also find the metastore ID in the Databricks UI:"
    echo "  Catalog > gear icon > Metastore > Details tab"
    exit 1
fi

log_info "Metastore ID: $METASTORE_ID"

# List current schema statuses
log_info "Current system schema statuses:"
LIST_OUTPUT=$($DB system-schemas list "$METASTORE_ID" 2>&1) && \
    echo "$LIST_OUTPUT" | jq -r '.schemas[]? | "  \(.schema) — \(.state)"' || \
    log_error "$LIST_OUTPUT"
echo ""

# Schemas to enable
SCHEMAS=("access" "query" "lineage" "billing")
FAILED=0

for schema in "${SCHEMAS[@]}"; do
    log_info "Enabling system schema: $schema"
    OUTPUT=$($DB system-schemas enable "$METASTORE_ID" "$schema" 2>&1) && \
        log_info "  $schema enabled" || \
        { log_error "  $schema: $OUTPUT"; FAILED=1; }
done

if [[ $FAILED -eq 1 ]]; then
    echo ""
    log_warn "Some schemas failed to enable. Common causes:"
    echo "  - You need account admin privileges (not just workspace admin)"
    echo "  - Grant account admin at: https://accounts.azuredatabricks.net > User management"
    echo "  - Or ask an existing account admin to run this script"
fi

# Verify
echo ""
log_info "Final system schema statuses:"
LIST_OUTPUT=$($DB system-schemas list "$METASTORE_ID" 2>&1) && \
    echo "$LIST_OUTPUT" | jq -r '.schemas[]? | "  \(.schema) — \(.state)"' || \
    log_error "$LIST_OUTPUT"

echo ""
log_info "Done! Verify with:"
echo "  SELECT COUNT(*) FROM system.access.audit WHERE event_date >= CURRENT_DATE - INTERVAL 1 DAY;"
echo "  SELECT COUNT(*) FROM system.query.history WHERE start_time >= CURRENT_TIMESTAMP - INTERVAL 1 HOUR;"
