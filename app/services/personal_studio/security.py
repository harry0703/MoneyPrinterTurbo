"""Consentimiento, almacenamiento privado y validación de rutas.

Las grabaciones de voz y las fotografías son datos personales. Este módulo
concentra las reglas que impiden crear un perfil sin autorización explícita,
salir del directorio del estudio por una ruta manipulada y dejar archivos
personales con permisos amplios. No sustituye a un cifrado de disco: en Windows
los permisos POSIX son limitados y el panel lo indica.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.utils import utils

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CONSENT_VERSION = 1

CONSENT_STATEMENT = (
    "Declaro que soy la persona de la voz o la imagen, o que cuento con una "
    "autorización verificable de su titular, para crear este perfil y generar "
    "contenido audiovisual. No usaré el perfil para suplantar identidad, "
    "engañar, ni evadir autenticación biométrica."
)


class StudioError(ValueError):
    """Error de validación o estado mostrable al usuario."""


class ConsentError(StudioError):
    """Falta el consentimiento o sus datos no son verificables."""


def studio_root() -> Path:
    root = Path(utils.storage_dir("personal_studio", create=True)).resolve()
    for name in ("voices", "avatars", "projects", "exports", "library"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def safe_identifier(value: Any, field: str = "identificador") -> str:
    if not isinstance(value, str):
        raise StudioError(f"{field} debe ser texto")
    value = value.strip()
    if not _IDENTIFIER.fullmatch(value):
        raise StudioError(
            f"{field} debe tener 1-64 letras, números, guiones o guiones bajos"
        )
    return value


def confined_path(base: Path, *parts: Any) -> Path:
    """Resuelve ``base/parts`` y rechaza cualquier escape del directorio base."""
    base = Path(base).resolve()
    candidate = base.joinpath(*[str(part) for part in parts]).resolve()
    if candidate != base and base not in candidate.parents:
        raise StudioError("Ruta no permitida fuera del estudio personal")
    return candidate


def ensure_private(path: Path) -> Path:
    """Restringe permisos al propietario cuando el sistema lo permite."""
    path = Path(path)
    try:
        if path.is_dir():
            os.chmod(path, stat.S_IRWXU)
        elif path.exists():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows y algunos volúmenes ignoran chmod; no es un error fatal.
        pass
    return path


def atomic_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise StudioError(f"No existe el archivo: {Path(path).name}") from exc
    except (OSError, ValueError) as exc:
        raise StudioError(f"El archivo {Path(path).name} no es JSON válido") from exc
    if not isinstance(data, dict):
        raise StudioError(f"El archivo {Path(path).name} debe ser un objeto JSON")
    return data


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class Consent:
    subject_name: str
    scope: tuple[str, ...]
    granted: bool
    age_confirmed: bool
    is_minor: bool = False
    guardian_name: str = ""
    accepted_at: str = ""

    def document(self) -> dict:
        payload = {
            "version": CONSENT_VERSION,
            "statement": CONSENT_STATEMENT,
            "subject_name": self.subject_name,
            "scope": sorted(self.scope),
            "granted": self.granted,
            "age_confirmed": self.age_confirmed,
            "is_minor": self.is_minor,
            "guardian_name": self.guardian_name,
            "accepted_at": self.accepted_at or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        payload["signature"] = hashlib.sha256(_canonical(payload)).hexdigest()
        return payload


def build_consent(
    payload: Any,
    *,
    scope: Iterable[str],
    require_minor_guardian: bool = True,
) -> dict:
    """Construye y firma un consentimiento a partir del formulario del panel."""
    if not isinstance(payload, dict):
        raise ConsentError("Debes confirmar la autorización de uso")
    required_scope = tuple(sorted({str(item) for item in scope}))
    subject_name = str(payload.get("subject_name") or "").strip()
    if len(subject_name) < 3 or len(subject_name) > 120:
        raise ConsentError("El nombre del titular debe tener entre 3 y 120 caracteres")
    if payload.get("granted") is not True:
        raise ConsentError("Debes aceptar la autorización de uso de voz e imagen")
    if payload.get("age_confirmed") is not True:
        raise ConsentError("Debes confirmar que eres mayor de edad o tienes autorización")
    is_minor = bool(payload.get("is_minor"))
    guardian_name = str(payload.get("guardian_name") or "").strip()
    if is_minor and require_minor_guardian and len(guardian_name) < 3:
        raise ConsentError(
            "Para perfiles de menores se requiere el nombre del padre, madre o tutor"
        )
    consent = Consent(
        subject_name=subject_name,
        scope=required_scope,
        granted=True,
        age_confirmed=True,
        is_minor=is_minor,
        guardian_name=guardian_name,
    )
    return consent.document()


def require_consent(consent: Any, scope: Iterable[str] = ("voz",)) -> dict:
    """Valida un consentimiento guardado y que cubra el alcance solicitado."""
    if not isinstance(consent, dict) or consent.get("granted") is not True:
        raise ConsentError("Falta el consentimiento explícito para este perfil")
    if consent.get("age_confirmed") is not True:
        raise ConsentError("El consentimiento no confirma la edad del titular")
    if consent.get("is_minor") and not str(consent.get("guardian_name") or "").strip():
        raise ConsentError("El perfil de un menor requiere autorización del tutor")
    granted_scope = {str(item) for item in consent.get("scope") or ()}
    missing = {str(item) for item in scope} - granted_scope
    if missing:
        raise ConsentError(
            "El consentimiento no cubre: " + ", ".join(sorted(missing))
        )
    signature = consent.get("signature")
    if not isinstance(signature, str) or len(signature) != 64:
        raise ConsentError("El consentimiento no tiene firma verificable")
    unsigned = {key: value for key, value in consent.items() if key != "signature"}
    expected = hashlib.sha256(_canonical(unsigned)).hexdigest()
    if expected != signature:
        raise ConsentError("El consentimiento fue alterado y no es verificable")
    return consent


def delete_tree(base: Path, identifier: Any) -> None:
    """Elimina un perfil completo sin permitir rutas externas."""
    target = confined_path(base, safe_identifier(identifier))
    if target == Path(base).resolve():
        raise StudioError("No se puede eliminar el directorio raíz")
    if target.exists():
        shutil.rmtree(target)


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
