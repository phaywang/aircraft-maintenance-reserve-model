#!/bin/zsh

cd "$(dirname "$0")" || exit 1
PORT="${1:-8765}"

(sleep 1; open "http://127.0.0.1:${PORT}") &
PYTHONPYCACHEPREFIX=/private/tmp/aircraft-reserve-pycache python3 scripts/run_dashboard_api.py --port "${PORT}"
