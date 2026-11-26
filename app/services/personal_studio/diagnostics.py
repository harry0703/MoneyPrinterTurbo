"""Diagnóstico del sistema para el panel de BYNEX AI Personal Studio.

El informe no ejecuta modelos salvo que se pida ``deep`` (importación real de
torch/melo/openvoice, ~10-20 s). Todo lo demás son comprobaciones de archivos y
versiones.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from app.services.personal_studio import engines, resources
from app.services.personal_studio.avatars import AvatarStore
from app.services.personal_studio.security import studio_root
from app.services.personal_studio.studio import ProjectStore
from app.services.personal_studio.voice_profiles import VoiceStore
from app.utils import utils


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return round(total / (1024 * 1024), 1)


def _job_count(root: Path) -> int:
    path = root / "jobs.json"
    if not path.is_file():
        return 0
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data.get("jobs") or [])
    except (OSError, ValueError):
        return 0


def _ffmpeg_version() -> str:
    try:
        result = subprocess.run(
            [utils.get_ffmpeg_binary(), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return (result.stdout or "").splitlines()[0] if result.stdout else "no disponible"
    except (OSError, subprocess.TimeoutExpired):
        return "no disponible"


def report(*, deep: bool = False) -> dict:
    root = studio_root()
    voice = VoiceStore(root)
    avatars = AvatarStore(root)
    projects = ProjectStore(root)
    warnings: list[str] = []

    has_cv2 = importlib.util.find_spec("cv2") is not None
    if not has_cv2:
        warnings.append(
            "OpenCV no está instalado: la detección de rostro usa una heurística de "
            "tono de piel y no se puede segmentar el fondo."
        )
    if importlib.util.find_spec("psutil") is None:
        warnings.append(
            "psutil no está instalado: la RAM se lee con la API del sistema y el uso "
            "de CPU no está disponible."
        )

    engine_list = engines.probe(refresh=True, deep=deep)
    checkpoint_dir = engines.checkpoints()
    model_files = {
        name: path.is_file()
        for name, path in {
            "converter/config.json": checkpoint_dir / "converter" / "config.json",
            "converter/checkpoint.pth": checkpoint_dir / "converter" / "checkpoint.pth",
            "base_speakers/ses/es.pth": checkpoint_dir / "base_speakers" / "ses" / "es.pth",
        }.items()
    }
    if not all(model_files.values()):
        warnings.append("Faltan checkpoints de OpenVoice V2; el motor local no estará disponible.")

    python = engines.voice_python()
    ram = resources.snapshot()
    if ram.get("ram_available_mb") and ram["ram_available_mb"] < 900:
        warnings.append("Memoria libre baja: cierra aplicaciones antes de narrar.")

    return {
        "app": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "executable": sys.executable,
            "ffmpeg": _ffmpeg_version(),
            "ffmpeg_path": utils.get_ffmpeg_binary(),
        },
        "hardware": ram,
        "voice_engine": {
            "python": str(python) if python else None,
            "local_voice_dir": str(engines.local_voice_dir()),
            "checkpoints": model_files,
            "checkpoints_size_mb": _dir_size_mb(checkpoint_dir),
            "licenses": {
                "meloTTS": "MIT",
                "openvoice_v2": "MIT (código y checkpoints)",
            },
        },
        "engines": engine_list,
        "capabilities": {
            "face_detection": "opencv" if has_cv2 else "heurística de piel",
            "background_removal": False,
            "lip_sync": "envolvente de amplitud (no fonemas)",
            "outputs": ["mp4", "wav", "mp3", "srt"],
            "max_resolution": "1080p declarado; solo 480p/720p medidos",
        },
        "storage": {
            "root": str(root),
            "disk_free_gb": ram.get("disk_free_gb"),
            "voice_profiles": len(voice.list()),
            "voice_size_mb": _dir_size_mb(root / "voices"),
            "avatars": len(avatars.list()),
            "avatar_size_mb": _dir_size_mb(root / "avatars"),
            "projects": len(projects.list()),
            "projects_size_mb": _dir_size_mb(root / "projects"),
            "jobs": _job_count(root),

        },
        "privacy": {
            "local_only": True,
            "external_service": "Edge TTS solo si se elige como respaldo",
            "consent_required": True,
            "exports_blocked_until_approval": True,
        },
        "warnings": warnings,
    }


def smoke_test() -> dict:
    """Comprobación corta que el panel ofrece antes de generar contenido."""
    checks = []
    python = engines.voice_python()
    checks.append(
        {
            "name": "Entorno de voz",
            "ok": python is not None,
            "detail": str(python) if python else "Falta local-voice/.venv",
        }
    )
    available, reason = engines.openvoice_available()
    checks.append({"name": "OpenVoice V2", "ok": available, "detail": reason})
    ffmpeg = shutil.which(utils.get_ffmpeg_binary()) or Path(utils.get_ffmpeg_binary()).is_file()
    checks.append(
        {"name": "FFmpeg", "ok": bool(ffmpeg), "detail": utils.get_ffmpeg_binary()}
    )
    ram_ok, message = resources.guard()
    checks.append({"name": "Memoria", "ok": ram_ok, "detail": message})
    return {"ok": all(item["ok"] for item in checks), "checks": checks}
