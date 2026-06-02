#!/bin/bash
set -euo pipefail

CONFIG_PATH="./config.toml"
APP_PORT="${PORT:-8080}"
LLM="${LLM_PROVIDER:-openai}"
OPENAI_KEY="${OPENAI_API_KEY:-}"
GEMINI_KEY="${GEMINI_API_KEY:-}"
DEEPSEEK_KEY="${DEEPSEEK_API_KEY:-}"
PEXELS_KEYS="${PEXELS_API_KEYS:-}"

# Write config using printf to avoid heredoc variable expansion issues
# (API keys with special chars like +/= break heredoc expansion)
printf '%s\n' \
"# Auto-generated at container startup" \
"" \
"listen_host = \"0.0.0.0\"" \
"listen_port = ${APP_PORT}" \
"llm_provider = \"${LLM}\"" \
"" \
"[app]" \
"host = \"0.0.0.0\"" \
"port = ${APP_PORT}" \
"log_level = \"INFO\"" \
"" \
"[llm]" \
"provider = \"${LLM}\"" \
"llm_provider = \"${LLM}\"" \
"openai_api_key = \"${OPENAI_KEY}\"" \
"openai_model_name = \"gpt-4o-mini\"" \
"openai_base_url = \"https://api.openai.com/v1\"" \
"gemini_api_key = \"${GEMINI_KEY}\"" \
"gemini_model_name = \"gemini-1.5-flash\"" \
"deepseek_api_key = \"${DEEPSEEK_KEY}\"" \
"deepseek_base_url = \"https://api.deepseek.com/v1\"" \
"deepseek_model_name = \"deepseek-chat\"" \
"" \
"[media]" \
"pexels_api_keys = [\"${PEXELS_KEYS}\"]" \
"" \
"[storage]" \
"tasks_dir = \"./storage/tasks\"" \
> "$CONFIG_PATH"

echo "[Config] Generated config.toml with llm_provider=${LLM}"
echo "[Config] OpenAI key set: $([ -n "${OPENAI_KEY}" ] && echo YES || echo NO)"
echo "[Config] Gemini key set: $([ -n "${GEMINI_KEY}" ] && echo YES || echo NO)"
echo "[Config] --- config.toml contents ---"
cat "$CONFIG_PATH"
echo "[Config] --- end config.toml ---"
