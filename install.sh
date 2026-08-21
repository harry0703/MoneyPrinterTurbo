#!/usr/bin/env sh

# One-time setup: installs uv (if missing), Python 3.11, all dependencies,
# and creates config.toml from the example file.

set -e
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

echo "***** MoneyPrinterTurbo - one-time setup *****"

UV_BIN="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
fi

if [ -z "$UV_BIN" ]; then
  echo "***** uv not found - installing uv automatically, please wait... *****"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV_BIN="$(command -v uv 2>/dev/null || true)"
  if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
  fi
fi

if [ -z "$UV_BIN" ]; then
  echo "***** Failed to install uv automatically. *****"
  echo "***** Please install it manually: https://docs.astral.sh/uv/getting-started/installation/ *****"
  echo "***** Then run install.sh again. *****"
  exit 1
fi

echo "***** Using uv: $UV_BIN *****"

# Install Python 3.11 and all dependencies into .venv
"$UV_BIN" python install 3.11
"$UV_BIN" sync --frozen

# Create the local config file on first run
if [ ! -f config.toml ]; then
  echo "***** Creating config.toml from config.example.toml *****"
  cp config.example.toml config.toml
fi

echo
echo "***** Setup finished successfully! *****"
echo "***** Start the WebUI:        run sh webui.sh *****"
echo "***** Start the API service:  run sh api.sh *****"
