set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set dotenv-load := false

root := justfile_directory()
sock := root / ".run/process-compose.sock"
export PC_SOCKET_PATH := sock
export PC_LOG_FILE := root / "logs/process-compose-cli.log"

# List stack commands
default:
    @just --list

# Install process-compose (run once; needs your confirmation for the tap)
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    just _pc-config
    if command -v process-compose >/dev/null 2>&1; then
      echo "process-compose already on PATH: $(command -v process-compose)"
      process-compose version
      exit 0
    fi
    echo "process-compose is not installed."
    echo
    echo "Install it once with Homebrew:"
    echo "  brew tap f1bonacc1/tap"
    echo "  brew install process-compose"
    echo
    echo "Or download the official binary from:"
    echo "  https://github.com/F1bonacc1/process-compose/releases/latest"
    exit 1

# Foreground: MLX + OCR API + Astro UI
dev: _tools _prepare
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ root }}"
    if just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack already running in the background. Stop it first: just stop"
      echo "Or attach to its TUI: just attach"
      exit 1
    fi
    just _refuse-busy-ports 8111 8788 4321
    process-compose --unix-socket "{{ sock }}" -e backend/.env up --tui=true

# Background: MLX + OCR API only
serve: _tools _prepare
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ root }}"
    if just --quiet _stack-up >/dev/null 2>&1; then
      if just --quiet _api-healthy >/dev/null 2>&1; then
        echo "Stack already running."
        just status
        echo
        echo "Serving in the background."
        just _announce
        exit 0
      fi
      echo "Stack process is up but the OCR API is not healthy. Restarting..." >&2
      just stop
    fi
    just _refuse-busy-ports 8111 8788
    process-compose --unix-socket "{{ sock }}" -e backend/.env \
      up --namespace ocr --detached --tui=false
    echo "Waiting for OCR API..."
    if just _wait-api; then
      echo
      echo "Serving in the background."
      just _announce
      exit 0
    fi
    echo "API did not become healthy. See just logs / just status." >&2
    exit 1

# Stop the process-compose stack
stop: _tools
    #!/usr/bin/env bash
    set -euo pipefail
    if ! just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack is not running."
      exit 0
    fi
    process-compose --unix-socket "{{ sock }}" down
    rm -f "{{ sock }}"
    echo "Stopped."

# Show process-compose process list and HTTP health
status: _tools
    #!/usr/bin/env bash
    set -euo pipefail
    if ! just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack is not running."
      exit 1
    fi
    process-compose --unix-socket "{{ sock }}" process list -o wide
    echo
    echo -n "MLX     "; curl -sS -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8111/docs || echo "down"
    echo
    echo -n "OCR API "; curl -sS -m 3 "$(just --quiet _api-base)/v1/healthz" || echo "down"
    echo

# Attach the TUI to a detached stack
attach: _tools
    #!/usr/bin/env bash
    set -euo pipefail
    if ! just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack is not running. Start it with just serve or just dev." >&2
      exit 1
    fi
    process-compose --unix-socket "{{ sock }}" attach

# Tail on-disk logs
logs:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ justfile_directory() }}"
    shopt -s nullglob
    files=(logs/*.log)
    if [[ ${#files[@]} -eq 0 ]]; then
      echo "No log files yet under logs/."
      exit 1
    fi
    tail -n 50 -f "${files[@]}"

# Start the Astro UI on all interfaces. `just web 127.0.0.1` for loopback only.
web host="0.0.0.0":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ root }}"
    if [[ ! -f web/.env ]]; then
      cp web/.env.example web/.env
    fi
    proxy_origin="$(sed -n 's/^OCR_API_ORIGIN=//p' web/.env | tail -1 | tr -d '\r')"
    proxy_origin="${proxy_origin:-http://127.0.0.1:8788}"
    if ! curl -sf -o /dev/null --connect-timeout 1 "${proxy_origin}/v1/healthz"; then
      echo "OCR API is not reachable at ${proxy_origin} (web/.env OCR_API_ORIGIN)." >&2
      echo "just serve must bind FastAPI to that same address (backend/.env OCR_BIND_HOST)." >&2
      echo "Start or restart the API with: just stop && just serve" >&2
      exit 1
    fi
    pnpm --dir web dev --host "{{ host }}"

[private]
_tools:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v process-compose >/dev/null 2>&1; then
      echo "process-compose is not on PATH. Run: just setup" >&2
      exit 1
    fi
    if [[ ! -x "{{ root }}/.venv/bin/python" ]]; then
      echo "Missing .venv/bin/python. Create the project virtualenv first." >&2
      exit 1
    fi
    just _pc-config

# process-compose v1.x dumps a JSON "config home" debug line on every CLI
# invocation unless this directory exists. ~/.config is on its macOS search path.
[private]
_pc-config:
    @mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/process-compose" "{{ root }}/logs"

[private]
_prepare:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ root }}"
    mkdir -p logs .run
    just _pc-config
    if [[ ! -f web/.env ]]; then
      cp web/.env.example web/.env
    fi
    if [[ -e "{{ sock }}" ]] && ! process-compose --unix-socket "{{ sock }}" process list >/dev/null 2>&1; then
      rm -f "{{ sock }}"
    fi

[private]
_stack-up:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ -S "{{ sock }}" ]] || exit 1
    process-compose --unix-socket "{{ sock }}" process list >/dev/null 2>&1

[private]
_load-backend-env:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ root }}"
    if [[ -f backend/.env ]]; then
      set -a
      # shellcheck disable=SC1091
      source backend/.env
      set +a
    fi
    port="${OCR_PORT:-8788}"
    bind="${OCR_BIND_HOST:-127.0.0.1}"
    if [[ "$bind" == "0.0.0.0" ]]; then
      bind="127.0.0.1"
    fi
    echo "OCR_BIND_HOST=${bind}"
    echo "OCR_PORT=${port}"

[private]
_api-base:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --quiet _load-backend-env)"
    echo "http://${OCR_BIND_HOST}:${OCR_PORT}"

[private]
_api-healthy:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --quiet _load-backend-env)"
    hosts=("${OCR_BIND_HOST}")
    [[ "${OCR_BIND_HOST}" != "127.0.0.1" ]] && hosts+=("127.0.0.1")
    for h in "${hosts[@]}"; do
      if curl -sf -o /dev/null --connect-timeout 1 "http://${h}:${OCR_PORT}/v1/healthz"; then
        exit 0
      fi
    done
    exit 1

[private]
_wait-api:
    #!/usr/bin/env bash
    set -euo pipefail
    for _ in $(seq 1 90); do
      if just --quiet _api-healthy >/dev/null 2>&1; then
        exit 0
      fi
      sleep 1
    done
    exit 1

[private]
_announce:
    #!/usr/bin/env bash
    set -euo pipefail
    api_base="$(just --quiet _api-base)"
    echo "  MLX     http://127.0.0.1:8111/"
    echo "  OCR API ${api_base}/v1/healthz"
    echo "  UI      just web   (or just web 0.0.0.0 for LAN)"
    echo "  stop    just stop"
    echo "  logs    just logs"

[private]
_refuse-busy-ports +ports:
    #!/usr/bin/env bash
    set -euo pipefail
    busy=()
    for port in {{ ports }}; do
      if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        busy+=("$port")
      fi
    done
    if [[ ${#busy[@]} -gt 0 ]]; then
      echo "Port(s) already in use: ${busy[*]}" >&2
      echo "Stop the existing servers before starting the stack." >&2
      lsof -nP -iTCP:8111 -sTCP:LISTEN -iTCP:8788 -sTCP:LISTEN -iTCP:4321 -sTCP:LISTEN || true
      exit 1
    fi
