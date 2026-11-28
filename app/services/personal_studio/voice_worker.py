"""Trabajador de voz que se ejecuta en el entorno de ``local-voice``.

La aplicación no importa torch: escribe un trabajo JSON en la entrada estándar y
este script, ejecutado con ``local-voice/.venv``, sintetiza con MeloTTS en
español y transfiere el timbre del perfil con OpenVoice V2. El resultado se
resume en un archivo ``report`` para no mezclar la salida ruidosa del modelo con
el JSON.

Uso:
    python voice_worker.py < job.json
"""

from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import wave
from pathlib import Path


def _fail(report_path: Path, message: str, detail: str = "") -> int:
    payload = {"ok": False, "error": message, "detail": detail[-4000:]}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"BYNEX_ERROR {message}", file=sys.stderr)
    return 1


def _ffmpeg(ffmpeg: str, args: list[str]) -> None:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[-1000:] or "FFmpeg falló")


def _normalize_wav(ffmpeg: str, source: Path, destination: Path, rate: int) -> None:
    _ffmpeg(
        ffmpeg,
        ["-i", str(source), "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(destination)],
    )


def _concat_wavs(parts: list[Path], destination: Path) -> float:
    if not parts:
        raise RuntimeError("No hay segmentos de voz")
    with wave.open(str(parts[0]), "rb") as first:
        channels = first.getnchannels()
        width = first.getsampwidth()
        rate = first.getframerate()
    total_frames = 0
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        for part in parts:
            with wave.open(str(part), "rb") as source:
                if (
                    source.getnchannels() != channels
                    or source.getsampwidth() != width
                    or source.getframerate() != rate
                ):
                    raise RuntimeError("Los segmentos tienen formatos incompatibles")
                frames = source.readframes(source.getnframes())
                output.writeframes(frames)
                total_frames += source.getnframes()
    return total_frames / float(rate)


def _silence(path: Path, seconds: float, rate: int) -> None:
    frames = max(1, int(round(seconds * rate)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)


def _target_se(converter, reference: Path, cache_dir: Path, digest: str):
    import torch

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"se-{digest[:16]}.pth"
    if cached.is_file():
        try:
            return torch.load(str(cached), map_location="cpu", weights_only=True)
        except Exception:
            cached.unlink(missing_ok=True)
    from openvoice import se_extractor

    speaker, _ = se_extractor.get_se(
        str(reference), converter, target_dir=str(cache_dir / "extract"), vad=True
    )
    try:
        torch.save(speaker, str(cached))
    except Exception:
        pass
    return speaker


def run(job: dict, report_path: Path) -> int:
    started = time.time()
    output = Path(job["output"])
    reference = Path(job["reference"])
    checkpoints = Path(job["checkpoints"])
    ffmpeg = job.get("ffmpeg") or "ffmpeg"
    rate = int(job.get("sample_rate", 24000))
    language = str(job.get("language", "es")).upper()
    speed = float(job.get("speed", 1.0))
    segments = job.get("segments") or []
    if not segments:
        return _fail(report_path, "El guion no tiene segmentos narrables")
    if not reference.is_file():
        return _fail(report_path, "La referencia de voz del perfil no existe")
    converter_config = checkpoints / "converter" / "config.json"
    converter_ckpt = checkpoints / "converter" / "checkpoint.pth"
    source_se_path = checkpoints / "base_speakers" / "ses" / "es.pth"
    for required in (converter_config, converter_ckpt, source_se_path):
        if not required.is_file():
            return _fail(report_path, f"Falta un archivo de OpenVoice: {required.name}")

    try:
        import torch

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
        from melo.api import TTS

        model = TTS(language=language, device="cpu")
        speaker_ids = model.hps.data.spk2id
        speaker_id = next(iter(speaker_ids.values()))

        durations: list[float] = []
        timings: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="bynnex-voice-") as temp:
            temporary = Path(temp)
            parts: list[Path] = []
            for index, segment in enumerate(segments):
                text = str(segment.get("text") or "").strip()
                if not text:
                    continue
                raw = temporary / f"seg-{index}.wav"
                model.tts_to_file(text, speaker_id, str(raw), speed=speed)
                normalized = temporary / f"seg-{index}-norm.wav"
                _normalize_wav(ffmpeg, raw, normalized, 44100)
                duration = 0.0
                with wave.open(str(normalized), "rb") as handle:
                    duration = handle.getnframes() / float(handle.getframerate())
                if duration <= 0:
                    continue
                parts.append(normalized)
                durations.append(duration)
                timings.append({"text": text, "duration": duration})
                pause = float(segment.get("pause_after") or 0.0)
                if pause > 0.01:
                    silence = temporary / f"gap-{index}.wav"
                    _silence(silence, pause, 44100)
                    parts.append(silence)
                    durations.append(pause)
            if not parts:
                return _fail(report_path, "MeloTTS no generó audio")
            combined = temporary / "combined.wav"
            speech_duration = _concat_wavs(parts, combined)

            from openvoice.api import ToneColorConverter

            converter = ToneColorConverter(str(converter_config), device="cpu")
            converter.load_ckpt(str(converter_ckpt))
            cache_dir = Path(job.get("cache_dir") or (output.parent / ".voice_cache"))
            target = _target_se(converter, reference, cache_dir, str(job.get("digest") or "ref"))
            source = torch.load(str(source_se_path), map_location="cpu", weights_only=True)
            converted = temporary / "converted.wav"
            converter.convert(
                audio_src_path=str(combined),
                src_se=source,
                tgt_se=target,
                output_path=str(converted),
                message=str(job.get("watermark") or "@BYNEX"),
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            _ffmpeg(
                ffmpeg,
                [
                    "-i",
                    str(converted),
                    "-af",
                    "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ac",
                    "1",
                    "-ar",
                    str(rate),
                    "-c:a",
                    "pcm_s16le",
                    str(output),
                ],
            )
            del converter, model
            gc.collect()
            if not output.is_file() or output.stat().st_size == 0:
                return _fail(report_path, "La conversión no generó audio")
            report = {
                "ok": True,
                "engine": "openvoice_melotts",
                "cloned": True,
                "watermark": str(job.get("watermark") or "@BYNEX"),
                "duration": round(speech_duration, 3),
                "timings": timings,
                "elapsed": round(time.time() - started, 2),
            }
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False), encoding="utf-8"
            )
            return 0
    except Exception as exc:  # noqa: BLE001 - el informe debe llevar el detalle
        return _fail(report_path, f"El motor de voz falló: {exc}", traceback.format_exc())


def main() -> int:
    try:
        job = json.load(sys.stdin)
    except ValueError as exc:
        print(f"BYNEX_ERROR trabajo inválido: {exc}", file=sys.stderr)
        return 2
    report_path = Path(job.get("report") or (Path(job.get("output", "out.wav")).parent / "report.json"))
    if not isinstance(job, dict):
        return _fail(report_path, "El trabajo debe ser un objeto JSON")
    return run(job, report_path)


if __name__ == "__main__":
    sys.exit(main())
