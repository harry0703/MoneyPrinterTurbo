"""Motion Studio voice: one track with exact word and beat times.

Edge TTS (free): one call per beat, joined, so every beat's start time is known exactly.
OpenAI (uses the creator's OpenAI key): the whole script in one directed take, which sounds far more
natural, then a transcription pass gives word times that are matched back to the script's words.
The same samples give the per-frame loudness the host's mouth follows.
"""

import asyncio
import difflib
import io
import json
import re
import subprocess
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import numpy as np
import openai
from imageio_ffmpeg import get_ffmpeg_exe

from app.services.motion.errors import MotionError

SAMPLE_RATE = 24000  # Edge TTS output rate; divisible by FPS so loudness windows match frames
FPS = 30
TICKS_PER_SECOND = 10_000_000  # Edge TTS offsets are in 100 ns units
BEAT_GAP_S = 0.18  # breath between beats
HOLD_S = 0.8  # silence after the last word, while the last frame stays on screen
RATE = "+15%"  # brisk Shorts pace
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
OPENAI_TIMING_MODEL = "whisper-1"  # returns word timestamps
OPENAI_TIMEOUT_S = 120
OPENAI_INSTRUCTIONS = (
    "You are a friendly YouTube Shorts host explaining something useful to young viewers. Speak natural, "
    "conversational {language}, and say English words the way local speakers do. Warm and energetic but not "
    "shouting, a quick Shorts pace, real pauses at commas and full stops, like talking to a friend."
)
LEAD_S = 0.12  # a scene appears just before its first word
PHRASE_END = (",", "?", "।", "!", ".", ":", ";", "，", "。", "？", "！")
EDGE_PUNCT = "\"'“”‘’()[]{}.,!?;:…।॥—–，。？！"  # stripped from the ends of caption words

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
    # OpenAI voices reuse the script writer's OpenAI key (provider must be OpenAI).
    {"id": "openai-marin-hi", "label": "Hindi, Marin (OpenAI, most natural; uses your OpenAI key)", "language": "Hindi",
     "openai": "marin", "lang": "hi"},
    {"id": "openai-cedar-hi", "label": "Hindi, Cedar (OpenAI; uses your OpenAI key)", "language": "Hindi",
     "openai": "cedar", "lang": "hi"},
    {"id": "openai-marin-en", "label": "English, Marin (OpenAI, most natural; uses your OpenAI key)", "language": "English",
     "openai": "marin", "lang": "en"},
    {"id": "openai-cedar-en", "label": "English, Cedar (OpenAI; uses your OpenAI key)", "language": "English",
     "openai": "cedar", "lang": "en"},
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


def join_glued(words: list[dict], text: str) -> list[dict]:
    """Merge spoken tokens the script writes without a space between them.

    Edge TTS splits "cybercrime.gov.in" into five tokens; the caption should show it as one word.
    Tokens that can't be found in the script are kept as they are.
    """
    out, pos, glued_at = [], 0, None
    for w in words:
        at = text.find(w["text"], pos)
        if at < 0:
            out.append(dict(w))
            glued_at = None
            continue
        if out and at == glued_at:
            out[-1] = {**out[-1], "text": out[-1]["text"] + w["text"], "end": w["end"]}
        else:
            out.append(dict(w))
        pos = glued_at = at + len(w["text"])
    return out


def mark_breaks(words: list[dict], text: str) -> None:
    """Flag words that end a caption phrase (followed by , ? । ! . in the script).

    Only applied when script tokens line up 1:1 with spoken words; the beat's last word always breaks.
    """
    tokens = text.split()
    if len(tokens) == len(words) and all(w["text"] in tok for w, tok in zip(words, tokens)):
        for w, tok in zip(words, tokens):
            w["br"] = _ends_phrase(tok)
    if words:
        words[-1]["br"] = True


def _ends_phrase(token: str) -> bool:
    return token.rstrip("\"'”’").endswith(PHRASE_END)


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


def _edge_take(texts: list[str], voice: str) -> tuple[np.ndarray, list[dict], list[tuple[float, float]]]:
    """Speak each beat with Edge TTS and join them with a short breath."""
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
        beat_words = join_glued(beat_words, text)
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
    return np.concatenate(parts), words, beats


def _key(text: str) -> str:
    """Comparison form of a word: case, nukta and punctuation don't count (आवाज़ = आवाज)."""
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFC", text).casefold().replace("़", ""))


def _script_tokens(texts: list[str]) -> list[dict]:
    """Every written word with its beat, its caption text and whether a caption phrase ends after it."""
    out = []
    for beat, text in enumerate(texts):
        first = len(out)
        for token in text.split():
            shown = token.strip(EDGE_PUNCT)
            if shown:
                out.append({"beat": beat, "text": shown, "br": _ends_phrase(token)})
            elif len(out) > first and _ends_phrase(token):  # a lone "..." after a word
                out[-1]["br"] = True
        if len(out) > first:
            out[-1]["br"] = True
    return out


def _spread(tokens: list[dict], times: list, i1: int, i2: int, lo: float, hi: float) -> None:
    """Share lo..hi among tokens[i1:i2] in proportion to their length."""
    weights = [max(len(t["text"]), 1) for t in tokens[i1:i2]]
    total, at = sum(weights), lo
    for k, weight in enumerate(weights):
        end = at + (hi - lo) * weight / total
        times[i1 + k] = (at, end)
        at = end


def align(texts: list[str], heard: list[tuple[str, float, float]], total: float) -> tuple[list[dict], list[tuple[float, float]]]:
    """Time every written word from the transcribed audio; returns the words and each beat's (start, end).

    The transcript spells some words differently from the script (आवाज़/आवाज, call/कौल). Matching words take
    the transcript's times, differing runs share their transcript span, and the rest share the gap between
    timed neighbours. Captions always show the script's own spelling.
    """
    tokens = _script_tokens(texts)
    times: list = [None] * len(tokens)
    matcher = difflib.SequenceMatcher(None, [_key(t["text"]) for t in tokens], [_key(h[0]) for h in heard], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                times[i1 + k] = heard[j1 + k][1:]
        elif tag == "replace":
            _spread(tokens, times, i1, i2, heard[j1][1], heard[j2 - 1][2])
    i = 0
    while i < len(tokens):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(tokens) and times[j] is None:
            j += 1
        lo = times[i - 1][1] if i else 0.0
        _spread(tokens, times, i, j, lo, max(times[j][0] if j < len(tokens) else total, lo))
        i = j
    words = [{"text": t["text"], "start": round(s, 3), "end": round(e, 3), "br": t["br"]} for t, (s, e) in zip(tokens, times)]
    starts, last_end = [], 0.0
    for beat in range(len(texts)):
        mine = [w for w, t in zip(words, tokens) if t["beat"] == beat]
        starts.append(0.0 if beat == 0 else max(last_end, mine[0]["start"] - LEAD_S) if mine else last_end)
        last_end = mine[-1]["end"] if mine else last_end
    ends = starts[1:] + [round(max(total, last_end), 3)]
    return words, [(round(s, 3), round(e, 3)) for s, e in zip(starts, ends)]


def _wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


def _openai_take(texts: list[str], voice: dict, api_key: str | None) -> tuple[np.ndarray, list[dict], list[tuple[float, float]]]:
    """The whole script in one directed OpenAI take, timed by a transcription pass."""
    if not api_key:
        raise MotionError("OpenAI voices use your OpenAI API key. Choose OpenAI as the provider and paste your key.")
    client = openai.OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_S, max_retries=1)  # never the server's env key
    try:
        pcm = client.audio.speech.create(
            model=OPENAI_TTS_MODEL, voice=voice["openai"], input=" ".join(texts), response_format="pcm",
            instructions=OPENAI_INSTRUCTIONS.format(language=voice["language"]),
        ).content
        heard = client.audio.transcriptions.create(
            model=OPENAI_TIMING_MODEL, file=("voice.wav", _wav(pcm), "audio/wav"), language=voice["lang"],
            response_format="verbose_json", timestamp_granularities=["word"],
        ).words or []
    except openai.AuthenticationError:
        raise MotionError("OpenAI rejected the API key.") from None
    except openai.PermissionDeniedError:
        raise MotionError(f"This OpenAI key can't use the voice models ({OPENAI_TTS_MODEL}, {OPENAI_TIMING_MODEL}).") from None
    except openai.RateLimitError:
        raise MotionError("OpenAI's rate limit or quota is reached. Check your plan and try again.") from None
    except openai.APIConnectionError:
        raise MotionError("Couldn't reach OpenAI. Check your internet connection and try again.") from None
    except openai.APIError:
        raise MotionError("OpenAI's voice service failed. Try again in a minute.") from None
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], np.int16)  # 24 kHz 16-bit mono
    if not len(samples):
        raise MotionError("OpenAI returned no audio. Try again in a minute.")
    words, beats = align(texts, [(w.word, w.start, w.end) for w in heard], len(samples) / SAMPLE_RATE)
    return samples, words, beats


def synthesize(texts: list[str], voice: str, out_dir: Path, api_key: str | None = None) -> Speech:
    """Speak the beats and write audio.m4a, words.json and env.json into out_dir.

    api_key is only used by OpenAI voices, for this one take, and is never stored.
    """
    if voice not in VOICE_BY_ID:
        raise MotionError(f"Unknown voice: {voice}")
    entry = VOICE_BY_ID[voice]
    samples, words, beats = _openai_take(texts, entry, api_key) if entry.get("openai") else _edge_take(texts, voice)
    audio = np.concatenate([samples, np.zeros(int(HOLD_S * SAMPLE_RATE), np.int16)])
    subprocess.run(
        [get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-c:a", "aac", "-b:a", "160k", str(out_dir / "audio.m4a")],
        input=audio.tobytes(), check=True,
    )
    (out_dir / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (out_dir / "env.json").write_text(json.dumps(envelope(audio)), encoding="utf-8")
    return Speech(words=words, beats=beats, duration=round(len(audio) / SAMPLE_RATE, 3))
