"""Composición final con FFmpeg: voz, subtítulos, música y logotipo.

Los filtros se ejecutan con ``cwd`` en un directorio temporal y referencias
relativas, evitando que una letra de unidad o un apóstrofo del perfil de usuario
entre en el grafo de filtros.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from app.services.personal_studio.security import StudioError
from app.utils import utils

MUSIC_GAIN = 0.18
LOGO_RATIO = 0.14


def _timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    seconds_int, fraction = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{seconds_int:02d}.{fraction:02d}"


def _clean(value: str) -> str:
    return " ".join(str(value).split()).replace("{", "(").replace("}", ")")


def ass_document(
    events: Iterable[tuple[str, float]],
    *,
    width: int,
    height: int,
    font: str = "Arial",
    font_size: int | None = None,
) -> str:
    size = font_size or max(20, int(round(height * 0.032)))
    margin = max(10, height // 16)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,"
        f"1,0,0,0,100,100,0,0,1,3,1,2,80,80,{margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    start = 0.0
    for text, duration in events:
        text = _clean(text)
        if not text:
            start += float(duration)
            continue
        end = start + max(0.15, float(duration))
        lines.append(
            f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Default,,0,0,0,,{text}"
        )
        start = end
    return "\n".join(lines) + "\n"


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds_int, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{millis:03d}"


def srt_document(events: Iterable[tuple[str, float]]) -> str:
    blocks = []
    start = 0.0
    index = 1
    for text, duration in events:
        text = _clean(text)
        if not text:
            start += float(duration)
            continue
        end = start + max(0.15, float(duration))
        blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
        start = end
        index += 1
    return "\n".join(blocks)


def write_subtitles(events: list[tuple[str, float]], destination: Path, *, width: int, height: int) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".srt":
        destination.write_text(srt_document(events), encoding="utf-8")
    else:
        destination.write_text(
            ass_document(events, width=width, height=height), encoding="utf-8"
        )
    return destination


def _logo_position(expression: str, ratio: float) -> str:
    return {
        "br": "W-w-24:H-h-24",
        "bl": "24:H-h-24",
        "tr": "W-w-24:24",
        "tl": "24:24",
    }.get(expression, "W-w-24:H-h-24")


def finalize(
    video: Path,
    narration: Path,
    destination: Path,
    *,
    events: list[tuple[str, float]] | None = None,
    music: Path | None = None,
    logo: Path | None = None,
    logo_position: str = "br",
    width: int = 1080,
    height: int = 1920,
    crf: int = 20,
    preset: str = "veryfast",
    music_gain: float = MUSIC_GAIN,
) -> Path:
    """Mux final: añade voz, subtítulos quemados, música y logotipo."""
    video, narration, destination = Path(video), Path(narration), Path(destination)
    for required in (video, narration):
        if not required.is_file():
            raise StudioError(f"Falta un archivo para la composición: {required.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    burn = bool(events)
    overlay = bool(logo and Path(logo).is_file())
    mix = bool(music and Path(music).is_file())

    with tempfile.TemporaryDirectory(prefix=".compose-", dir=destination.parent) as temp_dir:
        temp = Path(temp_dir)
        shutil.copyfile(video, temp / "input.mp4")
        shutil.copyfile(narration, temp / "narration.wav")
        arguments = [utils.get_ffmpeg_binary(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        arguments += ["-i", "input.mp4", "-i", "narration.wav"]
        filters: list[str] = []
        video_label = "[0:v]"
        index = 2
        music_index = None
        if mix:
            arguments += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
            music_index = index
            index += 1
        logo_index = None
        if overlay:
            shutil.copyfile(Path(logo), temp / "logo.png")
            arguments += ["-i", "logo.png"]
            logo_index = index
            index += 1

        if burn:
            assert events is not None
            (temp / "subtitles.ass").write_text(
                ass_document(events, width=width, height=height), encoding="utf-8"
            )
            filters.append("[0:v]ass=subtitles.ass[vsub]")
            video_label = "[vsub]"

        if overlay and logo_index is not None:
            logo_width = max(48, int(width * LOGO_RATIO))
            filters.append(
                f"[{logo_index}:v]scale={logo_width}:-1[lg]"
            )
            filters.append(
                f"{video_label}[lg]overlay={_logo_position(logo_position, logo_width)}:format=auto[vout]"
            )
            video_label = "[vout]"

        if music_index is not None:
            filters.append(f"[{music_index}:a]volume={music_gain:.3f}[bg]")
            filters.append(
                "[1:a][bg]amix=inputs=2:duration=first:normalize=0[aout]"
            )
            audio_label = "[aout]"
        else:
            audio_label = "1:a"

        if burn or overlay or mix:
            arguments += ["-filter_complex", ";".join(filters)]
            arguments += ["-map", video_label, "-map", audio_label]
            arguments += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
        else:
            arguments += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
        arguments += [
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            "result.mp4",
        ]
        try:
            result = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=temp,
                timeout=1800,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StudioError(f"FFmpeg no pudo componer el video: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()
            raise StudioError(
                "FFmpeg falló al componer: "
                + (detail[-1][:300] if detail else f"código {result.returncode}")
            )
        produced = temp / "result.mp4"
        if not produced.is_file() or produced.stat().st_size == 0:
            raise StudioError("La composición no generó un video")
        shutil.copyfile(produced, destination)
    return destination


def extract_audio(video: Path, destination: Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            utils.get_ffmpeg_binary(),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vn",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        raise StudioError("No se pudo extraer el audio del video")
    return destination
