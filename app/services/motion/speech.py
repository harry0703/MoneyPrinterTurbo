"""Motion Studio voice: one Edge TTS call per beat, joined into one track with exact beat times.

Per-beat synthesis means every beat's start time is known exactly, so visuals never drift from the
voice. The same decoded samples give the per-frame loudness the host's mouth follows.
"""

import asyncio
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import numpy as np
from imageio_ffmpeg import get_ffmpeg_exe

from app.services.motion.errors import MotionError

SAMPLE_RATE = 24000  # Edge TTS output rate; divisible by FPS so loudness windows match frames
FPS = 30
TICKS_PER_SECOND = 10_000_000  # Edge TTS offsets are in 100 ns units
BEAT_GAP_S = 0.18  # breath between beats
HOLD_S = 0.8  # silence after the last word, while the last frame stays on screen
RATE = "+15%"  # brisk Shorts pace

# Voices whose script the engine fonts cover (Baloo 2: Latin + Devanagari; CJK uses system fonts).
VOICES = [
    {"id": "hi-IN-MadhurNeural", "label": "Hindi, Madhur (male)", "language": "Hindi"},
    {"id": "hi-IN-SwaraNeural", "label": "Hindi, Swara (female)", "language": "Hindi"},
    {"id": "en-IN-PrabhatNeural", "label": "English (India), Prabhat (male)", "language": "English"},
    {"id": "en-IN-NeerjaNeural", "label": "English (India), Neerja (female)", "language": "English"},
    {"id": "en-US-AndrewNeural", "label": "English (US), Andrew (male)", "language": "English"},
    {"id": "en-US-AvaNeural", "label": "English (US), Ava (female)", "language": "English"},
    {"id": "mr-IN-ManoharNeural", "label": "Marathi, Manohar (male)", "language": "Marathi"},
    {"id": "zh-CN-YunxiNeural", "label": "Chinese, Yunxi (male)", "language": "Simplified Chinese"},
    {"id": "zh-CN-XiaoxiaoNeural", "label": "Chinese, Xiaoxiao (female)", "language": "Simplified Chinese"},
    {"id": "es-ES-AlvaroNeural", "label": "Spanish, Alvaro (male)", "language": "Spanish"},
    {"id": "pt-BR-FranciscaNeural", "label": "Portuguese (Brazil), Francisca (female)", "language": "Brazilian Portuguese"},
]
VOICE_BY_ID = {voice["id"]: voice for voice in VOICES}


@dataclass(frozen=True)
class Speech:
    words: list[dict]  # [{"text", "start", "end", "br"?}], seconds
    beats: list[tuple[float, float]]  # (start, end) of each beat's voice
    duration: float  # end of the audio file, including the hold


async def _synthesize(text: str, voice: str) -> tuple[bytes, list[dict]]:
    audio, words = bytearray(), []
    stream = edge_tts.Communicate(text, voice, rate=RATE, boundary="WordBoundary").stream()
    async for chunk in stream:
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start = chunk["offset"] / TICKS_PER_SECOND
            words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / TICKS_PER_SECOND})
    if not audio or not words:
        raise MotionError("The voice service returned no audio. Try again in a minute.")
    return bytes(audio), words


def _decode(mp3: bytes) -> np.ndarray:
    pcm = subprocess.run(
        [get_ffmpeg_exe(), "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
        input=mp3, capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, np.int16)


def mark_breaks(words: list[dict], text: str) -> None:
    """Flag words that end a caption phrase (followed by , ? । ! . in the script).

    Only applied when script tokens line up 1:1 with spoken words; the beat's last word always breaks.
    """
    tokens = text.split()
    if len(tokens) == len(words) and all(w["text"] in tok for w, tok in zip(words, tokens)):
        for w, tok in zip(words, tokens):
            w["br"] = tok.rstrip("\"'”’").endswith((",", "?", "।", "!", ".", ":", ";", "，", "。", "？", "！"))
    if words:
        words[-1]["br"] = True


def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFC", s).casefold())


def emphasis_time(words: list[dict], emphasis: str | None) -> float | None:
    """Start of the first spoken word matching the beat's emphasis word, if any."""
    key = _norm((emphasis or "").split()[0]) if (emphasis or "").split() else ""
    if not key:
        return None
    for w in words:
        spoken = _norm(w["text"])
        if spoken and (spoken == key or key in spoken or spoken in key and len(spoken) > 2):
            return w["start"]
    return None


def envelope(samples: np.ndarray) -> list[float]:
    """Voice loudness (RMS) per video frame, scaled so normal speech peaks near 1."""
    x = samples.astype(np.float32) / 32768
    hop = SAMPLE_RATE // FPS
    n = len(x) // hop
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    return (rms / max(float(np.percentile(rms, 95)), 1e-6)).clip(0, 1).round(3).tolist()


def synthesize(texts: list[str], voice: str, out_dir: Path) -> Speech:
    """Speak each beat, join them, and write audio.m4a, words.json and env.json into out_dir."""
    if voice not in VOICE_BY_ID:
        raise MotionError(f"Unknown voice: {voice}")
    words, beats, parts, cursor = [], [], [], 0
    gap = np.zeros(int(BEAT_GAP_S * SAMPLE_RATE), np.int16)
    for i, text in enumerate(texts):
        try:
            mp3, beat_words = asyncio.run(_synthesize(text, voice))
        except MotionError:
            raise
        except Exception as error:  # network, service or codec failure
            raise MotionError("Couldn't reach the voice service (Edge TTS). Check your internet connection and try again.") from error
        samples = _decode(mp3)
        offset = cursor / SAMPLE_RATE
        for w in beat_words:
            w["start"] = round(w["start"] + offset, 3)
            w["end"] = round(w["end"] + offset, 3)
        mark_breaks(beat_words, text)
        words.extend(beat_words)
        beats.append((round(offset, 3), round(offset + len(samples) / SAMPLE_RATE, 3)))
        parts.append(samples)
        cursor += len(samples)
        if i < len(texts) - 1:
            parts.append(gap)
            cursor += len(gap)
    parts.append(np.zeros(int(HOLD_S * SAMPLE_RATE), np.int16))
    audio = np.concatenate(parts)
    subprocess.run(
        [get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-c:a", "aac", "-b:a", "160k", str(out_dir / "audio.m4a")],
        input=audio.tobytes(), check=True,
    )
    (out_dir / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (out_dir / "env.json").write_text(json.dumps(envelope(audio)), encoding="utf-8")
    return Speech(words=words, beats=beats, duration=round(len(audio) / SAMPLE_RATE, 3))
