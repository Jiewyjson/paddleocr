#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8111}"

cd "$PROJECT_ROOT"

exec ./.venv/bin/python -m mlx_vlm.server --host "$HOST" --port "$PORT"
