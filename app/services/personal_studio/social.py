"""Preparación de publicaciones por plataforma, sin publicar nada.

Las plataformas exigen identificar el contenido sintético realista cuando una
persona real parece decir algo que no dijo. El módulo incluye la divulgación en
los metadatos y la exportación queda bloqueada hasta que el usuario aprueba el
contenido. Nunca se envía nada a una red social desde aquí.
"""

from __future__ import annotations

import re

from app.services.personal_studio.presets import (
    AI_DISCLOSURE,
    DEFAULT_HASHTAGS,
    PLATFORMS,
)

_HASHTAG = re.compile(r"^[#\wÁÉÍÓÚÜÑáéíóúüñ]+$", re.UNICODE)


def platform_spec(platform: str) -> dict:
    try:
        return PLATFORMS[platform]
    except KeyError as exc:
        raise ValueError(f"Plataforma no soportada: {platform}") from exc


def normalize_hashtags(values, limit: int) -> list[str]:
    result: list[str] = []
    for value in values or ():
        text = str(value).strip().replace(" ", "")
        if not text:
            continue
        if not text.startswith("#"):
            text = "#" + text
        if not _HASHTAG.fullmatch(text):
            continue
        if text.lower() not in {item.lower() for item in result}:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _clean_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def build_metadata(
    *,
    project: dict,
    platform: str,
    duration: float,
    approved_by: str = "",
    synthetic: bool = True,
) -> dict:
    spec = platform_spec(platform)
    title = _clean_text(
        project.get("name") or project.get("topic") or "BYNEX", spec["title_limit"]
    )
    keywords = [str(item).strip() for item in project.get("keywords") or [] if str(item).strip()]
    hashtags = normalize_hashtags(
        [*keywords, *DEFAULT_HASHTAGS], spec["hashtags"]
    )
    summary = _clean_text(project.get("description") or project.get("topic") or "", 180)
    cta = _clean_text(project.get("cta") or "Escríbenos para conocer más.", 120)
    description_parts = []
    if summary:
        description_parts.append(summary)
    description_parts.append(cta)
    if synthetic:
        description_parts.append(AI_DISCLOSURE)
    description = "\n\n".join(description_parts)
    warnings: list[str] = []
    if duration > spec["max_seconds"]:
        warnings.append(
            f"El video dura {duration:.0f} s y {spec['label']} sugiere un máximo de "
            f"{spec['max_seconds']} s."
        )
    if project.get("is_minor"):
        warnings.append(
            "El perfil pertenece a un menor: no se automatiza ninguna publicación."
        )
    return {
        "platform": platform,
        "platform_label": spec["label"],
        "aspect": spec["aspect"],
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "keywords": keywords,
        "ai_disclosure": AI_DISCLOSURE if synthetic else "",
        "synthetic_media": bool(synthetic),
        "duration_seconds": round(float(duration), 2),
        "approved_by": approved_by,
        "warnings": warnings,
        "auto_publish": False,
        "note": "Exportación local. La publicación requiere acción manual del usuario.",
    }


def export_folder_name(project: dict, platform: str) -> str:
    base = re.sub(
        r"[^A-Za-z0-9_-]+", "-", str(project.get("name") or project.get("id") or "bynnex")
    ).strip("-")
    return f"{base[:40] or 'bynnex'}_{platform}"
