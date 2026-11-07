"""Opt-in FFmpeg-compatible export profiles; legacy remains byte-for-byte settings default."""

from __future__ import annotations

from copy import deepcopy

from app.config import config


_DEFAULT_PROFILES = {
    "legacy": {
        "fps": 30, "video_bitrate": None, "audio_bitrate": "192k",
        "cpu_preset": "medium", "faststart": False,
    },
    "shorts": {
        "fps": 30, "video_bitrate": "8M", "audio_bitrate": "192k",
        "cpu_preset": "medium", "faststart": True,
    },
    "high_quality": {
        "fps": 30, "video_bitrate": "14M", "audio_bitrate": "256k",
        "cpu_preset": "slow", "faststart": True,
    },
    "fast": {
        "fps": 30, "video_bitrate": "5M", "audio_bitrate": "160k",
        "cpu_preset": "ultrafast", "faststart": True,
    },
}
_ALLOWED_OVERRIDES = {"fps", "video_bitrate", "audio_bitrate", "cpu_preset", "faststart"}


def available_profiles() -> tuple[str, ...]:
    return tuple(_DEFAULT_PROFILES)


def resolve_profile(name: str | None, *, codec: str) -> dict:
    key = name if name in _DEFAULT_PROFILES else "legacy"
    result = deepcopy(_DEFAULT_PROFILES[key])
    configured = config.app.get("video_export_profiles", {})
    overrides = configured.get(key, {}) if isinstance(configured, dict) else {}
    if isinstance(overrides, dict):
        result.update({k: v for k, v in overrides.items() if k in _ALLOWED_OVERRIDES})
    try:
        result["fps"] = min(60, max(1, int(result["fps"])))
    except (TypeError, ValueError, OverflowError):
        result["fps"] = 30
    # Preset names are encoder-specific. Only libx264 has the same documented
    # preset vocabulary across supported FFmpeg builds; hardware encoders keep
    # their driver/FFmpeg defaults and are still bounded by explicit bitrate.
    result["encoder_preset"] = result["cpu_preset"] if codec == "libx264" else None
    return result
