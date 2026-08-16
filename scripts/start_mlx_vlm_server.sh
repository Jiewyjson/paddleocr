#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Do not read $HOST. macOS sets it to the machine hostname, which would bind
# MLX-VLM on every interface. LAN exposure belongs on FastAPI only.
MLX_HOST="${MLX_HOST:-127.0.0.1}"
MLX_PORT="${MLX_PORT:-8111}"

cd "$PROJECT_ROOT"

exec ./.venv/bin/python scripts/serve_mlx_vlm.py --host "$MLX_HOST" --port "$MLX_PORT"
