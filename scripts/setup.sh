#!/usr/bin/env bash
# One-time setup: Python venv + backend deps, and frontend deps.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null || PY=python3
"$PY" -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  # Local-only random key for invisible watermarking (never commit .env; set your own in production).
  echo "IMAGEGUARD_WATERMARK_KEY=$(backend/.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(32))')" >> backend/.env
fi
(cd frontend && npm install)
[ -f frontend/.env ] || cp frontend/.env.example frontend/.env
echo "Setup complete. Run scripts/dev-backend.sh and scripts/dev-frontend.sh in two terminals."
