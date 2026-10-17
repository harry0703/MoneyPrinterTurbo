"""Director stage: turn the generated script into a structured shot plan.

Runs only when creative mode is enabled (``VideoParams.creative_mode`` plus
the ``[creative]`` config section). It reuses the same provider-agnostic LLM
path as script and terms generation, so no new model integration is needed.
The resulting plan is persisted as ``shot_plan.json`` in the task directory
so it can be inspected or edited before asset generation.
"""

from __future__ import annotations

import json

from loguru import logger

from app.models.creative import (
    SHOT_SOURCE_GENERATED,
    CreativeBrief,
    ShotPlan,
    StyleProfile,
    validate_shot_plan,
)
from app.models.schema import VideoParams
from app.services import llm, task_artifacts
from app.utils import utils

_SHOT_PLAN_JSON_SHAPE = (
    '{"shots": [{"index": 1, "script_segment": "...", "duration": 5.0, '
    '"source_type": "stock", "query": "short search query", '
    '"camera": "...", "framing": "...", "motion": "..."}, '
    '{"index": 2, "script_segment": "...", "duration": 5.0, '
    '"source_type": "generated_image", '
    '"prompt": "detailed visual prompt for image generation", '
    '"camera": "...", "framing": "...", "motion": "..."}]}'
)


def _format_brief_section(brief: CreativeBrief | None) -> str:
    if brief is None:
        return ""
    lines = [f"- topic: {brief.topic}"]
    for label, value in (
        ("audience", brief.audience),
        ("objective", brief.objective),
        ("thesis", brief.thesis),
        ("tone", brief.tone),
        ("visual language", brief.visual_language),
        ("notes", brief.notes),
    ):
        if value and str(value).strip():
            lines.append(f"- {label}: {value}")
    if brief.references:
        lines.append(f"- references: {'; '.join(brief.references)}")
    if brief.forbidden_elements:
        lines.append(
            "- forbidden elements (never use these): "
            + "; ".join(brief.forbidden_elements)
        )
    return "### Creative Brief\n" + "\n".join(lines)


def _format_style_section(style_profile: StyleProfile | None) -> str:
    if style_profile is None:
        return ""
    lines = [f"- name: {style_profile.name}"]
    for label, value in (
        ("visual style", style_profile.visual_style),
        ("camera language", style_profile.camera_language),
        ("motion language", style_profile.motion_language),
    ):
        if value and str(value).strip():
            lines.append(f"- {label}: {value}")
    if style_profile.palette:
        lines.append(f"- palette: {', '.join(style_profile.palette)}")
    if style_profile.character_rules:
        lines.append(
            "- character rules: " + "; ".join(style_profile.character_rules)
        )
    if style_profile.negative_rules:
        lines.append(
            "- negative rules (never do these): "
            + "; ".join(style_profile.negative_rules)
        )
    if style_profile.reference_images:
        lines.append(
            "- reference images: " + ", ".join(style_profile.reference_images)
        )
    return "### Style Profile\n" + "\n".join(lines)


def build_shot_plan_prompt(
    video_script: str,
    brief: CreativeBrief | None = None,
    style_profile: StyleProfile | None = None,
    aspect_ratio: str = "",
    clip_duration: int = 5,
) -> str:
    context_lines = [
        "### Video Script\n" + video_script.strip(),
    ]
    brief_section = _format_brief_section(brief)
    if brief_section:
        context_lines.append(brief_section)
    style_section = _format_style_section(style_profile)
    if style_section:
        context_lines.append(style_section)
    if aspect_ratio:
        context_lines.append(f"### Aspect Ratio\n{aspect_ratio}")
    context_lines.append(
        f"### Typical Shot Length\nabout {clip_duration} seconds per shot"
    )
    context = "\n".join(context_lines)

    return f"""# Role: Video Shot Planner

## Goals:
Break the video script into an ordered shot plan for visual production.

## Constraints:
1. return a single JSON object and nothing else, no markdown.
2. the object must have exactly this shape: {_SHOT_PLAN_JSON_SHAPE}
3. shots must be ordered by index starting at 1 and cover the whole script in order.
4. every shot needs a source_type: stock, local, generated_image, generated_video, graphic or archive.
5. stock and local shots must include a short search query of 1-4 words in English in the "query" field.
6. generated_image and generated_video shots must include a detailed visual prompt in the "prompt" field describing the frame (subject, action, setting, lighting, style). Never put a generation prompt in "query"; "query" is only for stock and local search.
7. duration is the shot length in seconds; shot durations should roughly match how long each part of the narration takes.
8. prefer generated_image when the frame needs a consistent look, generated_video only when real motion is essential, and stock for generic B-roll.
9. respect the creative brief and style profile exactly; forbidden elements must never appear.
10. reply with English field values only.

## Context:
{context}
"""


def _normalize_shot_fields(shot: dict) -> dict:
    """Promote an LLM-provided generation prompt out of the ``query`` field.

    Smaller models often put the visual prompt of a generated shot in
    ``query`` (the first example field in the prompt shape). When a
    generated shot has no ``prompt`` of its own, move ``query`` into
    ``prompt`` so the plan stays usable without burning a retry.
    """
    source_type = str(shot.get("source_type") or "").strip().lower()
    if source_type not in SHOT_SOURCE_GENERATED:
        return shot
    if (shot.get("prompt") or "").strip():
        return shot
    query = shot.get("query")
    if isinstance(query, str) and query.strip():
        shot["prompt"] = query
        shot.pop("query", None)
    return shot


def parse_shot_plan_response(response: str, task_id: str) -> ShotPlan:
    """Parse a raw LLM response into a validated ``ShotPlan``."""
    payload = json.loads(llm._strip_code_fence(response))
    if isinstance(payload, dict):
        shots = payload.get("shots")
    elif isinstance(payload, list):
        shots = payload
    else:
        raise ValueError("shot plan response must be a JSON object or list")
    if not isinstance(shots, list):
        raise ValueError("shot plan response is missing the shots list")
    shots = [
        _normalize_shot_fields(shot) if isinstance(shot, dict) else shot
        for shot in shots
    ]
    return ShotPlan.model_validate({"task_id": task_id, "shots": shots})


def generate_shot_plan(
    task_id: str,
    params: VideoParams,
    video_script: str,
) -> ShotPlan | None:
    """
    Generate and persist the creative shot plan for a task.

    Returns the validated plan on success or ``None`` when the LLM keeps
    failing or the plan stays invalid after all retries, mirroring how script
    and terms generation signal failure to the pipeline.
    """
    video_script = utils.remove_pause_tags(video_script or "").strip()
    prompt = build_shot_plan_prompt(
        video_script=video_script,
        brief=params.creative_brief,
        style_profile=params.style_profile,
        aspect_ratio=params.video_aspect or "",
        clip_duration=params.video_clip_duration,
    )
    logger.info(
        f"[creative] generating shot plan: task_id={task_id}, "
        f"subject={params.video_subject}"
    )

    plan: ShotPlan | None = None
    last_issues: list[str] = []
    for attempt in range(llm._max_retries):
        try:
            response = llm._generate_response(prompt)
        except Exception as exc:
            logger.warning(
                f"[creative] shot plan generation error: "
                f"{type(exc).__name__}: {exc}"
            )
            response = ""
        if not response or response.startswith("Error: "):
            logger.error(
                f"[creative] failed to generate shot plan: "
                f"{(response or 'empty response').strip()}"
            )
            break
        try:
            candidate = parse_shot_plan_response(response, task_id)
            last_issues = validate_shot_plan(candidate)
            if last_issues:
                logger.warning(
                    f"[creative] shot plan validation issues: {last_issues}"
                )
            else:
                plan = candidate
                break
        except Exception as exc:
            logger.warning(
                f"[creative] failed to parse shot plan: "
                f"{type(exc).__name__}: {exc}"
            )
        if attempt < llm._max_retries - 1:
            logger.warning(
                f"[creative] retrying shot plan generation... {attempt + 1}"
            )

    if plan is None:
        if last_issues:
            logger.error(
                f"[creative] shot plan rejected after retries: {last_issues}"
            )
        return None

    task_artifacts.write_shot_plan_data(task_id, plan.model_dump(mode="json"))
    total_duration = round(sum(shot.duration or 0 for shot in plan.shots), 1)
    logger.success(
        f"[creative] shot plan created: task_id={task_id}, "
        f"shots={len(plan.shots)}, total_duration={total_duration}s"
    )
    return plan
