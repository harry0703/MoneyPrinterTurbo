"""Premiere Pro handoff export for the creative pipeline.

Builds a portable handoff package from the creative task artifacts:

- ``timeline.xml`` — Premiere Pro XML 4.1 sequence (V1 video + A1 voiceover)
- ``manifest.json`` — shot metadata, media map and import instructions
- ``media/`` — the exact segment files used by the rough cut, plus the
  voiceover and the subtitles

Premiere stays the finishing environment: this module only exports, it never
re-renders or edits the timeline.

Format choice (plan section 20): Premiere Pro XML over FCPXML/OTIO because
the finishing environment is Premiere Pro (FCPXML targets Final Cut and
Premiere does not import OTIO natively).

Time convention: classic Premiere 4.1 — ``TimeScale`` 24, all ``in``/``out``/
``duration`` values in ``seconds * frame_rate * 24``. Media URLs are relative
to the package root so the unzipped folder keeps the clips linked wherever it
is placed.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional


from app.utils import utils

PREMIERE_VERSION = 1
TIMELINE_FILE = "timeline.xml"
MANIFEST_FILE = "manifest.json"

TIME_SCALE = 24
DEFAULT_FRAME_RATE = 30
DEFAULT_VIDEO_SIZE = (1920, 1080)
DEFAULT_SAMPLE_RATE = 48000

ROUGH_CUT_FILE = "rough_cut.json"
SHOT_PLAN_FILE = "shot_plan.json"
SCRIPT_FILE = "script.json"
AUDIO_FILE = "audio.mp3"
SUBTITLE_FILE = "subtitle.srt"
ROUGH_CUT_VIDEO_FILE = "rough_cut.mp4"


class PremiereExportError(Exception):
    """Raised when a task cannot be exported to Premiere."""


def _units(seconds: float, frame_rate: int) -> int:
    return int(round(float(seconds) * frame_rate * TIME_SCALE))


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


def _probe_media(path: str) -> Optional[dict]:
    """Best-effort ffprobe of the rough cut video (size/fps/sample rate)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not os.path.isfile(path):
        return None
    try:
        out = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        if not out:
            return None
        width, height, rate = out.split(",")[:3]
        fps_num, fps_den = (part.strip() for part in rate.split("/"))
        frame_rate = round(int(fps_num) / max(1, int(fps_den)))
        sample_out = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        sample_rate = int(sample_out) if sample_out.isdigit() else None
        return {
            "width": int(width),
            "height": int(height),
            "frame_rate": max(1, frame_rate),
            "sample_rate": sample_rate,
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _resolve_segment(task_dir: str, task_id: str, shot: dict) -> Optional[str]:
    """Resolve a shot segment to a path on disk under the task dir.

    Timeline paths are stored container-absolute; when the container root
    differs from the current filesystem (tests, relocated storage) the path
    is re-anchored on the task dir via the ``/<task_id>/`` marker or the
    standard ``assets/shot_NNN`` layout.
    """
    for key in ("segment_path", "asset_path"):
        raw = shot.get(key)
        if not raw:
            continue
        candidate = os.path.normpath(raw)
        if os.path.isfile(candidate):
            return candidate
    index = shot.get("index")
    try:
        index_name = f"shot_{int(index):03d}"
    except (TypeError, ValueError):
        index_name = None
    for key in ("segment_path", "asset_path"):
        raw = shot.get(key)
        if not raw:
            continue
        marker = f"/{task_id}/"
        if marker in raw:
            suffix = raw.split(marker, 1)[1]
            candidate = os.path.normpath(os.path.join(task_dir, suffix))
            if os.path.isfile(candidate):
                return candidate
        if index_name:
            candidate = os.path.normpath(
                os.path.join(task_dir, "assets", index_name, os.path.basename(raw))
            )
            if os.path.isfile(candidate):
                return candidate
    return None


def _clip_comment(shot: dict, plan_shot: Optional[dict]) -> str:
    parts = [
        f"shot {shot.get('index')}",
        str(shot.get("source") or plan_shot.get("source_type") or ""),
    ]
    provider = shot.get("provider") or plan_shot.get("provider") or ""
    if provider:
        parts.append(provider)
    for field in ("camera", "framing"):
        value = (plan_shot or {}).get(field)
        if value:
            parts.append(f"{field}: {value}")
    segment_text = (plan_shot or {}).get("script_segment") or shot.get("prompt")
    if segment_text:
        parts.append(str(segment_text).strip())
    return " | ".join(part for part in parts if part)


def _build_xml(
    task_id: str,
    shots: list[dict],
    plan_shots: list[dict],
    total_duration: float,
    frame_rate: int,
    width: int,
    height: int,
    sample_rate: int,
    media: list[dict],
    has_audio: bool,
) -> str:
    total_units = _units(total_duration, frame_rate)
    name = f"MPT creative {task_id[:8]}"
    root = ET.Element(
        "Sequence",
        {
            "formatVersion": "1|8",
            "id": "p1",
            "name": name,
            "in": "0",
            "out": str(total_units),
            "duration": str(total_units),
            "audioRate": f"{float(sample_rate):.3f}",
            "videoRate": f"{float(frame_rate):.3f}",
            "audioChannels": "2",
        },
    )
    ET.SubElement(root, "DOMetaData")
    ET.SubElement(
        root,
        "DOVidRes",
        {
            "frameRate": f"{float(frame_rate):.3f}",
            "displayFrameRate": f"{float(frame_rate):.3f}",
            "width": str(width),
            "height": str(height),
            "pixelAspectRatio": "1.000",
        },
    )
    ET.SubElement(
        root,
        "DOAudRes",
        {"sampleRate": f"{float(sample_rate):.3f}", "numAudioChannels": "2"},
    )
    ET.SubElement(
        root,
        "TimeFormat",
        {
            "timeScale": str(TIME_SCALE),
            "displayScale": str(TIME_SCALE),
            "sourceTCDropFrame": "0",
            "audioTCDropFrame": "0",
            "videoRate": f"{float(frame_rate):.3f}",
            "audioRate": f"{float(sample_rate):.3f}",
        },
    )

    ruler = ET.SubElement(
        root,
        "Ruler",
        {"in": "0", "out": str(total_units), "duration": str(total_units)},
    )
    ET.SubElement(
        ruler,
        "TimeScale",
        {"timeScale": str(TIME_SCALE), "videoRate": f"{float(frame_rate):.3f}"},
    )
    in_out = ET.SubElement(ruler, "InAndOutPoints")
    time_el = ET.SubElement(in_out, "Time")
    ET.SubElement(time_el, "TimeCode", {"timeFormat": str(TIME_SCALE), "time": "00:00:00;00"})

    track_structure = ET.SubElement(root, "TrackStructure")
    tracks = ET.SubElement(
        track_structure,
        "Tracks",
        {"count": "2", "name": name},
    )
    ET.SubElement(
        tracks,
        "Track",
        {"id": "v1", "name": "Video 1", "trackHeight": "75", "clipHasMedia": "1"},
    )
    ET.SubElement(
        tracks,
        "Track",
        {"id": "a1", "name": "Audio 1", "trackHeight": "75", "clipHasMedia": "1"},
    )

    track_list = ET.SubElement(root, "TrackList")
    video_track = ET.SubElement(
        track_list, "Track", {"targetTrack": "v1", "name": "Video 1"}
    )
    for position, (shot, entry) in enumerate(zip(shots, media)):
        seq = ET.SubElement(
            video_track,
            "SeqItem",
            {
                "id": f"v1_r{position + 1}",
                "in": str(entry["in_units"]),
                "out": str(entry["out_units"]),
                "duration": str(entry["out_units"] - entry["in_units"]),
                "name": entry["media_name"],
            },
        )
        clip = ET.SubElement(
            seq,
            "ClipItem",
            {
                "id": f"c{position + 1}",
                "markerCount": "0",
                "name": entry["media_name"],
                "in": "0",
                "out": str(entry["out_units"] - entry["in_units"]),
                "duration": str(entry["out_units"] - entry["in_units"]),
                "sourceClip": f"p1_c{position + 1}",
                "audio": "0",
                "video": "1",
            },
        )
        media_path = ET.SubElement(clip, "MediaPath")
        ET.SubElement(
            media_path,
            "MediaPathURL",
            {"URL": entry["url"], "mediaPathType": "file"},
        )
        comment = _clip_comment(shot, plan_shots[position] if position < len(plan_shots) else None)
        if comment:
            ET.SubElement(clip, "Comment").text = comment

    if has_audio:
        audio_track = ET.SubElement(
            track_list, "Track", {"targetTrack": "a1", "name": "Audio 1"}
        )
        seq = ET.SubElement(
            audio_track,
            "SeqItem",
            {
                "id": "a1_r1",
                "in": "0",
                "out": str(total_units),
                "duration": str(total_units),
                "name": AUDIO_FILE,
            },
        )
        clip = ET.SubElement(
            seq,
            "ClipItem",
            {
                "id": "ca",
                "markerCount": "0",
                "name": AUDIO_FILE,
                "in": "0",
                "out": str(total_units),
                "duration": str(total_units),
                "sourceClip": "p1_ca",
                "audio": "1",
                "video": "0",
            },
        )
        media_path = ET.SubElement(clip, "MediaPath")
        ET.SubElement(
            media_path,
            "MediaPathURL",
            {"URL": f"media/{AUDIO_FILE}", "mediaPathType": "file"},
        )

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )


def build_premiere_package(task_id: str) -> dict:
    """Build the handoff package for a creative task.

    Returns ``{"xml": str, "manifest": dict, "files": {arcname: disk_path}}``.
    Raises :class:`PremiereExportError` when the rough cut is missing.
    """
    task_dir = utils.task_dir(task_id)
    if not os.path.isdir(task_dir):
        raise PremiereExportError(f"no task directory found for {task_id}")
    timeline = _load_json(task_dir, ROUGH_CUT_FILE)
    if not timeline or not timeline.get("shots"):
        raise PremiereExportError(f"no rough cut timeline found for {task_id}")

    shots: list[dict] = [shot for shot in timeline.get("shots", []) if isinstance(shot, dict)]
    if not shots:
        raise PremiereExportError(f"rough cut timeline has no shots for {task_id}")
    plan = _load_json(task_dir, SHOT_PLAN_FILE) or {}
    plan_shots: list[dict] = [
        shot for shot in plan.get("shots", []) if isinstance(shot, dict)
    ]
    script = _load_json(task_dir, SCRIPT_FILE) or {}
    total_duration = float(timeline.get("total_duration") or 0.0)
    if total_duration <= 0:
        total_duration = float(shots[-1].get("out") or 0.0)
    if total_duration <= 0:
        raise PremiereExportError(f"rough cut has no duration for {task_id}")

    probe = _probe_media(os.path.join(task_dir, ROUGH_CUT_VIDEO_FILE)) or {}
    width = probe.get("width") or DEFAULT_VIDEO_SIZE[0]
    height = probe.get("height") or DEFAULT_VIDEO_SIZE[1]
    frame_rate = probe.get("frame_rate") or DEFAULT_FRAME_RATE
    sample_rate = probe.get("sample_rate") or DEFAULT_SAMPLE_RATE

    has_audio = os.path.isfile(os.path.join(task_dir, AUDIO_FILE))
    has_subtitles = os.path.isfile(os.path.join(task_dir, SUBTITLE_FILE))

    files: dict[str, str] = {}
    media_entries: list[dict] = []
    manifest_shots: list[dict] = []
    cursor_units = 0
    for position, shot in enumerate(shots):
        index = shot.get("index")
        plan_shot = None
        for candidate in plan_shots:
            if candidate.get("index") == index:
                plan_shot = candidate
                break
        duration = float(shot.get("duration") or 0.0)
        if duration <= 0:
            duration = float(shot.get("out") or 0.0) - float(shot.get("in") or 0.0)
        in_units = cursor_units
        out_units = in_units + _units(duration, frame_rate)
        cursor_units = out_units

        disk_path = _resolve_segment(task_dir, task_id, shot)
        if disk_path:
            try:
                rel = os.path.relpath(disk_path, task_dir)
            except ValueError:
                rel = os.path.basename(disk_path)
            arcname = "media/" + rel.replace(os.sep, "/")
        else:
            rel = os.path.basename(shot.get("segment_path") or shot.get("asset_path") or "")
            arcname = "media/" + rel
        url = arcname
        media_name = os.path.basename(arcname)
        if disk_path:
            files[arcname] = disk_path

        media_entries.append(
            {
                "media_name": media_name,
                "url": url,
                "in_units": in_units,
                "out_units": out_units,
            }
        )
        manifest_shots.append(
            {
                "index": index,
                "file": arcname,
                "missing": disk_path is None,
                "source_type": shot.get("source") or (plan_shot or {}).get("source_type"),
                "provider": shot.get("provider") or (plan_shot or {}).get("provider"),
                "query": shot.get("query") or (plan_shot or {}).get("query") or None,
                "prompt": shot.get("prompt") or (plan_shot or {}).get("prompt") or None,
                "camera": (plan_shot or {}).get("camera"),
                "framing": (plan_shot or {}).get("framing"),
                "motion": (plan_shot or {}).get("motion"),
                "script_segment": (plan_shot or {}).get("script_segment"),
                "duration": duration,
                "timeline_in": float(shot.get("in") or 0.0),
                "timeline_out": float(shot.get("out") or 0.0),
            }
        )

    if has_audio:
        files["media/" + AUDIO_FILE] = os.path.join(task_dir, AUDIO_FILE)
    if has_subtitles:
        files["media/" + SUBTITLE_FILE] = os.path.join(task_dir, SUBTITLE_FILE)

    xml_text = _build_xml(
        task_id,
        shots,
        plan_shots,
        total_duration,
        frame_rate,
        width,
        height,
        sample_rate,
        media_entries,
        has_audio,
    )

    manifest: dict[str, Any] = {
        "version": PREMIERE_VERSION,
        "task_id": task_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "format": "premiere-pro-xml-4.1",
        "video": {"width": width, "height": height, "fps": frame_rate},
        "audio": {"file": f"media/{AUDIO_FILE}", "sample_rate": sample_rate}
        if has_audio
        else None,
        "subtitles": {"file": f"media/{SUBTITLE_FILE}"} if has_subtitles else None,
        "total_duration": total_duration,
        "script": script.get("script"),
        "shots": manifest_shots,
        "notes": (
            "Import timeline.xml in Premiere Pro (File > Import > Premiere Pro "
            "XML). If a clip shows offline, right-click it and Link Media to "
            "the matching file in the media/ folder."
        ),
    }
    return {"xml": xml_text, "manifest": manifest, "files": files}


def build_premiere_zip(task_id: str) -> tuple[bytes, str]:
    """Build the handoff as zip bytes plus a suggested filename."""
    package = build_premiere_package(task_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(TIMELINE_FILE, package["xml"])
        archive.writestr(
            MANIFEST_FILE, json.dumps(package["manifest"], indent=2, ensure_ascii=False)
        )
        for arcname, disk_path in sorted(package["files"].items()):
            archive.write(disk_path, arcname)
    return buffer.getvalue(), f"premiere-{task_id[:8]}.zip"
