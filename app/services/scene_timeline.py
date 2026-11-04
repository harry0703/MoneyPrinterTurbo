"""Build a renderable scene timeline from the Sprint 1/2 artifacts."""

from __future__ import annotations

import re
import unicodedata
from html import unescape
from pathlib import Path

from app.models.scene_media import SceneMediaManifest
from app.models.scene_timeline import SceneTimeline, TimelineItem
from app.models.video_plan import VideoPlan
from app.utils.subtitle_reader import file_to_subtitles
from moviepy.tools import convert_to_seconds


def _normalize_for_alignment(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(char for char in text if char.isalnum())


def _subtitle_cues(subtitle_path: str | None) -> list[tuple[float, float, str]]:
    if not subtitle_path:
        return []
    result = []
    for _index, timing, text in file_to_subtitles(subtitle_path):
        timestamps = re.findall(r"([0-9]*:[0-9]*:[0-9]*,[0-9]*)", timing)
        if len(timestamps) != 2 or not text.strip():
            continue
        start, end = (convert_to_seconds(value) for value in timestamps)
        if end > start >= 0:
            result.append((float(start), float(end), text))
    return result


def _tts_cues(sub_maker) -> list[tuple[float, float, str]]:
    if sub_maker is None:
        return []
    cues = getattr(sub_maker, "cues", None) or []
    if cues:
        return [
            (cue.start.total_seconds(), cue.end.total_seconds(), unescape(str(cue.content)))
            for cue in cues
            if cue.end > cue.start and str(cue.content).strip()
        ]
    offsets = getattr(sub_maker, "offset", None) or []
    subs = getattr(sub_maker, "subs", None) or []
    result = []
    for (start, end), text in zip(offsets, subs):
        start, end = float(start) / 10_000_000, float(end) / 10_000_000
        if end > start and str(text).strip():
            result.append((start, end, str(text)))
    return result


def _find_scene_anchors(plan: VideoPlan, cues: list[tuple[float, float, str]]) -> list[float]:
    """Require every scene's spoken words to occur, in order, in timed cues."""
    cue_text = "".join(_normalize_for_alignment(text) for _, _, text in cues)
    cue_ranges = []
    cursor = 0
    for start, end, text in cues:
        normalized = _normalize_for_alignment(text)
        cue_ranges.append((cursor, cursor + len(normalized), start, end))
        cursor += len(normalized)

    anchors = []
    cursor = 0
    for scene in plan.scenes:
        expected = _normalize_for_alignment(scene.narration_text)
        if not expected:
            raise ValueError(f"scene has no alignable narration: {scene.scene_id}")
        match = cue_text.find(expected, cursor)
        if match < 0:
            raise ValueError(f"timed speech does not match scene narration: {scene.scene_id}")
        matching_cue = next(
            (
                (cue_start, cue_end, start, end)
                for cue_start, cue_end, start, end in cue_ranges
                if cue_end > match and cue_start <= match
            ),
            None,
        )
        if matching_cue is None:
            raise ValueError(f"could not resolve cue timestamp for scene: {scene.scene_id}")
        cue_start, cue_end, start, end = matching_cue
        cue_progress = (match - cue_start) / max(1, cue_end - cue_start)
        anchors.append(float(start + (end - start) * cue_progress))
        cursor = match + len(expected)
    return anchors


def _estimated_anchors(plan: VideoPlan, audio_duration: float) -> list[float]:
    weights = [max(1, scene.timing.estimated_duration_ms) for scene in plan.scenes]
    total = sum(weights)
    starts = [0.0]
    elapsed = 0.0
    for weight in weights[:-1]:
        elapsed += audio_duration * weight / total
        starts.append(elapsed)
    return starts


def build_scene_timeline(
    plan: VideoPlan,
    manifest: SceneMediaManifest,
    *,
    audio_duration: float,
    asset_root: str | Path | None = None,
    subtitle_path: str | None = None,
    sub_maker=None,
    fps: int = 30,
    video_fit_mode: str = "cover",
    image_motion: str = "zoom",
) -> SceneTimeline:
    if manifest.plan_id != plan.plan_id or manifest.script_sha256 != plan.script_sha256:
        raise ValueError("scene media manifest does not belong to the active plan")
    if audio_duration <= 0:
        raise ValueError("audio duration must be positive")
    assignments = {entry.scene_id: entry for entry in manifest.assignments}
    missing = [scene.scene_id for scene in plan.scenes if scene.scene_id not in assignments]
    if missing:
        raise ValueError(f"scene media assignments are missing: {', '.join(missing)}")
    unselected = [
        scene.scene_id for scene in plan.scenes
        if assignments[scene.scene_id].status != "selected"
        or assignments[scene.scene_id].selected_candidate is None
        or not assignments[scene.scene_id].selected_candidate.local_path
    ]
    if unselected:
        raise ValueError(f"scenes do not have selected local media: {', '.join(unselected)}")

    subtitle_cues = _subtitle_cues(subtitle_path)
    tts_cues = _tts_cues(sub_maker)
    anchors = None
    alignment_error = None
    if subtitle_cues:
        try:
            anchors = _find_scene_anchors(plan, subtitle_cues)
            alignment_source, synchronization = "subtitles", "subtitle_aligned"
        except ValueError as exc:
            alignment_error = exc
    if anchors is None and tts_cues:
        try:
            anchors = _find_scene_anchors(plan, tts_cues)
            alignment_source, synchronization = "tts_cues", "tts_aligned"
        except ValueError as exc:
            alignment_error = exc
    if anchors is None and not subtitle_cues and not tts_cues:
        anchors = _estimated_anchors(plan, audio_duration)
        alignment_source, synchronization = "estimated", "estimated"
    elif anchors is None:
        raise ValueError(f"available speech timestamps could not be aligned: {alignment_error}")

    if anchors and anchors[0] > 0.75:
        raise ValueError("timed narration does not begin near the start of the audio")
    boundaries = [0.0]
    boundaries.extend(anchors[1:])
    boundaries.append(float(audio_duration))
    if any(right <= left for left, right in zip(boundaries, boundaries[1:])):
        raise ValueError("scene narration anchors are not strictly increasing")

    items = []
    used_fingerprints = set()
    for index, scene in enumerate(plan.scenes):
        assignment = assignments[scene.scene_id]
        candidate = assignment.selected_candidate
        if candidate.resource_fingerprint in used_fingerprints:
            raise ValueError(f"scene media is repeated in the timeline: {scene.scene_id}")
        used_fingerprints.add(candidate.resource_fingerprint)
        asset = Path(candidate.local_path).expanduser()
        if not asset.is_absolute() and asset_root is not None:
            root = Path(asset_root).expanduser().resolve()
            asset = (root / asset).resolve()
            if not asset.is_relative_to(root):
                raise ValueError(f"scene media path escapes its task directory: {scene.scene_id}")
        if not asset.is_file():
            raise ValueError(f"selected media file is unavailable: {scene.scene_id}")
        start, end = boundaries[index], boundaries[index + 1]
        duration = end - start
        if duration <= 0:
            raise ValueError(f"scene has an invalid duration: {scene.scene_id}")
        if (
            candidate.material_type != "generated_image"
            and candidate.duration_seconds > 0
            and candidate.duration_seconds + 0.025 < duration
        ):
            raise ValueError(
                f"selected video is shorter than its narration interval: {scene.scene_id}"
            )
        items.append(TimelineItem(
            scene_id=scene.scene_id,
            asset_path=str(asset.resolve()),
            material_type=candidate.material_type,
            provider=candidate.provider,
            original_asset_id=candidate.original_asset_id,
            timeline_start=start,
            timeline_end=end,
            source_start=0,
            source_end=duration,
            entry_transition="cut",
            exit_transition="cut",
            fit_mode=video_fit_mode,
            image_motion=image_motion,
            synchronization=synchronization,
            narration_text=scene.narration_text,
            shot_id=scene.shots[0].shot_id,
            scene_label=scene.visual.subject[0][:160],
        ))

    return SceneTimeline(
        plan_id=plan.plan_id,
        script_sha256=plan.script_sha256,
        audio_duration=float(audio_duration),
        alignment_source=alignment_source,
        synchronization=synchronization,
        fps=fps,
        items=items,
    )
