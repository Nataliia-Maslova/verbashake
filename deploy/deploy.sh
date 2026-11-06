#!/usr/bin/env bash
# Upload the app from this Mac to the VPS and rebuild/restart it.
# Usage: deploy/deploy.sh root@<server-ip>
# The server keeps its own .env and .streamlit/secrets.toml (production
# redirect_uri) -- they're never overwritten from this Mac.
set -euo pipefail

SERVER="${1:?usage: deploy/deploy.sh root@<server-ip>}"
cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude venv/ --exclude .venv/ --exclude .git/ --exclude .cache/ \
  --exclude audio_cache/ --exclude logs/ --exclude __pycache__/ \
  --exclude .pytest_cache/ --exclude .claude/ --exclude .DS_Store \
  --exclude .env --exclude .streamlit/secrets.toml --exclude '.streamlit/*.json' \
  ./ "$SERVER:/opt/verbashake/"

ssh "$SERVER" "cd /opt/verbashake && docker compose up -d --build && docker image prune -f"
echo "Deployed. Logs: ssh $SERVER 'cd /opt/verbashake && docker compose logs -f app'"
