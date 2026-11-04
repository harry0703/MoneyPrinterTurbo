"""LLM-backed scene planning, isolated from the legacy script contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from loguru import logger

from app.models.video_plan import Scene, SceneTiming, Shot, VideoPlan, validate_plan_script_coverage
from app.services import llm
from app.utils import utils


class ScenePlanError(ValueError):
    """The provider response could not be converted into a faithful scene plan."""


_PLANNER_INSTRUCTIONS = """You are a visual scene planner for an existing narration.
Return one JSON object only, with this shape:
{
  "scenes": [{
    "narration_text": "an exact contiguous excerpt from the supplied script",
    "estimated_duration_ms": 4000,
    "timing_confidence": 0.3,
    "subject": ["specific subject"],
    "action": "observable action",
    "context": "visual context",
    "description": "specific visual description of the shot",
    "shot_type": "wide|medium|close_up|...",
    "visual_prompt": "specific image/video generation prompt",
    "search_queries": ["English visual search query"],
    "recommended_material_type": ["stock_video", "generated_video", "generated_image", "local"],
    "avoid": ["visually misleading content"]
  }]
}
Split the narration into a small number of coherent visual beats. Every narration_text
must be copied exactly from the script, stay in its original order, and collectively
cover the complete script without omissions or paraphrasing. Do not add dialogue,
titles, stage directions, or facts. Make visual descriptions concrete and specific;
do not substitute a broad category for an explicitly named object, place, person,
event, or phenomenon. Search queries must be concise English phrases. Return no
Markdown fences or explanatory prose."""


def _extract_json_object(response: str) -> dict[str, Any]:
    text = (response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ScenePlanError("planner response did not contain a JSON object")


def _build_plan(
    payload: dict[str, Any], *, script: str, subject: str, language: str
) -> VideoPlan:
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ScenePlanError("planner response must contain a non-empty scenes array")

    scenes = []
    for index, raw in enumerate(raw_scenes):
        if not isinstance(raw, dict):
            raise ScenePlanError(f"scene {index + 1} must be an object")
        try:
            timing = SceneTiming(
                estimated_duration_ms=raw.get("estimated_duration_ms", 0),
                confidence=raw.get("timing_confidence", 0.25),
                source="estimated",
            )
            visual = {
                "subject": raw["subject"],
                "action": raw["action"],
                "context": raw.get("context", ""),
                "description": raw["description"],
                "shot_type": raw.get("shot_type", "medium"),
                "visual_prompt": raw["visual_prompt"],
                "search_queries": raw["search_queries"],
                "recommended_material_type": raw.get(
                    "recommended_material_type", ["stock_video"]
                ),
                "avoid": raw.get("avoid", []),
            }
            text = raw["narration_text"]
            scene = Scene(
                scene_id=f"scene-{index + 1:03d}",
                order=index,
                narration_text=text,
                timing=timing,
                visual=visual,
                shots=[
                    Shot(
                        shot_id=f"scene-{index + 1:03d}-shot-001",
                        role="primary",
                        duration_share=1.0,
                    )
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ScenePlanError(f"invalid planner scene {index + 1}: {exc}") from exc
        scenes.append(scene)

    script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
    try:
        plan = VideoPlan(
            script_sha256=script_hash,
            subject=subject,
            language=language,
            scenes=scenes,
        )
        validate_plan_script_coverage(script, plan)
    except ValueError as exc:
        raise ScenePlanError(str(exc)) from exc
    return plan


def plan_script(
    script: str,
    *,
    subject: str,
    language: str = "",
    app_config=None,
) -> VideoPlan:
    """Create a validated visual plan while preserving the spoken narration."""
    spoken_script = utils.remove_pause_tags(script or "")
    if not spoken_script.strip():
        raise ScenePlanError("cannot plan scenes for an empty narration")

    prompt = (
        f"{_PLANNER_INSTRUCTIONS}\n\n"
        f"Subject: {subject}\nLanguage: {language or 'same as narration'}\n\n"
        "Script to segment (copy exact excerpts):\n"
        f"<script>\n{spoken_script}\n</script>"
    )
    try:
        response = llm.generate_structured_response(prompt, app_config=app_config)
        if not response or response.startswith("Error: "):
            raise ScenePlanError(response.removeprefix("Error: ").strip() or "LLM returned no plan")
        return _build_plan(
            _extract_json_object(response),
            script=spoken_script,
            subject=subject,
            language=language,
        )
    except ScenePlanError:
        raise
    except Exception as exc:
        logger.warning("scene planning failed: {}: {}", type(exc).__name__, exc)
        raise ScenePlanError(f"scene planning failed: {type(exc).__name__}: {exc}") from exc
