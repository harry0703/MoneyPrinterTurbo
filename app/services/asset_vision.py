"""
Vision annotation for photo library assets — caption, weighted tags, readable
text flag and a recommended minimum on-screen duration for one image file.

Pure adapter: it knows nothing about the database or the render pipeline, it
takes a file and returns what the model saw. The caller decides what to store.
Disabled by default: without `photo_library_enabled` and a `gemini_api_key`
every call is a no-op returning None.

Config (config.toml, [app] section):
    photo_library_enabled = true
    photo_library_vision_model = "gemini-2.5-flash"
    gemini_api_key = "..."
"""

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from loguru import logger
from pydantic import BaseModel, ValidationError

from app.config import config

DEFAULT_VISION_MODEL = "gemini-2.5-flash"
MIN_DISPLAY_FLOOR = 1.0
MIN_DISPLAY_CEIL = 8.0

PROMPT = (
    "Ты размечаешь кадр для библиотеки фото-ассетов коротких вертикальных роликов.\n"
    "Опиши именно то, что видно в кадре, без домыслов и без оценок качества.\n"
    "- caption: одно-два предложения на русском о содержимом кадра;\n"
    "- tags: 3-8 тегов на русском с весом 0..1 (вес — насколько тег важен "
    "для этого кадра);\n"
    "- has_text: true, если в кадре есть читаемый текст — надписи, титры, "
    "заголовки, скриншот переписки, цифры на графике;\n"
    "- min_display: сколько секунд кадр должен минимум висеть на экране, "
    "чтобы зритель успел его считать. Кадр с читаемым текстом требует заметно "
    "больше времени, чем кадр без текста."
)


class _Tag(BaseModel):
    name: str
    weight: float


class _Annotation(BaseModel):
    caption: str
    tags: list[_Tag]
    has_text: bool
    min_display: float


@dataclass
class AssetAnnotation:
    caption: str
    tags: dict[str, float]
    has_text: bool
    min_display: float
    model: str


def is_enabled() -> bool:
    """True only when the photo library is on and a Gemini key is configured."""
    return bool(config.app.get("photo_library_enabled")) and bool(
        config.app.get("gemini_api_key")
    )


def _client():
    from google import genai

    return genai.Client(api_key=config.app.get("gemini_api_key"))


def _to_annotation(parsed: _Annotation, model: str) -> AssetAnnotation:
    tags: dict[str, float] = {}
    for tag in parsed.tags:
        name = tag.name.strip()
        if name:
            tags[name] = min(max(tag.weight, 0.0), 1.0)
    return AssetAnnotation(
        caption=parsed.caption.strip(),
        tags=tags,
        has_text=parsed.has_text,
        min_display=min(max(parsed.min_display, MIN_DISPLAY_FLOOR), MIN_DISPLAY_CEIL),
        model=model,
    )


def annotate_image(
    image_path: Union[str, Path],
    model: Optional[str] = None,
) -> Optional[AssetAnnotation]:
    """
    Describe one image file with the vision model.

    Returns None when the feature is disabled, the file is unreadable or the
    provider fails — a failure on one asset must not stop a batch, so nothing
    is raised.
    """
    if not is_enabled():
        return None
    model = model or config.app.get("photo_library_vision_model", DEFAULT_VISION_MODEL)
    path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        logger.warning(f"asset_vision: not an image file, skipping: {path}")
        return None

    try:
        from google.genai import types

        data = path.read_bytes()
        with _client() as client:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_Annotation,
                ),
            )
        parsed = _Annotation.model_validate(json.loads(response.text))
    except (ValidationError, ValueError, TypeError) as e:
        logger.warning(f"asset_vision: unparsable model response for {path}: {e}")
        return None
    except Exception as e:  # noqa: BLE001 - one bad asset must not stop the batch
        logger.warning(f"asset_vision: annotation failed for {path}: {e}")
        return None

    annotation = _to_annotation(parsed, model)
    if not annotation.caption:
        logger.warning(f"asset_vision: empty caption for {path}")
        return None
    return annotation
