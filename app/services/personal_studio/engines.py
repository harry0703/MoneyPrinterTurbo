"""Adaptadores de motores de voz y sondeo de disponibilidad.

Motor principal: MeloTTS (español) + OpenVoice V2 (timbre del perfil), ejecutado
en ``local-voice/.venv`` como proceso hijo. Respaldo: Edge TTS del proyecto, que
no clona la voz y requiere conexión. Piper solo se usa si el usuario ya instaló
el binario y una voz; el módulo no descarga nada.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.services.personal_studio import audio, script
from app.services.personal_studio.security import StudioError, digest_file, studio_root
from app.utils import utils

WORKER = Path(__file__).with_name("voice_worker.py")
DEFAULT_EDGE_VOICE = "es-CO-GonzaloNeural-Male"
_PROBE_TTL = 30.0
_probe_cache: dict[str, Any] = {"at": 0.0, "value": None}

ENGINE_INFO = {
    "openvoice_melotts": {
        "label": "MeloTTS + OpenVoice V2 (local)",
        "cloned": True,
        "offline": True,
        "license": "MIT (código y checkpoints V2)",
        "note": "Clonación de timbre por transferencia sobre voz base en español.",
    },
    "edge_tts": {
        "label": "Edge TTS (respaldo sin clonación)",
        "cloned": False,
        "offline": False,
        "license": "Servicio de Microsoft; requiere conexión",
        "note": "Voz natural en español, pero no conserva el timbre del perfil.",
    },
    "piper": {
        "label": "Piper (local, opcional)",
        "cloned": False,
        "offline": True,
        "license": "Motor GPL-3.0; licencia por voz",
        "note": "Solo si ya existe el binario y una voz instalada.",
    },
}


def project_dir() -> Path:
    return Path(utils.root_dir()).resolve()


def local_voice_dir() -> Path:
    return Path(os.environ.get("BYNEX_LOCAL_VOICE_DIR") or (project_dir() / "local-voice")).resolve()


def voice_python() -> Path | None:
    override = os.environ.get("BYNEX_VOICE_PYTHON")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    base = local_voice_dir() / ".venv"
    candidates = [
        base / "Scripts" / "python.exe",
        base / "bin" / "python",
    ]
    return next((path for path in candidates if path.is_file()), None)


def checkpoints() -> Path:
    return local_voice_dir() / "checkpoints_v2"


def piper_binary() -> str | None:
    override = os.environ.get("BYNEX_PIPER_EXE")
    if override and Path(override).is_file():
        return override
    return shutil.which("piper")


def piper_model() -> Path | None:
    value = os.environ.get("BYNEX_PIPER_MODEL")
    if value and Path(value).is_file():
        return Path(value)
    return None


def openvoice_available() -> tuple[bool, str]:
    python = voice_python()
    if python is None:
        return False, "No se encontró local-voice/.venv con Python 3.11"
    files = [
        checkpoints() / "converter" / "config.json",
        checkpoints() / "converter" / "checkpoint.pth",
        checkpoints() / "base_speakers" / "ses" / "es.pth",
    ]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        return False, "Faltan checkpoints de OpenVoice V2: " + ", ".join(missing)
    return True, "Listo (torch CPU + MeloTTS + OpenVoice V2)"


def probe(*, refresh: bool = False, deep: bool = False) -> list[dict]:
    """Estado de cada motor para el panel y el diagnóstico."""
    now = time.time()
    if not refresh and _probe_cache["value"] and now - _probe_cache["at"] < _PROBE_TTL:
        return _probe_cache["value"]
    enabled, reason = openvoice_available()
    if enabled and deep:
        enabled, reason = _deep_import_check() or (enabled, reason)
    engines = [
        {**ENGINE_INFO["openvoice_melotts"], "id": "openvoice_melotts", "available": enabled, "reason": reason},
        {
            **ENGINE_INFO["edge_tts"],
            "id": "edge_tts",
            "available": True,
            "reason": "Disponible con conexión a Internet",
        },
    ]
    binary = piper_binary()
    model = piper_model()
    engines.append(
        {
            **ENGINE_INFO["piper"],
            "id": "piper",
            "available": bool(binary and model),
            "reason": (
                "Binario y voz configurados"
                if binary and model
                else "Define BYNEX_PIPER_EXE y BYNEX_PIPER_MODEL si deseas usarlo"
            ),
        }
    )
    _probe_cache.update(at=now, value=engines)
    return engines


def _deep_import_check() -> tuple[bool, str] | None:
    python = voice_python()
    if python is None:
        return None
    try:
        result = subprocess.run(
            [str(python), "-c", "import torch, melo, openvoice; print('ok')"],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(local_voice_dir()),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"No se pudo probar el entorno de voz: {exc}"
    if result.returncode == 0:
        return True, "Importación de torch, melo y openvoice verificada"
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    return False, detail[-1][:200] if detail else "El entorno de voz no importa"


def resolve_engine(requested: str, profile: dict | None) -> str:
    if requested and requested != "auto":
        return requested
    if profile:
        available, _ = openvoice_available()
        if available:
            return "openvoice_melotts"
    if piper_binary() and piper_model():
        return "piper"
    return "edge_tts"


def _run_worker(job: dict, *, timeout: float, cancel) -> dict:
    python = voice_python()
    if python is None:
        raise StudioError("No se encontró el entorno local de voz (local-voice/.venv)")
    output = Path(job["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    report = output.parent / f".voice-report-{os.getpid()}-{int(time.time())}.json"
    job["report"] = str(report)
    job.setdefault("ffmpeg", utils.get_ffmpeg_binary())
    if report.exists():
        report.unlink()
    stderr_tail = ""
    with tempfile.TemporaryFile("w+", encoding="utf-8") as stderr_file, tempfile.TemporaryFile(
        "w+", encoding="utf-8"
    ) as stdout_file:
        process = subprocess.Popen(
            [str(python), str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            cwd=str(local_voice_dir()),
        )
        try:
            assert process.stdin is not None
            process.stdin.write(json.dumps(job, ensure_ascii=False))
            process.stdin.close()
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel is not None and cancel():
                    process.terminate()
                    raise StudioError("Generación de voz cancelada")
                if time.monotonic() > deadline:
                    process.kill()
                    raise StudioError("El motor de voz superó el tiempo máximo")
                time.sleep(0.25)
            stderr_file.seek(0)
            stderr_tail = stderr_file.read()[-2000:]
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if not report.is_file():
        raise StudioError(
            "El motor de voz terminó sin informe: " + (stderr_tail.strip()[-400:] or "sin detalle")
        )
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    finally:
        report.unlink(missing_ok=True)
    if not data.get("ok"):
        raise StudioError(str(data.get("error") or "El motor de voz falló"))
    return data


def _synthesize_openvoice(
    segments: list[dict],
    *,
    profile: dict,
    output: Path,
    speed: float,
    cancel,
    store,
) -> dict:
    available, reason = openvoice_available()
    if not available:
        raise StudioError(reason)
    reference = store.reference(profile["id"])
    if not (profile.get("processed") or {}).get("reference"):
        raise StudioError("El perfil de voz no tiene referencia procesada")
    characters = sum(len(item["text"]) for item in segments)
    timeout = min(1800.0, max(300.0, 120.0 + characters * 1.5))
    job = {
        "segments": segments,
        "output": str(output),
        "reference": str(reference),
        "checkpoints": str(checkpoints()),
        "language": "ES",
        "speed": max(0.8, min(1.2, float(speed))),
        "digest": digest_file(reference),
        "watermark": "@BYNEX",
        "sample_rate": 24000,
    }
    # La caché de timbre vive junto a los perfiles, no dentro de un proyecto.
    job["cache_dir"] = str(store.voices / ".se_cache" / profile["id"])
    started = time.time()
    data = _run_worker(job, timeout=timeout, cancel=cancel)
    return {
        "engine": "openvoice_melotts",
        "cloned": True,
        "offline": True,
        "output": str(output),
        "duration": float(data.get("duration") or audio.ffprobe_duration(output)),
        "timings": data.get("timings") or [],
        "watermark": data.get("watermark"),
        "elapsed": round(time.time() - started, 2),
        "warnings": [],
    }


def _synthesize_edge(
    text: str, segments: list[dict], *, output: Path, style: str, speed: float
) -> dict:
    from app.services import voice

    params = script.style_parameters(style)
    rate = max(0.5, min(2.0, float(speed) * float(params["rate"])))
    started = time.time()
    result = voice.tts(text, DEFAULT_EDGE_VOICE, rate, str(output))
    if result is None or not Path(output).is_file():
        raise StudioError("Edge TTS no pudo generar la narración (¿sin conexión?)")
    duration = audio.ffprobe_duration(Path(output))
    if duration <= 0:
        raise StudioError("Edge TTS generó un archivo vacío")
    total_chars = max(1, sum(len(item["text"]) for item in segments))
    timings = []
    for item in segments:
        share = len(item["text"]) / total_chars
        timings.append({"text": item["text"], "duration": round(duration * share, 3)})
    return {
        "engine": "edge_tts",
        "cloned": False,
        "offline": False,
        "output": str(output),
        "duration": round(duration, 3),
        "timings": timings,
        "watermark": None,
        "elapsed": round(time.time() - started, 2),
        "warnings": [
            "Edge TTS no clona la voz y envía el texto a Microsoft. Los tiempos de "
            "subtítulo son proporcionales, no medidos."
        ],
    }


def _synthesize_piper(text: str, *, output: Path, speed: float) -> dict:
    binary = piper_binary()
    model = piper_model()
    if not binary or not model:
        raise StudioError("Piper no está configurado (BYNEX_PIPER_EXE / BYNEX_PIPER_MODEL)")
    started = time.time()
    raw = output.with_suffix(".piper.wav")
    try:
        result = subprocess.run(
            [binary, "--model", str(model), "--output_file", str(raw)],
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
            check=False,
        )
        if result.returncode != 0 or not raw.is_file():
            raise StudioError("Piper falló: " + (result.stderr or "").strip()[-300:])
        audio.ffmpeg(["-i", str(raw), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(output)])
    finally:
        raw.unlink(missing_ok=True)
    duration = audio.ffprobe_duration(output)
    return {
        "engine": "piper",
        "cloned": False,
        "offline": True,
        "output": str(output),
        "duration": round(duration, 3),
        "timings": [],
        "watermark": None,
        "elapsed": round(time.time() - started, 2),
        "warnings": ["Piper no clona el timbre del perfil."],
    }


def synthesize(
    text: str,
    *,
    output: str | Path,
    profile: dict | None = None,
    style: str = "conversacional",
    speed: float = 1.0,
    engine: str = "auto",
    expand_numbers: bool = True,
    glossary: bool = True,
    cancel=None,
    voice_store=None,
    allow_unapproved: bool = False,
) -> dict:
    """Genera la narración completa y devuelve tiempos por segmento.

    ``allow_unapproved`` solo lo usa el asistente para la vista previa previa a
    aprobar el perfil; los proyectos exigen siempre un perfil aprobado.
    """
    from app.services.personal_studio.voice_profiles import VoiceStore

    profile = profile if isinstance(profile, dict) else None
    if (
        profile
        and not profile.get("approved")
        and not allow_unapproved
        and engine in {"auto", "openvoice_melotts"}
    ):
        raise StudioError("El perfil de voz debe estar aprobado antes de narrar")
    segments = script.segment_script(
        text, style, expand=expand_numbers, glossary=glossary
    )
    prepared = script.plain_text(segments)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    selected = resolve_engine(engine, profile)
    if selected == "openvoice_melotts":
        if not profile:
            raise StudioError("El motor local necesita un perfil de voz aprobado")
        result = _synthesize_openvoice(
            segments,
            profile=profile,
            output=output,
            speed=speed,
            cancel=cancel,
            store=voice_store or VoiceStore(),
        )
    elif selected == "piper":
        result = _synthesize_piper(prepared, output=output, speed=speed)
    else:
        result = _synthesize_edge(
            prepared, segments, output=output, style=style, speed=speed
        )
    if not result.get("timings"):
        total = float(result.get("duration") or 0)
        shares = [1.0 / len(segments)] * len(segments)
        result["timings"] = [
            {"text": item["text"], "duration": round(total * share, 3)}
            for item, share in zip(segments, shares)
        ]
    # La pausa declarada también ocupa tiempo real de audio: incluirla en el
    # tiempo del subtítulo evita que las frases se adelanten progresivamente.
    for index, timing in enumerate(result.get("timings") or []):
        extra = 0.0
        if index < len(segments):
            extra = float(segments[index].get("pause_after") or 0.0)
        timing["duration"] = round(float(timing.get("duration") or 0.0) + extra, 3)
    result["segments"] = segments
    result["text"] = prepared
    result["style"] = style
    return result


def ensure_studio_root() -> Path:
    return studio_root()
