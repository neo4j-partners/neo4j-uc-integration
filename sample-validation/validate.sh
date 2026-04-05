#!/usr/bin/env bash
# Run the full validation suite: upload all scripts then run 01, 02, 03 in order.
#
# Usage:
#   ./validate.sh              # upload + run all three scripts sequentially
#   ./validate.sh --skip-upload # run without re-uploading (scripts already on workspace)
#
# Each script depends on the previous:
#   01 creates the UC JDBC connection
#   02 loads Delta tables and Neo4j graph data
#   03 materializes and queries the data

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

SKIP_UPLOAD=""
if [[ "${1:-}" == "--skip-upload" ]]; then
    SKIP_UPLOAD="true"
fi

echo "========================================"
echo "sample-validation: Full Validation Suite"
echo "========================================"
echo ""

# Step 1: Upload all scripts
if [[ -z "$SKIP_UPLOAD" ]]; then
    echo "--- Step 1: Uploading all scripts ---"
    "$SCRIPT_DIR/upload.sh" --all
    echo ""
else
    echo "--- Step 1: Skipping upload (--skip-upload) ---"
    echo ""
fi

# Step 2: Run scripts in order
SCRIPTS=(
    "run_01_connect_test.py"
    "run_02_federated_queries.py"
    "run_03_materialized_tables.py"
)

FAILED=0
for script in "${SCRIPTS[@]}"; do
    echo "--- Running: $script ---"
    if "$SCRIPT_DIR/submit.sh" "$script"; then
        echo "[OK] $script completed"
    else
        echo "[FAIL] $script failed"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done

# Summary
echo "========================================"
echo "VALIDATION SUMMARY"
echo "========================================"
echo "  Total scripts: ${#SCRIPTS[@]}"
echo "  Failed: $FAILED"

if [[ $FAILED -eq 0 ]]; then
    echo "  Result: ALL PASSED"
else
    echo "  Result: $FAILED FAILED"
    exit 1
fi
