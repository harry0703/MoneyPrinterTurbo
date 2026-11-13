"""AI background music with Google Flow Music (Lyria) through useapi.net.

useapi.net is a third-party API; the music is generated on the user's own
Google Flow Music account and uses the Google Flow Music credits included in the user's
Google AI plan.  One instrumental track is generated per output video from a
text prompt, then looped or trimmed to the video length so MPT's usual
fade-out lands at the end of the video.

The module implements the video music provider interface used by
``task._VIDEO_MUSIC_PROVIDERS``: ``is_enabled``, ``generate_bgm``,
``validate_generation_access`` and ``MAX_PROMPT_LENGTH``.
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
from typing import Any

from loguru import logger

from app.config import config
from app.services import bgm as bgm_service
from app.services import useapi_audio
from app.utils import utils


MUSIC_URL = f"{useapi_audio.DEFAULT_BASE_URL}/flowmusic/music"
JOBS_URL = f"{useapi_audio.DEFAULT_BASE_URL}/flowmusic/jobs"
DOWNLOAD_URL = f"{useapi_audio.DEFAULT_BASE_URL}/flowmusic/music/download"
ACCOUNTS_URL = f"{useapi_audio.DEFAULT_BASE_URL}/flowmusic/accounts"
# lyria-3.5 is Google's current flagship; lyria-3-pro is the API's default.
MODELS = {
    "lyria-3.5": "Lyria 3.5",
    "lyria-3-pro": "Lyria 3 Pro",
}
DEFAULT_MODEL = "lyria-3.5"
MAX_PROMPT_LENGTH = 2000
MAX_SUBJECT_LENGTH = 300
MAX_VIDEO_DURATION_SECONDS = 3600
FIT_TIMEOUT_SECONDS = 300
# Mirrors bgm._validate_audio: MP3, M4A/MOV, AAC, WAV, FLAC, OGG and WMA.
AUDIO_PROTOCOL_WHITELIST = "file,pipe"
AUDIO_FORMAT_WHITELIST = "mp3,mov,aac,wav,flac,ogg,asf"


class FlowMusicError(RuntimeError):
    """Google Flow Music generation, download or local processing failed.

    The message is masked like ``UseAPIAudioError``: job and clip ids carry
    the account email.
    """

    def __init__(self, message: str = ""):
        super().__init__(useapi_audio.safe_text(message))


class FlowMusicAccessError(FlowMusicError):
    """The token was rejected or no working Google Flow Music account is connected."""


def get_api_key() -> str:
    return useapi_audio.get_api_key()


def is_enabled() -> bool:
    return useapi_audio.is_enabled()


def model_id() -> str:
    """The configured Lyria model, or the default when it is not offered."""
    value = str(config.app.get("useapi_flowmusic_model", "") or DEFAULT_MODEL).strip()
    return value if value in MODELS else DEFAULT_MODEL


def default_prompt(subject: str = "", script: str = "") -> str:
    """A background music prompt for a video about ``subject``.

    Used when the user leaves the music style empty; the script's opening
    stands in for a missing subject.
    """
    topic = " ".join(str(subject or "").split()) or " ".join(str(script or "").split())
    if len(topic) > MAX_SUBJECT_LENGTH:
        topic = topic[:MAX_SUBJECT_LENGTH].rsplit(" ", 1)[0] or topic[:MAX_SUBJECT_LENGTH]
    prompt = (
        "Instrumental background music for a short narrated video. Steady, "
        "unobtrusive and warm, with a mood that fits the topic, mixed to sit "
        "under a voice-over; no vocals."
    )
    if topic:
        prompt += f" Topic: {topic}"
    return prompt


def test_connection() -> int:
    """Check the token and count the connected Google Flow Music accounts (no credits)."""
    api_token = get_api_key()
    if not api_token:
        raise FlowMusicAccessError("Google Flow Music requires a useapi.net API token")
    try:
        accounts = useapi_audio.get_json(ACCOUNTS_URL, api_token)
    except useapi_audio.UseAPIAudioError as exc:
        if exc.status_code in {401, 403}:
            raise FlowMusicAccessError(str(exc)) from exc
        raise FlowMusicError(str(exc)) from exc
    if not isinstance(accounts, dict):
        raise FlowMusicError("useapi.net returned an unexpected Google Flow Music account list")
    healthy = [
        account
        for account in accounts.values()
        if isinstance(account, dict) and not account.get("error")
    ]
    if not healthy:
        raise FlowMusicAccessError(
            "No working Google Flow Music account is connected to this useapi.net token"
        )
    logger.info(f"useapi.net Google Flow Music check succeeded: accounts={len(healthy)}")
    return len(healthy)


def validate_generation_access() -> None:
    """Stop before the script and voice-over when the music cannot be generated.

    A rejected token or no connected account is certain to fail; a network
    error proves nothing, so it only logs a warning and generation decides.
    """
    try:
        test_connection()
    except FlowMusicAccessError:
        raise
    except FlowMusicError as exc:
        logger.warning(
            "useapi.net Google Flow Music preflight was inconclusive; generation will "
            f"verify access: error={exc}"
        )


def _clip(job: dict[str, Any]) -> dict[str, Any]:
    clips = job.get("clips")
    for clip in clips if isinstance(clips, list) else []:
        if isinstance(clip, dict) and clip.get("clip"):
            return clip
    return {}


def _generate_track(prompt: str, output_path: str) -> str:
    """Generate one instrumental track and download it as MP3; return the job id."""
    api_token = useapi_audio.require_api_key()
    model = model_id()
    payload = {
        "prompt": prompt,
        "instrumental": True,
        "model": model,
        "mode": "async",
    }
    logger.info(
        "requesting useapi.net Google Flow Music background music: "
        f"model={model}, prompt_length={len(prompt)}"
    )
    response = useapi_audio.post(MUSIC_URL, payload, api_token)
    job = useapi_audio.check_submission(response, api_token, "Google Flow Music")
    job_id = str(job.get("jobid") or "").strip()
    status = str(job.get("status") or "").strip().lower()
    if status in useapi_audio.FAILURE_STATUSES:
        raise FlowMusicError(
            "useapi.net Google Flow Music generation failed: "
            f"{useapi_audio.payload_error(job, 200, api_token)}"
        )
    if status != "completed" or not _clip(job):
        if not job_id:
            raise useapi_audio.UseAPIAudioUnconfirmedError(
                "useapi.net accepted the music request without a job id"
            )
        logger.info(f"useapi.net Google Flow Music job created: id={useapi_audio.safe_job_id(job_id)}")
        job = useapi_audio.wait_for_job(
            f"{JOBS_URL}/{useapi_audio.path_segment(job_id)}", api_token, job_id
        )
        if job is None:
            raise FlowMusicError(f"useapi.net Google Flow Music job failed: id={useapi_audio.safe_job_id(job_id)}")
    clip = _clip(job)
    if not clip:
        raise FlowMusicError(
            f"useapi.net Google Flow Music job completed without a track: id={useapi_audio.safe_job_id(job_id)}"
        )
    try:
        useapi_audio.download(
            f"{DOWNLOAD_URL}?id={useapi_audio.path_segment(clip['clip'])}&format=mp3",
            output_path,
            api_token=api_token,
            job_id=job_id,
        )
    except useapi_audio.UseAPIAudioError:
        # The clip's own signed m4a link is the same track; try it once.
        audio_url = clip.get("audio_url")
        if not (isinstance(audio_url, str) and audio_url.startswith("https://")):
            raise
        logger.warning(
            "useapi.net Google Flow Music MP3 download failed; using the track's own link: "
            f"id={useapi_audio.safe_job_id(job_id)}"
        )
        useapi_audio.download(audio_url, output_path, job_id=job_id)
    return job_id


def _fit_to_duration(source_path: str, output_path: str, duration: float) -> None:
    """Loop or trim the track to ``duration`` seconds and encode it as MP3."""
    command = [
        utils.get_ffmpeg_binary(),
        "-nostdin",
        "-v",
        "error",
        "-y",
        # Same input hardening as bgm.py: local files only, audio containers
        # only, so a downloaded playlist cannot make FFmpeg read other files.
        "-protocol_whitelist",
        AUDIO_PROTOCOL_WHITELIST,
        "-format_whitelist",
        AUDIO_FORMAT_WHITELIST,
        "-stream_loop",
        "-1",
        "-i",
        source_path,
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        output_path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FIT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FlowMusicError("fitting the Google Flow Music track to the video timed out") from exc
    except OSError as exc:
        raise FlowMusicError("failed to run FFmpeg for the Google Flow Music track") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip().replace("\n", " ")[-500:]
        raise FlowMusicError(f"failed to fit the Google Flow Music track to the video: {detail}")


def _validate_track(file_path: str, message: str) -> None:
    """Fully decode ``file_path`` with MPT's background music validator."""
    try:
        bgm_service.validate_audio_file(file_path, timeout_seconds=120)
    except (bgm_service.BgmUploadError, bgm_service.BgmServiceError) as exc:
        raise FlowMusicError(message) from exc


def _remove_file(file_path: str) -> None:
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as exc:
            logger.warning(f"failed to remove Google Flow Music temporary file: {exc}")


def generate_bgm(
    video_path: str,
    output_path: str,
    video_duration: float,
    prompt: str = "",
) -> str:
    """Generate an instrumental track as long as the video; return ``output_path``.

    ``video_path`` is part of the provider interface; Google Flow Music works from
    the text prompt alone, so the video is not uploaded.
    """
    if not get_api_key():
        raise FlowMusicError("Google Flow Music requires a useapi.net API token")
    try:
        duration = float(video_duration)
    except (TypeError, ValueError) as exc:
        raise FlowMusicError("Google Flow Music video duration is invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise FlowMusicError("Google Flow Music video duration is invalid")
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise FlowMusicError(
            f"Google Flow Music background music supports videos up to "
            f"{MAX_VIDEO_DURATION_SECONDS} seconds"
        )
    prompt = str(prompt or "").strip() or default_prompt()
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise FlowMusicError(
            f"Google Flow Music prompt exceeds {MAX_PROMPT_LENGTH} characters"
        )

    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    descriptor, track_path = tempfile.mkstemp(
        prefix=".flowmusic-track-", suffix=".mp3", dir=output_dir
    )
    os.close(descriptor)
    descriptor, fitted_path = tempfile.mkstemp(
        prefix=".flowmusic-fitted-", suffix=".mp3", dir=output_dir
    )
    os.close(descriptor)
    try:
        try:
            job_id = _generate_track(prompt, track_path)
        except useapi_audio.UseAPIAudioError as exc:
            raise FlowMusicError(str(exc)) from exc
        # The download is remote content: check that it is self-contained,
        # decodable audio (not a playlist or other media) before FFmpeg
        # processes it, then check the fitted result the same way.
        _validate_track(track_path, "Google Flow Music returned a file that is not audio")
        _fit_to_duration(track_path, fitted_path, duration)
        _validate_track(
            fitted_path, "Google Flow Music returned audio that FFmpeg cannot decode"
        )
        os.replace(fitted_path, output_path)
        fitted_path = ""
        logger.info(
            "useapi.net Google Flow Music background music ready: "
            f"id={useapi_audio.safe_job_id(job_id)}, output={output_path}, "
            f"duration={duration:.1f}s"
        )
        return output_path
    except OSError as exc:
        raise FlowMusicError(f"Google Flow Music local file operation failed: {exc}") from exc
    finally:
        _remove_file(track_path)
        _remove_file(fitted_path)
