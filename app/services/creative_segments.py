"""Still image to video segment preparation for the creative pipeline.

Turns resolved shot assets into video-compatible segments without touching
provider generation:

- video assets are returned as absolute paths, unchanged;
- image assets are rendered to mp4 next to the source, with a selectable
  motion style;
- an already rendered segment is reused instead of re-rendering.

Motion styles:

- ``"smooth"`` (default for the creative pipeline): the image is pre-scaled
  with 2x headroom once, and each frame is a center crop that is down-scaled
  to the output size. Because every frame is a down-scale (never an
  up-scale), the per-frame resampling stays stable and high-frequency detail
  does not flicker. Output file: ``<image>.smooth.mp4``.
- ``"standard"``: delegates to the shared slow-zoom renderer
  (``video.render_image_zoom_video``), keeping exact vanilla
  MoneyPrinterTurbo behavior. Output file: ``<image>.mp4``.

An empty string is returned when the asset is missing or rendering fails,
so the caller (rough cut stage) applies its own per-shot failure policy.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image
from loguru import logger
from moviepy import VideoClip

from app.models.const import FILE_TYPE_IMAGES
from app.services import video
from app.utils import utils

MOTION_STANDARD = "standard"
MOTION_SMOOTH = "smooth"
MOTION_STYLES = (MOTION_STANDARD, MOTION_SMOOTH)
DEFAULT_MOTION = MOTION_SMOOTH

_ZOOM_PER_SECOND = 0.03
_SMOOTH_HEADROOM = 2
_SEGMENT_FPS = 30


def _smooth_frame_function(image_path: str, clip_duration: int):
    """Build a per-frame function implementing the 2x-headroom zoom.

    The source image is up-scaled once to ``headroom * max_zoom`` size with
    Lanczos. Each frame takes a shrinking center window of that pre-scaled
    image and down-scales it to the original output size, so the zoom keeps
    the same 3%/s feel as the standard renderer while only ever
    down-sampling per frame.
    """
    src = Image.open(image_path).convert("RGB")
    out_w, out_h = src.size
    max_zoom = 1 + clip_duration * _ZOOM_PER_SECOND
    base_w = int(out_w * max_zoom * _SMOOTH_HEADROOM)
    base_h = int(out_h * max_zoom * _SMOOTH_HEADROOM)
    base = src.resize((base_w, base_h), Image.Resampling.LANCZOS)

    def make_frame(t):
        factor = 1 + (max_zoom - 1) * (t / clip_duration)
        win_w = int(base_w / factor)
        win_h = int(base_h / factor)
        left = (base_w - win_w) // 2
        top = (base_h - win_h) // 2
        crop = base.crop((left, top, left + win_w, top + win_h))
        frame = crop.resize((out_w, out_h), Image.Resampling.LANCZOS)
        return np.array(frame)

    return make_frame


def render_smooth_zoom_video(image_path: str, clip_duration: int) -> str:
    """Render a single image to mp4 with the smooth 2x-headroom zoom.

    Writes ``<image>.smooth.mp4`` next to the source. The render goes to a
    temporary file in the same directory and is only moved into place on
    success, so a failed render never leaves a truncated segment behind that
    could be reused later.
    """
    video_path = f"{image_path}.smooth.mp4"
    # The temp name must keep a .mp4 extension so moviepy can resolve the
    # output codec from the filename.
    tmp_path = f"{video_path}.tmp.mp4"
    clip = VideoClip(_smooth_frame_function(image_path, clip_duration), duration=clip_duration)
    try:
        try:
            clip.write_videofile(tmp_path, fps=_SEGMENT_FPS, logger=None)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    finally:
        video.close_clip(clip)
    os.replace(tmp_path, video_path)
    return video_path


def prepare_shot_segment(
    asset_path: str, clip_duration: int, motion: str = DEFAULT_MOTION
) -> str:
    """Return a video-compatible segment path for a resolved shot asset.

    Video files are used as-is; images are rendered to mp4 with the requested
    motion style so the existing assembly pipeline can consume them without
    changes. An empty string means the asset could not be prepared.
    """
    if motion not in MOTION_STYLES:
        raise ValueError(
            f"unknown segment motion style: {motion!r} (expected one of {MOTION_STYLES})"
        )

    if not asset_path or not os.path.isfile(asset_path):
        logger.warning(f"segment preparation failed, missing asset: {asset_path}")
        return ""

    asset_path = os.path.abspath(asset_path)
    ext = utils.parse_extension(asset_path)
    if ext not in FILE_TYPE_IMAGES:
        return asset_path

    if motion == MOTION_STANDARD:
        video_path = f"{asset_path}.mp4"
    else:
        video_path = f"{asset_path}.smooth.mp4"
    if os.path.isfile(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"reusing existing shot segment: {video_path}")
        return video_path

    try:
        if motion == MOTION_STANDARD:
            rendered = video.render_image_zoom_video(asset_path, clip_duration)
        else:
            rendered = render_smooth_zoom_video(asset_path, clip_duration)
    except Exception as exc:
        logger.error(
            f"failed to render shot image as video segment: "
            f"image={asset_path}, motion={motion}, error={type(exc).__name__}, detail={exc}"
        )
        return ""

    if not rendered or not os.path.isfile(rendered):
        logger.error(f"image rendering produced no segment: {asset_path}")
        return ""

    logger.success(f"shot image rendered as video segment: {rendered}")
    return rendered
