#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Avoid PaddleX's network model-host check: this project uses the already-local model.
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="${PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK:-True}"

# Honor backend/.env (OCR_BIND_HOST, CORS, model paths) without clobbering
# variables already set by process-compose / the caller.
if [[ -f "$ROOT_DIR/backend/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z "${!key+x}" ]]; then
      export "$key=$val"
    fi
  done < "$ROOT_DIR/backend/.env"
fi

OCR_BIND_HOST="${OCR_BIND_HOST:-127.0.0.1}"
OCR_PORT="${OCR_PORT:-8788}"
echo "Starting OCR API on http://${OCR_BIND_HOST}:${OCR_PORT}" >&2

exec ./.venv/bin/python -m uvicorn backend.app.main:app \
  --host "$OCR_BIND_HOST" \
  --port "$OCR_PORT" \
  --log-level info
