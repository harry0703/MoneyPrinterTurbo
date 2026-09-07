#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
TTS_DIR="$ROOT/tts-service"
TTS_LOG="$ROOT/tts-service.log"
TTS_PORT=8090
WEBUI_PORT=8080

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RESET='\033[0m'

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${CYAN}  MoneyPrinterTurbo + TTS Service Launcher${RESET}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

# ── Kill any leftover processes on our ports ───────────────────────────────────
for port in $TTS_PORT $WEBUI_PORT; do
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo -e "${YELLOW}  Stopping process on port $port…${RESET}"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 0.5
  fi
done

# ── Detect TTS venv ────────────────────────────────────────────────────────────
if [ -x "$TTS_DIR/venv311/bin/uvicorn" ]; then
  TTS_PYTHON="$TTS_DIR/venv311/bin"
elif [ -x "$TTS_DIR/venv/bin/uvicorn" ]; then
  TTS_PYTHON="$TTS_DIR/venv/bin"
else
  echo -e "${YELLOW}  No TTS venv found — skipping TTS service.${RESET}"
  TTS_PYTHON=""
fi

# ── Start TTS service ──────────────────────────────────────────────────────────
if [ -n "$TTS_PYTHON" ]; then
  echo -e "${GREEN}  Starting TTS Service on port $TTS_PORT…${RESET}"
  TTS_ENGINE="${TTS_ENGINE:-edge_tts}" \
    "$TTS_PYTHON/uvicorn" app.main:app \
      --host 0.0.0.0 \
      --port "$TTS_PORT" \
    > "$TTS_LOG" 2>&1 &
  TTS_PID=$!

  # Wait for TTS to be ready (up to 10s)
  for i in $(seq 1 20); do
    if curl -sf "http://localhost:$TTS_PORT/health" >/dev/null 2>&1; then
      echo -e "${GREEN}  ✓ TTS Service ready  →  http://localhost:$TTS_PORT${RESET}"
      break
    fi
    sleep 0.5
  done
fi

# ── Start MoneyPrinter WebUI ───────────────────────────────────────────────────
echo -e "${GREEN}  Starting MoneyPrinter WebUI on port $WEBUI_PORT…${RESET}"

# If you cannot download models from HuggingFace, uncomment:
# export HF_ENDPOINT=https://hf-mirror.com

# Prefer the project's own venv streamlit; fall back to PATH
STREAMLIT="${ROOT}/venv/bin/streamlit"
[ -x "$STREAMLIT" ] || STREAMLIT="$(command -v streamlit 2>/dev/null || true)"
[ -x "$STREAMLIT" ] || { echo -e "${YELLOW}  streamlit not found — install via: pip install streamlit${RESET}"; exit 1; }

"$STREAMLIT" run "$ROOT/webui/Main.py" \
  --server.port="$WEBUI_PORT" \
  --server.address="0.0.0.0" \
  --browser.serverAddress="127.0.0.1" \
  --server.enableCORS=True \
  --browser.gatherUsageStats=False &
WEBUI_PID=$!

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  MoneyPrinter WebUI  →  ${GREEN}http://localhost:$WEBUI_PORT${RESET}"
[ -n "$TTS_PYTHON" ] && \
echo -e "  TTS Service         →  ${GREEN}http://localhost:$TTS_PORT${RESET}"
[ -n "$TTS_PYTHON" ] && \
echo -e "  TTS API Docs        →  ${GREEN}http://localhost:$TTS_PORT/docs${RESET}"
[ -n "$TTS_PYTHON" ] && \
echo -e "  TTS Log             →  $TTS_LOG"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  Press ${YELLOW}Ctrl+C${RESET} to stop both services."
echo ""

# ── Wait and handle Ctrl+C ────────────────────────────────────────────────────
trap 'echo -e "\n${YELLOW}Shutting down…${RESET}"; kill $TTS_PID $WEBUI_PID 2>/dev/null; exit 0' INT TERM

wait
