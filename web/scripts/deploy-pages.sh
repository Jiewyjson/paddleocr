#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: pnpm pages:deploy -- <project-name> [branch]

Build the Astro site and deploy it, including the /functions Pages Function,
to an existing Cloudflare Pages Direct Upload project. The branch defaults to
"main" and must match the production branch chosen during project creation.
EOF
}

if [[ "${1:-}" == "--" ]]; then
  shift
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 || $# -gt 2 || -z "${1:-}" ]]; then
  usage >&2
  exit 64
fi

project_name="$1"
branch="${2:-main}"

pnpm run pages:build

exec pnpm exec wrangler pages deploy dist \
  --project-name "$project_name" \
  --branch "$branch"
