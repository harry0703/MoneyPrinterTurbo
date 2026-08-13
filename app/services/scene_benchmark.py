"""Simple A/B benchmark harness for Scene Engine (minimal).

This harness runs the deterministic scene_plan -> asset_plan path across a set of
sample scripts and records high-level metrics: scene_count, decisions_count,
selected_count, fallback_rate (selected / scenes). It intentionally avoids
network calls and acquisition: it runs asset_router.route_assets which is
deterministic and safe for benchmarking without API keys.

Write results to storage/benchmark/<run_id>.json for later analysis.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger

from app.services import scene, asset_router
from app.utils import utils


def run_benchmark(run_id: str, scripts: List[str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": time.time(),
        "cases": [],
        "summary": {},
    }

    aggregate = {"scenes": 0, "decisions": 0, "selected": 0}

    for i, script in enumerate(scripts, start=1):
        task_id = f"bench-{run_id}-{i}"
        # generate deterministic scene plan
        plan = scene.generate_scene_plan(task_id, params=None, video_script=script)
        decisions = asset_router.route_assets(task_id, params=None, scene_plan=plan)
        selected = sum(1 for d in (decisions or []) if d.get("selected_asset") is not None)
        cases = {
            "task_id": task_id,
            "scenes": len(plan.get("scenes", [])),
            "decisions": len(decisions or []),
            "selected": selected,
        }
        aggregate["scenes"] += cases["scenes"]
        aggregate["decisions"] += cases["decisions"]
        aggregate["selected"] += cases["selected"]
        results["cases"].append(cases)

    # compute summary metrics
    total = aggregate["scenes"] or 1
    results["summary"] = {
        "total_scenes": aggregate["scenes"],
        "total_decisions": aggregate["decisions"],
        "total_selected": aggregate["selected"],
        "selection_rate": aggregate["selected"] / total,
    }

    # persist to storage/benchmark
    out_dir = utils.storage_dir("benchmark", create=True)
    out_path = Path(out_dir) / f"{run_id}.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"benchmark saved: {out_path}")
    except Exception:
        logger.exception("failed to write benchmark result")

    return results
