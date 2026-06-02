#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[Clipp Engine]${NC} $1"; }
fail() { echo -e "${RED}[Error]${NC} $1"; exit 1; }

[ -z "${INTERNAL_API_SECRET:-}" ] && fail "Missing required env var: INTERNAL_API_SECRET"
[ -z "${PEXELS_API_KEYS:-}"     ] && fail "Missing required env var: PEXELS_API_KEYS"
[ -z "${OPENAI_API_KEY:-}"      ] && fail "Missing required env var: OPENAI_API_KEY"

export PORT="${PORT:-8080}"

# Generate real config FIRST — overwrite placeholder baked into image
log "Generating config.toml (port=${PORT})..."
./generate-config.sh

# Force Python to re-read config before uvicorn imports the app
# This patches the in-memory config object with the real API key
log "Preloading config into Python..."
python3 -c "
import toml, os, sys
cfg = toml.load('./config.toml')
key = cfg.get('openai_api_key', '')
if not key or key == 'PLACEHOLDER':
    print('[FATAL] openai_api_key is empty in config.toml!')
    sys.exit(1)
print(f'[Config] openai_api_key loaded: {key[:8]}...{key[-4:]}')
print(f'[Config] llm_provider: {cfg.get(\"llm_provider\", \"NOT SET\")}')
" || fail "Config validation failed"

log "Verifying FFmpeg..."
ffmpeg -version 2>&1 | head -1 || fail "FFmpeg not found"

log "Starting MPT on 0.0.0.0:${PORT}..."
exec python -m uvicorn app.asgi:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --log-level warning
