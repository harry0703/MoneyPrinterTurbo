"""Rough-cut assembly and review timeline for the creative pipeline.

Sits between material resolution and final assembly:

- resolves the director's shot plan through the hybrid material router;
- turns every resolved shot into a video-compatible segment via
  ``creative_segments``;
- concatenates the segments into a reviewable rough cut and persists the
  timeline metadata (``rough_cut.json``) in the task directory.

Every shot keeps its asset and duration and the timeline keeps the motion
style, so editing the metadata is always sufficient to rebuild the rough
cut: ``rebuild_rough_cut`` re-renders only the missing or stale segments.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from moviepy import VideoFileClip, concatenate_videoclips

from app.config import config
from app.models import creative
from app.models.schema import VideoAspect
from app.services import creative_segments
from app.services import material_router
from app.services import state as sm
from app.services import task_artifacts
from app.services import video
from app.utils import utils

ROUGH_CUT_FILE = "rough_cut.json"
ROUGH_CUT_VIDEO_FILE = "rough_cut.mp4"
ROUGH_CUT_VERSION = 1
ROUGH_CUT_FPS = 30


class RoughCutError(RuntimeError):
    """Rough-cut failure carrying the HTTP status the API layer should map."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def default_motion() -> str:
    """Segment motion style for new rough cuts (creative.motion)."""
    motion = str(config.creative.get("motion", "") or "").strip()
    if motion in creative_segments.MOTION_STYLES:
        return motion
    return creative_segments.DEFAULT_MOTION


def default_fallback() -> str:
    """Material router fallback (creative.material_fallback)."""
    fallback = str(config.creative.get("material_fallback", "") or "").strip()
    if fallback in material_router.FALLBACKS:
        return fallback
    return material_router.FALLBACK_STOCK


def timeline_path(task_id: str) -> str:
    return os.path.join(utils.task_dir(task_id), ROUGH_CUT_FILE)


def video_path(task_id: str) -> str:
    return os.path.join(utils.task_dir(task_id), ROUGH_CUT_VIDEO_FILE)


def _param_value(params: Any, key: str, default: Any = None) -> Any:
    if isinstance(params, dict):
        return params.get(key, default)
    return getattr(params, key, default)


def _shot_context(task_id: str, params: Any) -> dict:
    media_root = os.path.join(utils.task_dir(task_id), "assets")
    os.makedirs(media_root, exist_ok=True)
    stock_provider = str(
        _param_value(params, "video_source", "") or ""
    ).strip().lower()
    if stock_provider not in {"pexels", "pixabay", "coverr"}:
        stock_provider = "pexels"
    return {
        "task_id": task_id,
        "media_root": media_root,
        "video_aspect": str(_param_value(params, "video_aspect", "") or "16:9"),
        "stock_provider": stock_provider,
    }


def resolve_shot_materials(task_id: str, params: Any, plan: Any) -> Optional[list]:
    """Resolve the director shot plan into one local asset per shot."""
    if plan is None or not getattr(plan, "shots", None):
        logger.error(f"[rough_cut] no shots to resolve: task_id={task_id}")
        return None
    router = material_router.MaterialRouter(fallback=default_fallback())
    resolved = router.resolve_shot_plan(plan, _shot_context(task_id, params))
    default_duration = float(_param_value(params, "video_clip_duration", 5) or 5)
    shots = []
    for shot in resolved.shots:
        if (
            shot.status != creative.SHOT_STATUS_RESOLVED
            or not shot.asset_path
            or not os.path.isfile(shot.asset_path)
        ):
            logger.error(
                f"[rough_cut] shot {shot.index:02d} unresolved: "
                f"{shot.error or shot.status}"
            )
            return None
        shots.append(
            {
                "index": shot.index,
                "source": shot.source_type,
                "asset_path": shot.asset_path,
                "provider": shot.provider or "",
                "prompt": shot.prompt or "",
                "query": shot.query or "",
                "duration": float(shot.duration or default_duration),
            }
        )
    task_artifacts.write_shot_plan_data(task_id, resolved.model_dump(mode="json"))
    logger.success(f"[rough_cut] resolved {len(shots)} shots: task_id={task_id}")
    return shots


def prepare_segments(task_id: str, shots: list, motion: Optional[str] = None) -> list:
    """Render every shot asset into a video segment (cached per asset)."""
    motion = motion or default_motion()
    prepared = []
    for shot in shots:
        segment = creative_segments.prepare_shot_segment(
            shot["asset_path"], int(round(float(shot["duration"]))), motion
        )
        if not segment:
            raise RoughCutError(
                f"failed to prepare segment for shot {shot['index']} "
                f"(asset={shot['asset_path']}, motion={motion})"
            )
        prepared.append({**shot, "segment_path": segment})
    return prepared


def _aspect_resolution(params: Any) -> tuple:
    aspect_value = str(_param_value(params, "video_aspect", "") or "16:9").strip()
    try:
        aspect = VideoAspect(aspect_value)
    except ValueError:
        aspect = VideoAspect.landscape
    return aspect.to_resolution()


def _concatenate_segments(
    task_id: str, segment_paths: list, width: int, height: int
) -> str:
    target = video_path(task_id)
    tmp_path = f"{target}.tmp.mp4"
    clips = []
    cut = None
    try:
        for segment in segment_paths:
            clips.append(VideoFileClip(segment))
        resized = [clip.resized(new_size=(width, height)) for clip in clips]
        cut = concatenate_videoclips(resized, method="chain")
        cut.write_videofile(tmp_path, fps=ROUGH_CUT_FPS, audio=False, logger=None)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    finally:
        for clip in clips:
            video.close_clip(clip)
        if cut is not None:
            video.close_clip(cut)
    return target


def _normalize_shots(shots: list) -> float:
    """Renumber shots and compute in/out points; returns the total duration."""
    cursor = 0.0
    for index, shot in enumerate(shots, start=1):
        shot["index"] = index
        shot["in"] = round(cursor, 3)
        shot["out"] = round(cursor + float(shot["duration"]), 3)
        cursor += float(shot["duration"])
    return round(cursor, 3)


def _make_timeline(task_id: str, shots: list, motion: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "version": ROUGH_CUT_VERSION,
        "task_id": task_id,
        "motion": motion,
        "created_at": now,
        "updated_at": now,
        "total_duration": _normalize_shots(shots),
        "shots": shots,
    }


def build_rough_cut(
    task_id: str,
    shots: list,
    params: Any = None,
    motion: Optional[str] = None,
) -> dict:
    """Prepare every shot, concat the rough cut and persist the timeline."""
    motion = motion or default_motion()
    prepared = prepare_segments(task_id, shots, motion)
    timeline = _make_timeline(task_id, prepared, motion)
    width, height = _aspect_resolution(params)
    _concatenate_segments(
        task_id, [shot["segment_path"] for shot in prepared], width, height
    )
    task_artifacts.write_task_json(task_id, ROUGH_CUT_FILE, timeline)
    logger.success(
        f"[rough_cut] built rough cut: task_id={task_id}, "
        f"{len(prepared)} shots, {timeline['total_duration']}s"
    )
    return timeline


def load_rough_cut(task_id: str) -> Optional[dict]:
    path = timeline_path(task_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            timeline = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[rough_cut] cannot read timeline {path}: {exc}")
        return None
    if not isinstance(timeline, dict) or not timeline.get("shots"):
        return None
    return timeline


def rebuild_rough_cut(task_id: str, params: Any = None) -> Optional[dict]:
    """Re-render stale segments, recompute timing, re-concat and save.

    The persisted timeline is the single source of truth: every shot keeps
    its asset and duration, so no other state is needed to rebuild.
    """
    timeline = load_rough_cut(task_id)
    if timeline is None:
        return None
    if params is None:
        task = sm.state.get_task(task_id) or {}
        params = task.get("params") or {}
    motion = timeline.get("motion") or default_motion()
    shots = timeline.get("shots") or []
    prepared = []
    for shot in shots:
        segment = creative_segments.prepare_shot_segment(
            shot["asset_path"], int(round(float(shot["duration"]))), motion
        )
        if not segment:
            raise RoughCutError(
                f"failed to rebuild segment for shot {shot.get('index')} "
                f"(asset={shot.get('asset_path')}, motion={motion})"
            )
        prepared.append({**shot, "segment_path": segment})
    timeline["shots"] = prepared
    timeline["motion"] = motion
    timeline["total_duration"] = _normalize_shots(prepared)
    timeline["updated_at"] = datetime.now(timezone.utc).isoformat()
    width, height = _aspect_resolution(params)
    _concatenate_segments(
        task_id, [shot["segment_path"] for shot in prepared], width, height
    )
    task_artifacts.write_task_json(task_id, ROUGH_CUT_FILE, timeline)
    logger.success(
        f"[rough_cut] rebuilt rough cut: task_id={task_id}, "
        f"{len(prepared)} shots, {timeline['total_duration']}s"
    )
    return timeline
