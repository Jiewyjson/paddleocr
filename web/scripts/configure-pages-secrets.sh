#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: pnpm pages:secrets -- <project-name>

Prompts for the three runtime bindings required by the Pages OCR relay. Values
are stored as encrypted Pages secrets and are never written to this repository.
EOF
}

if [[ "${1:-}" == "--" ]]; then
  shift
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 || -z "${1:-}" ]]; then
  usage >&2
  exit 64
fi

project_name="$1"

for secret_name in OCR_API_ORIGIN CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET; do
  if [[ "$secret_name" == "OCR_API_ORIGIN" ]]; then
    printf '\nSet %s for Pages project %s. Enter a full URL, for example https://ocr.example.com.\n' \
      "$secret_name" "$project_name"
  else
    printf '\nSet %s for Pages project %s. Wrangler will prompt without echoing the value.\n' \
      "$secret_name" "$project_name"
  fi
  pnpm exec wrangler pages secret put "$secret_name" --project-name "$project_name"
done
