#!/usr/bin/env sh

# If you cannot download the model from the official site, you can use the mirror site.
# Just remove the comment of the following line.

# export HF_ENDPOINT=https://hf-mirror.com

CURRENT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$CURRENT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# First-run bootstrap: if no project Python and no uv exist, run the
# one-time installer automatically so a fresh clone can start directly.
if [ ! -x "$CURRENT_DIR/.venv/bin/python" ] && ! command -v uv >/dev/null 2>&1; then
  echo "***** No Python environment found - running first-time setup, please wait... *****"
  sh "$CURRENT_DIR/install.sh" || {
    echo "***** First-time setup failed. Follow the messages above, then try again. *****"
    exit 1
  }
fi

# 0.0.0.0 only means "listen on all network interfaces"; it is not a valid
# browser address. On macOS/Linux, opening http://0.0.0.0:8501 may be routed
# through a proxy or gateway and fail with 502. Bind to 127.0.0.1 by default,
# matching the behavior of the Windows launch script.
MPT_WEBUI_HOST="${MPT_WEBUI_HOST:-127.0.0.1}"
MPT_WEBUI_PORT="${MPT_WEBUI_PORT:-8501}"

if [ -x "$CURRENT_DIR/.venv/bin/python" ]; then
  PORT_CHECK_CMD="$CURRENT_DIR/.venv/bin/python"
  set -- "$CURRENT_DIR/.venv/bin/python" -m streamlit
elif command -v uv >/dev/null 2>&1; then
  PORT_CHECK_CMD="uv run python"
  set -- uv run streamlit
elif command -v streamlit >/dev/null 2>&1; then
  echo "***** Warning: using streamlit from PATH. If dependencies fail, run 'uv sync --frozen' first. *****"
  PORT_CHECK_CMD="python3"
  set -- streamlit
else
  echo "***** Neither project Python, uv, nor streamlit was found. Please install dependencies first. *****"
  exit 1
fi

find_available_port() {
  WEBUI_HOST="$MPT_WEBUI_HOST" WEBUI_PORT="$MPT_WEBUI_PORT" "$@" - <<'PY' 2>/dev/null
import os
import socket
import sys

host = os.environ.get("WEBUI_HOST", "127.0.0.1")
preferred = int(os.environ.get("WEBUI_PORT", "8501"))
candidates = [preferred] + [port for port in range(8502, 8600) if port != preferred]

for port in candidates:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            continue
        print(port)
        sys.exit(0)

sys.exit(1)
PY
}

# Use Python for port probing to avoid depending on lsof/nc, which differ
# across macOS and Linux distributions.
# shellcheck disable=SC2086
SELECTED_WEBUI_PORT=$(find_available_port $PORT_CHECK_CMD)

if [ -z "$SELECTED_WEBUI_PORT" ]; then
  echo "***** No available WebUI port found in 8501-8599 for $MPT_WEBUI_HOST. *****"
  exit 1
fi

if [ "$SELECTED_WEBUI_PORT" != "$MPT_WEBUI_PORT" ]; then
  echo "***** Port $MPT_WEBUI_PORT is unavailable, using $SELECTED_WEBUI_PORT instead. *****"
fi

MPT_WEBUI_PORT="$SELECTED_WEBUI_PORT"

echo "***** WebUI address: http://$MPT_WEBUI_HOST:$MPT_WEBUI_PORT *****"
"$@" run "$CURRENT_DIR/webui/Main.py" \
  --server.address="$MPT_WEBUI_HOST" \
  --server.port="$MPT_WEBUI_PORT" \
  --browser.serverAddress="$MPT_WEBUI_HOST" \
  --browser.gatherUsageStats=False \
  --client.toolbarMode=minimal \
  --logger.hideWelcomeMessage=True \
  --server.showEmailPrompt=False \
  --server.enableCORS=True
