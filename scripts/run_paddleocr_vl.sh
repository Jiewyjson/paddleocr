#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

./.venv/bin/python scripts/apply_paddleocr_vl_compat_patch.py
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

exec ./.venv/bin/python scripts/run_paddleocr_vl_batch.py "$@"
