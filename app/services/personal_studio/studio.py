"""Estudio personal: proyectos, narración, render de los 7 modos y aprobación.

Un proyecto vive en ``storage/personal_studio/projects/<id>`` con
``project.json``, ``assets/`` y ``outputs/``. Nada se publica: exportar copia
archivos locales y escribe ``publication.json`` con ``auto_publish: false``.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from app.services.personal_studio import audio, compose, engines, social, visuals
from app.services.personal_studio.avatars import AvatarStore, _backdrop
from app.services.personal_studio.presets import (
    ASPECT_SIZES,
    NARRATION_STYLES,
    PLATFORMS,
    PRODUCTION_MODES,
    QUALITY_PROFILES,
    SCENES,
)
from app.services.personal_studio.security import (
    StudioError,
    atomic_json,
    confined_path,
    delete_tree,
    digest_file,
    ensure_private,
    read_json,
    require_consent,
    safe_identifier,
    studio_root,
    timestamp,
)
from app.services.personal_studio.voice_profiles import VoiceStore

PROJECT_FIELDS = {
    "name",
    "description",
    "topic",
    "script",
    "keywords",
    "voice_id",
    "avatar_id",
    "style",
    "mode",
    "scene",
    "platform",
    "quality",
    "aspect",
    "fps",
    "subtitles",
    "music",
    "logo",
    "cta",
    "images",
    "logo_position",
    "music_gain",
}

PROJECT_DEFAULTS = {
    "description": "",
    "topic": "",
    "script": "",
    "keywords": [],
    "voice_id": "",
    "avatar_id": "",
    "style": "conversacional",
    "mode": "presentador",
    "scene": "estudio",
    "platform": "instagram_reels",
    "quality": "equilibrado",
    "aspect": "9:16",
    "subtitles": True,
    "music": "",
    "logo": "",
    "cta": "Escríbenos para conocer más.",
    "images": [],
    "logo_position": "br",
    "music_gain": 0.18,
}

ASSET_KINDS = {
    "image": ((".jpg", ".jpeg", ".png", ".webp"), 25 * 1024 * 1024),
    "cover": ((".jpg", ".jpeg", ".png", ".webp"), 25 * 1024 * 1024),
    "logo": ((".png", ".jpg", ".jpeg", ".webp"), 10 * 1024 * 1024),
    "music": ((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"), 50 * 1024 * 1024),
}


class ProjectError(StudioError):
    pass


def _text(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ProjectError(f"{field} debe ser texto")
    value = value.strip()
    if required and not value:
        raise ProjectError(f"{field} es obligatorio")
    if len(value) > limit:
        raise ProjectError(f"{field} no puede superar {limit} caracteres")
    return value


def _choice(value: Any, options: dict, field: str, default: str) -> str:
    value = str(value or default)
    if value not in options:
        raise ProjectError(f"{field} no es válido: {value}")
    return value


def _keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.replace("\n", ",").split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        raise ProjectError("keywords debe ser una lista o texto separado por comas")
    result: list[str] = []
    for item in items:
        if not item:
            continue
        if len(item) > 30:
            raise ProjectError("Cada palabra clave debe tener máximo 30 caracteres")
        if item not in result:
            result.append(item)
    if len(result) > 15:
        raise ProjectError("Máximo 15 palabras clave")
    return result


def _assignable(value: Any) -> str:
    if value in (None, ""):
        return ""
    return safe_identifier(str(value), "referencia")


def normalize_project(payload: Any, *, partial: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ProjectError("Los datos del proyecto deben ser un objeto")
    unknown = set(payload) - PROJECT_FIELDS
    if unknown:
        raise ProjectError("Campos no permitidos: " + ", ".join(sorted(unknown)))
    data = {} if partial else dict(PROJECT_DEFAULTS)
    if "name" in payload:
        data["name"] = _text(payload.get("name"), "nombre", 80, required=True)
    elif not partial:
        raise ProjectError("El nombre del proyecto es obligatorio")
    if "description" in payload:
        data["description"] = _text(payload.get("description"), "descripción", 500)
    if "topic" in payload:
        data["topic"] = _text(payload.get("topic"), "tema", 200)
    if "script" in payload:
        data["script"] = _text(payload.get("script"), "guion", 20000)
    if "keywords" in payload:
        data["keywords"] = _keywords(payload.get("keywords"))
    if "voice_id" in payload:
        data["voice_id"] = _assignable(payload.get("voice_id"))
    if "avatar_id" in payload:
        data["avatar_id"] = _assignable(payload.get("avatar_id"))
    if "style" in payload:
        data["style"] = _choice(payload.get("style"), NARRATION_STYLES, "estilo", "conversacional")
    if "mode" in payload:
        data["mode"] = _choice(payload.get("mode"), PRODUCTION_MODES, "modo", "presentador")
    if "scene" in payload:
        data["scene"] = _choice(payload.get("scene"), SCENES, "escenario", "estudio")
    if "platform" in payload:
        data["platform"] = _choice(payload.get("platform"), PLATFORMS, "plataforma", "instagram_reels")
    if "quality" in payload:
        data["quality"] = _choice(payload.get("quality"), QUALITY_PROFILES, "calidad", "equilibrado")
    if "aspect" in payload and payload.get("aspect"):
        data["aspect"] = _choice(payload.get("aspect"), ASPECT_SIZES, "relación de aspecto", "9:16")
    if "fps" in payload:
        try:
            fps = int(payload.get("fps"))
        except (TypeError, ValueError) as exc:
            raise ProjectError("fps debe ser un entero entre 12 y 30") from exc
        if not 12 <= fps <= 30:
            raise ProjectError("fps debe ser un entero entre 12 y 30")
        data["fps"] = fps
    if "subtitles" in payload:
        data["subtitles"] = bool(payload.get("subtitles"))
    for key in ("music", "logo"):
        if key in payload:
            data[key] = _text(payload.get(key), key, 200)
    if "cta" in payload:
        data["cta"] = _text(payload.get("cta"), "llamada a la acción", 160)
    if "images" in payload:
        images = payload.get("images") or []
        if not isinstance(images, (list, tuple)):
            raise ProjectError("images debe ser una lista")
        data["images"] = [_text(item, "imagen", 200) for item in images][:20]
    if "logo_position" in payload:
        data["logo_position"] = _choice(
            payload.get("logo_position"),
            {"br": 1, "bl": 1, "tr": 1, "tl": 1},
            "posición del logotipo",
            "br",
        )
    if "music_gain" in payload:
        try:
            gain = float(payload.get("music_gain"))
        except (TypeError, ValueError) as exc:
            raise ProjectError("music_gain debe ser un número entre 0 y 1") from exc
        if not 0.0 <= gain <= 1.0:
            raise ProjectError("music_gain debe estar entre 0 y 1")
        data["music_gain"] = round(gain, 3)
    return data


def output_size(project: dict) -> tuple[int, int]:
    quality = QUALITY_PROFILES[project["quality"]]
    base = ASPECT_SIZES.get(project.get("aspect") or PLATFORMS[project["platform"]]["aspect"])
    if not base:
        raise ProjectError("Relación de aspecto no soportada")
    scale = min(1.0, quality["max_height"] / float(base[1]))
    width = int(round(base[0] * scale / 2.0)) * 2
    height = int(round(base[1] * scale / 2.0)) * 2
    return max(2, width), max(2, height)


def project_fps(project: dict) -> int:
    return int(project.get("fps") or QUALITY_PROFILES[project["quality"]]["fps"])


class ProjectStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or studio_root()).resolve()
        self.projects = confined_path(self.root, "projects")
        self.projects.mkdir(parents=True, exist_ok=True)
        self.exports = confined_path(self.root, "exports")
        self.exports.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        identifier = safe_identifier(project_id, "proyecto")
        directory = confined_path(self.projects, identifier)
        if not directory.is_dir():
            raise ProjectError(f"El proyecto no existe: {identifier}")
        return directory

    def _path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def get(self, project_id: str) -> dict:
        return read_json(self._path(project_id))

    def list(self) -> list[dict]:
        items = []
        for entry in sorted(self.projects.iterdir()):
            path = entry / "project.json"
            if not path.is_file():
                continue
            try:
                items.append(read_json(path))
            except StudioError:
                continue
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return items

    def _save(self, project: dict) -> dict:
        project["updated_at"] = timestamp()
        atomic_json(self._path(project["id"]), project)
        return project

    def create(self, payload: dict) -> dict:
        data = normalize_project(payload)
        identifier = f"p_{uuid.uuid4().hex[:10]}"
        directory = confined_path(self.projects, identifier)
        (directory / "assets").mkdir(parents=True, exist_ok=False)
        (directory / "outputs").mkdir(parents=True, exist_ok=False)
        ensure_private(directory)
        project = {
            "schema_version": 1,
            "id": identifier,
            **data,
            "state": "draft",
            "approval": None,
            "narration": None,
            "render": None,
            "warnings": [],
            "created_at": timestamp(),
            "updated_at": timestamp(),
        }
        self._save(project)
        return project

    def update(self, project_id: str, payload: dict) -> dict:
        project = self.get(project_id)
        changes = normalize_project(payload, partial=True)
        if "voice_id" in changes and changes["voice_id"] != project.get("voice_id"):
            project["approval"] = None
        for key, value in changes.items():
            project[key] = value
        if changes:
            project["state"] = "draft" if project.get("state") == "rendered" else project.get("state")
            project["approval"] = None
        return self._save(project)

    def delete(self, project_id: str) -> None:
        self.project_dir(project_id)
        delete_tree(self.projects, project_id)

    # -- activos -------------------------------------------------------
    def add_asset(self, project_id: str, kind: str, filename: str, payload: bytes) -> dict:
        project = self.get(project_id)
        if kind not in ASSET_KINDS:
            raise ProjectError(f"Tipo de activo no soportado: {kind}")
        extensions, limit = ASSET_KINDS[kind]
        suffix = Path(str(filename or "")).suffix.lower()
        if suffix not in extensions:
            raise ProjectError(f"Formato no admitido para {kind}: {sys_extensions(extensions)}")
        if not payload:
            raise ProjectError("El archivo está vacío")
        if len(payload) > limit:
            raise ProjectError(f"El archivo supera {limit // (1024 * 1024)} MB")
        directory = self.project_dir(project_id) / "assets"
        count = len([item for item in directory.iterdir() if item.is_file()]) + 1
        stem = audio.safe_stem(filename, kind)
        name = f"{kind}-{count:02d}-{stem}{suffix}"
        target = confined_path(directory, name)
        target.write_bytes(payload)
        ensure_private(target)
        if kind == "image":
            project["images"] = [*(project.get("images") or []), name]
        elif kind == "logo":
            project["logo"] = name
        elif kind == "music":
            project["music"] = name
        project["approval"] = None
        project["state"] = "draft"
        self._save(project)
        return {"name": name, "kind": kind, "size": len(payload)}

    def asset_path(self, project_id: str, name: str) -> Path:
        if not name:
            raise ProjectError("El activo no tiene nombre")
        path = confined_path(self.project_dir(project_id) / "assets", name)
        if not path.is_file():
            raise ProjectError(f"El activo no existe: {name}")
        return path

    def output_path(self, project_id: str, name: str) -> Path:
        return confined_path(self.project_dir(project_id) / "outputs", name)


def sys_extensions(extensions: tuple[str, ...]) -> str:
    return ", ".join(extensions)


def fingerprint(project: dict) -> str:
    """Identidad del contenido aprobado: si algo cambia, la aprobación caduca."""
    parts = [
        str(project.get("script") or ""),
        str(project.get("mode") or ""),
        str(project.get("style") or ""),
        str(project.get("scene") or ""),
        str(project.get("platform") or ""),
        str(project.get("quality") or ""),
        str(project.get("aspect") or ""),
        str(project.get("fps") or ""),
        "1" if project.get("subtitles") else "0",
        str(project.get("voice_id") or ""),
        str(project.get("avatar_id") or ""),
        str(project.get("cta") or ""),
        str(project.get("logo") or ""),
        str(project.get("music") or ""),
        str(project.get("music_gain") or ""),
        ",".join(project.get("images") or []),
        str((project.get("narration") or {}).get("sha256") or ""),
        str((project.get("render") or {}).get("sha256") or ""),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def approval_state(project: dict) -> dict:
    approval = project.get("approval") or {}
    current = fingerprint(project)
    approved = bool(approval.get("decision") == "approve" and approval.get("fingerprint") == current)
    return {
        "approved": approved,
        "stale": bool(approval and approval.get("fingerprint") != current),
        "decision": approval.get("decision"),
        "reviewer": approval.get("reviewer"),
        "note": approval.get("note"),
        "at": approval.get("at"),
    }


def _stage(progress: Callable[[str, float], None] | None, stage: str, value: float = 0.0) -> None:
    if progress is not None:
        progress(stage, max(0.0, min(1.0, value)))


def _cover(project_id: str, store: ProjectStore, project: dict, avatar: dict | None) -> Path:
    size = (1080, 1080)
    canvas = _backdrop(project.get("scene") or "estudio", size)
    image_path = None
    if project.get("avatar_id") and avatar:
        try:
            image_path = AvatarStore(store.root).image(project["avatar_id"], "portrait")
        except StudioError:
            image_path = None
    if image_path is None and project.get("images"):
        try:
            image_path = store.asset_path(project_id, project["images"][0])
        except StudioError:
            image_path = None
    if image_path is not None:
        source = Image.open(image_path).convert("RGB")
        source.thumbnail((880, 880))
        canvas.paste(source, ((size[0] - source.width) // 2, (size[1] - source.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, size[1] - 150, size[0], size[1]), fill=(10, 14, 22))
    target = store.output_path(project_id, "cover.png")
    canvas.save(target, format="PNG")
    return target


def _events(result: dict) -> list[tuple[str, float]]:
    events = []
    for item in result.get("timings") or []:
        events.append((str(item.get("text") or ""), float(item.get("duration") or 0)))
    return events


def _extend_with_silence(narration: Path, seconds: float) -> Path:
    temporary = narration.with_name("silence.wav")
    audio.add_silence(temporary, seconds)
    joined = narration.with_name("narration-extended.wav")
    audio.concat_audio([narration, temporary], joined)
    temporary.unlink(missing_ok=True)
    joined.replace(narration)
    return narration


def build_project(
    project_id: str,
    *,
    store: ProjectStore | None = None,
    voice_store: VoiceStore | None = None,
    avatar_store: AvatarStore | None = None,
    engine: str = "auto",
    progress: Callable[[str, float], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    store = store or ProjectStore()
    project = store.get(project_id)
    mode = PRODUCTION_MODES[project["mode"]]
    voice_store = voice_store or VoiceStore(store.root)
    avatar_store = avatar_store or AvatarStore(store.root)
    if not project.get("script", "").strip():
        raise ProjectError("Escribe un guion antes de generar")
    if not project.get("voice_id"):
        raise ProjectError("Selecciona un perfil de voz aprobado")
    profile = voice_store.get(project["voice_id"])
    require_consent(profile.get("consent"), ("voz",))
    if not profile.get("approved"):
        raise ProjectError("El perfil de voz no está aprobado")
    avatar = None
    if mode["needs_avatar"]:
        if not project.get("avatar_id"):
            raise ProjectError("Este modo necesita un perfil de avatar")
        avatar = avatar_store.get(project["avatar_id"])
        require_consent(avatar.get("consent"), ("imagen",))
    if mode["needs_images"] and not project.get("images"):
        raise ProjectError("Este modo necesita al menos una imagen de apoyo")

    directory = store.project_dir(project_id)
    outputs = directory / "outputs"
    outputs.mkdir(exist_ok=True)
    warnings: list[str] = []

    _stage(progress, "narracion", 0.02)
    narration = outputs / "narration.wav"
    result = engines.synthesize(
        project["script"],
        output=narration,
        profile=profile,
        style=project["style"],
        speed=1.0,
        engine=engine,
        cancel=cancel,
        voice_store=voice_store,
    )
    warnings.extend(result.get("warnings") or [])
    audio.to_mp3(narration, outputs / "narration.mp3")
    events = _events(result)
    duration = float(result.get("duration") or audio.ffprobe_duration(narration))

    if project["mode"] == "publicidad" and project.get("cta"):
        _extend_with_silence(narration, 2.2)
        events = [*events, (project["cta"], 2.2)]
        duration = audio.ffprobe_duration(narration)

    spec = PLATFORMS[project["platform"]]
    if duration > spec["max_seconds"]:
        warnings.append(
            f"La narración dura {duration:.0f} s; {spec['label']} sugiere máximo {spec['max_seconds']} s."
        )

    width, height = output_size(project)
    fps = project_fps(project)
    quality = QUALITY_PROFILES[project["quality"]]
    work = visuals.work_size((width, height), quality["work_width"])
    render_info: dict = {
        "width": width,
        "height": height,
        "fps": fps,
        "duration": round(duration, 3),
        "mode": project["mode"],
        "audio_only": False,
        "quality": project["quality"],
        "quality_verified": quality["verified"],
    }

    music = store.asset_path(project_id, project["music"]) if project.get("music") else None
    logo = store.asset_path(project_id, project["logo"]) if project.get("logo") else None
    subtitles_enabled = bool(project.get("subtitles"))

    if mode["kind"] == "audio":
        _stage(progress, "portada", 0.4)
        _cover(project_id, store, project, avatar)
        _stage(progress, "audio", 1.0)
        video = None
        render_info["audio_only"] = True
        render_info["cover"] = "cover.png"
    else:
        _stage(progress, "animacion", 0.15)
        silent = outputs / "silent.mp4"
        common = {
            "audio_path": narration,
            "destination": silent,
            "size": work,
            "output_size": (width, height),
            "fps": fps,
            "scene": project["scene"],
            "crf": quality["crf"],
            "preset": quality["preset"],
            "cancel": cancel,
            "progress": lambda seconds: _stage(
                progress, "animacion", 0.15 + 0.6 * min(1.0, seconds / max(1.0, duration))
            ),
        }
        images = [store.asset_path(project_id, name) for name in project.get("images") or []]
        if project["mode"] == "caricatura":
            visuals.render_cartoon(
                palette=(avatar or {}).get("cartoon", {}).get("palette", {}),
                **common,
            )
        elif project["mode"] == "hibrido":
            visuals.render_presenter(
                portrait_path=avatar_store.image(avatar["id"], "portrait"),
                face_normalized=(avatar.get("image") or {}).get("face_normalized"),
                slides=images,
                **common,
            )
        elif mode["needs_avatar"]:
            visuals.render_presenter(
                portrait_path=avatar_store.image(avatar["id"], "portrait"),
                face_normalized=(avatar.get("image") or {}).get("face_normalized"),
                **common,
            )
        else:
            visuals.render_slideshow(images=images, **common)

        _stage(progress, "composicion", 0.8)
        video = outputs / "video.mp4"
        compose.finalize(
            silent,
            narration,
            video,
            events=events if subtitles_enabled else None,
            music=music,
            logo=logo,
            logo_position=project.get("logo_position") or "br",
            width=width,
            height=height,
            crf=quality["crf"],
            preset=quality["preset"],
            music_gain=float(project.get("music_gain") or 0.18),
        )
        silent.unlink(missing_ok=True)
        render_info["size_bytes"] = video.stat().st_size
        render_info["sha256"] = digest_file(video)

    compose.write_subtitles(events, outputs / "subtitles.srt", width=width, height=height)

    project["narration"] = {
        "engine": result.get("engine"),
        "cloned": bool(result.get("cloned")),
        "offline": bool(result.get("offline")),
        "watermark": result.get("watermark"),
        "duration": round(duration, 3),
        "sha256": digest_file(narration),
        "timings": result.get("timings") or [],
    }
    project["render"] = render_info
    project["warnings"] = warnings
    project["state"] = "rendered"
    project["approval"] = None
    project["is_minor"] = bool(
        (profile.get("consent") or {}).get("is_minor")
        or ((avatar or {}).get("consent") or {}).get("is_minor")
    )
    # Toda narración de este módulo es sintética, incluso el respaldo Edge TTS:
    # se divulga siempre para cumplir las políticas de contenido generado.
    metadata = social.build_metadata(
        project=project,
        platform=project["platform"],
        duration=duration,
        synthetic=True,
    )
    metadata["warnings"] = [*metadata["warnings"], *warnings]
    atomic_json(outputs / "metadata.json", metadata)
    project = store._save(project)
    _stage(progress, "listo", 1.0)
    return project


def approve(
    project_id: str,
    *,
    reviewer: str,
    decision: str,
    note: str = "",
    store: ProjectStore | None = None,
) -> dict:
    store = store or ProjectStore()
    project = store.get(project_id)
    if decision not in {"approve", "request_changes", "reject"}:
        raise ProjectError("La decisión debe ser approve, request_changes o reject")
    if project.get("state") != "rendered":
        raise ProjectError("Genera el contenido antes de aprobarlo")
    reviewer = _text(reviewer, "revisor", 80, required=True)
    note = _text(note, "nota", 500)
    record = {
        "decision": decision,
        "reviewer": reviewer,
        "note": note,
        "at": timestamp(),
        "fingerprint": fingerprint(project),
        "content_sha256": (project.get("render") or {}).get("sha256")
        or (project.get("narration") or {}).get("sha256"),
    }
    project["approval"] = record
    store._save(project)
    log_path = store.project_dir(project_id) / "approvals.json"
    history = []
    if log_path.is_file():
        try:
            history = (read_json(log_path).get("history") or [])
        except StudioError:
            history = []
    history.append(record)
    atomic_json(log_path, {"history": history})
    return record


def export(project_id: str, *, store: ProjectStore | None = None) -> dict:
    store = store or ProjectStore()
    project = store.get(project_id)
    state = approval_state(project)
    if not state["approved"]:
        raise ProjectError(
            "El contenido no tiene una aprobación vigente. Revisa y aprueba antes de exportar."
        )
    metadata = social.build_metadata(
        project=project,
        platform=project["platform"],
        duration=float((project.get("render") or {}).get("duration") or 0),
        approved_by=str(state.get("reviewer") or ""),
        synthetic=True,
    )
    folder = confined_path(
        store.exports, social.export_folder_name(project, project["platform"])
    )
    folder.mkdir(parents=True, exist_ok=True)
    outputs = store.project_dir(project_id) / "outputs"
    copied = []
    for name in ("video.mp4", "narration.mp3", "narration.wav", "subtitles.srt", "cover.png"):
        source = outputs / name
        if source.is_file():
            shutil.copyfile(source, folder / name)
            copied.append(name)
    atomic_json(folder / "metadata.json", metadata)
    publication = {
        "project_id": project["id"],
        "project_name": project["name"],
        "platform": project["platform"],
        "aspect": metadata["aspect"],
        "approved_by": state.get("reviewer"),
        "approved_at": state.get("at"),
        "fingerprint": state.get("fingerprint") or fingerprint(project),
        "files": copied,
        "ai_disclosure": metadata["ai_disclosure"],
        "auto_publish": False,
        "published": False,
        "exported_at": timestamp(),
    }
    atomic_json(folder / "publication.json", publication)
    return {**publication, "path": str(folder)}


def delete_project(project_id: str, *, store: ProjectStore | None = None) -> None:
    (store or ProjectStore()).delete(project_id)
