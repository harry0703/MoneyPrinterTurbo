#!/bin/bash
set -euo pipefail

CONFIG_PATH="./config.toml"
APP_PORT="${PORT:-8080}"
APP_HOST="0.0.0.0"
LLM="${LLM_PROVIDER:-openai}"

cat > "$CONFIG_PATH" << TOML
# Auto-generated at container startup — do not edit

listen_host = "${APP_HOST}"
listen_port = ${APP_PORT}
llm_provider = "${LLM}"

[app]
host = "${APP_HOST}"
port = ${APP_PORT}
log_level = "${LOG_LEVEL:-INFO}"

[llm]
provider = "${LLM}"
llm_provider = "${LLM}"
openai_api_key = "${OPENAI_API_KEY:-}"
openai_model_name = "${OPENAI_MODEL:-gpt-4o-mini}"
openai_base_url = "https://api.openai.com/v1"
gemini_api_key = "${GEMINI_API_KEY:-}"
gemini_model_name = "gemini-1.5-flash"
deepseek_api_key = "${DEEPSEEK_API_KEY:-}"
deepseek_base_url = "https://api.deepseek.com/v1"
deepseek_model_name = "deepseek-chat"
moonshot_api_key = "${MOONSHOT_API_KEY:-}"
moonshot_base_url = "https://api.moonshot.cn/v1"
moonshot_model_name = "moonshot-v1-8k"

[media]
pexels_api_keys = ["${PEXELS_API_KEYS}"]

[storage]
tasks_dir = "./storage/tasks"
TOML

echo "[Config] Generated config.toml with listen_port=${APP_PORT} llm_provider=${LLM}"

# Show key presence (not value) for debugging
echo "[Config] OpenAI key set: $([ -n "${OPENAI_API_KEY:-}" ] && echo YES || echo NO)"
echo "[Config] Gemini key set: $([ -n "${GEMINI_API_KEY:-}" ] && echo YES || echo NO)"
