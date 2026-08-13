"""Scene Engine minimal integration helpers.

Provides:
- generate_scene_plan(task_id, params, video_script) -> dict
- save_scene_plan(task_id, scene_plan) -> None
- route_scene_assets(task_id, params, scene_plan) -> list | None

These are intentionally lightweight stubs for initial integration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from app.utils import utils


def _scene_plan_path(task_id: str) -> Path:
    return Path(utils.task_dir(task_id)) / "scene_plan.json"


def save_scene_plan(task_id: str, scene_plan: Dict[str, Any]) -> None:
    """Atomically save scene_plan.json into task dir."""
    target = _scene_plan_path(task_id)
    tmp = target.parent / ("." + target.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(scene_plan, fp, ensure_ascii=False, indent=4)
            fp.write("\n")
        os.replace(tmp, target)
        logger.info(f"saved scene_plan.json for task {task_id}")
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def generate_scene_plan(task_id: str, params, video_script: str) -> Dict[str, Any]:
    """Generate a minimal scene plan from the script.

    This implementation splits the script into paragraphs and creates simple
    scene entries with required fields from the spec. It's deterministic and
    lightweight so it can be used for initial A/B testing.
    """
    logger.info(f"generate_scene_plan: task_id={task_id}")
    paragraphs = [p.strip() for p in video_script.splitlines() if p.strip()]
    if not paragraphs:
        paragraphs = [video_script.strip()] if video_script.strip() else []

    scenes: List[Dict[str, Any]] = []
    # naive duration allocation: default guess 3.0s per paragraph
    for i, para in enumerate(paragraphs, start=1):
        scene = {
            "scene_id": i,
            "narration": para,
            "duration": float(3.0),
            "visual_objective": para[:120],
            "visual_description": para[:400],
            "keywords": [],
            "search_queries": [],
            "asset_type": "stock",
            "motion_required": False,
            "camera_style": "medium",
            "transition": "cut",
        }
        scenes.append(scene)

    plan = {"task_id": task_id, "scenes": scenes}
    return plan


def route_scene_assets(task_id: str, params, scene_plan: Dict[str, Any]) -> List[Any] | None:
    """Route assets for each scene.

    Minimal stub: return None to indicate no pre-acquired materials. The real
    router will search providers and return downloaded material descriptors.
    """
    logger.info(f"route_scene_assets stub: task_id={task_id}, scenes={len(scene_plan.get('scenes', []))}")
    # For now, do not acquire assets — let legacy material pipeline run as fallback.
    return None
