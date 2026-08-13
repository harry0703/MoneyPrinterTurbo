"""H3 provider adapter skeleton.

This module provides a VideoGenerator interface as specified in the ТЗ-2
and a minimal skeleton implementation. Do NOT enable H3 by default.
"""
from __future__ import annotations

from typing import Any


class VideoGenerator:
    """Adapter interface for H3-like providers.

    Minimal stub that returns a deterministic failure response so higher-level
    code can decide fallback without raising. Replace with a real implementation
    when H3 credentials and API client are available.
    """

    @staticmethod
    def generate(scene: dict, prompt: str, settings: dict) -> dict:
        """Generate a video for given scene.

        Returns a dict with at least {'success': bool, 'path': str | None, 'error': str | None}
        """
        # Stub behavior: indicate H3 is not configured. Callers should check
        # config.app['h3_enabled'] before using H3 in production.
        return {"success": False, "path": None, "error": "h3-not-configured"}
