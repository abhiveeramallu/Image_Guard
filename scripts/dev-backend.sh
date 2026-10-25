#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec .venv/bin/uvicorn app.main:app --reload --port 8000
