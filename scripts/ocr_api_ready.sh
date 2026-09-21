#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT_DIR/backend/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/backend/.env"
  set +a
fi

port="${OCR_PORT:-8788}"
hosts=()
if [[ -n "${OCR_BIND_HOST:-}" && "${OCR_BIND_HOST}" != "0.0.0.0" ]]; then
  hosts+=("${OCR_BIND_HOST}")
fi
hosts+=("127.0.0.1")

for h in "${hosts[@]}"; do
  if curl -sf -o /dev/null --connect-timeout 1 "http://${h}:${port}/v1/healthz"; then
    exit 0
  fi
done
exit 1
