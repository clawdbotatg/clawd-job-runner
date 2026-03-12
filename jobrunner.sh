#!/usr/bin/env bash
# clawd-job-runner — Give it a job. It finds the best LLM. It runs it.
# Bash entry point: loads .env, forwards args to Python.

set -euo pipefail

# Resolve real path even when called via symlink
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SCRIPT_SOURCE" ]]; do
    SCRIPT_SOURCE="$(readlink "$SCRIPT_SOURCE")"
done
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"

# Load .env if present
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Check for API key
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo "Error: OPENROUTER_API_KEY not set." >&2
    echo "Set it in .env or export it: export OPENROUTER_API_KEY=sk-or-v1-..." >&2
    exit 1
fi

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found" >&2
    exit 1
fi

# Check requests
if ! python3 -c "import requests" 2>/dev/null; then
    echo "Error: Python 'requests' package not installed." >&2
    echo "Install with: pip install requests" >&2
    exit 1
fi

exec python3 -W ignore::Warning "$SCRIPT_DIR/jobrunner.py" "$@"
