import re
from typing import Any

PRESET_SCHEMA = "moneyprinterturbo.preset"
PRESET_VERSION = 1

_SESSION_KEYS = (
    "video_subject",
    "video_script",
    "video_terms",
    "video_script_prompt",
    "use_custom_system_prompt",
    "custom_system_prompt",
    "paragraph_number_input",
)

_UI_KEYS = (
    "language",
    "tts_server",
    "voice_name",
    "font_name",
    "subtitle_position",
    "custom_position",
    "text_fore_color",
    "font_size",
    "subtitle_background_enabled",
    "subtitle_background_color",
    "rounded_subtitle_background",
    "video_language",
    "video_aspect",
    "video_clip_duration",
    "video_count",
    "voice_volume",
    "voice_rate",
    "bgm_type",
    "bgm_volume",
    "subtitle_enabled",
)

_APP_KEYS = (
    "llm_provider",
    "video_source",
    "video_codec",
    "subtitle_provider",
)

_AZURE_KEYS = (
    "speech_region",
)

_SENSITIVE_TOKENS = (
    "api_key",
    "secret_key",
    "speech_key",
    "token",
    "password",
)

_PROVIDER_SETTINGS_SUFFIXES = (
    "_model_name",
    "_base_url",
    "_account_id",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(token in normalized for token in _SENSITIVE_TOKENS)


def _copy_allowed_values(source: dict[str, Any], allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key in allowed_keys:
        if key in source and not _is_sensitive_key(key):
            copied[key] = source[key]

    for key, value in source.items():
        if key in copied:
            continue
        if _is_sensitive_key(key):
            continue
        if any(key.endswith(suffix) for suffix in _PROVIDER_SETTINGS_SUFFIXES):
            copied[key] = value

    return copied


def sanitize_preset_name(name: str, default: str = "moneyprinterturbo-preset") -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-._")
    return normalized or default


def build_preset(
    *,
    app_config: dict[str, Any],
    ui_config: dict[str, Any],
    azure_config: dict[str, Any],
    siliconflow_config: dict[str, Any],
    session_state: dict[str, Any],
    name: str = "",
) -> dict[str, Any]:
    session_data = {
        key: session_state[key]
        for key in _SESSION_KEYS
        if key in session_state and not _is_sensitive_key(key)
    }

    return {
        "schema": PRESET_SCHEMA,
        "version": PRESET_VERSION,
        "name": sanitize_preset_name(name),
        "app": _copy_allowed_values(app_config, _APP_KEYS),
        "ui": _copy_allowed_values(ui_config, _UI_KEYS),
        "azure": _copy_allowed_values(azure_config, _AZURE_KEYS),
        "siliconflow": _copy_allowed_values(siliconflow_config, tuple()),
        "session": session_data,
    }


def apply_preset(
    *,
    preset: dict[str, Any],
    app_config: dict[str, Any],
    ui_config: dict[str, Any],
    azure_config: dict[str, Any],
    siliconflow_config: dict[str, Any],
    session_state: dict[str, Any],
) -> None:
    app_data = preset.get("app", {})
    if isinstance(app_data, dict):
        for key, value in _copy_allowed_values(app_data, _APP_KEYS).items():
            app_config[key] = value

    ui_data = preset.get("ui", {})
    if isinstance(ui_data, dict):
        for key, value in _copy_allowed_values(ui_data, _UI_KEYS).items():
            ui_config[key] = value

    azure_data = preset.get("azure", {})
    if isinstance(azure_data, dict):
        for key, value in _copy_allowed_values(azure_data, _AZURE_KEYS).items():
            azure_config[key] = value

    siliconflow_data = preset.get("siliconflow", {})
    if isinstance(siliconflow_data, dict):
        for key, value in _copy_allowed_values(siliconflow_data, tuple()).items():
            siliconflow_config[key] = value

    session_data = preset.get("session", {})
    if isinstance(session_data, dict):
        for key in _SESSION_KEYS:
            if key in session_data and not _is_sensitive_key(key):
                session_state[key] = session_data[key]
