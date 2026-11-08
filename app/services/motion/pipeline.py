"""Motion Studio pipeline steps shared by background jobs and the smoke script."""

import json
import shutil
from pathlib import Path

from app.models.motion import Storyboard
from app.services.motion import speech
from app.services.motion.speech import Speech

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def scene_storyboard(storyboard: Storyboard, voice: Speech, character: dict) -> dict:
    """The engine's storyboard: every beat gets its voice start/end and the time of its emphasis word."""
    beats = []
    for beat, (start, end) in zip(storyboard.beats, voice.beats):
        words = [w for w in voice.words if start - 0.01 <= w["start"] < end + 0.01]
        data = beat.model_dump(exclude={"say"}, exclude_none=True)
        data.update(start=start, end=end, emph=speech.emphasis_time(words, beat.emphasis))
        beats.append(data)
    return {"character": character, "beats": beats, "duration": voice.duration}


def prepare(job_dir: Path, storyboard: Storyboard, voice_id: str, character_file: Path | None) -> Speech:
    """Record the voice and lay out everything the renderer needs inside job_dir."""
    character = {"kind": "none"}
    if character_file is not None:
        target = job_dir / f"character{character_file.suffix.lower()}"
        shutil.copyfile(character_file, target)
        kind = "image" if target.suffix in IMAGE_SUFFIXES else "glb"
        character = {"kind": kind, "url": f"/job/{target.name}"}
    voice = speech.synthesize([beat.say for beat in storyboard.beats], voice_id, job_dir)
    scene = scene_storyboard(storyboard, voice, character)
    (job_dir / "storyboard.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
    return voice
