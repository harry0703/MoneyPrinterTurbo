#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Clipp Engine — Railway Startup Script
#
# Runs before MPT starts. Generates config.toml from
# environment variables injected by Railway, then
# launches the FastAPI server on Railway's $PORT.
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# Colours for readable logs in Railway's log stream
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[Clipp Engine]${NC} $1"; }
warn() { echo -e "${YELLOW}[Warn]${NC} $1"; }
fail() { echo -e "${RED}[Error]${NC} $1"; exit 1; }

# ── Validate required env vars ────────────────────────────────
REQUIRED_VARS=(
    "INTERNAL_API_SECRET"
    "PEXELS_API_KEYS"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        fail "Missing required environment variable: $var"
    fi
done

# ── Railway provides PORT ─────────────────────────────────────
# Railway sets $PORT dynamically. MPT must listen on it.
export APP_PORT="${PORT:-8080}"
export APP_HOST="0.0.0.0"

log "Generating config.toml from environment variables..."
./generate-config.sh

log "Verifying FFmpeg installation..."
ffmpeg -version 2>&1 | head -1 || fail "FFmpeg not found"

log "Verifying ImageMagick installation..."
convert -version 2>&1 | head -1 || warn "ImageMagick not available"

log "Starting Clipp Engine on port ${APP_PORT}..."
log "Internal API authentication: ENABLED"

# Start MPT
exec python main.py
