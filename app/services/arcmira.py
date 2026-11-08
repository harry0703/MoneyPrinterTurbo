"""Search spoken passages and fetch only the selected video segments."""

from __future__ import annotations

import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
from loguru import logger

from app.config import config


API_URL = "https://api.arcmira.com/v1/search"
CLIP_RIGHTS_LINE = (
    "You need the rights to download, cut or reuse this video. "
    "Arcmira finds the moment and gives you the link and the seconds. "
    "It grants no rights to the video."
)
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class ArcmiraError(RuntimeError):
    """A configuration or search failure that must stop the material request."""


@dataclass(frozen=True)
class Moment:
    video_id: str
    start_seconds: float
    text: str
    channel: str
    published_at: str

    @property
    def watch_url(self) -> str:
        return (
            f"https://www.youtube.com/watch?v={self.video_id}&t={self.start_seconds:g}s"
        )


def search_arcmira_moments(search_term: str, limit: int = 5) -> list[Moment]:
    if not isinstance(search_term, str) or len(search_term.strip()) < 2:
        raise ArcmiraError(
            "Arcmira search needs a topic or phrase of at least two characters"
        )
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ArcmiraError("Arcmira search limit must be between 1 and 20")
    key = str(config.app.get("arcmira_api_key", "") or "").strip()
    if not key:
        raise ArcmiraError("Set arcmira_api_key before searching Arcmira")
    try:
        response = requests.get(
            API_URL,
            params={"q": search_term.strip(), "limit": limit},
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ArcmiraError("Arcmira search could not connect") from None
    if response.status_code != 200:
        raise ArcmiraError(f"Arcmira search returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise ArcmiraError("Arcmira search returned invalid JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("chunks"), list):
        raise ArcmiraError("Arcmira search returned an invalid passage list")
    moments = []
    for chunk in payload["chunks"][:limit]:
        if not isinstance(chunk, dict):
            continue
        video_id, start, text = (
            chunk.get(k) for k in ("video_id", "start_seconds", "text")
        )
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            continue
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or not math.isfinite(start)
            or start < 0
        ):
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        moments.append(
            Moment(
                video_id,
                float(start),
                text,
                chunk.get("channel_name")
                if isinstance(chunk.get("channel_name"), str)
                else "",
                chunk.get("published_at")
                if isinstance(chunk.get("published_at"), str)
                else "",
            )
        )
    return moments


def fetch_arcmira_clip(
    moment: Moment, save_dir: str, max_clip_duration: float
) -> str | None:
    """Fetch one segment without reading downloader configuration or signing in."""
    import imageio_ffmpeg

    if not math.isfinite(max_clip_duration) or max_clip_duration <= 0:
        raise ArcmiraError("Arcmira clip duration must be positive and finite")
    end = moment.start_seconds + max_clip_duration
    directory = Path(save_dir)
    directory.mkdir(parents=True, exist_ok=True)
    output = (
        directory / f"arcmira-{moment.video_id}-{moment.start_seconds:g}-{end:g}.mp4"
    )
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "--retries",
        "0",
        "--fragment-retries",
        "0",
        "--download-sections",
        f"*{moment.start_seconds:g}-{end:g}",
        "--force-keyframes-at-cuts",
        "--ffmpeg-location",
        imageio_ffmpeg.get_ffmpeg_exe(),
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "--max-filesize",
        "512M",
        "--no-overwrites",
        "-o",
        str(output),
        moment.watch_url,
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning(
            "Arcmira clip download failed or timed out; skipping {}", moment.video_id
        )
        return None
    if result.returncode:
        message = result.stderr.lower()
        needs_sign_in = any(
            term in message
            for term in (
                "sign in",
                "sign-in",
                "private video",
                "members-only",
                "age-restricted",
                "login required",
            )
        )
        reason = "video requires sign-in" if needs_sign_in else "downloader failed"
        logger.warning("Arcmira clip skipped: {} ({})", moment.video_id, reason)
        return None
    return str(output) if output.is_file() and output.stat().st_size else None
