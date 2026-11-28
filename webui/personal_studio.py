"""BYNEX AI Personal Studio: sección del panel web existente.

La página es fina: valida formularios, llama a la capa de servicio y muestra
resultados. No importa torch ni ejecuta FFmpeg directamente. Todo el contenido
es local y ninguna acción publica en redes sociales.
"""

from __future__ import annotations

import json

import streamlit as st

from app.services.personal_studio import diagnostics, engines, resources, studio
from app.services.personal_studio.avatars import AvatarStore
from app.services.personal_studio.jobs import (
    CANCELLED,
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    default_manager,
    StudioJobManager,
)
from app.services.personal_studio.presets import (
    ASPECT_SIZES,
    AVATAR_STYLES,
    NARRATION_STYLES,
    PLATFORMS,
    PRODUCTION_MODES,
    QUALITY_PROFILES,
    SCENES,
    VOICE_SAMPLE_SCRIPTS,
)
from app.services.personal_studio.security import StudioError
from app.services.personal_studio.voice_profiles import VoiceStore

_STATE_LABELS = {
    PENDING: "Pendiente",
    RUNNING: "Ejecutando",
    COMPLETED: "Completado",
    FAILED: "Fallido",
    CANCELLED: "Cancelado",
}


def _flash(kind: str, message: str) -> None:
    st.session_state["bynnex_flash"] = (kind, message)


def _render_flash() -> None:
    value = st.session_state.pop("bynnex_flash", None)
    if value:
        kind, message = value
        getattr(st, kind, st.info)(message)


def _voice_store() -> VoiceStore:
    return VoiceStore()


def _avatar_store() -> AvatarStore:
    return AvatarStore()


def _project_store() -> studio.ProjectStore:
    return studio.ProjectStore()


def _voice_options(store: VoiceStore) -> dict[str, str]:
    return {
        f"{item['name']} · {'aprobado' if item.get('approved') else item.get('status', 'borrador')}": item["id"]
        for item in store.list()
    }


def _avatar_options(store: AvatarStore) -> dict[str, str]:
    return {
        f"{item['name']} · {item.get('style_label', item.get('style'))}": item["id"]
        for item in store.list()
    }


def _consent_widgets(prefix: str, *, voice: bool) -> dict:
    st.markdown("**Autorización de uso**")
    subject = st.text_input("Nombre del titular", key=f"{prefix}_subject")
    granted = st.checkbox(
        "Confirmo que soy el titular o tengo autorización verificable para usar "
        + ("esta voz" if voice else "esta imagen"),
        key=f"{prefix}_granted",
    )
    age = st.checkbox("Confirmo que el titular es mayor de edad", key=f"{prefix}_age")
    minor = st.checkbox("El titular es menor de edad", key=f"{prefix}_minor")
    guardian = ""
    if minor:
        guardian = st.text_input("Nombre del padre, madre o tutor", key=f"{prefix}_guardian")
    return {
        "subject_name": subject,
        "granted": granted,
        "age_confirmed": age,
        "is_minor": minor,
        "guardian_name": guardian,
        "scope": ["voz"] if voice else ["imagen"],
    }


def _format_metrics(item: dict) -> str:
    return (
        f"{item.get('duration', 0):.1f}s · SNR {item.get('snr_db', 0)} dB · "
        f"nota {item.get('score', 0)}/100 ({item.get('verdict', '—')})"
    )


def _quality_guard() -> bool:
    ok, message = resources.guard()
    if not ok:
        st.warning(message)
    return ok


# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------

def _render_dashboard() -> None:
    voices = _voice_store().list()
    avatars = _avatar_store().list()
    projects = _project_store().list()
    jobs = default_manager().list()
    report = diagnostics.smoke_test()

    columns = st.columns(4)
    columns[0].metric("Perfiles de voz", len(voices))
    columns[1].metric("Avatares", len(avatars))
    columns[2].metric("Proyectos", len(projects))
    columns[3].metric("Trabajos en cola", sum(1 for job in jobs if job["state"] in {PENDING, RUNNING}))

    if report["ok"]:
        st.success("Entorno listo: voz local, FFmpeg y memoria disponibles.")
    else:
        for check in report["checks"]:
            if not check["ok"]:
                st.error(f"{check['name']}: {check['detail']}")

    st.markdown("#### Flujo de trabajo")
    st.markdown(
        "1. **Mi voz**: crea un perfil, añade muestras, procesa, prueba y aprueba.\n"
        "2. **Mis avatares**: crea un avatar con una foto autorizada.\n"
        "3. **Estudio personal**: escribe el guion, elige voz y avatar, genera y revisa.\n"
        "4. **Aprobaciones**: aprueba el contenido final.\n"
        "5. **Exportaciones**: copia local con metadatos; publicar sigue siendo manual."
    )
    if not voices:
        st.info("Empieza creando tu perfil de voz en la pestaña **Mi voz**.")


# ---------------------------------------------------------------------------
# Mi voz
# ---------------------------------------------------------------------------

def _render_voice_tab() -> None:
    store = _voice_store()
    st.markdown("#### Perfil de voz")
    options = _voice_options(store)
    selected_id = None
    if options:
        labels = list(options)
        preferred = st.session_state.get("bynnex_voice_selected_id")
        index = next(
            (i for i, label in enumerate(labels) if options[label] == preferred), 0
        )
        label = st.selectbox("Perfil", labels, index=index, key="bynnex_voice_selected")
        selected_id = options[label]

    with st.expander("➕ Crear perfil de voz", expanded=not options):
        st.caption(
            "Necesitas al menos 10 segundos de voz clara. La grabación se procesa en "
            "tu equipo; solo la narración de respaldo Edge TTS envía texto a Microsoft."
        )
        sample_key = st.selectbox(
            "Texto guía para la muestra", list(VOICE_SAMPLE_SCRIPTS), key="bynnex_voice_script"
        )
        st.info(VOICE_SAMPLE_SCRIPTS[sample_key])
        name = st.text_input("Nombre del perfil", key="bynnex_voice_name")
        language = st.selectbox("Idioma", ["es"], format_func=lambda value: "Español (Colombia)", key="bynnex_voice_lang")
        notes = st.text_area("Notas", key="bynnex_voice_notes", height=70)
        consent = _consent_widgets("bynnex_voice_consent", voice=True)
        if st.button("Crear perfil", key="bynnex_voice_create"):
            try:
                created = store.create(
                    name=name, language=language, consent=consent, notes=notes,
                    is_minor=bool(consent.get("is_minor")),
                )
            except StudioError as exc:
                st.error(str(exc))
            else:
                st.session_state["bynnex_voice_selected_id"] = created["id"]
                _flash("success", "Perfil creado. Añade muestras de voz.")
                st.rerun()

    if not selected_id:
        return
    try:
        profile = store.get(selected_id)
    except StudioError as exc:
        st.error(str(exc))
        return

    st.markdown(f"**{profile['name']}** · estado: `{profile.get('status')}` · "
                f"{'aprobado' if profile.get('approved') else 'sin aprobar'}")
    if profile.get("processed"):
        processed = profile["processed"]
        st.caption(
            f"Referencia: {processed['duration']:.1f}s · {processed['sample_count']} muestra(s) · "
            f"calidad {processed['metrics']['verdict']}"
        )

    st.markdown("##### Muestras")
    files = st.file_uploader(
        "Subir WAV, MP3, FLAC o M4A",
        type=["wav", "mp3", "flac", "m4a", "ogg", "aac"],
        accept_multiple_files=True,
        key="bynnex_voice_upload",
    )
    recorded = st.audio_input("o grabar una muestra autorizada", key="bynnex_voice_mic")
    if st.button("Añadir muestras", key="bynnex_voice_add"):
        added = 0
        try:
            for uploaded in files or []:
                store.add_sample(profile["id"], uploaded.name, uploaded.getvalue())
                added += 1
            if recorded is not None:
                store.add_sample(profile["id"], "grabacion.wav", recorded.getvalue())
                added += 1
        except StudioError as exc:
            st.error(str(exc))
        if added:
            _flash("success", f"{added} muestra(s) analizada(s) y limpiada(s).")
            st.rerun()

    for sample in profile.get("samples") or []:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown(f"**Muestra {sample['index']}**")
            left.caption("Original: " + _format_metrics(sample["raw"]))
            left.caption("Limpia: " + _format_metrics(sample["clean"]))
            right.write("")
            if right.button("Quitar", key=f"bynnex_remove_sample_{sample['index']}"):
                try:
                    store.remove_sample(profile["id"], sample["index"])
                except StudioError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            for issue in sample["raw"]["issues"]:
                left.warning(issue)

    columns = st.columns(3)
    if columns[0].button("Procesar muestras", key="bynnex_voice_process", disabled=not profile.get("samples")):
        try:
            store.process(profile["id"])
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", "Referencia de timbre creada.")
            st.rerun()
    if columns[1].button(
        "Aprobar perfil", key="bynnex_voice_approve",
        disabled=profile.get("status") != "ready" or profile.get("approved"),
    ):
        try:
            store.approve(profile["id"])
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", "Perfil aprobado. Ya puede usarse en el estudio.")
            st.rerun()

    st.markdown("##### Vista previa y comparación")
    st.caption(
        "El estilo ajusta ritmo y pausas del texto. MeloTTS no recibe emociones: "
        "no se ofrecen controles que el modelo no soporte."
    )
    preview_text = st.text_area(
        "Texto de prueba", value=VOICE_SAMPLE_SCRIPTS["pronunciacion"], height=100,
        key="bynnex_voice_preview_text",
    )
    preview_style = st.selectbox(
        "Estilo", list(NARRATION_STYLES),
        format_func=lambda value: NARRATION_STYLES[value]["label"], key="bynnex_voice_preview_style",
    )
    if st.button("Generar vista previa", key="bynnex_voice_preview"):
        if profile.get("status") != "ready":
            st.error("Procesa primero las muestras.")
        else:
            try:
                target = store.profile_dir(profile["id"]) / "preview.wav"
                with st.spinner("Sintetizando en CPU (puede tardar ~30 s)…"):
                    result = engines.synthesize(
                        preview_text, output=target, profile=profile, style=preview_style,
                        allow_unapproved=True, voice_store=store,
                    )
            except StudioError as exc:
                st.error(str(exc))
            else:
                st.audio(str(target))
                st.caption(
                    f"Motor: {result['engine']} · clonación: {'sí' if result['cloned'] else 'no'} · "
                    f"{result['duration']:.1f}s · {result['elapsed']}s de proceso"
                )
                for warning in result.get("warnings") or []:
                    st.warning(warning)

    with st.expander("🗑️ Eliminar perfil y archivos derivados"):
        confirm = st.checkbox("Entiendo que se borran muestras, referencia y caché", key="bynnex_voice_delete_confirm")
        if st.button("Eliminar perfil", key="bynnex_voice_delete", disabled=not confirm):
            try:
                store.remove(profile["id"])
            except StudioError as exc:
                st.error(str(exc))
            else:
                _flash("success", "Perfil de voz eliminado del almacenamiento local.")
                st.rerun()


# ---------------------------------------------------------------------------
# Mis avatares
# ---------------------------------------------------------------------------

def _render_avatar_tab() -> None:
    store = _avatar_store()
    st.markdown("#### Avatares personales")
    st.caption(
        "La detección de rostro solo sirve para encuadrar: no identifica personas. "
        "No se recorta el fondo (requiere segmentación no instalada); se usa un "
        "fondo desenfocado o un escenario cartoon."
    )
    with st.expander("➕ Crear avatar", expanded=not store.list()):
        name = st.text_input("Nombre del avatar", key="bynnex_avatar_name")
        style = st.selectbox(
            "Estilo", list(AVATAR_STYLES),
            format_func=lambda value: AVATAR_STYLES[value]["label"], key="bynnex_avatar_style",
        )
        background = st.selectbox(
            "Escenario", list(SCENES), format_func=lambda value: SCENES[value]["label"],
            key="bynnex_avatar_background",
        )
        upload = st.file_uploader(
            "Fotografía (mínimo 512 px por lado)", type=["jpg", "jpeg", "png", "webp", "bmp"],
            key="bynnex_avatar_upload",
        )
        consent = _consent_widgets("bynnex_avatar_consent", voice=False)
        if st.button("Crear avatar", key="bynnex_avatar_create"):
            if upload is None:
                st.error("Sube una fotografía.")
            else:
                try:
                    created = store.create(
                        name=name, style=style, consent=consent, filename=upload.name,
                        payload=upload.getvalue(), background=background,
                    )
                except StudioError as exc:
                    st.error(str(exc))
                else:
                    _flash("success", f"Avatar creado. Rostro: {created['image']['face']['source']}.")
                    st.rerun()

    avatars = store.list()
    if not avatars:
        return
    st.markdown("##### Biblioteca")
    for start in range(0, len(avatars), 3):
        columns = st.columns(3)
        for column, avatar in zip(columns, avatars[start : start + 3]):
            with column:
                st.image(str(store.image(avatar["id"], "thumb")), use_container_width=True)
                st.markdown(f"**{avatar['name']}**")
                st.caption(
                    f"{avatar['style_label']} · nitidez {avatar['image']['sharpness']} · "
                    f"nota {avatar['image']['score']}/100"
                )
                for warning in avatar["image"].get("warnings") or []:
                    st.warning(warning)
                with st.expander("Detalles"):
                    st.json(
                        {
                            "rostro": avatar["image"]["face"],
                            "brillo": avatar["image"]["brightness"],
                            "contraste": avatar["image"]["contrast"],
                            "consentimiento": {
                                "titular": avatar["consent"]["subject_name"],
                                "menor": avatar["consent"]["is_minor"],
                            },
                        }
                    )
                    confirm = st.checkbox("Confirmo borrado", key=f"bynnex_avatar_del_{avatar['id']}")
                    if st.button("Eliminar", key=f"bynnex_avatar_delete_{avatar['id']}", disabled=not confirm):
                        try:
                            store.remove(avatar["id"])
                        except StudioError as exc:
                            st.error(str(exc))
                        else:
                            _flash("success", "Avatar eliminado.")
                            st.rerun()


# ---------------------------------------------------------------------------
# Estudio personal
# ---------------------------------------------------------------------------

def _project_form(store: studio.ProjectStore, current: dict | None, *, mode_default: str | None = None) -> None:
    voices = _voice_options(_voice_store())
    avatars = _avatar_options(_avatar_store())
    value = current or studio.PROJECT_DEFAULTS
    key = f"bynnex_form_{current['id'] if current else 'new'}"

    if not voices:
        st.warning("Crea y aprueba un perfil de voz antes de configurar el proyecto.")

    name = st.text_input("Nombre del proyecto", value=value.get("name", ""), key=f"{key}_name")
    description = st.text_area("Descripción", value=value.get("description", ""), height=70, key=f"{key}_desc")
    topic = st.text_input("Tema del video", value=value.get("topic", ""), key=f"{key}_topic")
    script_text = st.text_area(
        "Guion", value=value.get("script", ""), height=200, key=f"{key}_script",
        help="Escribe el texto completo. Los números se expanden a palabras al narrar.",
    )
    keywords = st.text_input(
        "Palabras clave (separadas por coma)", value=", ".join(value.get("keywords") or []),
        key=f"{key}_keywords",
    )

    left, right = st.columns(2)
    voice_labels = list(voices)
    voice_index = next(
        (i for i, label in enumerate(voice_labels) if voices[label] == value.get("voice_id")), 0
    )
    voice_label = left.selectbox(
        "Perfil de voz", voice_labels or ["Sin perfiles"], index=voice_index if voice_labels else 0,
        key=f"{key}_voice", disabled=not voices,
    )
    avatar_labels = list(avatars)
    avatar_index = next(
        (i for i, label in enumerate(avatar_labels) if avatars[label] == value.get("avatar_id")), 0
    )
    avatar_label = right.selectbox(
        "Perfil de avatar", ["(ninguno)", *avatar_labels],
        index=(avatar_index + 1) if avatar_labels and value.get("avatar_id") else 0,
        key=f"{key}_avatar",
    )

    mode_keys = list(PRODUCTION_MODES)
    mode_index = mode_keys.index(mode_default or value.get("mode", "presentador"))
    mode = st.selectbox(
        "Tipo de video", mode_keys,
        index=mode_index,
        format_func=lambda item: PRODUCTION_MODES[item]["label"], key=f"{key}_mode",
    )
    st.caption(PRODUCTION_MODES[mode]["description"])

    row = st.columns(4)
    style = row[0].selectbox(
        "Estilo narrativo", list(NARRATION_STYLES),
        index=list(NARRATION_STYLES).index(value.get("style", "conversacional")),
        format_func=lambda item: NARRATION_STYLES[item]["label"], key=f"{key}_style",
    )
    scene = row[1].selectbox(
        "Escenario", list(SCENES),
        index=list(SCENES).index(value.get("scene", "estudio")),
        format_func=lambda item: SCENES[item]["label"], key=f"{key}_scene",
    )
    platform = row[2].selectbox(
        "Plataforma", list(PLATFORMS),
        index=list(PLATFORMS).index(value.get("platform", "instagram_reels")),
        format_func=lambda item: PLATFORMS[item]["label"], key=f"{key}_platform",
    )
    quality = row[3].selectbox(
        "Perfil de calidad", list(QUALITY_PROFILES),
        index=list(QUALITY_PROFILES).index(value.get("quality", "equilibrado")),
        format_func=lambda item: QUALITY_PROFILES[item]["label"], key=f"{key}_quality",
    )

    row2 = st.columns(4)
    aspect = row2[0].selectbox(
        "Relación de aspecto", list(ASPECT_SIZES),
        index=list(ASPECT_SIZES).index(value.get("aspect") or PLATFORMS[platform]["aspect"]),
        key=f"{key}_aspect",
    )
    fps = row2[1].number_input(
        "FPS", min_value=12, max_value=30, value=int(value.get("fps") or QUALITY_PROFILES[quality]["fps"]),
        key=f"{key}_fps",
    )
    subtitles = row2[2].checkbox("Subtítulos", value=bool(value.get("subtitles", True)), key=f"{key}_subs")
    cta = row2[3].text_input("Llamada a la acción", value=value.get("cta", ""), key=f"{key}_cta")

    draft = {
        "name": name,
        "description": description,
        "topic": topic,
        "script": script_text,
        "keywords": keywords,
        "voice_id": voices.get(voice_label, ""),
        "avatar_id": avatars.get(avatar_label, ""),
        "mode": mode,
        "style": style,
        "scene": scene,
        "platform": platform,
        "quality": quality,
        "aspect": aspect,
        "fps": int(fps),
        "subtitles": subtitles,
        "cta": cta,
    }
    if current and current.get("logo"):
        draft["logo"] = current["logo"]
    if current and current.get("music"):
        draft["music"] = current["music"]
    draft["images"] = current.get("images") if current else []

    size = None
    try:
        size = studio.output_size({"quality": quality, "aspect": aspect, "platform": platform})
    except StudioError:
        pass
    if size:
        note = "medido" if QUALITY_PROFILES[quality]["verified"] else "sin medir en este equipo"
        st.caption(f"Resolución de salida: {size[0]}×{size[1]} · {fps} fps · perfil {note}.")

    if st.button("Guardar proyecto" if current else "Crear proyecto", type="primary", key=f"{key}_save"):
        try:
            if current:
                updated = store.update(current["id"], draft)
                st.session_state["bynnex_project"] = updated["id"]
                _flash("success", "Proyecto actualizado; la aprobación anterior queda invalidada.")
            else:
                created = store.create(draft)
                st.session_state["bynnex_project"] = created["id"]
                _flash("success", "Proyecto creado.")
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.rerun()


def _render_assets(store: studio.ProjectStore, project: dict) -> None:
    with st.expander("🖼️ Material visual, logotipo y música"):
        images = st.file_uploader(
            "Imágenes o capturas", type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True, key=f"bynnex_images_{project['id']}",
        )
        logo = st.file_uploader("Logotipo BYNEX (PNG con transparencia)", type=["png", "jpg", "jpeg", "webp"], key=f"bynnex_logo_{project['id']}")
        music = st.file_uploader("Música de fondo", type=["mp3", "wav", "m4a", "aac", "ogg", "flac"], key=f"bynnex_music_{project['id']}")
        if st.button("Añadir archivos", key=f"bynnex_add_assets_{project['id']}"):
            try:
                for uploaded in images or []:
                    store.add_asset(project["id"], "image", uploaded.name, uploaded.getvalue())
                if logo is not None:
                    store.add_asset(project["id"], "logo", logo.name, logo.getvalue())
                if music is not None:
                    store.add_asset(project["id"], "music", music.name, music.getvalue())
            except StudioError as exc:
                st.error(str(exc))
            else:
                _flash("success", "Activos añadidos.")
                st.rerun()
        loaded = store.get(project["id"])
        st.caption(f"Imágenes: {len(loaded.get('images') or [])} · "
                   f"Logotipo: {loaded.get('logo') or 'ninguno'} · Música: {loaded.get('music') or 'ninguna'}")
        if loaded.get("images"):
            columns = st.columns(min(3, len(loaded["images"])))
            for column, name in zip(columns, loaded["images"]):
                try:
                    column.image(str(store.asset_path(project["id"], name)), use_container_width=True)
                except StudioError:
                    pass


@st.fragment(run_every=2)
def _job_panel(manager: StudioJobManager, job_id: str, store: studio.ProjectStore) -> None:
    try:
        job = manager.get(job_id)
    except StudioError as exc:
        st.error(str(exc))
        return
    st.progress(float(job.get("progress") or 0.0), text=f"{manager.stage_label(job.get('stage', ''))}")
    st.caption(f"Estado: {_STATE_LABELS.get(job['state'], job['state'])}")
    if job.get("error"):
        st.error(job["error"])
    for warning in job.get("warnings") or []:
        st.warning(warning)
    if job["state"] == COMPLETED:
        _render_outputs(store, job["project_id"])
    elif job["state"] not in {FAILED, CANCELLED}:
        if st.button("Cancelar trabajo", key=f"bynnex_cancel_{job_id}"):
            manager.cancel(job_id)


def _render_outputs(store: studio.ProjectStore, project_id: str) -> None:
    try:
        project = store.get(project_id)
    except StudioError:
        return
    outputs = store.project_dir(project_id) / "outputs"
    video = outputs / "video.mp4"
    if video.is_file():
        st.video(str(video))
    elif (outputs / "narration.mp3").is_file():
        st.audio(str(outputs / "narration.mp3"))
        if (outputs / "cover.png").is_file():
            st.image(str(outputs / "cover.png"), width=320)
    subtitles = outputs / "subtitles.srt"
    if subtitles.is_file():
        with st.expander("Subtítulos (SRT)"):
            st.code(subtitles.read_text(encoding="utf-8"), language="text")
            st.download_button(
                "Descargar SRT", subtitles.read_bytes(), file_name="subtitles.srt",
                key=f"bynnex_srt_{project_id}",
            )
    metadata = outputs / "metadata.json"
    if metadata.is_file():
        with st.expander("Metadatos de publicación"):
            st.json(json.loads(metadata.read_text(encoding="utf-8")))
    state = studio.approval_state(project)
    st.caption(
        "Aprobación vigente" if state["approved"]
        else "Aprobación caducada: el contenido cambió" if state["stale"]
        else "Pendiente de aprobación"
    )


def _render_studio_tab() -> None:
    store = _project_store()
    projects = store.list()
    st.markdown("#### Estudio personal")
    ids = [item["id"] for item in projects]
    labels = {
        item["id"]: f"{item['name']} · {PRODUCTION_MODES.get(item['mode'], {}).get('label', item['mode'])} · {item['state']}"
        for item in projects
    }
    options = ["(nuevo proyecto)", *ids]
    current_id = st.session_state.get("bynnex_project")
    index = options.index(current_id) if current_id in options else 0
    choice = st.selectbox(
        "Proyecto", options, index=index,
        format_func=lambda value: labels.get(value, value), key="bynnex_project_select",
    )
    st.session_state["bynnex_project"] = None if choice == "(nuevo proyecto)" else choice
    current = store.get(choice) if choice in ids else None

    _project_form(store, current)
    if not current:
        return
    _render_assets(store, current)

    st.markdown("##### Generar")
    manager = default_manager()
    active = [job for job in manager.list() if job["project_id"] == current["id"]]
    if st.button("🎬 Generar con la cola", type="primary", key=f"bynnex_generate_{current['id']}"):
        if not _quality_guard():
            st.stop()
        try:
            job = manager.submit(current["id"])
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.session_state["bynnex_job"] = job["id"]
    job_id = st.session_state.get("bynnex_job")
    if job_id and any(job["id"] == job_id for job in active):
        _job_panel(manager, job_id, store)
    elif active:
        _job_panel(manager, active[0]["id"], store)
    elif current.get("state") == "rendered":
        _render_outputs(store, current["id"])


def _render_projects_tab() -> None:
    store = _project_store()
    projects = store.list()
    st.markdown("#### Proyectos y biblioteca multimedia")
    if not projects:
        st.info("Todavía no hay proyectos. Crea uno en **Estudio personal**.")
        return
    for project in projects:
        with st.container(border=True):
            columns = st.columns([3, 1, 1])
            columns[0].markdown(f"**{project['name']}** · `{project['id']}`")
            columns[0].caption(
                f"{PRODUCTION_MODES.get(project['mode'], {}).get('label', project['mode'])} · "
                f"{PLATFORMS.get(project['platform'], {}).get('label', project['platform'])} · "
                f"{project['state']} · imágenes: {len(project.get('images') or [])}"
            )
            state = studio.approval_state(project)
            columns[1].caption("Aprobado" if state["approved"] else "Sin aprobar")
            if columns[2].button("Eliminar", key=f"bynnex_del_project_{project['id']}"):
                try:
                    store.delete(project["id"])
                except StudioError as exc:
                    st.error(str(exc))
                else:
                    _flash("success", "Proyecto eliminado con sus archivos derivados.")
                    st.rerun()


# ---------------------------------------------------------------------------
# Presentador BYNEX
# ---------------------------------------------------------------------------

def _render_presenter_tab() -> None:
    st.markdown("#### Presentador Digital BYNEX")
    st.caption(
        "Flujo corto para presentar servicios, tutoriales o publicidad: guion, voz "
        "autorizada, avatar, escenario y logotipo. Se genera un proyecto normal, "
        "por lo que luego pasa por aprobación y exportación."
    )
    voices = _voice_options(_voice_store())
    avatars = _avatar_options(_avatar_store())
    if not voices or not avatars:
        st.info("Necesitas un perfil de voz aprobado y un avatar para este flujo.")
        return
    with st.form("bynnex_presenter_form"):
        name = st.text_input("Nombre del video", placeholder="Consejo BYNEX: copias de seguridad")
        script_text = st.text_area("Guion", height=180)
        row = st.columns(2)
        voice = row[0].selectbox("Voz", list(voices))
        avatar = row[1].selectbox("Avatar", list(avatars))
        row2 = st.columns(3)
        scene = row2[0].selectbox("Escenario", list(SCENES), format_func=lambda item: SCENES[item]["label"])
        platform = row2[1].selectbox("Plataforma", list(PLATFORMS), format_func=lambda item: PLATFORMS[item]["label"])
        quality = row2[2].selectbox("Calidad", list(QUALITY_PROFILES), format_func=lambda item: QUALITY_PROFILES[item]["label"])
        cta = st.text_input("Llamada a la acción final", value="Escríbenos y te ayudamos.")
        logo = st.file_uploader("Logotipo BYNEX (opcional)", type=["png", "jpg", "jpeg", "webp"])
        music = st.file_uploader("Música de fondo (opcional)", type=["mp3", "wav", "m4a", "ogg"])
        submitted = st.form_submit_button("Crear y generar", type="primary")
    if submitted:
        try:
            store = _project_store()
            project = store.create(
                {
                    "name": name,
                    "script": script_text,
                    "voice_id": voices[voice],
                    "avatar_id": avatars[avatar],
                    "mode": "presentador",
                    "scene": scene,
                    "platform": platform,
                    "quality": quality,
                    "cta": cta,
                    "subtitles": True,
                }
            )
            if logo is not None:
                store.add_asset(project["id"], "logo", logo.name, logo.getvalue())
            if music is not None:
                store.add_asset(project["id"], "music", music.name, music.getvalue())
            job = default_manager().submit(project["id"])
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.session_state["bynnex_job"] = job["id"]
            st.session_state["bynnex_project"] = project["id"]
            _flash("success", "Trabajo enviado a la cola.")
            st.rerun()
    job_id = st.session_state.get("bynnex_job")
    if job_id:
        _job_panel(default_manager(), job_id, _project_store())


# ---------------------------------------------------------------------------
# Aprobaciones y exportaciones
# ---------------------------------------------------------------------------

def _render_approval_tab() -> None:
    store = _project_store()
    rendered = [item for item in store.list() if item.get("state") == "rendered"]
    st.markdown("#### Aprobaciones")
    st.caption("Ninguna exportación se habilita sin una aprobación vigente del contenido.")
    if not rendered:
        st.info("Genera un proyecto para revisarlo aquí.")
        return
    for project in rendered:
        with st.container(border=True):
            st.markdown(f"**{project['name']}** · `{project['id']}`")
            _render_outputs(store, project["id"])
            state = studio.approval_state(project)
            if state["approved"]:
                st.success(f"Aprobado por {state['reviewer']} el {state['at']}.")
            else:
                reviewer = st.text_input("Revisor", key=f"bynnex_rev_{project['id']}")
                note = st.text_area("Observaciones", key=f"bynnex_note_{project['id']}", height=70)
                columns = st.columns(3)
                if columns[0].button("Aprobar", key=f"bynnex_ok_{project['id']}"):
                    _decide(store, project["id"], reviewer, "approve", note)
                if columns[1].button("Pedir cambios", key=f"bynnex_changes_{project['id']}"):
                    _decide(store, project["id"], reviewer, "request_changes", note)
                if columns[2].button("Rechazar", key=f"bynnex_reject_{project['id']}"):
                    _decide(store, project["id"], reviewer, "reject", note)


def _decide(store: studio.ProjectStore, project_id: str, reviewer: str, decision: str, note: str) -> None:
    try:
        studio.approve(project_id, reviewer=reviewer, decision=decision, note=note, store=store)
    except StudioError as exc:
        st.error(str(exc))
    else:
        _flash("success", "Decisión registrada.")
        st.rerun()


def _render_exports_tab() -> None:
    store = _project_store()
    projects = store.list()
    st.markdown("#### Exportaciones")
    st.caption(
        "La exportación copia los archivos a storage/personal_studio/exports y escribe "
        "publication.json. No se publica en ninguna red social."
    )
    ready = [item for item in projects if studio.approval_state(item)["approved"]]
    if not ready:
        st.info("No hay proyectos con aprobación vigente.")
    for project in ready:
        columns = st.columns([3, 1])
        columns[0].markdown(f"**{project['name']}** · {PLATFORMS[project['platform']]['label']}")
        if columns[1].button("Exportar", key=f"bynnex_export_{project['id']}"):
            try:
                result = studio.export(project["id"], store=store)
            except StudioError as exc:
                st.error(str(exc))
            else:
                _flash("success", f"Exportado a {result['path']}")
                st.rerun()
    if store.exports.exists():
        folders = sorted(path for path in store.exports.iterdir() if path.is_dir())
        if folders:
            st.markdown("##### Paquetes locales")
            for folder in folders:
                with st.expander(folder.name):
                    for file in sorted(folder.iterdir()):
                        st.caption(file.name)
                        if file.suffix.lower() == ".json":
                            st.json(json.loads(file.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Cola y diagnóstico
# ---------------------------------------------------------------------------

def _render_queue_tab() -> None:
    manager = default_manager()
    st.markdown("#### Cola de procesamiento")
    st.caption("Un trabajo pesado a la vez para no agotar la RAM. Se puede cancelar.")
    jobs = manager.list()
    if not jobs:
        st.info("La cola está vacía.")
        return
    for job in jobs[:20]:
        with st.container(border=True):
            columns = st.columns([3, 1, 1])
            columns[0].markdown(f"**{job.get('project_name') or job['project_id']}**")
            columns[0].caption(
                f"{manager.stage_label(job.get('stage', ''))} · "
                f"{int(float(job.get('progress') or 0) * 100)}% · {_STATE_LABELS.get(job['state'], job['state'])}"
            )
            if job.get("error"):
                columns[0].error(job["error"])
            if job["state"] in {PENDING, RUNNING}:
                if columns[2].button("Cancelar", key=f"bynnex_q_cancel_{job['id']}"):
                    manager.cancel(job["id"])
                    st.rerun()


def _render_diagnostics_tab() -> None:
    st.markdown("#### Diagnóstico del sistema")
    if st.button("Actualizar diagnóstico", key="bynnex_diag"):
        st.session_state["bynnex_diag_report"] = diagnostics.report(deep=False)
    report = st.session_state.get("bynnex_diag_report") or diagnostics.report(deep=False)
    columns = st.columns(3)
    ram = report["hardware"]
    columns[0].metric("Python", report["app"]["python"])
    columns[1].metric("RAM libre", f"{ram.get('ram_available_mb') or '—'} MB")
    columns[2].metric("Disco libre", f"{ram.get('disk_free_gb') or '—'} GB")
    st.caption(report["app"]["ffmpeg"])
    st.markdown("##### Motores de voz")
    st.table(
        [
            {
                "Motor": item["label"],
                "Disponible": "sí" if item["available"] else "no",
                "Clona": "sí" if item["cloned"] else "no",
                "Licencia": item["license"],
                "Detalle": item["reason"],
            }
            for item in report["engines"]
        ]
    )
    st.markdown("##### Capacidades reales")
    st.json(report["capabilities"])
    st.markdown("##### Almacenamiento")
    st.json(report["storage"])
    for warning in report["warnings"]:
        st.warning(warning)
    if st.button("Comprobar importación real de torch/melo/openvoice (lento)", key="bynnex_deep"):
        with st.spinner("Importando modelos…"):
            deep = diagnostics.report(deep=True)
        for engine in deep["engines"]:
            if engine["id"] == "openvoice_melotts":
                (st.success if engine["available"] else st.error)(engine["reason"])


def render() -> None:
    _render_flash()
    st.markdown("### 🤖 BYNEX AI Personal Studio")
    st.caption(
        "Voz clonada y avatares personalizados, 100 % local. Solo se usa voz e "
        "imagen propias o con autorización verificable. Nada se publica sin aprobación."
    )
    tabs = st.tabs(
        [
            "Inicio",
            "Mi voz",
            "Mis avatares",
            "Estudio personal",
            "Presentador BYNEX",
            "Proyectos",
            "Aprobaciones",
            "Exportaciones",
            "Cola",
            "Diagnóstico",
        ]
    )
    with tabs[0]:
        _render_dashboard()
    with tabs[1]:
        _render_voice_tab()
    with tabs[2]:
        _render_avatar_tab()
    with tabs[3]:
        _render_studio_tab()
    with tabs[4]:
        _render_presenter_tab()
    with tabs[5]:
        _render_projects_tab()
    with tabs[6]:
        _render_approval_tab()
    with tabs[7]:
        _render_exports_tab()
    with tabs[8]:
        _render_queue_tab()
    with tabs[9]:
        _render_diagnostics_tab()


__all__ = ["render"]
