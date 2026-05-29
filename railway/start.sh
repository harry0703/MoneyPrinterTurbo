#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Clipp Engine — Railway Startup Script
# ─────────────────────────────────────────────────────────────

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[Clipp Engine]${NC} $1"; }
fail() { echo -e "${RED}[Error]${NC} $1"; exit 1; }

# Validate required env vars
[ -z "${INTERNAL_API_SECRET:-}" ] && fail "Missing required environment variable: INTERNAL_API_SECRET"
[ -z "${PEXELS_API_KEYS:-}" ]     && fail "Missing required environment variable: PEXELS_API_KEYS"

# Railway assigns PORT dynamically — must use it
export APP_PORT="${PORT:-8080}"
export APP_HOST="0.0.0.0"

log "Generating config.toml..."
./generate-config.sh

log "Verifying FFmpeg..."
ffmpeg -version 2>&1 | head -1 || fail "FFmpeg not found"

log "Starting MPT on host=${APP_HOST} port=${APP_PORT}..."

# Override port directly via uvicorn — bypasses config.toml port reading entirely
# This guarantees MPT listens on Railway's assigned PORT
exec python -m uvicorn app.asgi:app \
    --host "${APP_HOST}" \
    --port "${APP_PORT}" \
    --log-level warning
