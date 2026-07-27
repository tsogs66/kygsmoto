#!/usr/bin/env bash
# Proxmox LXC / Linux install helper for KYGSMOTO
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Installing system packages (Debian/Ubuntu)"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip curl
  # Node via NodeSource or existing npm
  if ! command -v npm >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
  fi
fi

echo "==> Backend venv"
python3 -m venv "$ROOT/.venv"
source "$ROOT/.venv/bin/activate"
pip install -r backend/requirements.txt

echo "==> Frontend build"
cd frontend
npm ci
npm run build
mkdir -p ../backend/static
rm -rf ../backend/static/*
cp -r dist/* ../backend/static/
cd ..

echo "==> Starting API on :8000"
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
