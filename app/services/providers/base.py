"""Material provider abstraction for the creative pipeline.

A material provider turns one shot of a shot plan into concrete local asset
files. Providers are registered in a registry keyed by name; the material
router asks the registry for the provider a shot requires.

The vanilla MoneyPrinterTurbo flow never imports this package.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.models.creative import ShotPlanItem


class ProviderError(RuntimeError):
    """A provider could not produce material for a shot."""


class MaterialProvider:
    """Base class for material providers."""

    name: str = "base"

    def is_available(self) -> bool:
        """Cheap probe. Must not start services or have other side effects."""
        raise NotImplementedError

    def generate(self, shot: ShotPlanItem, context: dict[str, Any]) -> list[str]:
        """Produce local asset files for one shot.

        ``context`` is task-level data: ``task_id``, ``output_dir``,
        ``video_aspect``, an optional ``seed`` and provider-specific
        overrides.

        Returns at least one existing local file path.
        """
        raise NotImplementedError


class ProviderRegistry:
    """Registry of material providers keyed by provider name."""

    def __init__(self, providers: Optional[list[MaterialProvider]] = None):
        self._providers: dict[str, MaterialProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: MaterialProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> MaterialProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderError(f"unknown material provider: {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._providers)

    def is_available(self, name: str) -> bool:
        provider = self.get(name)
        try:
            return bool(provider.is_available())
        except Exception as exc:
            logger.warning(f"provider {name!r} availability probe failed: {exc}")
            return False


def build_registry() -> ProviderRegistry:
    """Build the default registry of enabled material providers.

    Concrete providers register themselves here as they are added; with no
    provider enabled the registry is empty.
    """
    return ProviderRegistry()
