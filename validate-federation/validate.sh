#!/usr/bin/env bash
# Run the full federation validation suite.
#
# Usage:
#   ./validate.sh              # upload + run all scripts sequentially
#   ./validate.sh --skip-upload

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

SKIP_UPLOAD=""
if [[ "${1:-}" == "--skip-upload" ]]; then
    SKIP_UPLOAD="true"
fi

echo "============================================"
echo "validate-federation: Full Validation Suite"
echo "============================================"
echo ""

SCRIPTS=(
    "run_01_connection_validation.py"
    "run_02_federated_queries.py"
    "run_03_metadata_sync_tables.py"
    "run_04_metadata_sync_api.py"
)

if [[ -z "$SKIP_UPLOAD" ]]; then
    echo "--- Step 1: Uploading all scripts ---"
    for script in "${SCRIPTS[@]}"; do
        uv run python -m cli upload "$script"
    done
    echo ""
else
    echo "--- Step 1: Skipping upload (--skip-upload) ---"
    echo ""
fi

FAILED=0
for script in "${SCRIPTS[@]}"; do
    echo "--- Running: $script ---"
    if uv run python -m cli submit "$script"; then
        echo "[OK] $script completed"
    else
        echo "[FAIL] $script failed"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done

echo "============================================"
echo "VALIDATION SUMMARY"
echo "============================================"
echo "  Total scripts: ${#SCRIPTS[@]}"
echo "  Failed: $FAILED"

if [[ $FAILED -eq 0 ]]; then
    echo "  Result: ALL PASSED"
else
    echo "  Result: $FAILED FAILED"
    exit 1
fi
