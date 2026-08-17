"""
Text embeddings for the photo asset library — one text in, one 768-dim vector
out, plus the id of the model that produced it.

Pure adapter: no database, no pipeline knowledge. The caller stores the vector
next to the model id so a model change can be re-vectorized selectively.
Disabled by default: without `photo_library_enabled` and a `gemini_api_key`
every call is a no-op returning None.

Config (config.toml, [app] section):
    photo_library_enabled = true
    photo_library_embed_model = "gemini-embedding-001"
    gemini_api_key = "..."
"""

import math
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger

from app.config import config

DEFAULT_EMBED_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768


@dataclass
class TextEmbedding:
    vector: List[float]
    model: str


def is_enabled() -> bool:
    """True only when the photo library is on and a Gemini key is configured."""
    return bool(config.app.get("photo_library_enabled")) and bool(
        config.app.get("gemini_api_key")
    )


def _client():
    from google import genai

    return genai.Client(api_key=config.app.get("gemini_api_key"))


def _unit(vector: List[float]) -> Optional[List[float]]:
    # gemini-embedding-001 only returns unit vectors at its native 3072 dims;
    # below that the vectors come back unnormalized (~0.59 norm at 768), so the
    # cosine scale would drift between models unless we normalize here.
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return None
    return [v / norm for v in vector]


def embed_text(text: str, model: Optional[str] = None) -> Optional[TextEmbedding]:
    """
    Embed one text into a unit-length 768-dim vector.

    Returns None when the feature is disabled, the text is empty or the
    provider fails — a failure on one asset must not stop a batch, so nothing
    is raised.
    """
    if not is_enabled() or not text or not text.strip():
        return None
    model = model or config.app.get("photo_library_embed_model", DEFAULT_EMBED_MODEL)

    try:
        from google.genai import types

        with _client() as client:
            response = client.models.embed_content(
                model=model,
                contents=text.strip(),
                config=types.EmbedContentConfig(
                    output_dimensionality=EMBEDDING_DIM,
                ),
            )
        vector = [float(v) for v in response.embeddings[0].values]
    except Exception as e:  # noqa: BLE001 - one bad asset must not stop the batch
        logger.warning(f"asset_embed: embedding failed: {e}")
        return None

    if len(vector) != EMBEDDING_DIM:
        logger.warning(
            f"asset_embed: {model} returned {len(vector)} dims, expected "
            f"{EMBEDDING_DIM}"
        )
        return None
    unit = _unit(vector)
    if unit is None:
        logger.warning(f"asset_embed: {model} returned a zero vector")
        return None
    return TextEmbedding(vector=unit, model=model)
