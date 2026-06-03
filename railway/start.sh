#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[Clipp Engine]${NC} $1"; }
fail() { echo -e "${RED}[Error]${NC} $1"; exit 1; }

[ -z "${INTERNAL_API_SECRET:-}" ] && fail "Missing required env var: INTERNAL_API_SECRET"
[ -z "${PEXELS_API_KEYS:-}"     ] && fail "Missing required env var: PEXELS_API_KEYS"
[ -z "${OPENAI_API_KEY:-}"      ] && fail "Missing required env var: OPENAI_API_KEY"

export PORT="${PORT:-8080}"

log "Generating config.toml (port=${PORT})..."
./generate-config.sh

log "Verifying FFmpeg..."
ffmpeg -version 2>&1 | head -1 || fail "FFmpeg not found"

log "Starting MPT on 0.0.0.0:${PORT}..."

# Single worker — MPT task state is in-memory and not safe to share.
# Health check is kept lightweight (always returns 200) so it never
# blocks on encoding. Railway restart policy is set to NEVER in
# railway.toml to prevent mid-job container kills.
exec python -m uvicorn app.asgi:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers 1 \
    --log-level warning
