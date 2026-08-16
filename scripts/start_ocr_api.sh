#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Avoid PaddleX's network model-host check: this project uses the already-local model.
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="${PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK:-True}"

OCR_BIND_HOST="${OCR_BIND_HOST:-127.0.0.1}"
OCR_PORT="${OCR_PORT:-8788}"

exec ./.venv/bin/python -m uvicorn backend.app.main:app \
  --host "$OCR_BIND_HOST" \
  --port "$OCR_PORT" \
  --log-level info
