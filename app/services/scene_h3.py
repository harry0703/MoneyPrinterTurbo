"""H3 provider adapter skeleton.

This module provides a VideoGenerator interface as specified in the ТЗ-2
and a minimal skeleton implementation. Do NOT enable H3 by default.
"""
from __future__ import annotations

from typing import Any


class VideoGenerator:
    """Adapter interface for H3-like providers."""

    @staticmethod
    def generate(scene: dict, prompt: str, settings: dict) -> dict:
        """Generate a video for given scene.

        Returns a dict with at least {'success': bool, 'path': str | None, 'error': str | None}
        Implementations should raise on misconfiguration.
        """
        raise NotImplementedError("H3 provider is not implemented yet")
