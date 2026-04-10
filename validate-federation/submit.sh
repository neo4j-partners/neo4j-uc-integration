#!/usr/bin/env bash
# Submit a Python script as a one-time Databricks job run.
#
# Usage:
#   ./submit.sh                                      # runs test_hello.py (default)
#   ./submit.sh run_01_connection_validation.py      # runs connection validation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

uv run python -m cli submit "${1:-test_hello.py}"
