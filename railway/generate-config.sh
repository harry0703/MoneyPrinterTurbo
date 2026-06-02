#!/bin/bash
set -euo pipefail

CONFIG_PATH="./config.toml"
APP_PORT="${PORT:-8080}"
APP_HOST="0.0.0.0"

cat > "$CONFIG_PATH" << TOML
# Auto-generated at container startup — do not edit

# Top-level keys read directly by config.py
listen_host = "${APP_HOST}"
listen_port = ${APP_PORT}

[app]
host = "${APP_HOST}"
port = ${APP_PORT}
log_level = "${LOG_LEVEL:-INFO}"

[llm]
provider = "${LLM_PROVIDER:-gemini}"
deepseek_api_key = "${DEEPSEEK_API_KEY:-}"
deepseek_base_url = "https://api.deepseek.com/v1"
deepseek_model_name = "deepseek-chat"
openai_api_key = "${OPENAI_API_KEY:-}"
openai_base_url = "https://api.openai.com/v1"
openai_model_name = "gpt-4o-mini"
gemini_api_key = "${GEMINI_API_KEY:-}"
gemini_model_name = "gemini-1.5-flash"

[video]
pexels_api_keys = ["${PEXELS_API_KEYS}"]

[security]
internal_api_secret = "${INTERNAL_API_SECRET}"

[storage]
tasks_dir = "./storage/tasks"

[voice]
default_voice = "${DEFAULT_VOICE:-en-US-AriaNeural}"
TOML

echo "[Config] Generated config.toml with listen_port=${APP_PORT} llm_provider=${LLM_PROVIDER:-gemini}"
