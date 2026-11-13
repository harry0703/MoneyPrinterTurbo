"""Configurable subtitle style presets with legacy-compatible defaults."""

from __future__ import annotations

from copy import deepcopy

from app.config import config


_PRESETS = {
    "classic": {},
    "cinematic": {
        "font_size": 54,
        "text_fore_color": "#FFFFFF",
        "stroke_width": 1.5,
        "subtitle_position": "safe_bottom",
        "background": None,
        "rounded_background": False,
        "animation": "none",
    },
    "modern": {
        "font_size": 64,
        "text_fore_color": "#FFFFFF",
        "highlight_color": "#FFE45E",
        "stroke_width": 2,
        "subtitle_position": "safe_bottom",
        "background": "#111827",
        "rounded_background": True,
        "animation": "pop_spring",
        "display_mode": "word_by_word",
    },
    "documentary": {
        "font_size": 56,
        "text_fore_color": "#FFFFFF",
        "stroke_width": 1.5,
        "subtitle_position": "safe_bottom",
        "background": "#000000",
        "rounded_background": False,
        "animation": "none",
    },
    "viral": {
        "font_size": 76,
        "text_fore_color": "#FFFFFF",
        "highlight_color": "#FFE45E",
        "stroke_width": 3,
        "subtitle_position": "safe_bottom",
        "background": "#111111",
        "rounded_background": True,
        "animation": "pop_spring",
        "display_mode": "word_by_word",
    },
    "minimalist": {
        "font_size": 48,
        "text_fore_color": "#FFFFFF",
        "stroke_width": 0,
        "subtitle_position": "safe_bottom",
        "background": None,
        "rounded_background": False,
        "animation": "none",
    },
}
_PRESET_KEYS = {key for preset in _PRESETS.values() for key in preset} | {
    "font_name", "stroke_color"
}


def available_presets() -> tuple[str, ...]:
    return tuple(_PRESETS)


def display_mode(params) -> str:
    """Use precise word cues for dynamic presets unless explicitly requested otherwise."""
    configured = getattr(params, "subtitle_display_mode", "sentence")
    if "subtitle_display_mode" in getattr(params, "model_fields_set", set()):
        return configured
    return resolve_preset(getattr(params, "subtitle_preset", "classic")).get(
        "display_mode", configured
    )


def highlight_word_cue(params, text: str) -> bool:
    """Only highlight a cue if it is one word with word-level timing."""
    return (
        display_mode(params) == "word_by_word"
        and getattr(params, "subtitle_preset", "classic") in {"modern", "viral"}
        and len((text or "").split()) == 1
    )


def safe_bottom_ratio(aspect: str) -> float:
    """Conservative lower edge for app-interface overlays on short-form video."""
    return 0.80 if str(getattr(aspect, "value", aspect)) == "9:16" else 0.88


def resolve_preset(name: str | None) -> dict:
    """Return built-in defaults merged with the matching `[ui.subtitle_presets]`.

    Unknown configuration keys are ignored. User overrides are plain data from
    config.toml, so this module never imports a rendering or UI dependency.
    """
    preset_name = name if name in _PRESETS else "classic"
    values = deepcopy(_PRESETS[preset_name])
    configured = config.ui.get("subtitle_presets", {})
    override = configured.get(preset_name, {}) if isinstance(configured, dict) else {}
    if isinstance(override, dict):
        for key, value in override.items():
            if key in _PRESET_KEYS:
                values[key] = value
    return values
