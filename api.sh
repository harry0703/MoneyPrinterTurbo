#!/usr/bin/env sh

# Launch the FastAPI API service (http://127.0.0.1:8080/docs).

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python main.py
elif command -v uv >/dev/null 2>&1; then
  exec uv run python main.py
else
  echo "***** No Python environment found. Run 'sh install.sh' first *****"
  echo "***** or run 'sh webui.sh' for automatic first-time setup. *****"
  exit 1
fi
