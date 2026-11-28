"""Local workspace for the Cartoon Studio 2D web panel.

This module is the service layer between the Streamlit page and the existing
engine (``cartoon_studio`` + ``cartoon_animation`` + ``video_project``). It
owns projects, editable manifests, studio settings, render exports and the
approval log. It never imports Streamlit and never publishes anything.

Everything is local: a project is a directory under ``storage/cartoon`` with
``cartoon.json`` (the manifest the CLI also reads), ``studio.json`` (panel
preferences) and ``approvals.json`` (review history). Writes are atomic and a
previous manifest is copied to ``backups/`` before it is replaced.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from app.services import cartoon_studio
from app.services.cartoon_animation import (
    AnimationError,
    CHARACTER_PRESETS,
    Pose,
    RenderSettings,
    animation_names,
    apply_expression,
    build_plan,
    expression_names,
    get_character,
    render_still,
    sample_animation,
)
from app.services.cartoon_animation.renderer import render_character
from app.services.video_project import ProjectError
from app.utils import utils

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

APPROVAL_SCHEMA = 1
# Approval actions accepted by the panel. ``approve`` is the only one that
# unlocks a video; the other two keep the episode in review.
DECISIONS = {"approve", "request_changes", "reject"}

# Only render-affecting preferences take part in the content identity. Changing
# the reviewer name or the description must not invalidate an approval.
_RENDER_SETTING_KEYS = (
    "voice",
    "voice_rate",
    "subtitles",
    "subtitle_font_size",
    "mode",
    "fps",
    "crf",
    "output_width",
    "output_height",
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "description": "",
    "voice": "",
    "voice_rate": 1.0,
    "subtitles": False,
    "subtitle_font_size": 56,
    "mode": "auto",
    "fps": 24,
    "crf": 20,
    "output_width": None,
    "output_height": None,
    "reviewer": "",
    "archived": False,
}


class StudioError(ValueError):
    """A user-facing validation or state error from the studio layer."""


def _text(value: Any, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StudioError(f"{field} debe ser texto")
    value = value.strip()
    if len(value) > limit:
        raise StudioError(f"{field} debe tener menos de {limit} caracteres")
    return value


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudioError(f"{field} debe ser un número")
    result = float(value)
    if not minimum <= result <= maximum:
        raise StudioError(f"{field} debe estar entre {minimum:g} y {maximum:g}")
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    """Write JSON atomically, reusing the manifest writer's fsync semantics."""
    cartoon_studio._atomic_json(path, value)


class StudioStore:
    """Project store confined to one cartoon root directory."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or utils.storage_dir("cartoon", create=True)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------

    def project_id(self, value: Any) -> str:
        if not isinstance(value, str) or not _PROJECT_ID.fullmatch(value.strip()):
            raise StudioError(
                "El identificador debe tener 1-64 letras, números, guiones o guiones bajos"
            )
        return value.strip()

    def project_dir(self, project_id: str) -> Path:
        """Resolve an existing project directory; never escape the root."""
        identifier = self.project_id(project_id)
        directory = (self.root / identifier).resolve()
        if directory.parent != self.root:
            raise StudioError("Ruta de proyecto no permitida")
        return directory

    def manifest_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "cartoon.json"

    def exists(self, project_id: str) -> bool:
        try:
            return self.manifest_path(project_id).is_file()
        except StudioError:
            return False

    def _confined(self, project_id: str, value: str | Path) -> Path:
        directory = self.project_dir(project_id)
        path = Path(value)
        if not path.is_absolute():
            path = directory / path
        path = path.resolve()
        if path != directory and directory not in path.parents:
            raise StudioError("Ruta de artefacto fuera del proyecto")
        return path

    # -- manifest ------------------------------------------------------

    def read_manifest(self, project_id: str) -> dict:
        path = self.manifest_path(project_id)
        try:
            size = path.stat().st_size
            if size > _MAX_MANIFEST_BYTES:
                raise StudioError("El manifiesto supera el tamaño permitido")
            with path.open(encoding="utf-8") as source:
                data = json.load(source)
        except FileNotFoundError as exc:
            raise StudioError(f"El proyecto no existe: {project_id}") from exc
        except json.JSONDecodeError as exc:
            raise StudioError(f"El manifiesto no es JSON válido: {exc}") from exc
        if not isinstance(data, dict):
            raise StudioError("El manifiesto debe ser un objeto JSON")
        return data

    def manifest_sha256(self, project_id: str) -> str:
        path = self.manifest_path(project_id)
        try:
            return _sha256_file(path)
        except FileNotFoundError as exc:
            raise StudioError(f"El proyecto no existe: {project_id}") from exc

    def load(self, project_id: str) -> dict:
        """Return the manifest, its storyboard and the panel state."""
        document = self.read_manifest(project_id)
        try:
            storyboard = cartoon_studio.parse_storyboard(document)
        except cartoon_studio.CartoonStudioError as exc:
            raise StudioError(str(exc)) from exc
        return {
            "id": storyboard.project_id,
            "path": str(self.project_dir(project_id)),
            "document": document,
            "storyboard": storyboard,
            "manifest_sha256": self.manifest_sha256(project_id),
            "settings": self.settings(project_id),
            "export": self.export(project_id),
            "approval": self.approval(project_id),
            "revisions": self.revisions(project_id),
        }

    def save_manifest(
        self,
        project_id: str,
        document: Any,
        *,
        expected_sha256: str | None = None,
    ) -> dict:
        """Validate, back up and atomically replace ``cartoon.json``.

        ``expected_sha256`` is the digest the editor loaded. If the file changed
        on disk (CLI run, another browser tab) the edit is rejected instead of
        silently overwriting the newer content.
        """
        if not isinstance(document, dict):
            raise StudioError("El manifiesto debe ser un objeto JSON")
        identifier = self.project_id(project_id)
        try:
            storyboard = cartoon_studio.parse_storyboard(document)
        except cartoon_studio.CartoonStudioError as exc:
            raise StudioError(str(exc)) from exc
        if storyboard.project_id != identifier:
            raise StudioError("El project_id del manifiesto no coincide con el proyecto")

        path = self.manifest_path(identifier)
        current = self.manifest_sha256(identifier) if path.is_file() else None
        if expected_sha256 is not None:
            if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(
                expected_sha256
            ):
                raise StudioError("Firma del manifiesto no válida")
            if current != expected_sha256:
                raise StudioError(
                    "El manifiesto cambió en disco desde que lo abriste. "
                    "Recarga el proyecto antes de guardar."
                )
        # Back up only manifests that already exist.
        if current is not None:
            backup = (
                self.project_dir(identifier)
                / "backups"
                / f"cartoon-{time.strftime('%Y%m%d-%H%M%S')}-{current[:8]}.json"
            )
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(path.read_bytes())
        _atomic_json(path, document)
        return {
            "project_id": identifier,
            "manifest_sha256": self.manifest_sha256(identifier),
            "scene_count": len(storyboard.scenes),
        }

    def create(
        self,
        project_id: str,
        title: str = "",
        *,
        style: str = "flat-2d",
        aspect: str = "9:16",
        description: str = "",
        character_preset: str = "tiko",
        character_name: str = "Tiko",
    ) -> dict:
        identifier = self.project_id(project_id)
        directory = self.project_dir(identifier)
        if (directory / "cartoon.json").exists():
            raise StudioError(f"El proyecto ya existe: {identifier}")
        if character_preset not in CHARACTER_PRESETS:
            choices = ", ".join(sorted(CHARACTER_PRESETS))
            raise StudioError(f"Personaje no disponible; usa uno de: {choices}")
        title = _text(title, "Título", 200) or identifier
        document = {
            "project_id": identifier,
            "title": title,
            "style": style,
            "aspect": aspect,
            "characters": [
                {
                    "name": character_name,
                    "description": "personaje articulado del estudio 2D",
                }
            ],
            "animation": {"characters": [{"id": character_name.lower(), "preset": character_preset}]},
            "scenes": [
                {
                    "id": "escena-01",
                    "visual": "Tiko saluda en un jardín colorido",
                    "narration": "",
                    "duration": 5,
                    "characters": [character_name],
                    "animation": {
                        "background": "garden",
                        "character": character_name.lower(),
                        "x": 0.5,
                        "y": 0.7,
                        "scale": 0.95,
                        "expression": "happy",
                        "lip_sync": True,
                        "actions": [{"animation": "wave", "at": 0.3}],
                        "props": [],
                    },
                }
            ],
        }
        directory.mkdir(parents=True, exist_ok=True)
        self.save_manifest(identifier, document)
        settings = dict(DEFAULT_SETTINGS)
        settings["description"] = _text(description, "Descripción", 2000)
        self.save_settings(identifier, settings)
        return {"project_id": identifier, "path": str(directory)}

    def duplicate(
        self, source_id: str, target_id: str, title: str | None = None
    ) -> dict:
        source = self.project_dir(source_id)
        target = self.project_dir(target_id)
        if (target / "cartoon.json").exists():
            raise StudioError(f"El proyecto ya existe: {target_id}")
        document = self.read_manifest(source_id)
        document["project_id"] = target_id
        if title is not None:
            document["title"] = _text(title, "Título", 200)
        target.mkdir(parents=True, exist_ok=True)
        self.save_manifest(target_id, document)
        copied = dict(DEFAULT_SETTINGS)
        source_settings = source / "studio.json"
        if source_settings.is_file():
            try:
                copied.update(self.settings(source_id))
            except StudioError:
                pass
        copied["archived"] = False
        self.save_settings(target_id, copied)
        return {"project_id": target_id, "path": str(target)}

    def move_scene(self, project_id: str, scene_id: str, offset: int) -> dict:
        document = self.read_manifest(project_id)
        scenes = document.get("scenes")
        if not isinstance(scenes, list):
            raise StudioError("El manifiesto no tiene escenas")
        index = next(
            (i for i, scene in enumerate(scenes) if scene.get("id") == scene_id), None
        )
        if index is None:
            raise StudioError(f"Escena no encontrada: {scene_id}")
        destination = index + int(offset)
        if not 0 <= destination < len(scenes):
            raise StudioError("La escena ya está en el extremo")
        scenes[index], scenes[destination] = scenes[destination], scenes[index]
        expected = self.manifest_sha256(project_id)
        self.save_manifest(project_id, document, expected_sha256=expected)
        return {"scenes": [scene.get("id") for scene in scenes]}

    # -- studio settings ----------------------------------------------

    def _settings_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "studio.json"

    def settings(self, project_id: str) -> dict:
        path = self._settings_path(project_id)
        values = dict(DEFAULT_SETTINGS)
        if path.is_file():
            try:
                with path.open(encoding="utf-8") as source:
                    stored = json.load(source)
            except (OSError, json.JSONDecodeError):
                stored = {}
            if isinstance(stored, dict):
                values.update(
                    {key: stored[key] for key in DEFAULT_SETTINGS if key in stored}
                )
        return values

    def save_settings(self, project_id: str, values: dict) -> dict:
        if not isinstance(values, dict):
            raise StudioError("La configuración debe ser un objeto")
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise StudioError(
                f"Campos de configuración desconocidos: {', '.join(sorted(unknown))}"
            )
        merged = self.settings(project_id)
        merged.update(values)
        merged["description"] = _text(merged["description"], "Descripción", 2000)
        merged["reviewer"] = _text(merged["reviewer"], "Revisor", 120)
        merged["voice"] = _text(merged["voice"], "Voz", 200)
        merged["voice_rate"] = _number(merged["voice_rate"], "Velocidad de voz", 0.5, 2.0)
        merged["subtitles"] = bool(merged["subtitles"])
        merged["subtitle_font_size"] = int(
            _number(merged["subtitle_font_size"], "Tamaño de subtítulos", 16, 160)
        )
        if merged["mode"] not in {"auto", "classic", "animation"}:
            raise StudioError("El modo debe ser auto, classic o animation")
        merged["fps"] = int(_number(merged["fps"], "FPS", 1, 60))
        merged["crf"] = int(_number(merged["crf"], "CRF", 0, 51))
        for key in ("output_width", "output_height"):
            if merged[key] is not None:
                merged[key] = int(_number(merged[key], key, 64, 4320))
        merged["archived"] = bool(merged["archived"])
        _atomic_json(self._settings_path(project_id), merged)
        return merged

    def archive(self, project_id: str, archived: bool = True) -> dict:
        return self.save_settings(project_id, {"archived": bool(archived)})

    # -- projects ------------------------------------------------------

    def projects(self, *, include_archived: bool = True) -> list[dict]:
        entries: list[dict] = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or not (directory / "cartoon.json").is_file():
                continue
            try:
                document = self.read_manifest(directory.name)
                storyboard = cartoon_studio.parse_storyboard(document)
                settings = self.settings(directory.name)
                export = self.export(directory.name)
                approval = self.approval(directory.name)
            except (StudioError, OSError, cartoon_studio.CartoonStudioError) as exc:
                entries.append(
                    {
                        "id": directory.name,
                        "title": directory.name,
                        "error": str(exc),
                        "archived": False,
                    }
                )
                continue
            if settings.get("archived") and not include_archived:
                continue
            entries.append(
                {
                    "id": storyboard.project_id,
                    "title": storyboard.title,
                    "description": settings.get("description", ""),
                    "aspect": storyboard.aspect.value,
                    "style": storyboard.style_name,
                    "scene_count": len(storyboard.scenes),
                    "animated": storyboard.animation is not None
                    or any(scene.animation is not None for scene in storyboard.scenes),
                    "updated_at": (directory / "cartoon.json").stat().st_mtime,
                    "archived": bool(settings.get("archived")),
                    "export": export,
                    "approval": approval,
                }
            )
        return entries

    # -- revisions and exports ---------------------------------------

    def revisions(self, project_id: str) -> list[dict]:
        directory = self.project_dir(project_id) / "revisions"
        if not directory.is_dir():
            return []
        current = None
        metadata = self.project_dir(project_id) / "project.json"
        if metadata.is_file():
            try:
                current = json.loads(metadata.read_text(encoding="utf-8")).get(
                    "current_revision"
                )
            except (OSError, json.JSONDecodeError):
                current = None
        revisions = []
        for folder in directory.iterdir():
            status_path = folder / "status.json"
            if not folder.is_dir() or not status_path.is_file():
                continue
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            export = status.get("export") if isinstance(status, dict) else None
            revisions.append(
                {
                    "revision_id": folder.name,
                    "state": status.get("state", "unknown"),
                    "promoted": bool(status.get("promoted")),
                    "current": folder.name == current,
                    "error": status.get("error", ""),
                    "failed_stage": status.get("failed_stage", ""),
                    "export": self._export_info(project_id, export),
                    "updated_at": status_path.stat().st_mtime,
                }
            )
        revisions.sort(key=lambda item: item["updated_at"], reverse=True)
        return revisions

    def _export_info(self, project_id: str, export: Any) -> dict | None:
        if not isinstance(export, dict) or not export.get("path"):
            return None
        try:
            path = self._confined(project_id, export["path"])
        except StudioError:
            return None
        exists = path.is_file()
        return {
            "revision_id": export.get("revision_id", ""),
            "path": str(path),
            "filename": path.name,
            "sha256": export.get("sha256", ""),
            "size": export.get("size", path.stat().st_size if exists else 0),
            "exists": exists,
        }

    def export(self, project_id: str) -> dict | None:
        metadata_path = self.project_dir(project_id) / "project.json"
        if not metadata_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        export = metadata.get("last_successful_export")
        info = self._export_info(project_id, export)
        if info and info["exists"]:
            return info
        return None

    def history(self, project_id: str) -> list[dict]:
        """Exported artifacts with their approval record, newest first."""
        entries = []
        for revision in self.revisions(project_id):
            if revision["export"] and revision["export"]["exists"]:
                entries.append(
                    {
                        **revision["export"],
                        "revision_id": revision["revision_id"],
                        "state": revision["state"],
                    }
                )
        return entries

    # -- approvals ----------------------------------------------------

    def _approvals_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "approvals.json"

    def approvals(self, project_id: str) -> list[dict]:
        path = self._approvals_path(project_id)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = data.get("records") if isinstance(data, dict) else None
        return [record for record in records or [] if isinstance(record, dict)]

    def _content_identity(self, project_id: str) -> dict:
        settings = self.settings(project_id)
        render_settings = {key: settings.get(key) for key in _RENDER_SETTING_KEYS}
        encoded = json.dumps(render_settings, sort_keys=True).encode("utf-8")
        return {
            "storyboard_sha256": self.manifest_sha256(project_id),
            "settings_sha256": hashlib.sha256(encoded).hexdigest(),
        }

    def approval(self, project_id: str) -> dict:
        """State of the latest exported revision, invalidated on any change."""
        export = self.export(project_id)
        records = self.approvals(project_id)
        latest = records[-1] if records else None
        if export is None:
            return {
                "state": "draft",
                "label": "Borrador",
                "valid": False,
                "record": latest,
                "stale": bool(latest and latest.get("status") == "approved"),
            }
        stale = False
        if latest is None:
            state, label = "pending_review", "Pendiente de revisión"
        else:
            identity = self._content_identity(project_id)
            matches = (
                latest.get("revision_id") == export["revision_id"]
                and latest.get("artifact_sha256") == export.get("sha256")
                and latest.get("storyboard_sha256") == identity["storyboard_sha256"]
                and latest.get("settings_sha256") == identity["settings_sha256"]
            )
            stale = not matches and latest.get("status") == "approved"
            if not matches:
                state, label = "pending_review", "Pendiente de revisión"
            elif latest.get("status") == "approved":
                state, label = "approved", "Aprobado"
            elif latest.get("status") == "rejected":
                state, label = "rejected", "Rechazado"
            else:
                state, label = "changes_requested", "Cambios solicitados"
        return {
            "state": state,
            "label": label,
            "valid": state == "approved",
            "record": latest,
            "stale": stale,
            "export": export,
        }

    def decide(
        self,
        project_id: str,
        action: str,
        *,
        reviewer: str = "",
        note: str = "",
        revision_id: str | None = None,
    ) -> dict:
        """Record an approval decision tied to the current artifact bytes."""
        if action not in DECISIONS:
            raise StudioError("La decisión debe ser approve, request_changes o reject")
        export = self.export(project_id)
        if export is None:
            raise StudioError("No hay un video exportado para revisar")
        if revision_id and revision_id != export["revision_id"]:
            raise StudioError(
                "La revisión indicada no es la exportación actual; "
                "aprueba solo el artefacto vigente"
            )
        path = self._confined(project_id, export["path"])
        if not path.is_file():
            raise StudioError("El artefacto aprobado no existe en disco")
        actual = _sha256_file(path)
        if export.get("sha256") and actual != export["sha256"]:
            raise StudioError(
                "El archivo del video no coincide con la exportación registrada; "
                "vuelve a renderizar antes de aprobar"
            )
        identity = self._content_identity(project_id)
        record = {
            "revision_id": export["revision_id"],
            "artifact_path": export["path"],
            "artifact_sha256": actual,
            "storyboard_sha256": identity["storyboard_sha256"],
            "settings_sha256": identity["settings_sha256"],
            "status": {
                "approve": "approved",
                "request_changes": "changes_requested",
                "reject": "rejected",
            }[action],
            "reviewer": _text(reviewer, "Revisor", 120),
            "note": _text(note, "Nota", 2000),
            "decided_at": time.time(),
        }
        records = self.approvals(project_id)
        records.append(record)
        _atomic_json(
            self._approvals_path(project_id),
            {"schema_version": APPROVAL_SCHEMA, "records": records},
        )
        return record

    # -- character library and previews -------------------------------

    def characters(self) -> list[dict]:
        """Only presets that actually exist in the engine."""
        entries = []
        for preset in sorted(CHARACTER_PRESETS):
            try:
                character = get_character(preset)
            except AnimationError as exc:  # pragma: no cover - broken preset
                entries.append({"id": preset, "error": str(exc)})
                continue
            entries.append(
                {
                    "id": preset,
                    "name": character.name,
                    "parts": [part.name for part in character.layered()],
                    "part_count": len(character.parts),
                    "canvas": list(character.canvas),
                    "expressions": list(expression_names()),
                    "animations": list(animation_names()),
                }
            )
        return entries

    def render_character_preview(
        self, preset: str = "tiko", expression: str = "neutral"
    ) -> str:
        character = get_character(preset)
        pose = apply_expression(Pose(), expression)
        sprite = render_character(character, pose)
        directory = self.root / ".previews"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"character-{preset}-{expression}.png"
        if not target.is_file():
            sprite.save(target, format="PNG")
        return str(target)

    def render_scene_preview(
        self, project_id: str, scene_id: str, time_seconds: float = 1.0
    ) -> dict:
        """Render one composed frame; never builds the full episode."""
        loaded = self.load(project_id)
        storyboard = loaded["storyboard"]
        scene = next(
            (item for item in storyboard.scenes if item.id == scene_id), None
        )
        if scene is None:
            raise StudioError(f"Escena no encontrada: {scene_id}")
        if scene.animation is None:
            raise StudioError(
                "La escena no tiene animación; añade una para previsualizar un fotograma"
            )
        try:
            project_animation, scenes = cartoon_studio.animation_context(storyboard)
            settings = cartoon_studio.animation_render_settings(storyboard.aspect)
            plan = build_plan(
                scenes[scene_id],
                project_animation.characters,
                scene.duration,
                settings,
            )
        except (AnimationError, cartoon_studio.CartoonStudioError) as exc:
            raise StudioError(str(exc)) from exc
        seconds = _number(time_seconds, "Tiempo", 0.0, float(scene.duration))
        target = (
            self.project_dir(project_id)
            / "previews"
            / f"{scene_id}-{seconds:g}s-{loaded['manifest_sha256'][:8]}.png"
        )
        if not target.is_file():
            render_still(plan, seconds, str(target))
        return {
            "scene": scene_id,
            "time": seconds,
            "path": str(target),
            "duration": scene.duration,
        }

    def render_pose_preview(
        self, preset: str = "tiko", animation: str = "idle", time_seconds: float = 1.0
    ) -> str:
        """Render a named built-in animation at one instant, as a PNG."""
        from app.services.cartoon_animation import get_animation

        character = get_character(preset)
        clip = get_animation(animation)
        seconds = _number(time_seconds, "Tiempo", 0.0, float(clip.duration))
        # Missing channels fall back to the pose defaults, which is exactly the
        # pose the scene compositor starts from.
        pose = Pose(sample_animation(clip, seconds))
        sprite = render_character(character, pose)
        directory = self.root / ".previews"
        directory.mkdir(parents=True, exist_ok=True)
        target = (
            directory
            / f"pose-{preset}-{animation}-{seconds:g}s-{self._digest(animation)}.png"
        )
        if not target.is_file():
            sprite.save(target, format="PNG")
        return str(target)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]

    def render_settings(self, project_id: str) -> RenderSettings:
        loaded = self.load(project_id)
        settings = loaded["settings"]
        return cartoon_studio.animation_render_settings(
            loaded["storyboard"].aspect,
            fps=settings["fps"],
            crf=settings["crf"],
            output_width=settings["output_width"],
            output_height=settings["output_height"],
        )


def default_store() -> StudioStore:
    return StudioStore()


__all__ = [
    "DECISIONS",
    "DEFAULT_SETTINGS",
    "ProjectError",
    "StudioError",
    "StudioStore",
    "default_store",
]
