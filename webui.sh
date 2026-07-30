#!/usr/bin/env sh

# If you could not download the model from the official site, you can use the mirror site.
# Just remove the comment of the following line .
# 공식 사이트에서 모델을 내려받을 수 없다면 미러 사이트를 쓸 수 있다.
# 아래 한 줄의 주석만 지우면 된다.

# export HF_ENDPOINT=https://hf-mirror.com

CURRENT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$CURRENT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# 0.0.0.0 은 '모든 네트워크 인터페이스에서 수신' 이라는 뜻일 뿐, 브라우저 접속 주소로는
# 적절하지 않다. macOS/Linux 에서 http://0.0.0.0:8501 을 열면 프록시나 게이트웨이를 거쳐
# 502 가 날 수 있다. 기본값으로 127.0.0.1 에 바인딩하고 그 주소를 열어, Windows 실행
# 스크립트와 동작을 맞춘다.
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

# 포트 탐지는 Python 으로 한다. macOS/Linux 배포판마다 다른 lsof/nc 에 의존하지 않기 위해서다.
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
