"""Material provider package for the creative pipeline."""

from app.services.providers.base import (
    GeneratedVideoProvider,
    MaterialProvider,
    ProviderError,
    ProviderRegistry,
    VideoProviderRegistry,
    build_registry,
    build_video_registry,
)
from app.services.providers.comfyui import ComfyUIProvider
from app.services.providers.drawthings import DrawThingsProvider
from app.services.providers.kling import KlingVideoProvider

__all__ = [
    "ComfyUIProvider",
    "DrawThingsProvider",
    "GeneratedVideoProvider",
    "KlingVideoProvider",
    "MaterialProvider",
    "ProviderError",
    "ProviderRegistry",
    "VideoProviderRegistry",
    "build_registry",
    "build_video_registry",
]
