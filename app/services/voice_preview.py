import os
import shutil
import time
from uuid import uuid4

from app.services import voice
from app.utils import utils


MAX_PREVIEW_TEXT_LENGTH = 500


def generate_preview_audio(
    preview_text: str,
    voice_name: str,
    voice_rate: float,
    voice_volume: float,
) -> str:
    sample_text = (preview_text or "").strip()
    if not sample_text:
        raise ValueError("Write a preview text before generating the voice sample.")
    if len(sample_text) > MAX_PREVIEW_TEXT_LENGTH:
        raise ValueError("Preview text cannot exceed 500 characters.")

    cleanup_voice_previews()
    preview_id = uuid4().hex[:10]
    preview_dir = utils.storage_dir(os.path.join("temp", "voice_previews", preview_id), create=True)
    audio_file = os.path.join(preview_dir, "preview.mp3")

    sub_maker = voice.tts(
        text=sample_text,
        voice_name=voice_name,
        voice_rate=voice_rate,
        voice_file=audio_file,
        voice_volume=voice_volume,
    )
    if sub_maker is None or not os.path.exists(audio_file):
        raise RuntimeError("Voice preview synthesis failed.")

    cleanup_voice_previews()
    return audio_file


def cleanup_voice_previews(max_age_seconds: int = 1800) -> None:
    previews_root = utils.storage_dir(os.path.join("temp", "voice_previews"), create=True)
    now = time.time()
    for entry in os.listdir(previews_root):
        candidate = os.path.join(previews_root, entry)
        if not os.path.isdir(candidate):
            continue
        age_seconds = max(0, int(now - os.path.getmtime(candidate)))
        if age_seconds > max_age_seconds:
            shutil.rmtree(candidate, ignore_errors=True)