#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[Clipp Engine]${NC} $1"; }
fail() { echo -e "${RED}[Error]${NC} $1"; exit 1; }

[ -z "${INTERNAL_API_SECRET:-}" ] && fail "Missing required environment variable: INTERNAL_API_SECRET"
[ -z "${PEXELS_API_KEYS:-}"     ] && fail "Missing required environment variable: PEXELS_API_KEYS"

export PORT="${PORT:-8080}"

# Find ALL python files mentioning openai_api_key or api_key
echo "=== Searching for API key references in MPT source ==="
grep -r "openai_api_key\|api_key\|load_config\|config\.get" /app --include="*.py" -l 2>/dev/null | head -10
echo "=== Key field names used ==="
grep -r "openai_api_key\|openai.*key\|api_key" /app --include="*.py" -h 2>/dev/null | grep -v "^#" | head -30
echo "=== end search ==="

log "Generating config.toml (port=${PORT})..."
./generate-config.sh

log "Verifying FFmpeg..."
ffmpeg -version 2>&1 | head -1 || fail "FFmpeg not found"

log "Starting MPT on 0.0.0.0:${PORT}..."
exec python -m uvicorn app.asgi:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --log-level warning
