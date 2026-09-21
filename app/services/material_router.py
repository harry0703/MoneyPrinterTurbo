"""Hybrid material router for the creative pipeline.

Resolves every shot of a director's shot plan into a concrete local asset:

- ``stock`` shots are downloaded through the existing stock search pipeline
  (Pexels / Pixabay / Coverr);
- ``local``, ``graphic`` and ``archive`` shots are validated on disk (the path
  may be absolute or relative to ``context['media_root']``);
- ``generated_image`` shots are produced by a registered material provider;
- ``generated_video`` shots fail until a video provider exists.

Each resolved shot gets ``asset_path``, ``provider`` (the source actually
used) and ``status``; ``error`` is only set when the shot finally fails.
Fallback policies turn a failed shot into stock material, a solid placeholder
image, or one retry of the original source.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from loguru import logger

from app.models.creative import (
    SHOT_SOURCE_ARCHIVE,
    SHOT_SOURCE_GENERATED_IMAGE,
    SHOT_SOURCE_GENERATED_VIDEO,
    SHOT_SOURCE_GRAPHIC,
    SHOT_SOURCE_LOCAL,
    SHOT_SOURCE_STOCK,
    SHOT_STATUS_FAILED,
    SHOT_STATUS_RESOLVED,
    ShotPlan,
    ShotPlanItem,
)
from app.services.providers.base import (
    ProviderError,
    ProviderRegistry,
    build_registry,
)

FALLBACK_NONE = "none"
FALLBACK_STOCK = "stock"
FALLBACK_LOCAL_PLACEHOLDER = "local_placeholder"
FALLBACK_RETRY = "retry"
FALLBACKS = (FALLBACK_NONE, FALLBACK_STOCK, FALLBACK_LOCAL_PLACEHOLDER, FALLBACK_RETRY)

_ASPECT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (832, 832),
}

StockSource = Callable[[ShotPlanItem, dict], str]


def _shot_dir(shot: ShotPlanItem, context: dict) -> str:
    media_root = (context or {}).get("media_root") or ""
    if not media_root:
        raise ProviderError("router context is missing 'media_root'")
    return os.path.join(media_root, f"shot_{shot.index:03d}")


def _to_aspect(value: Any) -> str:
    return str(value or "16:9").strip().lower() or "16:9"


def _default_stock_source() -> StockSource:
    from app.models.schema import VideoAspect
    from app.services import material

    def _resolve_stock(shot: ShotPlanItem, context: dict) -> str:
        provider = (context or {}).get("stock_provider") or "pexels"
        search_fn = getattr(material, f"search_videos_{provider}", None)
        if search_fn is None:
            raise ProviderError(f"unknown stock provider: {provider!r}")
        minimum_duration = int(shot.duration) if shot.duration else 3
        try:
            video_aspect = VideoAspect(_to_aspect((context or {}).get("video_aspect")))
        except ValueError:
            video_aspect = VideoAspect.landscape
        items = material._search_videos_with_cache(
            provider,
            search_fn,
            (shot.query or "").strip(),
            minimum_duration,
            video_aspect,
        )
        if not items:
            raise ProviderError(
                f"stock search returned no results for query {shot.query!r}"
            )
        return material.save_video(items[0].url, save_dir=_shot_dir(shot, context))

    return _resolve_stock


def _resolve_local_path(shot: ShotPlanItem, context: dict) -> str:
    raw_path = (shot.query or shot.asset_path or "").strip()
    if not raw_path:
        raise ProviderError(f"{shot.source_type} shot is missing a file path")
    if os.path.isabs(raw_path):
        candidate = raw_path
    else:
        media_root = (context or {}).get("media_root") or ""
        if not media_root:
            raise ProviderError(
                "router context is missing 'media_root' for relative paths"
            )
        candidate = os.path.join(media_root, raw_path)
    if not os.path.isfile(candidate):
        raise ProviderError(f"{shot.source_type} file not found: {candidate}")
    return candidate


def _make_placeholder(shot: ShotPlanItem, context: dict) -> str:
    from PIL import Image

    shot_dir = _shot_dir(shot, context)
    os.makedirs(shot_dir, exist_ok=True)
    aspect = _to_aspect((context or {}).get("video_aspect"))
    width, height = _ASPECT_SIZES.get(aspect, _ASPECT_SIZES["16:9"])
    path = os.path.join(shot_dir, "placeholder.png")
    Image.new("RGB", (width, height), (23, 25, 30)).save(path)
    return path


class MaterialRouter:
    """Resolve a shot plan into local assets."""

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        stock_source: Optional[StockSource] = None,
        fallback: str = FALLBACK_NONE,
    ):
        if fallback not in FALLBACKS:
            raise ValueError(f"fallback must be one of {', '.join(FALLBACKS)}")
        self.registry = registry if registry is not None else build_registry()
        self.stock_source = (
            stock_source if stock_source is not None else _default_stock_source()
        )
        self.fallback = fallback

    def resolve_shot_plan(
        self, plan: ShotPlan, context: dict[str, Any]
    ) -> ShotPlan:
        """Resolve every shot; the input plan is not mutated."""
        resolved = plan.model_copy(deep=True)
        for shot in resolved.shots:
            self._resolve_shot(shot, context)
        return resolved

    def _resolve_shot(self, shot: ShotPlanItem, context: dict) -> None:
        path, provider_name, error = self._attempt(shot, context)

        if path is None and self.fallback == FALLBACK_RETRY:
            logger.warning(
                f"[router] shot {shot.index:02d} failed ({error}), retrying once"
            )
            path, provider_name, error = self._attempt(shot, context)

        if (
            path is None
            and self.fallback == FALLBACK_STOCK
            and shot.source_type != SHOT_SOURCE_STOCK
        ):
            logger.warning(
                f"[router] shot {shot.index:02d} failed ({error}), "
                "falling back to stock"
            )
            path, provider_name, error = self._attempt_stock(shot, context, error)

        if path is None and self.fallback == FALLBACK_LOCAL_PLACEHOLDER:
            logger.warning(
                f"[router] shot {shot.index:02d} failed ({error}), "
                "using local placeholder"
            )
            path, provider_name, error = self._attempt_placeholder(shot, context)

        if path is None:
            shot.status = SHOT_STATUS_FAILED
            shot.error = error
            logger.error(f"[router] shot {shot.index:02d} failed: {error}")
        else:
            self._mark_resolved(shot, path, provider_name)

    def _attempt(
        self, shot: ShotPlanItem, context: dict
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        try:
            if shot.source_type == SHOT_SOURCE_STOCK:
                return self.stock_source(shot, context), SHOT_SOURCE_STOCK, None
            if shot.source_type in (
                SHOT_SOURCE_LOCAL,
                SHOT_SOURCE_GRAPHIC,
                SHOT_SOURCE_ARCHIVE,
            ):
                return (
                    _resolve_local_path(shot, context),
                    shot.source_type,
                    None,
                )
            if shot.source_type == SHOT_SOURCE_GENERATED_IMAGE:
                return self._resolve_generated(shot, context)
            raise ProviderError(
                f"no material provider for source type {shot.source_type!r} yet"
            )
        except (ProviderError, OSError) as exc:
            return None, None, str(exc)

    def _attempt_stock(
        self, shot: ShotPlanItem, context: dict, previous_error: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        try:
            return self.stock_source(shot, context), SHOT_SOURCE_STOCK, None
        except (ProviderError, OSError) as exc:
            return None, None, f"stock fallback failed: {exc} (after: {previous_error})"

    def _attempt_placeholder(
        self, shot: ShotPlanItem, context: dict
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        try:
            return _make_placeholder(shot, context), "placeholder", None
        except (ProviderError, OSError) as exc:
            return None, None, f"placeholder fallback failed: {exc}"

    def _resolve_generated(
        self, shot: ShotPlanItem, context: dict
    ) -> tuple[str, str, None]:
        provider_name = (shot.provider or "").strip()
        if not provider_name:
            from app.config import config

            provider_name = str(
                config.creative.get("default_image_provider", "comfyui")
            )
        provider = self.registry.get(provider_name)
        if not provider.is_available():
            raise ProviderError(f"image provider {provider_name!r} is not available")
        provider_context = dict(context or {})
        provider_context["output_dir"] = _shot_dir(shot, context)
        paths = provider.generate(shot, provider_context)
        if not paths:
            raise ProviderError(f"image provider {provider_name!r} returned no files")
        return paths[0], provider_name, None

    @staticmethod
    def _mark_resolved(shot: ShotPlanItem, path: str, provider_name: str) -> None:
        shot.asset_path = path
        shot.provider = provider_name
        shot.status = SHOT_STATUS_RESOLVED
        shot.error = None
        logger.info(f"[router] shot {shot.index:02d} -> {provider_name} ({path})")
