"""Still image to video segment preparation for the creative pipeline.

Turns resolved shot assets into video-compatible segments without touching
provider generation:

- video assets are returned as absolute paths, unchanged;
- image assets are rendered through the existing slow-zoom renderer
  (``video.render_image_zoom_video``), producing ``<image>.mp4`` next to
  the source;
- an already rendered segment is reused instead of re-rendering.

An empty string is returned when the asset is missing or rendering fails,
so the caller (rough cut stage) applies its own per-shot failure policy.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import os

from loguru import logger

from app.models.const import FILE_TYPE_IMAGES
from app.services import video
from app.utils import utils


def prepare_shot_segment(asset_path: str, clip_duration: int) -> str:
    """Return a video-compatible segment path for a resolved shot asset.

    Video files are used as-is; images are rendered to mp4 with the shared
    slow-zoom renderer so the existing assembly pipeline can consume them
    without changes. An empty string means the asset could not be prepared.
    """
    if not asset_path or not os.path.isfile(asset_path):
        logger.warning(f"segment preparation failed, missing asset: {asset_path}")
        return ""

    asset_path = os.path.abspath(asset_path)
    ext = utils.parse_extension(asset_path)
    if ext not in FILE_TYPE_IMAGES:
        return asset_path

    video_path = f"{asset_path}.mp4"
    if os.path.isfile(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"reusing existing shot segment: {video_path}")
        return video_path

    try:
        rendered = video.render_image_zoom_video(asset_path, clip_duration)
    except Exception as exc:
        logger.error(
            f"failed to render shot image as video segment: "
            f"image={asset_path}, error={type(exc).__name__}, detail={exc}"
        )
        return ""

    if not rendered or not os.path.isfile(rendered):
        logger.error(f"image rendering produced no segment: {asset_path}")
        return ""

    logger.success(f"shot image rendered as video segment: {rendered}")
    return rendered
