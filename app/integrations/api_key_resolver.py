from __future__ import annotations

import os

from app.config import config


def resolve_api_key(config_key: str, env_key: str | None = None, default: str = "") -> str:
    config_value = str(config.app.get(config_key, "") or "").strip()
    if config_value:
        return config_value

    resolved_env_key = str(env_key or "").strip()
    if resolved_env_key:
        env_value = str(os.getenv(resolved_env_key, "") or "").strip()
        if env_value:
            return env_value

    return str(default or "").strip()
