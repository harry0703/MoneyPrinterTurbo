# API conventions

- Never send secrets, tokens, or user PII to unrelated third-party endpoints.
- Prefer existing MCP connectors over raw curl when one fits.
- Validate at system boundaries (user input, external APIs) only — trust internal code.
- Sanitize error messages that might embed credentials (e.g. a custom `base_url` with embedded userinfo or a query-string token) before returning them from a FastAPI endpoint or the WebUI — see `_sanitize_error_message` in `app/services/llm.py` for the existing pattern.
- New LLM/TTS/material providers: add one entry to the relevant registry (e.g. `app/models/llm_provider.py`) rather than hardcoding a new branch in the WebUI; only add an adapter branch in the service layer when the protocol genuinely differs from the existing OpenAI-compatible path.
