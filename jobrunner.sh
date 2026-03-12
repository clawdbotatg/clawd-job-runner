#!/usr/bin/env bash
# clawd-job-runner entry point
# Loads .env, then delegates to jobrunner.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# Check for python3
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found" >&2
    exit 1
fi

# Check for requests
if ! python3 -c "import requests" &>/dev/null; then
    echo "Installing requests..." >&2
    pip3 install requests -q
fi

exec python3 "$SCRIPT_DIR/jobrunner.py" "$@"
