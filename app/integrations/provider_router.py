from __future__ import annotations

from typing import Any, Callable

from app.integrations.bannerbear import generate_bannerbear_video
from app.integrations.common import ensure_output_dir, error_result
from app.integrations.did import generate_did_talk
from app.integrations.fal import generate_fal_video
from app.integrations.getimg import generate_getimg_video
from app.integrations.heygen import generate_heygen_video
from app.integrations.replicate import generate_replicate_asset
from app.integrations.shotstack import render_shotstack_video
from app.integrations.stability import generate_stability_image

ProviderFn = Callable[[dict[str, Any], str | None], dict[str, Any]]


PROVIDER_MAP: dict[str, ProviderFn] = {
    "getimg": generate_getimg_video,
    "fal": generate_fal_video,
    "shotstack": render_shotstack_video,
    "stability": generate_stability_image,
    "did": generate_did_talk,
    "heygen": generate_heygen_video,
    "bannerbear": generate_bannerbear_video,
    "replicate": generate_replicate_asset,
}

DEFAULT_FALLBACK_ORDER = ["getimg", "fal", "stability", "replicate"]


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("aspectRatio", "9:16")
    normalized.setdefault("duration", 5)
    normalized.setdefault("outputType", "video")
    normalized.setdefault("metadata", {})
    return normalized


def _validate_payload(provider: str, payload: dict[str, Any]) -> str:
    output_type = str(payload.get("outputType") or "video")
    prompt = (payload.get("prompt") or "").strip()

    if provider in {"getimg", "fal", "stability", "replicate"} and not prompt:
        return "prompt is required"
    if provider == "did":
        if not (payload.get("imageUrl") or "").strip():
            return "imageUrl is required for D-ID"
        if not (payload.get("script") or "").strip():
            return "script is required for D-ID"
    if provider == "heygen" and not (payload.get("script") or "").strip():
        return "script is required for HeyGen"
    if provider in {"shotstack", "bannerbear"}:
        template_id = (payload.get("templateId") or "").strip()
        assets = payload.get("assets") or []
        if not template_id and not assets:
            return "templateId is required or provide assets"

    if output_type not in {"image", "video"}:
        return "outputType must be image or video"

    return ""


def generate_with_provider(
    provider: str,
    payload: dict[str, Any],
    output_dir: str | None = None,
) -> dict[str, Any]:
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider not in PROVIDER_MAP:
        return error_result(normalized_provider or "unknown", "unsupported provider")

    normalized_payload = _normalize_payload(payload)
    validation_error = _validate_payload(normalized_provider, normalized_payload)
    if validation_error:
        return error_result(normalized_provider, validation_error)

    directory = ensure_output_dir(output_dir)
    integration_fn = PROVIDER_MAP[normalized_provider]
    return integration_fn(normalized_payload, directory)


def generate_with_fallback(
    payload: dict[str, Any],
    output_dir: str | None = None,
    provider_order: list[str] | None = None,
    preferred_provider: str | None = None,
) -> dict[str, Any]:
    order = list(provider_order or DEFAULT_FALLBACK_ORDER)
    preferred = (preferred_provider or "").strip().lower()
    if preferred and preferred in order:
        order = [preferred] + [provider for provider in order if provider != preferred]

    last_error = "all providers failed"
    for provider in order:
        result = generate_with_provider(provider, payload, output_dir=output_dir)
        if result.get("success"):
            return result
        last_error = result.get("error") or last_error

    return error_result("fallback", last_error)
