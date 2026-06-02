#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[Clipp Engine]${NC} $1"; }
fail() { echo -e "${RED}[Error]${NC} $1"; exit 1; }

[ -z "${INTERNAL_API_SECRET:-}" ] && fail "Missing required environment variable: INTERNAL_API_SECRET"
[ -z "${PEXELS_API_KEYS:-}"     ] && fail "Missing required environment variable: PEXELS_API_KEYS"

export PORT="${PORT:-8080}"

# CRITICAL: Generate config BEFORE anything else
# MPT reads config.toml at Python module import time,
# so we must write it before uvicorn starts
log "Generating config.toml (port=${PORT})..."
./generate-config.sh

# Verify config was written with correct llm_provider
log "Config verification:"
grep "llm_provider" ./config.toml || echo "WARNING: llm_provider not found in config"

log "Verifying FFmpeg..."
ffmpeg -version 2>&1 | head -1 || fail "FFmpeg not found"

log "Starting MPT on 0.0.0.0:${PORT}..."
exec python -m uvicorn app.asgi:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --log-level warning
