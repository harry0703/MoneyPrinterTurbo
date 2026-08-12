import os
import tempfile

import requests
from loguru import logger

from app.config import config
from app.services import bgm as bgm_service


GLOBAL_MUSIC_URL = "https://api.minimax.io/v1/music_generation"
CN_MUSIC_URL = "https://api.minimaxi.com/v1/music_generation"
DEFAULT_MODEL = "music-3.0"
SUPPORTED_MODELS = frozenset(
    {"music-3.0", "music-2.6", "music-3.0-free", "music-2.6-free"}
)
MAX_PROMPT_LENGTH = 2000
MAX_AUDIO_HEX_LENGTH = 100 * 1024 * 1024
SUPPORTED_SAMPLE_RATES = frozenset({16000, 24000, 32000, 44100})
SUPPORTED_BITRATES = frozenset({32000, 64000, 128000, 256000})
SUPPORTED_AUDIO_FORMATS = frozenset({"mp3", "wav", "pcm"})


class MiniMaxMusicError(RuntimeError):
    """Raised when music generation or response validation fails."""


def get_api_key() -> str:
    configured_key = str(config.minimax_music.get("api_key", "") or "").strip()
    return configured_key or os.getenv("MINIMAX_API_KEY", "").strip()


def is_enabled() -> bool:
    return bool(get_api_key())


def output_suffix() -> str:
    audio_format = _configured_choice("audio_format", "mp3", SUPPORTED_AUDIO_FORMATS)
    return f".{audio_format}"


def _endpoint() -> str:
    configured = str(
        config.minimax_music.get("base_url", GLOBAL_MUSIC_URL) or GLOBAL_MUSIC_URL
    ).strip().rstrip("/")
    if configured in {GLOBAL_MUSIC_URL, CN_MUSIC_URL}:
        return configured
    if configured.endswith("/v1"):
        return f"{configured}/music_generation"
    return configured


def _configured_choice(name: str, default, supported: frozenset):
    value = config.minimax_music.get(name, default)
    try:
        value = type(default)(value)
    except (TypeError, ValueError):
        return default
    return value if value in supported else default


def _payload(prompt: str) -> dict:
    model = _configured_choice("model_id", DEFAULT_MODEL, SUPPORTED_MODELS)
    audio_format = output_suffix().removeprefix(".")
    sample_rate = _configured_choice("sample_rate", 44100, SUPPORTED_SAMPLE_RATES)
    bitrate = _configured_choice("bitrate", 256000, SUPPORTED_BITRATES)
    lyrics = str(config.minimax_music.get("lyrics", "") or "").strip()
    instrumental = bool(config.minimax_music.get("is_instrumental", True))
    lyrics_optimizer = bool(config.minimax_music.get("lyrics_optimizer", False))
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "output_format": "hex",
        "audio_setting": {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": audio_format,
        },
        "lyrics_optimizer": lyrics_optimizer,
        "is_instrumental": instrumental,
    }
    if lyrics:
        payload["lyrics"] = lyrics
    if _endpoint() == CN_MUSIC_URL:
        payload["aigc_watermark"] = bool(
            config.minimax_music.get("aigc_watermark", False)
        )
    return payload


def _decode_audio(response: requests.Response) -> bytes:
    try:
        body = response.json()
    except ValueError as exc:
        raise MiniMaxMusicError("MiniMax returned an invalid JSON response") from exc
    if not isinstance(body, dict):
        raise MiniMaxMusicError("MiniMax returned an unexpected response")
    base_resp = body.get("base_resp") or {}
    data = body.get("data") or {}
    if base_resp.get("status_code") != 0:
        message = str(base_resp.get("status_msg") or "request failed")[:300]
        raise MiniMaxMusicError(f"MiniMax music generation failed: {message}")
    if data.get("status") != 2:
        raise MiniMaxMusicError("MiniMax music generation did not complete")
    audio_hex = data.get("audio")
    if not isinstance(audio_hex, str) or not audio_hex:
        raise MiniMaxMusicError("MiniMax returned empty audio data")
    if len(audio_hex) > MAX_AUDIO_HEX_LENGTH:
        raise MiniMaxMusicError("MiniMax returned audio that exceeds the size limit")
    try:
        return bytes.fromhex(audio_hex)
    except ValueError as exc:
        raise MiniMaxMusicError("MiniMax returned invalid hex audio data") from exc


def generate_bgm(
    video_path: str,
    output_path: str,
    video_duration: float,
    prompt: str = "",
) -> str:
    """Generate instrumental background music with the synchronous Music API."""
    del video_duration
    if not get_api_key():
        raise MiniMaxMusicError("MiniMax API key is required")
    if not os.path.isfile(video_path):
        raise MiniMaxMusicError("MiniMax input video does not exist")
    prompt = str(prompt or "").strip()
    if not prompt:
        raise MiniMaxMusicError("MiniMax music prompt is required")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise MiniMaxMusicError("MiniMax music prompt exceeds 2000 characters")

    payload = _payload(prompt)
    try:
        response = requests.post(
            _endpoint(),
            json=payload,
            headers={
                "Authorization": f"Bearer {get_api_key()}",
                "Content-Type": "application/json",
            },
            timeout=(15, 600),
        )
        response.raise_for_status()
        audio = _decode_audio(response)
    except requests.RequestException as exc:
        raise MiniMaxMusicError(f"failed to request MiniMax music: {exc}") from exc

    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    audio_format = payload["audio_setting"]["format"]
    descriptor, temp_path = tempfile.mkstemp(
        prefix=".minimax-music-",
        suffix=f".{audio_format}",
        dir=output_dir,
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(audio)
            output.flush()
            os.fsync(output.fileno())
        bgm_service.validate_audio_file(temp_path, timeout_seconds=120)
        os.replace(temp_path, output_path)
        temp_path = ""
        logger.info(f"MiniMax background music generated: output={output_path}")
        return output_path
    except (OSError, bgm_service.BgmUploadError, bgm_service.BgmServiceError) as exc:
        raise MiniMaxMusicError("MiniMax returned unusable audio") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
