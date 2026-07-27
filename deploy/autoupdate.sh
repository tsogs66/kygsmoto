#!/usr/bin/env bash
# Autoupdate KYGSMOTO from GitHub: pull latest code, rebuild, restart.
#
# Usage (inside LXC, from the clone directory or anywhere):
#   ./deploy/autoupdate.sh
#   ./deploy/autoupdate.sh --branch cursor/kygsmoto-sales-inventory-9004
#   ./deploy/autoupdate.sh --branch main --no-build
#   REPO_DIR=/root/kygsmoto ./deploy/autoupdate.sh
#
# Cron example (daily 3am):
#   0 3 * * * /root/kygsmoto/deploy/autoupdate.sh >> /var/log/kygsmoto-autoupdate.log 2>&1
set -euo pipefail

BRANCH="${BRANCH:-}"
DO_BUILD=1
REPO_DIR="${REPO_DIR:-}"
REMOTE="${REMOTE:-origin}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch|-b) BRANCH="$2"; shift 2 ;;
    --no-build) DO_BUILD=0; shift ;;
    --repo-dir) REPO_DIR="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

# Resolve repo root
if [[ -z "$REPO_DIR" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$SCRIPT_DIR/../docker-compose.yml" ]]; then
    REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
  elif [[ -f "$HOME/kygsmoto/docker-compose.yml" ]]; then
    REPO_DIR="$HOME/kygsmoto"
  elif [[ -f "./docker-compose.yml" ]]; then
    REPO_DIR="$(pwd)"
  else
    echo "ERROR: cannot find kygsmoto repo (set REPO_DIR=...)" >&2
    exit 1
  fi
fi

cd "$REPO_DIR"
echo "==> Repo: $REPO_DIR"
echo "==> Time: $(date -Is)"

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git not installed (apt install -y git)" >&2
  exit 1
fi

if [[ ! -d .git ]]; then
  echo "ERROR: $REPO_DIR is not a git checkout" >&2
  exit 1
fi

# Detect compose command
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  COMPOSE=()
fi

echo "==> Fetching $REMOTE"
git fetch "$REMOTE" --prune

CURRENT="$(git rev-parse --abbrev-ref HEAD)"
if [[ -z "$BRANCH" ]]; then
  BRANCH="$CURRENT"
fi

echo "==> Current branch: $CURRENT → target: $BRANCH"
if [[ "$CURRENT" != "$BRANCH" ]]; then
  git checkout "$BRANCH"
fi

BEFORE="$(git rev-parse HEAD)"
# Prefer remote branch tip; allow dirty tree for local data files
git pull --ff-only "$REMOTE" "$BRANCH" || {
  echo "WARN: fast-forward pull failed; trying reset to $REMOTE/$BRANCH"
  git fetch "$REMOTE" "$BRANCH"
  git reset --hard "$REMOTE/$BRANCH"
}
AFTER="$(git rev-parse HEAD)"

if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "==> Already up to date ($AFTER)"
else
  echo "==> Updated $BEFORE → $AFTER"
  git log --oneline "$BEFORE..$AFTER" | head -20
fi

if [[ "$DO_BUILD" -eq 1 ]]; then
  if [[ ${#COMPOSE[@]} -eq 0 ]]; then
    echo "WARN: docker compose not found — skip rebuild. Install Docker or run deploy/lxc-install.sh"
  else
    echo "==> Rebuilding containers"
    "${COMPOSE[@]}" up -d --build --remove-orphans
    "${COMPOSE[@]}" ps
  fi
fi

echo "==> Autoupdate complete"
if command -v hostname >/dev/null 2>&1; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$IP" ]] && echo "App: http://${IP}:8000"
fi
