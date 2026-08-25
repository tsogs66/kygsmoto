#!/usr/bin/env bash
# Start the KYGS POS server.
#
#   ./run.sh              listen on localhost only
#   ./run.sh --lan        listen on the shop network so other tills can connect
set -euo pipefail

cd "$(dirname "$0")"

HOST=127.0.0.1
[[ "${1:-}" == "--lan" ]] && HOST=0.0.0.0
PORT="${PORT:-8000}"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

echo "KYGS POS starting on http://${HOST}:${PORT}"
exec ./.venv/bin/python -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT"
