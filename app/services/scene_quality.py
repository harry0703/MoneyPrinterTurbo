"""Low-cost local technical checks; semantic acceptance remains model-backed."""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from loguru import logger
from PIL import Image, ImageOps

from app.models.scene_quality import MediaQualityReport
from app.utils import utils


_BLACK_EVENT = re.compile(
    r"black_start:(?P<start>[0-9.]+)\s+black_end:(?P<end>[0-9.]+)\s+black_duration:(?P<duration>[0-9.]+)"
)
_FREEZE_EVENT = re.compile(
    r"freeze_start:(?P<start>[0-9.]+)\s+freeze_duration:(?P<duration>[0-9.]+)"
)
_CACHE: dict[tuple, dict] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 256


def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_events(file_path: Path) -> tuple[list[dict[str, float]], float, list[str]]:
    command = [
        utils.get_ffmpeg_binary(), "-hide_banner", "-nostdin", "-i", str(file_path),
        "-vf", "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-50dB:d=2",
        "-an", "-f", "null", os.devnull,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=90, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], 0.0, [f"visual technical scan unavailable: {type(exc).__name__}"]

    log = result.stderr or ""
    black_events = [
        {
            "start": float(match.group("start")),
            "end": float(match.group("end")),
            "duration": float(match.group("duration")),
        }
        for match in _BLACK_EVENT.finditer(log)
    ]
    freeze_events = [
        {
            "start": float(match.group("start")),
            "duration": float(match.group("duration")),
        }
        for match in _FREEZE_EVENT.finditer(log)
    ]
    issues = []
    if result.returncode and not (black_events or freeze_events):
        issues.append("FFmpeg could not complete the black/freeze scan")
    return freeze_events, sum(event["duration"] for event in black_events), issues


def inspect_media_file(
    file_path: str | Path,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    expected_duration: float | None = None,
    require_audio: bool = False,
    audio_video_tolerance: float = 0.35,
) -> MediaQualityReport:
    """Inspect readability, dimensions, duration, black frames, freezes and sync."""
    started = time.monotonic()
    target = Path(file_path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"media file does not exist: {target}")
    asset_sha256 = _sha256_file(target)
    try:
        stat = target.stat()
        key = (
            asset_sha256, stat.st_size, stat.st_mtime_ns, target_width, target_height,
            expected_duration, require_audio, audio_video_tolerance,
        )
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached is not None:
            result = MediaQualityReport.model_validate(cached)
            result.elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            result.cache_hit = True
            return result
    except OSError:
        key = None

    issues: list[str] = []
    audio_delta = None
    black_ratio = 0.0
    freeze_events: list[dict[str, float]] = []
    duration = 0.0
    try:
        with Image.open(target) as image:
            with ImageOps.exif_transpose(image) as oriented:
                oriented.load()
                width, height = oriented.size
                media_type = "image"
    except Exception:
        try:
            from moviepy import VideoFileClip

            with VideoFileClip(str(target), audio=True) as clip:
                duration = float(clip.duration or 0)
                width, height = (int(value) for value in clip.size)
                media_type = "video"
                if require_audio and clip.audio is None:
                    issues.append("final video has no audio stream")
                if clip.audio is not None:
                    audio_delta = abs(float(clip.audio.duration or 0) - duration)
            freeze_events, black_seconds, scan_issues = _frame_events(target)
            issues.extend(scan_issues)
            black_ratio = min(1.0, black_seconds / max(duration, 0.001))
        except Exception as exc:
            raise ValueError(f"media is unreadable: {type(exc).__name__}: {exc}") from exc

    if min(width, height) < 360:
        issues.append("media resolution is below 360 pixels on its shortest dimension")
    if duration <= 0 and media_type == "video":
        issues.append("video duration is zero or unavailable")
    if expected_duration is not None and media_type == "video":
        if abs(duration - expected_duration) > max(audio_video_tolerance, 0.05):
            issues.append(
                f"video duration differs from expected audio by {abs(duration - expected_duration):.3f}s"
            )
    if require_audio and audio_delta is not None and audio_delta > audio_video_tolerance:
        issues.append(f"audio/video duration differs by {audio_delta:.3f}s")
    if black_ratio > 0.30:
        issues.append(f"black frames cover {black_ratio:.1%} of the video")
    if any(event["duration"] >= 3.0 for event in freeze_events):
        issues.append("video contains a freeze lasting at least three seconds")

    if target_width and target_height:
        resolution_score = min(1.0, width / target_width, height / target_height)
        source_ratio = width / height
        target_ratio = target_width / target_height
        aspect_score = max(0.0, 1.0 - abs(math.log(source_ratio / target_ratio)))
    else:
        resolution_score = min(1.0, min(width, height) / 720)
        aspect_score = 1.0
    freeze_score = 0.0 if any(event["duration"] >= 3 for event in freeze_events) else 1.0
    technical_quality = max(
        0.0,
        min(1.0, 0.4 * resolution_score + 0.2 * aspect_score + 0.2 * (1 - black_ratio) + 0.2 * freeze_score),
    )
    if technical_quality < 0.50:
        issues.append("technical quality score is below 0.50")
    critical = any(
        "no audio stream" in issue
        or "differs from expected audio" in issue
        or "black frames cover" in issue
        or "freeze lasting" in issue
        for issue in issues
    )
    result = MediaQualityReport(
        asset_sha256=asset_sha256,
        media_type=media_type,
        result="rejected" if critical else "review" if issues else "accepted",
        duration_seconds=max(0.0, duration),
        width=width,
        height=height,
        resolution_score=resolution_score,
        aspect_score=aspect_score,
        technical_quality=technical_quality,
        black_duration_ratio=black_ratio,
        freeze_events=freeze_events,
        audio_video_delta_seconds=audio_delta,
        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        issues=issues,
    )
    if key is not None:
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = result.model_dump(mode="json")
    return result


def clear_quality_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
