"""Trim long TTS silence gaps between sentences and shift subtitles.

Root cause: Edge TTS leaves ~1.2s of silence after each period; with
short-sentence scripts a 39s video can contain ~6s of dead air
("talks, waits, continues" feeling).

Method: gaps between subtitle cues are pure silence (TTS). The excess
above the threshold is cut from the audio, and all later cue timestamps
are shifted back by the same amount — sync is preserved. On any error
the original files are left untouched and the pipeline continues as-is.
"""

import os
import re
from contextlib import ExitStack

from loguru import logger

# Inter-cue gaps longer than this are trimmed (seconds).
MAX_GAP_SECONDS = 0.6
# This much silence is kept from a trimmed gap (natural breath, seconds).
KEEP_GAP_SECONDS = 0.3


def _srt_to_seconds(stamp: str) -> float:
    m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", str(stamp or "").strip())
    if not m:
        raise ValueError(f"bad srt timestamp: {stamp!r}")
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def _seconds_to_srt(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        ms -= 1000
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def plan_cuts(subtitle_path: str) -> list[tuple[float, float]]:
    """Compute (cut_start, cut_end) ranges to remove. Pure function."""
    from app.services import subtitle as subtitle_service

    cues = subtitle_service.file_to_subtitles(subtitle_path)
    if len(cues) < 2:
        return []
    times: list[tuple[float, float]] = []
    for _idx, timerange, _text in cues:
        try:
            parts = str(timerange).split("-->")
            times.append((_srt_to_seconds(parts[0]), _srt_to_seconds(parts[1])))
        except Exception:
            return []
    cuts: list[tuple[float, float]] = []
    for (_ps, pe), (ns, _ne) in zip(times, times[1:]):
        gap = ns - pe
        if gap > MAX_GAP_SECONDS:
            cuts.append((pe + KEEP_GAP_SECONDS, ns))
    return [(s, e) for s, e in cuts if e > s]


def shift_cues(subtitle_path: str, cuts: list[tuple[float, float]]) -> list[tuple[int, str, str]]:
    """Return cue timestamps shifted as if the cuts were applied."""
    from app.services import subtitle as subtitle_service

    cues = subtitle_service.file_to_subtitles(subtitle_path)

    def shifted(t: float) -> float:
        off = 0.0
        for cs, ce in cuts:
            if t >= ce:
                off += ce - cs
            elif t > cs:
                off += t - cs
        return t - off

    out = []
    for idx, timerange, text in cues:
        parts = str(timerange).split("-->")
        s = _seconds_to_srt(shifted(_srt_to_seconds(parts[0])))
        e = _seconds_to_srt(shifted(_srt_to_seconds(parts[1])))
        out.append((idx, f"{s} --> {e}", text))
    return out


def trim_silences(audio_file: str, subtitle_path: str) -> tuple[str, float] | tuple[None, None]:
    """Trim silences and shift the SRT. Returns (audio_path, duration).

    On success the trimmed audio + updated SRT are in place. On any
    problem returns (None, None) — the caller continues with the original.
    """
    try:
        if not audio_file or not os.path.exists(audio_file):
            return (None, None)
        if not subtitle_path or not os.path.exists(subtitle_path):
            return (None, None)
        cuts = plan_cuts(subtitle_path)
        if not cuts:
            return (None, None)

        from moviepy import AudioFileClip, concatenate_audioclips

        with ExitStack() as stack:
            clip = stack.enter_context(AudioFileClip(audio_file))
            total = float(clip.duration or 0)
            if total <= 0:
                return (None, None)
            # Kept segments: [0, cut1_s], [cut1_e, cut2_s], ..., [cutN_e, total]
            bounds = [0.0]
            for cs, ce in cuts:
                bounds += [cs, ce]
            bounds.append(total)
            segments = []
            for s, e in zip(bounds[::2], bounds[1::2]):
                s = max(0.0, min(s, total))
                e = max(0.0, min(e, total))
                if e - s > 0.05:
                    segments.append(clip.subclipped(s, e))
            if not segments:
                return (None, None)
            joined = concatenate_audioclips(segments)
            tmp_audio = audio_file + ".trimmed.mp3"
            joined.write_audiofile(tmp_audio, logger=None)
            duration = float(joined.duration or 0)
            try:
                joined.close()
            except Exception:
                pass

        if not duration or not os.path.exists(tmp_audio):
            return (None, None)
        os.replace(tmp_audio, audio_file)

        shifted = shift_cues(subtitle_path, cuts)
        with open(subtitle_path, "w", encoding="utf-8") as f:
            for i, timerange, text in shifted:
                f.write(f"{i}\n{timerange}\n{text.strip()}\n\n")

        saved = sum(ce - cs for cs, ce in cuts)
        logger.info(
            f"silence trimmed: cuts={len(cuts)}, saved={saved:.2f}s, "
            f"new_duration={duration:.2f}s"
        )
        return (audio_file, duration)
    except Exception as e:
        logger.warning(f"silence trim failed, keeping original: {type(e).__name__}: {e}")
        try:
            tmp = (audio_file or "") + ".trimmed.mp3"
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return (None, None)
