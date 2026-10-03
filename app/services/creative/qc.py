"""Advisory creative QC for the creative pipeline.

Reads the four creative artifacts from the task directory
(``creative_brief.json``, ``style_profile.json``, ``shot_plan.json`` and
``rough_cut.json``), runs deterministic consistency checks and persists a
report (``qc_report.json``) next to them.

The report is advisory only: it never blocks the pipeline, never edits the
shot plan and never overwrites approved shots.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from app.services import task_artifacts
from app.utils import utils

QC_REPORT_FILE = "qc_report.json"
QC_VERSION = 1

BRIEF_FILE = "creative_brief.json"
STYLE_FILE = "style_profile.json"
SHOT_PLAN_FILE = "shot_plan.json"
ROUGH_CUT_FILE = "rough_cut.json"

_MIN_SHOT_DURATION = 0.5
_MAX_SHOT_DURATION = 600.0
_TIMING_TOLERANCE = 0.05
_AUDIO_DRIFT_BASE = 2.0
_AUDIO_DRIFT_RATIO = 0.1


def _load_json(task_dir: str, file_name: str) -> Optional[dict]:
    path = os.path.join(task_dir, file_name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _issue(code: str, message: str, shot_index: Optional[int] = None) -> dict:
    return {"code": code, "message": message, "shot_index": shot_index}


def _review(shot_index: Any, reason: str) -> dict:
    return {"shot_index": shot_index, "reason": reason}


def _check_timeline(timeline: dict) -> tuple[list, list, list]:
    issues: list[dict] = []
    shots_to_review: list[dict] = []
    notes: list[str] = []
    shots = timeline.get("shots") or []
    if not shots:
        issues.append(_issue("timeline_empty", "rough cut timeline has no shots"))
        return issues, shots_to_review, notes

    expected_index = 1
    cursor = 0.0
    for shot in shots:
        index = shot.get("index")
        if index != expected_index:
            issues.append(
                _issue(
                    "timeline_index_gap",
                    f"timeline shot index {index} out of sequence "
                    f"(expected {expected_index})",
                    index,
                )
            )
        expected_index += 1

        try:
            duration = float(shot.get("duration"))
        except (TypeError, ValueError):
            issues.append(
                _issue(
                    "timeline_bad_duration",
                    f"shot {index} has an invalid duration "
                    f"{shot.get('duration')!r}",
                    index,
                )
            )
            continue
        if duration <= 0:
            issues.append(
                _issue(
                    "timeline_bad_duration",
                    f"shot {index} duration must be positive, got {duration}",
                    index,
                )
            )
            continue
        if not _MIN_SHOT_DURATION <= duration <= _MAX_SHOT_DURATION:
            shots_to_review.append(
                _review(index, f"duration {duration}s outside sanity range")
            )

        shot_in = shot.get("in")
        shot_out = shot.get("out")
        if shot_in is not None and abs(float(shot_in) - cursor) > _TIMING_TOLERANCE:
            issues.append(
                _issue(
                    "timeline_gap",
                    f"shot {index} starts at {shot_in}s but the previous "
                    f"shot ends at {round(cursor, 3)}s",
                    index,
                )
            )
        if shot_out is not None:
            if abs(float(shot_out) - float(shot_in if shot_in is not None else cursor) - duration) > _TIMING_TOLERANCE:
                issues.append(
                    _issue(
                        "timeline_inout_mismatch",
                        f"shot {index} in/out points do not match its "
                        f"duration",
                        index,
                    )
                )
            cursor = float(shot_out)
        else:
            cursor += duration

        asset_path = shot.get("asset_path") or ""
        if asset_path and not os.path.isfile(asset_path):
            shots_to_review.append(
                _review(index, f"asset missing on disk: {asset_path}")
            )

    total = timeline.get("total_duration")
    if total is not None and abs(float(total) - cursor) > _TIMING_TOLERANCE:
        issues.append(
            _issue(
                "timeline_total_mismatch",
                f"total_duration {total}s does not match the last out "
                f"point {round(cursor, 3)}s",
            )
        )
    return issues, shots_to_review, notes


def _check_plan_coverage(
    plan: dict, timeline: Optional[dict]
) -> tuple[list, list, list]:
    issues: list[dict] = []
    shots_to_review: list[dict] = []
    notes: list[str] = []
    plan_shots = plan.get("shots") or []
    timeline_shots = (timeline or {}).get("shots") or []
    if timeline_shots:
        timeline_indices = {shot.get("index") for shot in timeline_shots}
        for shot in plan_shots:
            index = shot.get("index")
            if index not in timeline_indices:
                issues.append(
                    _issue(
                        "plan_shot_missing_in_timeline",
                        f"plan shot {index} has no rough cut entry",
                        index,
                    )
                )
    elif plan_shots:
        notes.append("rough cut missing; plan coverage not checked")

    for shot in plan_shots:
        if shot.get("status") == "failed":
            shots_to_review.append(
                _review(
                    shot.get("index"),
                    f"plan shot failed: {shot.get('error') or 'no error recorded'}",
                )
            )
    return issues, shots_to_review, notes


def _check_brief(brief: dict) -> tuple[list, list, list]:
    issues: list[dict] = []
    notes: list[str] = []
    if not str(brief.get("topic") or "").strip():
        issues.append(
            _issue("brief_missing_topic", "creative brief has no topic")
        )
    forbidden = brief.get("forbidden_elements") or []
    if forbidden:
        notes.append(
            "brief forbids: " + ", ".join(str(item) for item in forbidden)
            + " — check the shots visually"
        )
    return issues, [], notes


def _check_style(style: dict) -> tuple[list, list, list]:
    notes: list[str] = []
    has_constraints = bool(
        style.get("palette")
        or style.get("visual_style")
        or style.get("camera_language")
        or style.get("motion_language")
        or style.get("character_rules")
        or style.get("negative_rules")
    )
    if not has_constraints:
        notes.append(
            "style profile has no visual constraints; shots are not "
            "checked against an identity"
        )
    return [], [], notes


def run_qc(
    task_id: str, audio_duration: Optional[float] = None
) -> dict:
    """Run the deterministic QC checks over the task artifacts."""
    task_dir = utils.task_dir(task_id)
    brief = _load_json(task_dir, BRIEF_FILE)
    style = _load_json(task_dir, STYLE_FILE)
    plan = _load_json(task_dir, SHOT_PLAN_FILE)
    timeline = _load_json(task_dir, ROUGH_CUT_FILE)

    issues: list[dict] = []
    shots_to_review: list[dict] = []
    notes: list[str] = []

    missing = [
        name
        for name, payload in (
            (BRIEF_FILE, brief),
            (STYLE_FILE, style),
            (SHOT_PLAN_FILE, plan),
            (ROUGH_CUT_FILE, timeline),
        )
        if payload is None
    ]
    if missing:
        notes.append("artifacts missing: " + ", ".join(missing))

    brief_issues, brief_review, brief_notes = _check_brief(brief or {})
    if brief is not None:
        issues.extend(brief_issues)
        shots_to_review.extend(brief_review)
        notes.extend(brief_notes)

    if style is not None:
        style_issues, style_review, style_notes = _check_style(style)
        issues.extend(style_issues)
        shots_to_review.extend(style_review)
        notes.extend(style_notes)

    if plan is not None:
        plan_issues, plan_review, plan_notes = _check_plan_coverage(
            plan, timeline
        )
        issues.extend(plan_issues)
        shots_to_review.extend(plan_review)
        notes.extend(plan_notes)

    if timeline is not None:
        tl_issues, tl_review, tl_notes = _check_timeline(timeline)
        issues.extend(tl_issues)
        shots_to_review.extend(tl_review)
        notes.extend(tl_notes)
        total = timeline.get("total_duration")
        if total is not None and audio_duration:
            drift = abs(float(total) - float(audio_duration))
            if drift > max(_AUDIO_DRIFT_BASE, _AUDIO_DRIFT_RATIO * float(audio_duration)):
                notes.append(
                    f"rough cut is {round(float(total), 3)}s while the "
                    f"voice-over is {round(float(audio_duration), 3)}s "
                    f"(drift {round(drift, 3)}s)"
                )

    return {
        "version": QC_VERSION,
        "task_id": task_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issues": issues,
        "shots_to_review": shots_to_review,
        "notes": notes,
    }


def write_report(
    task_id: str, audio_duration: Optional[float] = None
) -> dict:
    """Run the checks and persist the report next to the artifacts."""
    report = run_qc(task_id, audio_duration=audio_duration)
    task_artifacts.write_task_json(task_id, QC_REPORT_FILE, report)
    logger.info(
        f"[creative_qc] report written: {len(report['issues'])} issues, "
        f"{len(report['shots_to_review'])} shots to review, "
        f"{len(report['notes'])} notes, task_id={task_id}"
    )
    return report


def load_report(task_id: str) -> Optional[dict]:
    return _load_json(utils.task_dir(task_id), QC_REPORT_FILE)
