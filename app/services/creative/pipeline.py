"""Creative pipeline stage status for external orchestration.

Derives a stage-by-stage view of the creative production pipeline
(brief, script, shot_plan, audio, subtitle, materials, rough_cut,
director_review, final_video, qc, publish) from the in-memory task
state and the artifacts on disk. An external orchestrator (for
example OpenCode driving the HTTP API) uses this single view to
inspect progress, pick the next action, and resume a run after a
pause. The vanilla MoneyPrinterTurbo flow is not affected by this
module.
"""

import glob
import json
import os
from typing import Optional

from app.models import const
from app.services import state as sm
from app.utils import utils

STAGE_NAMES = [
    "brief",
    "script",
    "shot_plan",
    "audio",
    "subtitle",
    "materials",
    "rough_cut",
    "director_review",
    "final_video",
    "qc",
    "publish",
]

STATE_NAMES = {
    const.TASK_STATE_FAILED: "failed",
    const.TASK_STATE_COMPLETE: "complete",
    const.TASK_STATE_PROCESSING: "processing",
    const.TASK_STATE_WAITING_FOR_DIRECTOR: "waiting_for_director",
}

ROUGH_CUT_FILE = "rough_cut.json"

# File-based stages: stage name -> artifact file name inside the task
# directory. Stages not listed here are derived from the task state or
# the rough cut timeline instead of a single file.
_STAGE_ARTIFACTS = {
    "brief": "creative_brief.json",
    "script": "script.json",
    "shot_plan": "shot_plan.json",
    "audio": "audio.mp3",
    "subtitle": "subtitle.srt",
    "rough_cut": "rough_cut.mp4",
    "qc": "qc_report.json",
}

_ACTIONS_WAITING_FOR_DIRECTOR = [
    "approve",
    "resume",
    "get_rough_cut",
    "regenerate_shot",
    "reorder_shots",
    "set_shot_duration",
    "replace_shot_asset",
    "delete_shot",
    "qc",
]

_ACTIONS_COMPLETE = ["qc", "premiere"]


def _load_json(task_dir: str, file_name: str) -> Optional[dict]:
    path = os.path.join(task_dir, file_name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _final_videos(task_dir: str) -> list:
    return sorted(glob.glob(os.path.join(task_dir, "final-*.mp4")))


def _first_missing_stage(task_dir: str) -> Optional[str]:
    """First file-based stage (in pipeline order) without its artifact."""
    for name in ("brief", "script", "shot_plan", "audio", "subtitle", "rough_cut"):
        if not os.path.isfile(os.path.join(task_dir, _STAGE_ARTIFACTS[name])):
            return name
    if not _final_videos(task_dir):
        return "final_video"
    if not os.path.isfile(os.path.join(task_dir, _STAGE_ARTIFACTS["qc"])):
        return "qc"
    return None


def _file_stage(name: str, state, task_dir: str, failed_at: Optional[str]) -> dict:
    file_name = _STAGE_ARTIFACTS[name]
    if os.path.isfile(os.path.join(task_dir, file_name)):
        return {"name": name, "status": "done", "detail": file_name}
    if state in (
        const.TASK_STATE_COMPLETE,
        const.TASK_STATE_WAITING_FOR_DIRECTOR,
    ):
        return {
            "name": name,
            "status": "skipped",
            "detail": f"no {file_name} (stage not reached or option disabled)",
        }
    if state == const.TASK_STATE_FAILED:
        if failed_at == name:
            return {
                "name": name,
                "status": "failed",
                "detail": f"task failed before {file_name} was produced",
            }
        return {
            "name": name,
            "status": "pending",
            "detail": "not reached (task failed earlier)",
        }
    return {"name": name, "status": "pending", "detail": f"waiting for {file_name}"}


def _materials_stage(state, timeline: Optional[dict]) -> dict:
    shots = (timeline or {}).get("shots") or []
    total = len(shots)
    if total == 0:
        status = "pending"
        detail = "no rough cut timeline yet"
    else:
        resolved = sum(
            1
            for shot in shots
            if shot.get("asset_path")
            and os.path.isfile(shot["asset_path"])
        )
        detail = f"{resolved}/{total} shot assets resolved"
        if resolved == total:
            status = "done"
        elif resolved > 0:
            status = "active"
        else:
            status = "pending"
    return {"name": "materials", "status": status, "detail": detail}


def _director_review_stage(state, failed_at: Optional[str]) -> dict:
    if state == const.TASK_STATE_WAITING_FOR_DIRECTOR:
        return {
            "name": "director_review",
            "status": "active",
            "detail": "awaiting director approval",
        }
    if state == const.TASK_STATE_COMPLETE:
        return {"name": "director_review", "status": "done", "detail": "approved"}
    if state == const.TASK_STATE_FAILED:
        return {
            "name": "director_review",
            "status": "pending",
            "detail": "not reached (task failed earlier)",
        }
    return {
        "name": "director_review",
        "status": "pending",
        "detail": "reached after the rough cut is built",
    }


def _final_video_stage(state, task_dir: str, failed_at: Optional[str]) -> dict:
    videos = _final_videos(task_dir)
    if videos:
        return {
            "name": "final_video",
            "status": "done",
            "detail": os.path.basename(videos[-1]),
        }
    if state == const.TASK_STATE_COMPLETE:
        return {
            "name": "final_video",
            "status": "failed",
            "detail": "task is complete but no final video was found",
        }
    if state == const.TASK_STATE_FAILED:
        if failed_at == "final_video":
            return {
                "name": "final_video",
                "status": "failed",
                "detail": "task failed while rendering the final video",
            }
        return {
            "name": "final_video",
            "status": "pending",
            "detail": "not reached (task failed earlier)",
        }
    return {
        "name": "final_video",
        "status": "pending",
        "detail": "rendered after director approval",
    }


def _qc_stage(state, task_dir: str, failed_at: Optional[str]) -> dict:
    file_name = _STAGE_ARTIFACTS["qc"]
    if os.path.isfile(os.path.join(task_dir, file_name)):
        return {"name": "qc", "status": "done", "detail": file_name}
    if state == const.TASK_STATE_COMPLETE:
        return {
            "name": "qc",
            "status": "skipped",
            "detail": f"no {file_name} (advisory report not generated)",
        }
    if state == const.TASK_STATE_FAILED:
        if failed_at == "qc":
            return {
                "name": "qc",
                "status": "failed",
                "detail": f"task failed before the {file_name} was written",
            }
        return {
            "name": "qc",
            "status": "pending",
            "detail": "not reached (task failed earlier)",
        }
    return {
        "name": "qc",
        "status": "pending",
        "detail": f"written after the final video ({file_name})",
    }


def _publish_stage(task_dir: str) -> dict:
    if _final_videos(task_dir):
        return {
            "name": "publish",
            "status": "done",
            "detail": "premiere handoff exportable via GET /creative/tasks/{task_id}/premiere",
        }
    return {
        "name": "publish",
        "status": "pending",
        "detail": "available once the final video exists",
    }


def _build_stage(name: str, state, task_dir: str, timeline: Optional[dict],
                 failed_at: Optional[str]) -> dict:
    if name in _STAGE_ARTIFACTS and name != "qc":
        return _file_stage(name, state, task_dir, failed_at)
    if name == "materials":
        return _materials_stage(state, timeline)
    if name == "director_review":
        return _director_review_stage(state, failed_at)
    if name == "final_video":
        return _final_video_stage(state, task_dir, failed_at)
    if name == "qc":
        return _qc_stage(state, task_dir, failed_at)
    if name == "publish":
        return _publish_stage(task_dir)
    raise ValueError(f"unknown stage: {name}")


def _shot_summaries(timeline: Optional[dict]) -> list:
    shots = (timeline or {}).get("shots") or []
    summaries = []
    for shot in shots:
        asset = shot.get("asset_path") or ""
        summaries.append(
            {
                "index": shot.get("index"),
                "source": shot.get("source"),
                "duration": shot.get("duration"),
                "asset_exists": bool(asset) and os.path.isfile(asset),
                "asset": os.path.basename(asset) if asset else None,
            }
        )
    return summaries


def build_pipeline_status(task_id: str, task: Optional[dict] = None) -> Optional[dict]:
    """Return the stage-by-stage pipeline view for a creative task.

    Returns None when the task is unknown to the in-memory state store.
    """
    if task is None:
        task = sm.state.get_task(task_id)
    if task is None:
        return None

    state = task.get("state")
    task_dir = utils.task_dir(task_id)
    timeline = _load_json(task_dir, ROUGH_CUT_FILE)
    failed_at = (
        _first_missing_stage(task_dir) if state == const.TASK_STATE_FAILED else None
    )

    stages = []
    for name in STAGE_NAMES:
        stage = _build_stage(name, state, task_dir, timeline, failed_at)
        stages.append(stage)

    if (
        state == const.TASK_STATE_PROCESSING
        and not any(stage["status"] == "active" for stage in stages)
    ):
        for stage in stages:
            if stage["status"] == "pending":
                stage["status"] = "active"
                stage["detail"] = "current stage"
                break

    if state == const.TASK_STATE_WAITING_FOR_DIRECTOR:
        available_actions = list(_ACTIONS_WAITING_FOR_DIRECTOR)
    elif state == const.TASK_STATE_COMPLETE:
        available_actions = list(_ACTIONS_COMPLETE)
    else:
        available_actions = []

    return {
        "task_id": task_id,
        "task_state": state,
        "state_name": STATE_NAMES.get(state, "unknown"),
        "progress": task.get("progress", 0),
        "stages": stages,
        "shots": _shot_summaries(timeline),
        "available_actions": available_actions,
    }
