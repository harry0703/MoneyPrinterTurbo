"""Small, local creative experiments tied to ordinary video generation tasks.

Only aggregate platform metrics are accepted. No platform credentials, viewer data,
or invented performance predictions are needed for this workflow.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.llm_provider import get_llm_provider
from app.models.schema import CreativeExperiment
from app.services import llm, task_artifacts
from app.utils import utils


HOOKS = (
    ("question", "Open with a concrete question the audience wants answered."),
    ("surprise", "Open with a counterintuitive fact supported by the source notes."),
    ("demonstration", "Open with an immediate action or visible demonstration."),
)
METRICS = {"three_second_hold_rate", "completion_rate"}
MAX_CSV_BYTES = 1024 * 1024
MAX_ROWS = 500


def create_experiment(brief: dict, *, language: str = "", app_config=None) -> dict:
    """Generate three deliberately different scripts for the existing task path."""
    subject = str(brief.get("subject", "")).strip()
    goal = str(brief.get("goal", "")).strip()
    audience = str(brief.get("audience", "")).strip()
    sources = str(brief.get("source_notes", "")).strip()
    metric = str(brief.get("metric", "three_second_hold_rate"))
    if not all((subject, goal, audience, sources)):
        raise ValueError("Subject, goal, audience, and source notes are required")
    if any(
        len(value) > limit
        for value, limit in (
            (subject, 300),
            (goal, 300),
            (audience, 300),
            (sources, 1000),
        )
    ):
        raise ValueError("Creative brief exceeds its length limit")
    if metric not in METRICS:
        raise ValueError("Unsupported experiment metric")

    variants = []
    for hook_type, direction in HOOKS:
        prompt = (
            f"Campaign goal: {goal}\nAudience: {audience}\n"
            f"Source facts (do not invent facts beyond these): {sources}\n"
            f"Creative angle: {hook_type}. {direction} "
            "Write a complete short video narration with a distinct opening, "
            "middle, and call to action. Do not name the angle in the narration."
        )
        script = llm.generate_script(
            video_subject=subject,
            language=language,
            video_script_prompt=prompt,
            app_config=app_config,
        ).strip()
        if not script or script.startswith("Error: "):
            raise ValueError(f"Could not generate the {hook_type} variant")
        if len(script) > 8000:
            raise ValueError(
                f"The {hook_type} variant exceeds the 8000-character limit"
            )
        # A provider may ignore creative directions. Do not present identical
        # outputs as an A/B experiment.
        if any(
            _normalized(script) == _normalized(previous["script"])
            for previous in variants
        ):
            raise ValueError("The model returned duplicate variants; try again")
        variants.append(
            {
                "id": hook_type,
                "hook_type": hook_type,
                "script": script,
                "storyboard": _storyboard(script, hook_type),
            }
        )

    provider = str((app_config or {}).get("llm_provider", "unknown"))
    provider_definition = get_llm_provider(provider)
    model_key = (
        provider_definition.config_key("model_name") if provider_definition else ""
    )
    model = str((app_config or {}).get(model_key) or "unknown")
    return {
        "version": 1,
        "experiment_id": str(uuid4()),
        "brief": {
            "subject": subject,
            "goal": goal,
            "audience": audience,
            "source_notes": sources,
            "metric": metric,
        },
        "variants": variants,
        "script_model": {"provider": provider, "model": model},
        "cost_usd": None,
    }


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _storyboard(script: str, hook_type: str) -> list[dict]:
    """A three-beat shot plan; directions are suggestions, not generated assets."""
    import re

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?。！？])\s*", script)
        if part.strip()
    ]
    if len(sentences) < 3:
        sentences = [part.strip() for part in script.splitlines() if part.strip()]
    if len(sentences) < 3:
        sentences = [script[:120], script[:120], script[:120]]
    visual_directions = {
        "question": (
            "Show the unanswered situation before revealing the solution",
            "Show the process or evidence that answers the question",
            "Show the practical answer in the final frame",
        ),
        "surprise": (
            "Contrast the familiar expectation with the surprising claim",
            "Show source-backed evidence or a concrete example",
            "Show the revised takeaway clearly",
        ),
        "demonstration": (
            "Start with the action in the first frame",
            "Use close-up footage of the steps or mechanism",
            "Show the result and the next action viewers can take",
        ),
    }
    return [
        {"beat": name, "narration": text[:300], "visual": direction}
        for name, text, direction in zip(
            ("hook", "development", "payoff"),
            (sentences[0], sentences[len(sentences) // 2], sentences[-1]),
            visual_directions[hook_type],
        )
    ]


def selected_manifest(experiment: dict, variant_id: str) -> dict:
    """Persist the choice with a generated task without modifying other variants."""
    variants = experiment.get("variants", [])
    if variant_id not in {item.get("id") for item in variants}:
        raise ValueError("Unknown experiment variant")
    return {**experiment, "selected_variant_id": variant_id}


def parse_analytics_csv(data: bytes) -> list[dict]:
    """Read a bounded, aggregate CSV with one row per generated task."""
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("Analytics CSV exceeds 1 MiB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("Analytics CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {
        "task_id",
        "impressions",
        "views",
        "three_second_views",
        "completed_views",
    }
    if not reader.fieldnames or set(reader.fieldnames) != required:
        raise ValueError(
            "CSV columns must be task_id,impressions,views,three_second_views,completed_views"
        )
    rows = []
    seen = set()
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise ValueError("Analytics CSV has too many rows")
        try:
            task_id = str(UUID(row["task_id"].strip()))
            counts = {key: int(row[key]) for key in required - {"task_id"}}
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(
                "Analytics rows need a UUID and whole-number counts"
            ) from exc
        if task_id in seen:
            raise ValueError(f"Duplicate task_id: {task_id}")
        if min(counts.values()) < 0 or not (
            counts["completed_views"]
            <= counts["three_second_views"]
            <= counts["views"]
            <= counts["impressions"]
        ):
            raise ValueError(
                "Counts must satisfy completed ≤ 3-second ≤ views ≤ impressions"
            )
        seen.add(task_id)
        rows.append({"task_id": task_id, **counts})
    if not rows:
        raise ValueError("Analytics CSV has no rows")
    return rows


def task_manifest(task_id: str) -> dict | None:
    """Load only an existing UUID task artifact; never create from CSV input."""
    try:
        task_id = str(UUID(task_id))
    except ValueError:
        return None
    task_path = Path(utils.task_dir()) / task_id
    if task_path.is_symlink():
        return None
    target = task_path / "script.json"
    try:
        if (
            not target.is_file()
            or target.is_symlink()
            or target.stat().st_size > 256 * 1024
        ):
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        manifest = CreativeExperiment.model_validate(
            payload.get("creative_experiment")
        ).model_dump()
    except ValidationError:
        return None
    selected = next(
        (
            variant
            for variant in manifest["variants"]
            if variant["id"] == manifest["selected_variant_id"]
        ),
        None,
    )
    if selected is None or payload.get("script") != selected["script"]:
        return None
    return {
        "manifest": manifest,
        "assets": payload.get("material_sources", []),
        "selected_materials": payload.get("material_selections", []),
    }


def compare_outcomes(rows: list[dict], manifests: dict[str, dict]) -> dict:
    """Use observed aggregate rates only; no causal or model prediction claims."""
    experiment_ids = {m["manifest"]["experiment_id"] for m in manifests.values()}
    if len(experiment_ids) != 1 or not experiment_ids:
        raise ValueError("Choose tasks from one creative experiment")
    experiment = next(iter(manifests.values()))["manifest"]
    common = {
        key: value for key, value in experiment.items() if key != "selected_variant_id"
    }
    if any(
        {
            key: value
            for key, value in entry["manifest"].items()
            if key != "selected_variant_id"
        }
        != common
        for entry in manifests.values()
    ):
        raise ValueError("Experiment manifests differ across tasks")
    metric = experiment["brief"]["metric"]
    summary = {
        variant["id"]: {
            "variant_id": variant["id"],
            "tasks": 0,
            "impressions": 0,
            "views": 0,
            "three_second_views": 0,
            "completed_views": 0,
        }
        for variant in experiment["variants"]
    }
    for row in rows:
        entry = manifests[row["task_id"]]["manifest"]
        variant_id = entry["selected_variant_id"]
        if variant_id not in summary:
            raise ValueError("Task has an unknown variant")
        bucket = summary[variant_id]
        bucket["tasks"] += 1
        for field in ("impressions", "views", "three_second_views", "completed_views"):
            bucket[field] += row[field]
    results = []
    for bucket in summary.values():
        views = bucket["views"]
        bucket["three_second_hold_rate"] = (
            bucket["three_second_views"] / views if views else None
        )
        bucket["completion_rate"] = bucket["completed_views"] / views if views else None
        results.append(bucket)
    eligible = [item for item in results if item["views"] >= 100]
    winner = (
        max(eligible, key=lambda item: item[metric]) if len(eligible) >= 2 else None
    )
    return {
        "experiment_id": experiment["experiment_id"],
        "metric": metric,
        "observed": results,
        "prediction": None,
        "next_batch_suggestion": (
            f"Consider testing a new {winner['variant_id']} hook against a control"
            if winner
            else "Collect at least 100 views for two variants before comparing"
        ),
        "caveat": "Observed association only; audience, timing, and distribution may differ.",
    }


def save_outcomes(rows: list[dict]) -> int:
    """Persist aggregate outcomes in task artifacts; reject missing manifests."""
    for row in rows:
        if task_manifest(row["task_id"]) is None:
            raise ValueError(f"Task {row['task_id']} has no creative experiment")
    saved = 0
    for row in rows:
        if task_artifacts.patch_script_data(row["task_id"], observed_outcome=row):
            saved += 1
    return saved
