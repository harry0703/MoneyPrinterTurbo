#!/bin/bash
set -euo pipefail

CONFIG_PATH="./config.toml"
APP_PORT="${PORT:-8080}"
APP_HOST="0.0.0.0"
LLM="${LLM_PROVIDER:-pollinations}"

cat > "$CONFIG_PATH" << TOML
# Auto-generated at container startup — do not edit

# ── Server ──────────────────────────────────────────────
listen_host = "${APP_HOST}"
listen_port = ${APP_PORT}

# ── LLM Provider (TOP-LEVEL — this is what MPT reads) ──
llm_provider = "${LLM}"

# ── API Keys ────────────────────────────────────────────
gemini_api_key = "${GEMINI_API_KEY:-}"
gemini_model_name = "gemini-1.5-flash"

openai_api_key = "${OPENAI_API_KEY:-}"
openai_model_name = "gpt-4o-mini"
openai_base_url = "https://api.openai.com/v1"

deepseek_api_key = "${DEEPSEEK_API_KEY:-}"
deepseek_base_url = "https://api.deepseek.com/v1"
deepseek_model_name = "deepseek-chat"

pollinations_api_key = ""
pollinations_base_url = "https://pollinations.ai/api/v1"
pollinations_model_name = "openai-fast"

# ── Video ────────────────────────────────────────────────
pexels_api_keys = ["${PEXELS_API_KEYS}"]

# ── App ──────────────────────────────────────────────────
[app]
host = "${APP_HOST}"
port = ${APP_PORT}
log_level = "${LOG_LEVEL:-INFO}"

# ── Storage ──────────────────────────────────────────────
[storage]
tasks_dir = "./storage/tasks"
TOML

echo "[Config] Generated config.toml with listen_port=${APP_PORT} llm_provider=${LLM}"
