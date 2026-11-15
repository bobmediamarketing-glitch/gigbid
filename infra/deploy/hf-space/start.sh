#!/usr/bin/env bash
# Container entrypoint for single-container hosts (Hugging Face Spaces, Render, ...).
set -euo pipefail
PORT=${PORT:-7860}
DATA=${DATA:-/data}
mkdir -p "$DATA"
export APP_DATABASE_URL=${APP_DATABASE_URL:-sqlite:///$DATA/app.sqlite}
export DATABASE_URL=${DATABASE_URL:-sqlite:///$DATA/checkpoints.sqlite}
export MEMORY_DATABASE_URL=${MEMORY_DATABASE_URL:-sqlite:///$DATA/memory.sqlite}
export WORKSPACE_DIR=${WORKSPACE_DIR:-$DATA/workspace}
export GIGSIM_STATE_FILE=${GIGSIM_STATE_FILE:-$DATA/gigsim.json}
# Secrets from the host's secret store; generated per boot if absent (sessions then reset on restart).
export JWT_SECRET=${JWT_SECRET:-$(python -c 'import secrets; print(secrets.token_hex(24))')}
export TOKEN_ENCRYPTION_KEY=${TOKEN_ENCRYPTION_KEY:-$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')}

uvicorn apps.api.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*' &
PID=$!
for _ in $(seq 1 90); do
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/api/ping')" 2>/dev/null && break
  sleep 2
done
if [ -n "${REVIEWER_EMAIL:-}" ] && [ -n "${REVIEWER_PASSWORD:-}" ]; then
  python -m apps.api.seed_reviewer --persona ai_ml --analyse 6 || echo "reviewer seeding failed (the app still runs)"
fi
wait "$PID"
