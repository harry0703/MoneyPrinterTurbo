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
    """Route assets for each scene and attempt acquisition + validation.

    For each scene decision produced by asset_router, try providers from the
    fallback_chain and download candidate videos using app.services.material.
    Validate candidates using asset_validator and pick the highest-scoring
    acceptable candidate per scene. Returns a list of local file paths for
    selected assets or None when nothing was selected (so legacy pipeline
    can continue).
    """
    logger.info(f"route_scene_assets: task_id={task_id}, scenes={len(scene_plan.get('scenes', []))}")
    try:
        from app.services import asset_router, asset_validator, material
        from moviepy.video.io.VideoFileClip import VideoFileClip
    except Exception as exc:
        logger.exception(f"failed to import routing dependencies: {exc}")
        return None

    decisions = asset_router.route_assets(task_id, params, scene_plan)
    selected_paths: List[str] = []

    for dec in decisions:
        scene_id = dec.get("scene_id")
        fallback_chain = dec.get("fallback_chain") or []
        search_queries = dec.get("search_queries") or []
        if not search_queries:
            # fallback to narration if no queries
            search_queries = [dec.get("narration")] if dec.get("narration") else []

        selected = None
        selected_meta = None

        for asset_type in fallback_chain:
            # map asset_type to provider list
            providers = []
            if asset_type == "stock":
                providers = ["pexels", "pixabay", "coverr"]
            elif asset_type == "generated_video":
                # H3 handled separately; skip generation here
                providers = []
            else:
                # image, graphics, local: not handled by video router now
                providers = []

            for provider in providers:
                try:
                    # try each query until we find a candidate
                    for q in search_queries:
                        if not q:
                            continue
                        paths = material.download_videos(
                            task_id=task_id,
                            search_terms=[q],
                            source=provider,
                            video_aspect=params.video_aspect,
                            video_concat_mode=params.video_concat_mode,
                            audio_duration=float(dec.get("duration") or 0.0),
                            max_clip_duration=int(getattr(params, "video_clip_duration", 5)),
                            match_script_order=False,
                        )
                        if paths:
                            # take first path
                            candidate_path = paths[0]
                            # inspect metadata
                            try:
                                clip = VideoFileClip(candidate_path)
                                cand_meta = {
                                    "local_file": str(candidate_path).split("\\")[-1],
                                    "duration": float(clip.duration or 0.0),
                                    "width": int(getattr(clip, "w", 0) or 0),
                                    "height": int(getattr(clip, "h", 0) or 0),
                                }
                                try:
                                    clip.close()
                                except Exception:
                                    pass
                            except Exception:
                                cand_meta = {"local_file": str(candidate_path).split("\\")[-1], "duration": 0.0}

                            score = asset_validator.score_candidate(dec, cand_meta)
                            # simple acceptance threshold
                            if score.get("final_score", 0) >= 0.5:
                                selected = candidate_path
                                selected_meta = score
                                dec["selected_asset"] = selected
                                dec["selected_reason"] = f"provider:{provider}"
                                dec["score"] = score
                                logger.info(f"selected asset for scene {scene_id}: {selected} (score={score.get('final_score')})")
                                break
                            else:
                                # keep best candidate but continue searching
                                logger.info(f"candidate for scene {scene_id} scored {score.get('final_score')}, continuing search")
                                # record candidate in decision
                                dec.setdefault("candidates", []).append({"path": candidate_path, "score": score})
                        # else no paths for this query
                    if selected:
                        break
                except Exception as e:
                    logger.warning(f"search provider {provider} failed for scene {scene_id}: {e}")
            if selected:
                break

        if selected:
            selected_paths.append(selected)
        else:
            dec["selected_asset"] = None
            dec["selected_reason"] = "none_found"

    # save updated asset_plan with selections and scores
    asset_plan = {"task_id": task_id, "decisions": decisions}
    try:
        asset_router.save_asset_plan(task_id, asset_plan)
    except Exception:
        logger.exception("failed to persist asset_plan.json after routing")

    return selected_paths if selected_paths else None
