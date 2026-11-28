"""Análisis y procesado de audio local con FFmpeg.

El módulo no usa numpy ni librosa: decodifica PCM con FFmpeg y recorre la señal
en Python. A 16 kHz y ventanas de 50 ms una muestra de un minuto se analiza en
menos de un segundo, suficiente para el panel.

Ningún dato sale del equipo: todas las funciones leen y escriben rutas locales.
"""

from __future__ import annotations

import array
import math
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from app.services.personal_studio.security import StudioError
from app.utils import utils

SUPPORTED_EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac")
MAX_SAMPLE_BYTES = 200 * 1024 * 1024
MAX_SAMPLE_SECONDS = 120.0
ANALYSIS_RATE = 16000
WINDOW_SECONDS = 0.05


class AudioError(StudioError):
    """El archivo no es audio válido o FFmpeg falló."""


def ffmpeg(args: list[str], *, timeout: float = 900, cwd: str | None = None) -> None:
    command = [
        utils.get_ffmpeg_binary(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"No se pudo ejecutar FFmpeg: {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip().splitlines()
        detail = message[-1] if message else f"código {result.returncode}"
        raise AudioError(f"FFmpeg falló: {detail[:300]}")


def ffprobe_duration(path: Path) -> float:
    """Duración en segundos; 0.0 si no se puede determinar."""
    binary = Path(utils.get_ffmpeg_binary())
    probe = binary.with_name("ffprobe" + binary.suffix)
    candidates = [str(probe)] if probe.exists() else []
    candidates.append("ffprobe")
    for candidate in candidates:
        try:
            result = subprocess.run(
                [
                    candidate,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            try:
                value = float((result.stdout or "").strip())
            except ValueError:
                continue
            if math.isfinite(value) and value > 0:
                return value
    return 0.0


def decode_pcm(path: Path, sample_rate: int = ANALYSIS_RATE) -> array.array:
    source = Path(path)
    if not source.is_file():
        raise AudioError(f"No existe el audio: {source.name}")
    command = [
        utils.get_ffmpeg_binary(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"No se pudo decodificar el audio: {exc}") from exc
    if result.returncode != 0:
        raise AudioError(
            "No se pudo decodificar el audio: "
            + (result.stderr.decode("utf-8", "replace").strip()[-300:] or "archivo inválido")
        )
    payload = result.stdout
    if len(payload) % 2:
        payload = payload[:-1]
    samples = array.array("h")
    samples.frombytes(payload)
    if not samples:
        raise AudioError("El audio no contiene muestras")
    return samples


def _dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(min(1.0, value / 32768.0))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def analyze(path: Path, *, sample_rate: int = ANALYSIS_RATE) -> dict:
    """Mide duración, nivel, ruido, silencios y recorte, con una nota 0-100."""
    samples = decode_pcm(path, sample_rate)
    duration = len(samples) / float(sample_rate)
    window = max(1, int(sample_rate * WINDOW_SECONDS))
    energies: list[float] = []
    peak = 0
    clipped = 0
    total_abs = 0
    for start in range(0, len(samples), window):
        chunk = samples[start : start + window]
        if not chunk:
            continue
        energy = 0.0
        for value in chunk:
            absolute = value if value >= 0 else -value
            if absolute > peak:
                peak = absolute
            if absolute >= 32760:
                clipped += 1
            total_abs += absolute
            energy += value * value
        energies.append(math.sqrt(energy / len(chunk)))

    speech_rms = _percentile(energies, 0.9)
    noise_floor = _percentile(energies, 0.1)
    speech_dbfs = _dbfs(speech_rms)
    noise_dbfs = _dbfs(noise_floor)
    snr = speech_dbfs - noise_dbfs if speech_rms > 0 else 0.0
    silence_ratio = (
        sum(1 for value in energies if _dbfs(value) < -45.0) / len(energies)
        if energies
        else 1.0
    )
    clipping_ratio = clipped / float(len(samples)) if samples else 0.0
    dc_offset = total_abs / float(len(samples)) / 32768.0
    peak_dbfs = _dbfs(peak)

    issues: list[str] = []
    if duration < 6.0:
        issues.append("La muestra dura menos de 6 segundos: la clonación pierde timbre.")
    if peak_dbfs > -1.0:
        issues.append("El audio está cerca del límite: puede saturar. Baja la ganancia.")
    if clipping_ratio > 0.001:
        issues.append("Hay recorte digital (saturación). Graba de nuevo con menos volumen.")
    if snr < 12.0:
        issues.append("La relación señal/ruido es baja: se oye ruido de fondo.")
    if noise_dbfs > -40.0:
        issues.append("El ruido de fondo es alto. Busca un lugar silencioso.")
    if speech_dbfs < -30.0:
        issues.append("La voz está muy baja. Acércate al micrófono.")
    if silence_ratio > 0.6:
        issues.append("Hay demasiado silencio: recorta o graba de nuevo.")
    if duration > MAX_SAMPLE_SECONDS:
        issues.append("La muestra supera los 120 s y se recortará.")

    score = 0.0
    score += 15.0 * min(1.0, duration / 20.0)
    score += 35.0 * max(0.0, min(1.0, (snr - 5.0) / 30.0))
    score += 15.0 * max(0.0, min(1.0, (-45.0 - noise_dbfs) / 20.0))
    score += 15.0 * max(0.0, 1.0 - clipping_ratio / 0.001)
    score += 10.0 * max(0.0, 1.0 - abs(speech_dbfs + 18.0) / 18.0)
    score += 10.0 * max(0.0, 1.0 - silence_ratio)
    if clipping_ratio > 0.001:
        score -= 10.0
    score = max(0.0, min(100.0, score))
    verdict = "buena" if score >= 75 else "aceptable" if score >= 50 else "deficiente"

    return {
        "duration": round(duration, 3),
        "sample_rate": sample_rate,
        "peak_dbfs": round(peak_dbfs, 1),
        "speech_dbfs": round(speech_dbfs, 1),
        "noise_floor_dbfs": round(noise_dbfs, 1),
        "snr_db": round(snr, 1),
        "silence_ratio": round(silence_ratio, 3),
        "clipping_ratio": round(clipping_ratio, 6),
        "dc_offset": round(dc_offset, 4),
        "score": round(score, 1),
        "verdict": verdict,
        "issues": issues,
    }


def _trim_filter() -> str:
    """Recorta silencio inicial y final sin borrar las pausas internas."""
    return (
        "silenceremove=start_periods=1:start_silence=0.10:start_threshold=-45dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0.15:start_threshold=-45dB,"
        "areverse"
    )


def process_sample(
    source: Path,
    destination: Path,
    *,
    trim_silence: bool = True,
    denoise: bool = True,
    normalize: bool = True,
    target_rate: int = 24000,
) -> Path:
    """Limpia una muestra para usarla como referencia de clonación."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    filters = ["highpass=f=70"]
    if denoise:
        filters.append("afftdn=nf=-25:nr=12")
    if trim_silence:
        filters.append(_trim_filter())
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    filters.append(f"aresample={int(target_rate)}")
    ffmpeg(
        [
            "-i",
            str(source),
            "-t",
            f"{MAX_SAMPLE_SECONDS:.1f}",
            "-vn",
            "-ac",
            "2" if _channels(source) > 1 else "1",
            "-af",
            ",".join(filters),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise AudioError("El procesado no generó audio")
    return destination


def _channels(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnchannels()
    except (OSError, wave.Error, EOFError):
        binary = Path(utils.get_ffmpeg_binary())
        probe = binary.with_name("ffprobe" + binary.suffix)
        if not probe.exists():
            return 1
        try:
            result = subprocess.run(
                [
                    str(probe),
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=channels",
                    "-of",
                    "default=nw=1:nk=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return max(1, int((result.stdout or "1").strip() or 1))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return 1


def concat_audio(parts: list[Path], destination: Path) -> Path:
    """Concatena audios ya normalizados al mismo formato (WAV 24 kHz)."""
    if not parts:
        raise AudioError("No hay audios para unir")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".concat-", dir=destination.parent) as temp:
        listing = Path(temp) / "list.txt"
        lines = []
        for index, part in enumerate(parts):
            target = Path(temp) / f"{index}.wav"
            ffmpeg(["-i", str(part), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target)])
            lines.append(f"file '{target.name}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                "list.txt",
                "-c:a",
                "pcm_s16le",
                "joined.wav",
            ],
            cwd=temp,
        )
        os.replace(Path(temp) / "joined.wav", destination)
    return destination


def to_mp3(source: Path, destination: Path, *, bitrate: str = "192k") -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        [
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(destination),
        ]
    )
    return destination


def add_silence(destination: Path, seconds: float, *, rate: int = 24000) -> Path:
    seconds = max(0.0, float(seconds))
    duration = max(0.01, seconds)
    ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={rate}:cl=mono",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    return Path(destination)


def prepare_upload(filename: str, payload: bytes) -> tuple[str, bytes]:
    """Valida extensión y tamaño de un archivo subido."""
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise AudioError(
            "Formato no admitido. Usa: " + ", ".join(SUPPORTED_EXTENSIONS)
        )
    if not payload:
        raise AudioError("El archivo está vacío")
    if len(payload) > MAX_SAMPLE_BYTES:
        raise AudioError("El archivo supera los 200 MB")
    return suffix, payload


def safe_stem(value: str, fallback: str = "muestra") -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(str(value or "")).stem).strip("-")
    return stem[:48] or fallback


def probe(path: Path) -> dict[str, Any]:
    """Metadatos básicos sin cargar la señal completa."""
    return {
        "duration": round(ffprobe_duration(Path(path)), 3),
        "size": Path(path).stat().st_size if Path(path).is_file() else 0,
        "channels": _channels(Path(path)),
    }
