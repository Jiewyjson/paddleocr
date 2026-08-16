set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set dotenv-load := false

export PC_SOCKET_PATH := justfile_directory() / ".run/process-compose.sock"

# List stack commands
default:
    @just --list

# Install process-compose (run once; needs your confirmation for the tap)
setup:
    #!/usr/bin/env bash
    set -euo pipefail
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
    cd "{{ justfile_directory() }}"
    if just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack already running in the background. Stop it first: just stop"
      echo "Or attach to its TUI: just attach"
      exit 1
    fi
    just _refuse-busy-ports 8111 8788 4321
    process-compose --unix-socket "{{ justfile_directory() }}/.run/process-compose.sock" up --tui=true

# Background: MLX + OCR API only
serve: _tools _prepare
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ justfile_directory() }}"
    if just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack already running."
      just status
      exit 0
    fi
    just _refuse-busy-ports 8111 8788
    process-compose --unix-socket "{{ justfile_directory() }}/.run/process-compose.sock" \
      up --namespace ocr --detached --tui=false
    echo "Waiting for OCR API..."
    api_host="${OCR_BIND_HOST:-127.0.0.1}"
    if [[ "$api_host" == "0.0.0.0" ]]; then
      api_host="127.0.0.1"
    fi
    api_port="${OCR_PORT:-8788}"
    for _ in $(seq 1 90); do
      if curl -sf -o /dev/null "http://${api_host}:${api_port}/v1/healthz"; then
        echo
        echo "Serving in the background."
        echo "  MLX     http://127.0.0.1:8111/"
        echo "  OCR API http://${api_host}:${api_port}/v1/healthz"
        echo "  UI      just web   (or just web 0.0.0.0 for LAN)"
        echo "  stop    just stop"
        echo "  logs    just logs"
        exit 0
      fi
      sleep 1
    done
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
    process-compose --unix-socket "{{ justfile_directory() }}/.run/process-compose.sock" down
    rm -f "{{ justfile_directory() }}/.run/process-compose.sock"
    echo "Stopped."

# Show process-compose process list and HTTP health
status: _tools
    #!/usr/bin/env bash
    set -euo pipefail
    if ! just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack is not running."
      exit 1
    fi
    process-compose --unix-socket "{{ justfile_directory() }}/.run/process-compose.sock" process list
    echo
    echo -n "MLX     "; curl -sS -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8111/docs || echo "down"
    echo
    echo -n "OCR API "; curl -sS -m 3 http://127.0.0.1:8788/v1/healthz || echo "down"
    echo

# Attach the TUI to a detached stack
attach: _tools
    #!/usr/bin/env bash
    set -euo pipefail
    if ! just --quiet _stack-up >/dev/null 2>&1; then
      echo "Stack is not running. Start it with just serve or just dev." >&2
      exit 1
    fi
    process-compose --unix-socket "{{ justfile_directory() }}/.run/process-compose.sock" attach

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
    cd "{{ justfile_directory() }}"
    if [[ ! -f web/.env ]]; then
      cp web/.env.example web/.env
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
    if [[ ! -x "{{ justfile_directory() }}/.venv/bin/python" ]]; then
      echo "Missing .venv/bin/python. Create the project virtualenv first." >&2
      exit 1
    fi

[private]
_prepare:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ justfile_directory() }}"
    mkdir -p logs .run
    if [[ ! -f web/.env ]]; then
      cp web/.env.example web/.env
    fi
    sock=".run/process-compose.sock"
    if [[ -e "$sock" ]] && ! process-compose --unix-socket "$sock" process list >/dev/null 2>&1; then
      rm -f "$sock"
    fi

[private]
_stack-up:
    #!/usr/bin/env bash
    set -euo pipefail
    sock="{{ justfile_directory() }}/.run/process-compose.sock"
    [[ -S "$sock" ]] || exit 1
    process-compose --unix-socket "$sock" process list >/dev/null 2>&1

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
