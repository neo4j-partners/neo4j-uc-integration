#!/usr/bin/env bash
# Upload Python scripts to the Databricks workspace.
#
# Usage:
#   ./upload.sh                          # uploads test_hello.py (default)
#   ./upload.sh run_01_connection_validation.py   # uploads a specific file
#   ./upload.sh --all                    # uploads all scripts/*.py files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ "${1:-}" == "--all" ]]; then
    for f in scripts/*.py; do
        uv run python -m cli upload "$(basename "$f")"
    done
else
    uv run python -m cli upload "${1:-test_hello.py}"
fi
