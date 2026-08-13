"""Asset Router (initial implementation).

This module implements a conservative router that:
- Iterates scene_plan.scenes and produces an asset decision per scene
- Builds a fallback chain and records search queries
- Writes asset_plan.json into the task directory

At this stage it does not call external APIs: it produces a deterministic
plan and leaves actual acquisition to material.download_videos or later router
implementations. This ensures the pipeline records asset decisions and
fallbacks for benchmarking and human QA.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from app.utils import utils
from app.config import config


def _asset_plan_path(task_id: str) -> Path:
    return Path(utils.task_dir(task_id)) / "asset_plan.json"


def save_asset_plan(task_id: str, asset_plan: Dict[str, Any]) -> None:
    target = _asset_plan_path(task_id)
    tmp = target.parent / ("." + target.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(asset_plan, fp, ensure_ascii=False, indent=4)
            fp.write("\n")
        os.replace(tmp, target)
        logger.info(f"saved asset_plan.json for task {task_id}")
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def route_assets(task_id: str, params, scene_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create an asset plan for the given scene_plan.

    Returns a list of per-scene decision dicts. Each decision contains:
    - scene_id
    - asset_type (preferred)
    - fallback_chain
    - search_queries
    - selected_asset (None if not found)
    """
    scenes = scene_plan.get("scenes", []) or []
    decisions: List[Dict[str, Any]] = []

    for s in scenes:
        preferred = s.get("asset_type", "stock") or "stock"
        fallback = [preferred]
        # simple default fallback ordering per spec
        if preferred == "generated_video":
            fallback = ["generated_video", "stock", "image", "graphics"]
        elif preferred == "stock":
            fallback = ["stock", "image", "graphics"]
        else:
            # generic fallback
            fallback = [preferred, "stock", "image", "graphics"]

        search_q = s.get("search_queries") or []
        if not search_q and s.get("keywords"):
            search_q = s.get("keywords")
        if not search_q:
            # fall back to narration short form
            narration = (s.get("narration") or "").strip()
            if narration:
                search_q = [narration[:120]]

        decision = {
            "scene_id": s.get("scene_id"),
            "asset_type": preferred,
            "fallback_chain": fallback,
            "search_queries": search_q,
            "selected_asset": None,
            "selected_reason": "not_searched",
        }
        # mark if H3 generation should be requested for generated_video preferred paths
        try:
            h3_enabled = bool(config.app.get("h3_enabled", False))
        except Exception:
            h3_enabled = False
        if preferred == "generated_video":
            decision["h3_requested"] = h3_enabled
        decisions.append(decision)

    asset_plan = {"task_id": task_id, "decisions": decisions}
    try:
        save_asset_plan(task_id, asset_plan)
    except Exception:
        logger.exception("failed to save asset_plan.json")

    return decisions
