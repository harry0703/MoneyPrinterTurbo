"""Perfiles de voz personales: muestras, limpieza, referencia y borrado.

Un perfil es un directorio bajo ``storage/personal_studio/voices`` con
``profile.json``, las muestras originales, las muestras limpias y una única
referencia ``reference.wav`` que usa OpenVoice para extraer el timbre.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from app.services.personal_studio import audio
from app.services.personal_studio.security import (
    StudioError,
    atomic_json,
    build_consent,
    confined_path,
    delete_tree,
    digest_bytes,
    digest_file,
    ensure_private,
    read_json,
    require_consent,
    safe_identifier,
    studio_root,
    timestamp,
)

MAX_SAMPLES = 20
REFERENCE_SECONDS = 30.0
LANGUAGES = {"es": "Español (Colombia)"}


class VoiceProfileError(StudioError):
    pass


def _now() -> float:
    return time.time()


class VoiceStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or studio_root()).resolve()
        self.voices = confined_path(self.root, "voices")
        self.voices.mkdir(parents=True, exist_ok=True)

    # -- utilidades ----------------------------------------------------
    def profile_dir(self, profile_id: str) -> Path:
        identifier = safe_identifier(profile_id, "perfil de voz")
        directory = confined_path(self.voices, identifier)
        if not directory.is_dir():
            raise VoiceProfileError(f"El perfil de voz no existe: {identifier}")
        return directory

    def _profile_path(self, profile_id: str) -> Path:
        return self.profile_dir(profile_id) / "profile.json"

    def _save(self, profile: dict) -> dict:
        profile["updated_at"] = timestamp()
        atomic_json(self._profile_path(profile["id"]), profile)
        return profile

    @staticmethod
    def _text(value: Any, field: str, limit: int) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise VoiceProfileError(f"{field} debe ser texto")
        value = value.strip()
        if len(value) > limit:
            raise VoiceProfileError(f"{field} no puede superar {limit} caracteres")
        return value

    # -- CRUD ----------------------------------------------------------
    def create(
        self,
        *,
        name: str,
        language: str = "es",
        consent: dict,
        notes: str = "",
        is_minor: bool = False,
    ) -> dict:
        name = self._text(name, "nombre", 80)
        if len(name) < 2:
            raise VoiceProfileError("El nombre del perfil debe tener al menos 2 caracteres")
        if language not in LANGUAGES:
            raise VoiceProfileError("Idioma no soportado; por ahora solo español")
        notes = self._text(notes, "notas", 500)
        document = build_consent(consent, scope=("voz",))
        if bool(consent.get("accepted_by_profile_owner", True)) is not True:
            raise VoiceProfileError("El consentimiento debe ser aceptado por el titular")

        identifier = f"v_{uuid.uuid4().hex[:10]}"
        directory = confined_path(self.voices, identifier)
        (directory / "samples").mkdir(parents=True, exist_ok=False)
        profile = {
            "schema_version": 1,
            "id": identifier,
            "name": name,
            "language": language,
            "language_label": LANGUAGES[language],
            "engine": "openvoice_melotts",
            "notes": notes,
            "is_minor": bool(is_minor),
            "consent": document,
            "samples": [],
            "processed": None,
            "status": "draft",
            "approved": False,
            "approved_at": None,
            "created_at": timestamp(),
            "updated_at": timestamp(),
        }
        ensure_private(directory)
        self._save(profile)
        return profile

    def get(self, profile_id: str) -> dict:
        return read_json(self._profile_path(profile_id))

    def list(self) -> list[dict]:
        items: list[dict] = []
        for entry in sorted(self.voices.iterdir()):
            if not entry.is_dir():
                continue
            path = entry / "profile.json"
            if not path.is_file():
                continue
            try:
                profile = read_json(path)
            except StudioError:
                continue
            items.append(profile)
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return items

    def update(self, profile_id: str, *, name: str | None = None, notes: str | None = None) -> dict:
        profile = self.get(profile_id)
        if name is not None:
            name = self._text(name, "nombre", 80)
            if len(name) < 2:
                raise VoiceProfileError("El nombre del perfil es demasiado corto")
            profile["name"] = name
        if notes is not None:
            profile["notes"] = self._text(notes, "notas", 500)
        return self._save(profile)

    def remove(self, profile_id: str) -> None:
        profile = self.get(profile_id)
        require_consent(profile.get("consent"), ("voz",))
        target = self.profile_dir(profile_id)
        delete_tree(self.voices, profile_id)
        if target.exists():
            raise VoiceProfileError("No se pudo eliminar el perfil completo")

    # -- muestras ------------------------------------------------------
    def add_sample(self, profile_id: str, filename: str, payload: bytes) -> dict:
        profile = self.get(profile_id)
        require_consent(profile.get("consent"), ("voz",))
        if len(profile.get("samples") or []) >= MAX_SAMPLES:
            raise VoiceProfileError(f"Máximo {MAX_SAMPLES} muestras por perfil")
        suffix, payload = audio.prepare_upload(filename, payload)
        directory = self.profile_dir(profile_id)
        index = len(profile.get("samples") or []) + 1
        stem = audio.safe_stem(filename, f"muestra-{index}")
        original = directory / "samples" / f"{index:02d}-{stem}{suffix}"
        original.write_bytes(payload)
        ensure_private(original)

        try:
            raw = audio.analyze(original)
        except audio.AudioError as exc:
            original.unlink(missing_ok=True)
            raise VoiceProfileError(f"El audio no es válido: {exc}") from exc
        clean = directory / "samples" / f"{index:02d}-{stem}.clean.wav"
        try:
            audio.process_sample(original, clean)
            processed = audio.analyze(clean)
        except audio.AudioError as exc:
            clean.unlink(missing_ok=True)
            original.unlink(missing_ok=True)
            raise VoiceProfileError(f"No se pudo limpiar la muestra: {exc}") from exc
        ensure_private(clean)

        sample = {
            "index": index,
            "file": str(original.relative_to(directory)),
            "clean_file": str(clean.relative_to(directory)),
            "sha256": digest_bytes(payload),
            "size": len(payload),
            "raw": raw,
            "clean": processed,
            "added_at": timestamp(),
        }
        profile.setdefault("samples", []).append(sample)
        profile["status"] = "draft"
        profile["processed"] = None
        profile["approved"] = False
        profile["approved_at"] = None
        self._save(profile)
        return sample

    def remove_sample(self, profile_id: str, index: int) -> dict:
        profile = self.get(profile_id)
        directory = self.profile_dir(profile_id)
        samples = profile.get("samples") or []
        match = next((item for item in samples if int(item.get("index", 0)) == int(index)), None)
        if match is None:
            raise VoiceProfileError(f"No existe la muestra {index}")
        for key in ("file", "clean_file"):
            relative = match.get(key)
            if relative:
                target = confined_path(directory, relative)
                if target.is_file():
                    target.unlink()
        profile["samples"] = [item for item in samples if item is not match]
        profile["processed"] = None
        profile["status"] = "draft"
        profile["approved"] = False
        return self._save(profile)

    # -- referencia ----------------------------------------------------
    def process(self, profile_id: str) -> dict:
        """Une las mejores muestras limpias en la referencia de timbre."""
        profile = self.get(profile_id)
        require_consent(profile.get("consent"), ("voz",))
        samples = profile.get("samples") or []
        if not samples:
            raise VoiceProfileError("Añade al menos una muestra de voz antes de procesar")
        usable = sorted(
            (item for item in samples if item["clean"]["duration"] >= 2.0),
            key=lambda item: item["clean"]["score"],
            reverse=True,
        )
        if not usable:
            raise VoiceProfileError("Ninguna muestra tiene audio suficiente para clonar")
        if usable[0]["clean"]["score"] < 35:
            raise VoiceProfileError(
                "Ninguna muestra supera la calidad mínima. Graba en un lugar silencioso."
            )

        directory = self.profile_dir(profile_id)
        chosen: list[Path] = []
        total = 0.0
        for sample in usable:
            path = confined_path(directory, sample["clean_file"])
            if not path.is_file():
                continue
            chosen.append(path)
            total += float(sample["clean"]["duration"])
            if total >= REFERENCE_SECONDS or len(chosen) >= 4:
                break
        reference = directory / "reference.wav"
        audio.concat_audio(chosen, reference)
        ensure_private(reference)
        metrics = audio.analyze(reference)
        if metrics["verdict"] == "deficiente":
            raise VoiceProfileError(
                "La referencia final sigue siendo deficiente: " + "; ".join(metrics["issues"])
            )
        profile["processed"] = {
            "reference": "reference.wav",
            "sha256": digest_file(reference),
            "duration": metrics["duration"],
            "sample_count": len(chosen),
            "metrics": metrics,
            "processed_at": timestamp(),
        }
        profile["status"] = "ready"
        profile["approved"] = False
        self._save(profile)
        return profile["processed"]

    def reference(self, profile_id: str) -> Path:
        profile = self.get(profile_id)
        processed = profile.get("processed")
        if not processed:
            raise VoiceProfileError("El perfil todavía no tiene una referencia procesada")
        path = confined_path(self.profile_dir(profile_id), processed["reference"])
        if not path.is_file():
            raise VoiceProfileError("La referencia del perfil no está disponible")
        return path

    def approve(self, profile_id: str, approved: bool = True) -> dict:
        profile = self.get(profile_id)
        if approved and profile.get("status") != "ready":
            raise VoiceProfileError("Procesa la voz antes de aprobar el perfil")
        profile["approved"] = bool(approved)
        profile["approved_at"] = timestamp() if approved else None
        return self._save(profile)


def reference_digest(profile: dict) -> str:
    processed = profile.get("processed") or {}
    return str(processed.get("sha256") or "")


def sample_files(profile: dict, base: Path) -> list[Path]:
    result = []
    for sample in profile.get("samples") or []:
        path = confined_path(base, sample.get("file"))
        if path.is_file():
            result.append(path)
    return result
