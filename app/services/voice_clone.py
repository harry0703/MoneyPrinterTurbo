"""
Voice cloning service.

Uses external open-source voice cloning engines to generate TTS audio
from a short reference audio clip (few-shot / zero-shot voice cloning).

Supported backends:
- GPT-SoVITS   (https://github.com/RVC-Boss/GPT-SoVITS)  — best quality, MIT license
- Fish-Speech  (https://github.com/fishaudio/fish-speech) — clean API with base64 audio
"""

import base64
import json
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import requests
from loguru import logger

from app.utils import file_security, utils

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ClonedVoice:
    """Metadata for a saved cloned voice."""

    voice_id: str
    name: str
    prompt_text: str
    prompt_lang: str = "zh"
    engine: str = "gpt_sovits"
    ref_audio_path: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "prompt_text": self.prompt_text,
            "prompt_lang": self.prompt_lang,
            "engine": self.engine,
            "ref_audio_path": self.ref_audio_path,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClonedVoice":
        return cls(
            voice_id=data.get("voice_id", ""),
            name=data.get("name", ""),
            prompt_text=data.get("prompt_text", ""),
            prompt_lang=data.get("prompt_lang", "zh"),
            engine=data.get("engine", "gpt_sovits"),
            ref_audio_path=data.get("ref_audio_path", ""),
            created_at=data.get("created_at", time.time()),
        )


# ---------------------------------------------------------------------------
# Abstract engine
# ---------------------------------------------------------------------------


class BaseVoiceCloneEngine(ABC):
    """Abstract interface for voice cloning backends."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        ref_audio_path: str,
        prompt_text: str,
        prompt_lang: str = "zh",
        text_lang: str = "zh",
        speed: float = 1.0,
    ) -> Optional[bytes]:
        """Generate speech audio in the cloned voice.

        Returns:
            Raw audio bytes (WAV format), or None on failure.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the engine is reachable."""


# ---------------------------------------------------------------------------
# GPT-SoVITS engine
# ---------------------------------------------------------------------------


class GPTSoVITSEngine(BaseVoiceCloneEngine):
    """Client for GPT-SoVITS API (https://github.com/RVC-Boss/GPT-SoVITS).

    GPT-SoVITS provides a REST API via api_v2.py:
        python api_v2.py -a 0.0.0.0 -p 9880

    Reference audio must exist on the server's filesystem.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:9880"):
        self.base_url = base_url.rstrip("/")

    def synthesize(
        self,
        text: str,
        ref_audio_path: str,
        prompt_text: str,
        prompt_lang: str = "zh",
        text_lang: str = "zh",
        speed: float = 1.0,
    ) -> Optional[bytes]:
        url = f"{self.base_url}/tts"
        payload = {
            "text": text,
            "text_lang": text_lang,
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "text_split_method": "cut5",
            "speed_factor": speed,
            "media_type": "wav",
            "streaming_mode": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 200:
                return resp.content
            logger.error(
                f"GPT-SoVITS returned {resp.status_code}: {resp.text[:500]}"
            )
        except requests.RequestException as exc:
            logger.error(f"GPT-SoVITS request failed: {exc}")
        return None

    def health_check(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/docs", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False


# ---------------------------------------------------------------------------
# Fish-Speech engine
# ---------------------------------------------------------------------------


class FishSpeechEngine(BaseVoiceCloneEngine):
    """Client for Fish-Speech API (https://github.com/fishaudio/fish-speech).

    Fish-Speech sends reference audio as base64 inside the JSON body,
    making it the most self-contained and integration-friendly option.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8080"):
        self.base_url = base_url.rstrip("/")

    def synthesize(
        self,
        text: str,
        ref_audio_path: str,
        prompt_text: str,
        prompt_lang: str = "zh",
        text_lang: str = "zh",
        speed: float = 1.0,
    ) -> Optional[bytes]:
        # Read and base64-encode reference audio
        try:
            with open(ref_audio_path, "rb") as f:
                ref_audio_bytes = f.read()
            ref_audio_b64 = base64.b64encode(ref_audio_bytes).decode("ascii")
        except (OSError, IOError) as exc:
            logger.error(f"Failed to read reference audio: {exc}")
            return None

        url = f"{self.base_url}/v1/tts"
        payload = {
            "text": text,
            "reference_audio": ref_audio_b64,
            "reference_text": prompt_text,
            "format": "wav",
            "streaming": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 200:
                return resp.content
            logger.error(
                f"Fish-Speech returned {resp.status_code}: {resp.text[:500]}"
            )
        except requests.RequestException as exc:
            logger.error(f"Fish-Speech request failed: {exc}")
        return None

    def health_check(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/v1/health", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False


# ---------------------------------------------------------------------------
# Voice manager — CRUD for saved cloned voices
# ---------------------------------------------------------------------------


class VoiceCloneManager:
    """Manages saved cloned voices on disk."""

    VOICE_CLONE_DIR_NAME = "voice_clone"
    METADATA_FILE = "metadata.json"
    REF_AUDIO_FILE = "reference.wav"

    def __init__(self):
        self._storage_dir: Optional[str] = None

    @property
    def storage_dir(self) -> str:
        if self._storage_dir is None:
            self._storage_dir = utils.storage_dir(
                self.VOICE_CLONE_DIR_NAME, create=True
            )
        return self._storage_dir

    def _voice_dir(self, voice_id: str) -> str:
        return os.path.join(self.storage_dir, voice_id)

    def _resolve_voice_path(self, voice_id: str) -> str:
        """Resolve a voice directory safely within the voice clone storage."""
        voice_dir = self._voice_dir(voice_id)
        try:
            return file_security.resolve_path_within_directory(
                self.storage_dir, voice_dir, require_file=False,
            )
        except ValueError:
            raise ValueError(f"invalid voice_id: {voice_id}")

    def save_voice(
        self,
        name: str,
        audio_bytes: bytes,
        prompt_text: str,
        prompt_lang: str = "zh",
        engine: str = "gpt_sovits",
    ) -> ClonedVoice:
        """Save a new cloned voice from uploaded audio bytes.

        Args:
            name: Human-readable name for this voice.
            audio_bytes: Raw audio data (WAV/MP3).
            prompt_text: Transcript of what the reference audio says.
            prompt_lang: Language of the reference audio.
            engine: Voice cloning engine name.

        Returns:
            ClonedVoice metadata.
        """
        voice_id = utils.get_uuid()
        voice_dir = self._voice_dir(voice_id)
        os.makedirs(voice_dir, exist_ok=True)

        # Save uploaded bytes to a temp file first, then convert to WAV via ffmpeg
        temp_input = os.path.join(voice_dir, "_upload_temp.bin")
        ref_audio_path = os.path.join(voice_dir, self.REF_AUDIO_FILE)

        try:
            with open(temp_input, "wb") as f:
                f.write(audio_bytes)

            ffmpeg_bin = _find_ffmpeg()
            # Convert any audio format to 16kHz mono WAV (required by most engines)
            result = subprocess.run(
                [
                    ffmpeg_bin, "-y",
                    "-i", temp_input,
                    "-ar", "16000",
                    "-ac", "1",
                    "-sample_fmt", "s16",
                    ref_audio_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise ValueError(
                    f"ffmpeg conversion failed: {result.stderr[:500]}"
                )
        finally:
            # Clean up temp file
            try:
                os.remove(temp_input)
            except OSError:
                pass

        voice = ClonedVoice(
            voice_id=voice_id,
            name=name,
            prompt_text=prompt_text,
            prompt_lang=prompt_lang,
            engine=engine,
            ref_audio_path=ref_audio_path,
        )
        self._write_metadata(voice)
        logger.info(f"Saved cloned voice: {voice_id} ({name})")
        return voice

    def get_voice(self, voice_id: str) -> Optional[ClonedVoice]:
        """Load a saved voice by ID."""
        voice_dir = self._resolve_voice_path(voice_id)
        meta_path = os.path.join(voice_dir, self.METADATA_FILE)
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            voice = ClonedVoice.from_dict(data)
            # Ensure ref_audio_path points to the actual file
            voice.ref_audio_path = os.path.join(voice_dir, self.REF_AUDIO_FILE)
            return voice
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Failed to load voice metadata: {exc}")
            return None

    def list_voices(self) -> list[ClonedVoice]:
        """List all saved cloned voices."""
        voices = []
        if not os.path.isdir(self.storage_dir):
            return voices
        for entry in sorted(os.listdir(self.storage_dir)):
            voice_dir = os.path.join(self.storage_dir, entry)
            meta_path = os.path.join(voice_dir, self.METADATA_FILE)
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    voice = ClonedVoice.from_dict(data)
                    voice.ref_audio_path = os.path.join(
                        voice_dir, self.REF_AUDIO_FILE
                    )
                    voices.append(voice)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        f"Failed to load voice metadata from {entry}: {exc}"
                    )
        # Sort by creation time, newest first
        voices.sort(key=lambda v: v.created_at, reverse=True)
        return voices

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a saved voice and its files."""
        voice_dir = self._resolve_voice_path(voice_id)
        if not os.path.isdir(voice_dir):
            return False
        import shutil

        shutil.rmtree(voice_dir)
        logger.info(f"Deleted cloned voice: {voice_id}")
        return True

    def _write_metadata(self, voice: ClonedVoice) -> None:
        voice_dir = self._voice_dir(voice.voice_id)
        os.makedirs(voice_dir, exist_ok=True)
        meta_path = os.path.join(voice_dir, self.METADATA_FILE)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(voice.to_dict(), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


_engine_cache: Optional[BaseVoiceCloneEngine] = None
_engine_type: str = ""


def get_voice_clone_engine() -> Optional[BaseVoiceCloneEngine]:
    """Get or create the configured voice clone engine instance."""
    global _engine_cache, _engine_type

    from app.config import config

    engine_name = config.app.get("voice_clone_engine", "").strip().lower()
    api_url = config.app.get("voice_clone_api_url", "").strip()

    if not engine_name or not api_url:
        return None

    # Reuse cached engine if config hasn't changed
    if _engine_cache is not None and _engine_type == engine_name:
        return _engine_cache

    if engine_name == "gpt_sovits":
        _engine_cache = GPTSoVITSEngine(base_url=api_url)
    elif engine_name == "fish_speech":
        _engine_cache = FishSpeechEngine(base_url=api_url)
    else:
        logger.warning(f"Unknown voice clone engine: {engine_name}")
        return None

    _engine_type = engine_name
    logger.info(f"Voice clone engine initialized: {engine_name} @ {api_url}")
    return _engine_cache


# ---------------------------------------------------------------------------
# Public helpers for the TTS pipeline
# ---------------------------------------------------------------------------

voice_clone_manager = VoiceCloneManager()


def is_voice_clone_voice(voice_name: str) -> bool:
    """Check if a voice name refers to a cloned voice.

    Cloned voice names are formatted as: clone:{voice_id}
    """
    return isinstance(voice_name, str) and voice_name.startswith("clone:")


def parse_voice_clone_id(voice_name: str) -> str:
    """Extract the voice_id from a clone voice name.

    Accepts both formats:
        clone:{voice_id}
        clone:{voice_id}-Female  (or -Male)
    """
    name = voice_name.replace("clone:", "", 1).strip()
    # Strip gender suffix if present (follows the same pattern as
    # parse_voice_name for Azure voices)
    name = name.replace("-Female", "").replace("-Male", "").strip()
    return name


def get_voice_clone_voice_names() -> list[str]:
    """Get display-formatted names for all saved cloned voices.

    Format: clone:{voice_id} (for the internal dropdown value)
            clone:{voice_id}-Female or clone:{voice_id}-Male (for display)
    """
    voices = voice_clone_manager.list_voices()
    result = []
    for v in voices:
        result.append(f"clone:{v.voice_id}")
    return result


def synthesize_cloned_voice(
    text: str,
    voice_id: str,
    voice_file: str,
    speed: float = 1.0,
) -> Optional[bytes]:
    """Generate TTS audio using a cloned voice.

    Args:
        text: Target text to synthesize.
        voice_id: ID of the saved cloned voice.
        voice_file: Path to save the output audio.
        speed: Playback speed factor.

    Returns:
        Audio bytes on success, None on failure.
    """
    engine = get_voice_clone_engine()
    if engine is None:
        logger.error(
            "Voice clone engine is not configured. "
            "Set 'voice_clone_engine' and 'voice_clone_api_url' in config.toml."
        )
        return None

    voice = voice_clone_manager.get_voice(voice_id)
    if voice is None:
        logger.error(f"Cloned voice not found: {voice_id}")
        return None

    # Detect language from the first few characters of the text
    text_lang = voice.prompt_lang or "zh"
    if text_lang == "auto":
        text_lang = _detect_text_lang(text)

    audio_bytes = engine.synthesize(
        text=text,
        ref_audio_path=voice.ref_audio_path,
        prompt_text=voice.prompt_text,
        prompt_lang=voice.prompt_lang,
        text_lang=text_lang,
        speed=speed,
    )

    if audio_bytes is None:
        return None

    # Ensure output directory exists
    os.makedirs(os.path.dirname(voice_file), exist_ok=True)

    # Convert WAV (from engine) to MP3 via ffmpeg for consistency
    output_dir = os.path.dirname(voice_file)
    temp_wav = os.path.join(output_dir, "_temp_clone_output.wav")
    try:
        with open(temp_wav, "wb") as f:
            f.write(audio_bytes)

        ffmpeg_bin = _find_ffmpeg()
        result = subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-i", temp_wav,
                "-codec:a", "libmp3lame",
                "-b:a", "192k",
                voice_file,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                f"ffmpeg MP3 conversion failed, saving as WAV: "
                f"{result.stderr[:300]}"
            )
            # Fallback: save original WAV
            wav_output = voice_file.rsplit(".", 1)[0] + ".wav"
            with open(wav_output, "wb") as f:
                f.write(audio_bytes)
    finally:
        try:
            os.remove(temp_wav)
        except OSError:
            pass

    return audio_bytes


def _find_ffmpeg() -> str:
    """Find the ffmpeg binary, following the same priority as video.py."""
    configured = os.environ.get("IMAGEIO_FFMPEG_EXE")
    if configured:
        return configured

    system_bin = shutil.which("ffmpeg")
    if system_bin:
        return system_bin

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled:
            return bundled
    except Exception:
        pass

    return "ffmpeg"


def _detect_text_lang(text: str) -> str:
    """Simple language detection for the first few characters."""
    for ch in text[:10]:
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            return "zh"
    return "en"
