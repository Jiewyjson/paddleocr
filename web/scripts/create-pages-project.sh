#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: pnpm pages:create -- <project-name> [production-branch]

Create a Cloudflare Pages Direct Upload project. The production branch defaults
to "main". Direct Upload projects cannot later be converted to Git-integrated
Pages projects, so choose this only for the manual Wrangler deployment flow.
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
production_branch="${2:-main}"

printf 'Creating Cloudflare Pages Direct Upload project %q (production branch: %q)\n' \
  "$project_name" "$production_branch"

exec pnpm exec wrangler pages project create "$project_name" \
  --production-branch "$production_branch" \
  --compatibility-date 2026-08-16
