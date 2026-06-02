#!/bin/bash
set -euo pipefail

CONFIG_PATH="./config.toml"
APP_PORT="${PORT:-8080}"
LLM="${LLM_PROVIDER:-openai}"
OPENAI_KEY="${OPENAI_API_KEY:-}"
GEMINI_KEY="${GEMINI_API_KEY:-}"
DEEPSEEK_KEY="${DEEPSEEK_API_KEY:-}"
PEXELS_KEYS="${PEXELS_API_KEYS:-}"

# MPT reads ALL LLM keys from config.app — they MUST be inside [app] section
# Source: app/services/llm.py → config.app.get("openai_api_key")
printf '%s\n' \
"# Auto-generated at container startup" \
"" \
"[app]" \
"llm_provider = \"${LLM}\"" \
"openai_api_key = \"${OPENAI_KEY}\"" \
"openai_model_name = \"gpt-4o-mini\"" \
"openai_base_url = \"https://api.openai.com/v1\"" \
"gemini_api_key = \"${GEMINI_KEY}\"" \
"gemini_model_name = \"gemini-1.5-flash\"" \
"deepseek_api_key = \"${DEEPSEEK_KEY}\"" \
"deepseek_base_url = \"https://api.deepseek.com/v1\"" \
"deepseek_model_name = \"deepseek-chat\"" \
"pexels_api_keys = [\"${PEXELS_KEYS}\"]" \
"" \
"[storage]" \
"tasks_dir = \"./storage/tasks\"" \
> "$CONFIG_PATH"

echo "[Config] Generated config.toml — llm_provider=${LLM}"
echo "[Config] OpenAI key set: $([ -n "${OPENAI_KEY}" ] && echo YES || echo NO)"
