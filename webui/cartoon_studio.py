"""Cartoon Studio 2D section of the Streamlit WebUI.

The page is deliberately thin: every read/write goes through
:mod:`app.services.cartoon_studio_workspace` and every render goes through
:mod:`app.services.cartoon_studio_jobs`. The 2D engine is never rebuilt here.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from app.services import cartoon_studio_jobs as jobs_service
from app.services import voice
from app.services.cartoon_animation import (
    animation_names,
    assets,
    expression_names,
    get_animation,
)
from app.services.cartoon_studio_workspace import StudioError, StudioStore

_ACTION_COLUMNS = ["animation", "at", "weight", "speed"]
_PROP_COLUMNS = ["name", "x", "y", "scale", "appear"]
_STATE_LABELS = {
    jobs_service.QUEUED: "Pendiente",
    jobs_service.RUNNING: "Ejecutando",
    jobs_service.COMPLETED: "Completado",
    jobs_service.FAILED: "Fallido",
    jobs_service.CANCELLED: "Cancelado",
}
_APPROVAL_LABELS = {
    "draft": "Borrador",
    "rendered": "Renderizado",
    "pending_review": "Pendiente de revisión",
    "approved": "Aprobado",
    "rejected": "Rechazado",
    "changes_requested": "Cambios solicitados",
}
_RESOLUTIONS = {
    "Nativa del aspecto": None,
    "720p de entrega": (1280, 720),
    "1080p de entrega": (1920, 1080),
}


def _flash(kind: str, message: str) -> None:
    st.session_state["cartoon_flash"] = (kind, message)


def _render_flash() -> None:
    value = st.session_state.pop("cartoon_flash", None)
    if not value:
        return
    kind, message = value
    getattr(st, kind, st.info)(message)


def _format_time(timestamp: float | None) -> str:
    if not timestamp:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _elapsed(job: dict) -> str:
    started = job.get("started_at") or job.get("created_at")
    if not started:
        return "—"
    end = job.get("finished_at") or time.time()
    seconds = max(0, int(end - started))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _store() -> StudioStore:
    return StudioStore()


def _pending_project() -> None:
    pending = st.session_state.pop("cartoon_project_pending", None)
    if pending:
        st.session_state["cartoon_project"] = pending
        st.session_state["cartoon_project_selector"] = pending


# ---------------------------------------------------------------------------
# Shared widgets
# ---------------------------------------------------------------------------


def _actions_frame(actions: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "animation": action.get("animation", "idle"),
            "at": float(action.get("at", 0.0)),
            "weight": float(action.get("weight", 1.0)),
            "speed": float(action.get("speed", 1.0)),
        }
        for action in actions
        if isinstance(action, dict)
    ]
    return pd.DataFrame(rows, columns=_ACTION_COLUMNS)


def _props_frame(props: list[dict]) -> pd.DataFrame:
    rows = []
    for prop in props:
        if not isinstance(prop, dict):
            continue
        rows.append(
            {
                "name": prop.get("name", "seed"),
                "x": float(prop.get("x", 0.7)),
                "y": float(prop.get("y", 0.8)),
                "scale": float(prop.get("scale", 1.0)),
                "appear": float(prop.get("appear", 0.0)),
            }
        )
    return pd.DataFrame(rows, columns=_PROP_COLUMNS)


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    records = []
    for row in frame.to_dict("records"):
        item = {}
        valid = True
        for column in columns:
            value = row.get(column)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                if column == "animation":
                    valid = False
                    break
                value = 1.0 if column in {"weight", "scale", "speed"} else 0.0
            if column == "name" and not str(value).strip():
                valid = False
                break
            item[column] = value
        if valid:
            records.append(item)
    return records


def _action_timeline_table(actions: list[dict]) -> list[dict]:
    rows = []
    for index, action in enumerate(actions):
        name = action.get("animation")
        try:
            preset = get_animation(name)
            preset_duration = round(preset.duration, 2)
            priority = preset.priority
            additive = "Sí" if preset.additive else "No"
        except Exception:  # noqa: BLE001 - only for the read-only overview
            preset_duration, priority, additive = 0.0, 0, "No"
        rows.append(
            {
                "Orden": index + 1,
                "Animación": name,
                "Inicio (s)": round(float(action.get("at", 0.0)), 2),
                "Duración del preset (s)": preset_duration,
                "Peso": round(float(action.get("weight", 1.0)), 2),
                "Velocidad": round(float(action.get("speed", 1.0)), 2),
                "Prioridad (preset)": priority,
                "Aditiva (preset)": additive,
            }
        )
    return rows


def _scene_selector(loaded: dict, key: str) -> dict:
    scenes = list(loaded["document"].get("scenes") or [])
    ids = [scene.get("id") for scene in scenes]
    current = st.session_state.get(key)
    index = ids.index(current) if current in ids else 0
    selected = st.selectbox(
        "Escena", ids, index=index, key=f"{key}_selector", format_func=str
    )
    st.session_state[key] = selected
    return next(scene for scene in scenes if scene.get("id") == selected)


def _save(store: StudioStore, loaded: dict, document: dict, message: str) -> None:
    try:
        result = store.save_manifest(
            loaded["id"], document, expected_sha256=loaded["manifest_sha256"]
        )
    except StudioError as exc:
        st.error(str(exc))
        return
    _flash("success", f"{message} (manifiesto {result['manifest_sha256'][:8]})")
    st.rerun()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _render_dashboard(store: StudioStore, manager, projects: list[dict]) -> None:
    st.subheader("Inicio")
    drafts = rendered = pending = approved = 0
    for project in projects:
        if project.get("error"):
            continue
        if not project.get("export"):
            drafts += 1
            continue
        rendered += 1
        state = (project.get("approval") or {}).get("state")
        if state == "approved":
            approved += 1
        elif state in {"pending_review", "changes_requested", "rejected"}:
            pending += 1
    columns = st.columns(4)
    columns[0].metric("Proyectos", len(projects))
    columns[1].metric("Borradores", drafts)
    columns[2].metric("Pendientes de aprobación", pending)
    columns[3].metric("Aprobados", approved)
    st.caption(
        f"Videos exportados: {rendered}. Los indicadores se calculan de los "
        "archivos reales de storage/cartoon."
    )

    st.markdown("#### Últimos renders")
    jobs = manager.jobs()[:8]
    if jobs:
        st.dataframe(
            [
                {
                    "Proyecto": job["project_id"],
                    "Estado": _STATE_LABELS.get(job["state"], job["state"]),
                    "Etapa": job.get("stage", ""),
                    "Duración": _elapsed(job),
                    "Creado": _format_time(job.get("created_at")),
                }
                for job in jobs
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Todavía no hay renders iniciados desde el panel.")

    errors = [job for job in manager.jobs() if job["state"] == jobs_service.FAILED][:3]
    if errors:
        st.markdown("#### Errores recientes")
        for job in errors:
            st.warning(f"{job['project_id']} · {job.get('error') or 'sin detalle'}")

    st.markdown("#### Crear episodio")
    with st.form("cartoon_create_dashboard"):
        new_id = st.text_input("Identificador", placeholder="mi-episodio")
        title = st.text_input("Título")
        aspect = st.selectbox("Aspecto", ["9:16", "16:9", "1:1"])
        submitted = st.form_submit_button("Crear borrador")
    if submitted:
        try:
            available = [item["id"] for item in store.characters() if not item.get("error")]
            created = store.create(
                new_id,
                title,
                aspect=aspect,
                character_preset=available[0] if available else "tiko",
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.session_state["cartoon_project_pending"] = created["project_id"]
            _flash("success", "Episodio creado")
            st.rerun()


def _render_projects(store: StudioStore, loaded: dict, projects: list[dict]) -> None:
    st.subheader("Proyectos y episodios")
    rows = []
    for project in projects:
        if project.get("error"):
            rows.append(
                {
                    "Proyecto": project["id"],
                    "Título": "Manifiesto inválido",
                    "Estado": "Error",
                    "Error": project["error"],
                }
            )
            continue
        rows.append(
            {
                "Proyecto": project["id"],
                "Título": project["title"],
                "Escenas": project["scene_count"],
                "Aspecto": project["aspect"],
                "Estado": _APPROVAL_LABELS.get(
                    (project.get("approval") or {}).get("state"), "Borrador"
                ),
                "Archivado": "Sí" if project.get("archived") else "No",
                "Actualizado": _format_time(project.get("updated_at")),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

    document = loaded["document"]
    settings = loaded["settings"]
    st.markdown(f"#### {document.get('title') or loaded['id']}")
    with st.form("cartoon_project_edit"):
        title = st.text_input("Título", value=document.get("title", ""))
        description = st.text_area(
            "Descripción", value=settings.get("description", ""), height=90
        )
        saved = st.form_submit_button("Guardar título y descripción")
    if saved:
        try:
            updated = dict(document)
            updated["title"] = title
            store.save_manifest(
                loaded["id"], updated, expected_sha256=loaded["manifest_sha256"]
            )
            store.save_settings(loaded["id"], {"description": description})
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", "Proyecto actualizado")
            st.rerun()

    st.markdown("#### Orden del storyboard")
    scenes = list(document.get("scenes") or [])
    scene_id = st.selectbox(
        "Escena a mover", [scene.get("id") for scene in scenes], key="cartoon_order_scene"
    )
    left, right = st.columns(2)
    if left.button("↑ Subir", key="cartoon_move_up"):
        try:
            store.move_scene(loaded["id"], scene_id, -1)
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.rerun()
    if right.button("↓ Bajar", key="cartoon_move_down"):
        try:
            store.move_scene(loaded["id"], scene_id, 1)
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.rerun()
    st.caption("El orden del storyboard usa los IDs de escena existentes.")

    st.markdown("#### Duplicar y archivar")
    with st.form("cartoon_duplicate"):
        target_id = st.text_input("Identificador del duplicado")
        target_title = st.text_input("Título del duplicado")
        duplicate = st.form_submit_button("Duplicar episodio")
    if duplicate:
        try:
            created = store.duplicate(
                loaded["id"], target_id, target_title or None
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.session_state["cartoon_project_pending"] = created["project_id"]
            _flash("success", "Episodio duplicado")
            st.rerun()
    archived = bool(settings.get("archived"))
    if st.button("Desarchivar" if archived else "Archivar episodio"):
        try:
            store.archive(loaded["id"], not archived)
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.rerun()
    st.caption(
        "Archivar no borra nada: solo oculta el episodio de la vista normal. "
        "Los proyectos y sus renders se conservan."
    )


def _render_characters(store: StudioStore) -> None:
    st.subheader("Biblioteca de personajes")
    characters = [item for item in store.characters() if not item.get("error")]
    if not characters:
        st.info("El motor no expone personajes articulados.")
        return
    for character in characters:
        with st.expander(
            f"{character['name']} ({character['id']}) · "
            f"{character['part_count']} piezas · {len(character['animations'])} animaciones"
        ):
            st.write("Piezas:", ", ".join(character["parts"]))
            st.write("Expresiones:", ", ".join(character["expressions"]))
            st.write("Animaciones:", ", ".join(character["animations"]))
    st.caption(
        "Solo se muestran presets reales del motor. No existe todavía un editor "
        "gráfico de rigging; los personajes nuevos se añaden en el código del motor."
    )

    st.markdown("#### Vista previa de personaje")
    preset = st.selectbox(
        "Personaje", [item["id"] for item in characters], key="cartoon_char_preset"
    )
    expression = st.selectbox(
        "Expresión", list(expression_names()), key="cartoon_char_expression"
    )
    if st.button("Renderizar expresión", key="cartoon_char_preview"):
        try:
            path = store.render_character_preview(preset, expression)
        except Exception as exc:  # noqa: BLE001 - engine error shown to the user
            st.error(str(exc))
        else:
            st.image(path, caption=f"{preset} · {expression}")

    st.markdown("#### Vista previa de pose animada")
    animation = st.selectbox(
        "Animación", list(animation_names()), key="cartoon_pose_animation"
    )
    preset_info = get_animation(animation)
    seconds = st.slider(
        "Instante (s)",
        min_value=0.0,
        max_value=float(preset_info.duration),
        value=min(1.0, float(preset_info.duration)),
        step=0.05,
    )
    if st.button("Renderizar pose", key="cartoon_pose_preview"):
        try:
            path = store.render_pose_preview(preset, animation, seconds)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
        else:
            st.image(path, caption=f"{preset} · {animation} · {seconds:.2f}s")


def _render_scene_editor(store: StudioStore, loaded: dict) -> None:
    st.subheader("Editor de escenas y timeline")
    document = loaded["document"]
    scene = _scene_selector(loaded, "cartoon_scene")
    animated = isinstance(scene.get("animation"), dict)

    st.markdown("#### Vista previa estática")
    preview_columns = st.columns([1, 1, 1])
    preview_time = preview_columns[0].number_input(
        "Instante (s)",
        min_value=0.0,
        max_value=float(scene.get("duration", 5)),
        value=min(1.0, float(scene.get("duration", 5))),
        step=0.1,
        key="cartoon_preview_time",
    )
    if preview_columns[1].button("Generar fotograma", key="cartoon_preview_still"):
        try:
            preview = store.render_scene_preview(loaded["id"], scene["id"], preview_time)
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.image(preview["path"], caption=f"{scene['id']} · {preview_time:.1f}s (PNG)")
    preview_columns[2].caption(
        "Un fotograma no reproduce la animación; para eso usa Renderizado."
    )

    st.markdown("#### Escena")
    with st.form(f"cartoon_scene_form_{scene['id']}"):
        visual = st.text_area("Descripción visual", value=scene.get("visual", ""), height=100)
        narration = st.text_area(
            "Narración", value=scene.get("narration", ""), height=90
        )
        duration = st.number_input(
            "Duración (s)",
            min_value=1.0,
            max_value=60.0,
            value=float(scene.get("duration", 5)),
            step=0.5,
        )
        cast = st.multiselect(
            "Personajes del manifiesto",
            list(document.get("characters") and [c["name"] for c in document["characters"]] or []),
            default=list(scene.get("characters") or []),
        )
        use_animation = st.checkbox("Escena con animación articular", value=animated)
        animation = scene.get("animation") if animated else {}

        if use_animation:
            animation_root = document.get("animation")
            if not isinstance(animation_root, dict):
                animation_root = {"characters": [{"id": "tiko", "preset": "tiko"}]}
            declared = animation_root.get("characters") or []
            ids = [entry.get("id") for entry in declared] or ["tiko"]
            character = st.selectbox(
                "Personaje articulado",
                ids,
                index=ids.index(animation.get("character")) if animation.get("character") in ids else 0,
            )
            background = st.selectbox(
                "Escenario",
                list(assets.background_names()),
                index=list(assets.background_names()).index(
                    animation.get("background", "garden")
                )
                if animation.get("background") in assets.background_names()
                else 0,
            )
            expressions = list(expression_names())
            expression = st.selectbox(
                "Expresión",
                expressions,
                index=expressions.index(animation.get("expression", "neutral"))
                if animation.get("expression") in expressions
                else 0,
            )
            positions = st.columns(3)
            x = positions[0].slider(
                "X", 0.0, 1.0, float(animation.get("x", 0.5)), 0.01
            )
            y = positions[1].slider(
                "Y (pies)", 0.0, 1.0, float(animation.get("y", 0.7)), 0.01
            )
            scale = positions[2].slider(
                "Escala", 0.1, 3.0, float(animation.get("scale", 1.0)), 0.05
            )
            lip_sync = st.checkbox(
                "Sincronización labial con la narración",
                value=bool(animation.get("lip_sync", True)),
            )
            travel_enabled = st.checkbox(
                "Desplazamiento horizontal", value=animation.get("travel") is not None
            )
            travel = animation.get("travel") or {}
            travel_values = None
            if travel_enabled:
                tcols = st.columns(3)
                travel_values = {
                    "to_x": tcols[0].slider(
                        "Destino X", 0.0, 1.0, float(travel.get("to_x", 0.6)), 0.01
                    ),
                    "start": tcols[1].number_input(
                        "Inicio (s)", min_value=0.0, value=float(travel.get("start", 0.0)), step=0.1
                    ),
                    "duration": tcols[2].number_input(
                        "Duración (s)", min_value=0.1, value=float(travel.get("duration", 1.0)), step=0.1
                    ),
                }
            actions = st.data_editor(
                _actions_frame(animation.get("actions") or []),
                num_rows="dynamic",
                width="stretch",
                key=f"cartoon_actions_{scene['id']}",
                column_config={
                    "animation": st.column_config.SelectboxColumn(
                        "Animación", options=list(animation_names()), required=True
                    ),
                    "at": st.column_config.NumberColumn(
                        "Inicio (s)", min_value=0.0, step=0.1, format="%.2f"
                    ),
                    "weight": st.column_config.NumberColumn(
                        "Peso", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"
                    ),
                    "speed": st.column_config.NumberColumn(
                        "Velocidad", min_value=0.1, max_value=5.0, step=0.1, format="%.2f"
                    ),
                },
            )
            props = st.data_editor(
                _props_frame(animation.get("props") or []),
                num_rows="dynamic",
                width="stretch",
                key=f"cartoon_props_{scene['id']}",
                column_config={
                    "name": st.column_config.SelectboxColumn(
                        "Objeto", options=sorted(assets.PROP_NAMES), required=True
                    ),
                    "x": st.column_config.NumberColumn(
                        "X", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"
                    ),
                    "y": st.column_config.NumberColumn(
                        "Y", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"
                    ),
                    "scale": st.column_config.NumberColumn(
                        "Escala", min_value=0.1, max_value=3.0, step=0.05, format="%.2f"
                    ),
                    "appear": st.column_config.NumberColumn(
                        "Aparece en (s)", min_value=0.0, step=0.1, format="%.2f"
                    ),
                },
            )
        else:
            character = background = expression = None
            x = y = scale = None
            lip_sync = travel_values = None
            actions = props = None
        submitted = st.form_submit_button("Guardar escena")

    if submitted:
        updated = dict(document)
        new_scene = dict(scene)
        new_scene["visual"] = visual
        new_scene["narration"] = narration
        new_scene["duration"] = float(duration)
        new_scene["characters"] = list(cast)
        if use_animation:
            animation_root = updated.get("animation")
            if not isinstance(animation_root, dict):
                animation_root = {}
            declared = list(animation_root.get("characters") or [])
            if not any(entry.get("id") == character for entry in declared):
                declared.append({"id": character, "preset": "tiko"})
            animation_root["characters"] = declared
            updated["animation"] = animation_root
            animation_document = {
                "background": background,
                "character": character,
                "x": float(x),
                "y": float(y),
                "scale": float(scale),
                "expression": expression,
                "lip_sync": bool(lip_sync),
                "actions": _records(actions, _ACTION_COLUMNS),
                "props": _records(props, _PROP_COLUMNS),
            }
            if travel_values is not None:
                animation_document["travel"] = {
                    "to_x": float(travel_values["to_x"]),
                    "start": float(travel_values["start"]),
                    "duration": float(travel_values["duration"]),
                }
            new_scene["animation"] = animation_document
        else:
            new_scene.pop("animation", None)
        scenes = [new_scene if item.get("id") == scene["id"] else item for item in updated["scenes"]]
        updated["scenes"] = scenes
        _save(store, loaded, updated, "Escena guardada")

    if animation:
        st.markdown("#### Timeline de la escena")
        actions_list = animation.get("actions") or []
        if actions_list:
            st.dataframe(
                _action_timeline_table(actions_list), width="stretch", hide_index=True
            )
        else:
            st.caption("La escena no tiene acciones; cada acción necesita un inicio en segundos.")
        st.caption(
            "El manifiesto valida inicio, peso y velocidad por acción. La duración "
            "por acción, la prioridad y el modo aditivo no forman parte del esquema "
            "actual: se muestran como propiedades del preset, no como campos editables."
        )


def _voice_options() -> list[str]:
    try:
        names = list(voice.get_all_azure_voices())
    except Exception:  # noqa: BLE001 - voice catalog is optional
        names = []
    preferred = [name for name in names if name.startswith("es-")]
    rest = [name for name in names if not name.startswith("es-")]
    return preferred + rest


def _render_narration(store: StudioStore, loaded: dict) -> None:
    st.subheader("Narración y subtítulos")
    settings = loaded["settings"]
    document = loaded["document"]
    options = [""] + _voice_options()
    current = settings.get("voice", "")
    with st.form("cartoon_narration_form"):
        filter_text = st.text_input(
            "Buscar voz (opcional)", value="", placeholder="es-CO, Salome, en-US…"
        )
        filtered = options
        if filter_text.strip():
            needle = filter_text.strip().lower()
            filtered = [name for name in options if needle in name.lower()] or options
        selected = st.selectbox(
            "Voz", filtered, index=filtered.index(current) if current in filtered else 0
        )
        rate = st.slider(
            "Velocidad de voz", 0.5, 2.0, float(settings.get("voice_rate", 1.0)), 0.05
        )
        subtitles = st.checkbox(
            "Quemar subtítulos en el video", value=bool(settings.get("subtitles"))
        )
        font_size = st.slider(
            "Tamaño de subtítulos",
            16,
            160,
            int(settings.get("subtitle_font_size", 56)),
            2,
        )
        submitted = st.form_submit_button("Guardar narración")
    if submitted:
        try:
            store.save_settings(
                loaded["id"],
                {
                    "voice": selected,
                    "voice_rate": float(rate),
                    "subtitles": bool(subtitles),
                    "subtitle_font_size": int(font_size),
                },
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", "Narración guardada; el próximo render la usará")
            st.rerun()
    st.caption(
        "La voz usa el servicio TTS ya configurado. Edge TTS y los proveedores "
        "remotos requieren Internet; sin conexión no se genera audio."
    )

    st.markdown("#### Audio de prueba")
    scenes = list(document.get("scenes") or [])
    scene_id = st.selectbox(
        "Escena", [scene.get("id") for scene in scenes], key="cartoon_audio_scene"
    )
    scene = next(item for item in scenes if item.get("id") == scene_id)
    text = (scene.get("narration") or "").strip()
    if not text:
        st.caption("Esta escena no tiene narración.")
    else:
        st.code(text, language=None)
        if not selected:
            st.caption("Selecciona una voz y guarda la configuración para generar audio.")
        elif st.button("Generar audio de prueba", key="cartoon_audio_preview"):
            identity = f"{text}|{selected}|{rate}"
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
            target = store.project_dir(loaded["id"]) / "audio" / f"preview-{scene_id}-{digest}.mp3"
            try:
                if not target.is_file():
                    with st.spinner("Generando audio (requiere Internet)…"):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        voice.tts(text, selected, float(rate), str(target))
                st.audio(str(target))
            except Exception as exc:  # noqa: BLE001 - TTS failures shown to the user
                st.error(f"No se pudo generar el audio: {exc}")
    st.caption(
        "La sincronización labial se calcula del audio de la narración al renderizar. "
        "Cambiar el texto exige un nuevo render para que la boca lo refleje."
    )


def _render_active_job(manager, project_id: str) -> None:
    jobs = manager.jobs(project_id)
    active = [job for job in jobs if job["state"] in {jobs_service.QUEUED, jobs_service.RUNNING}]
    if not active:
        st.caption("No hay renders activos para este episodio.")
        return
    job = active[0]
    position = manager.queue_position(job["id"])
    st.info(
        f"{_STATE_LABELS.get(job['state'], job['state'])} · {job.get('message', '')} · "
        f"transcurrido {_elapsed(job)}"
        + (f" · posición en cola {position}" if position else "")
    )
    if job.get("revision"):
        st.caption(f"Revisión: {job['revision']}")
    if st.button("Cancelar render", key=f"cartoon_cancel_{job['id']}"):
        try:
            manager.cancel(job["id"])
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.rerun()


def _render_render_tab(store: StudioStore, manager, loaded: dict) -> None:
    st.subheader("Renderizado y progreso")
    settings = loaded["settings"]
    st.caption("Un render pesado a la vez por defecto; los siguientes esperan en cola.")

    with st.form("cartoon_render_form"):
        mode = st.selectbox(
            "Modo",
            ["auto", "animation", "classic"],
            index=["auto", "animation", "classic"].index(settings.get("mode", "auto")),
            help="auto usa animación solo si el manifiesto tiene la sección animation",
        )
        columns = st.columns(3)
        fps = columns[0].slider("FPS", 12, 30, int(settings.get("fps", 24)))
        crf = columns[1].slider(
            "CRF",
            14,
            32,
            max(14, min(32, int(settings.get("crf", 20)))),
            help="Menor CRF = más calidad y archivo más grande",
        )
        resolution_name = columns[2].selectbox(
            "Resolución de entrega",
            list(_RESOLUTIONS),
            index=0,
        )
        submitted = st.form_submit_button("Iniciar render")
    if submitted:
        width, height = _RESOLUTIONS[resolution_name] or (None, None)
        try:
            store.save_settings(loaded["id"], {"mode": mode, "fps": int(fps), "crf": int(crf)})
            job = manager.submit(
                loaded["id"],
                {
                    "mode": mode,
                    "fps": int(fps),
                    "crf": int(crf),
                    "output_width": width,
                    "output_height": height,
                    "voice": settings.get("voice", ""),
                    "voice_rate": settings.get("voice_rate", 1.0),
                    "subtitles": settings.get("subtitles", False),
                    "subtitle_font_size": settings.get("subtitle_font_size", 56),
                },
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", f"Render en cola: {job['id']}")
            st.rerun()

    fragment = st.fragment(run_every=2.0)(_render_active_job)
    fragment(manager, loaded["id"])

    jobs = manager.jobs(loaded["id"])
    if jobs:
        st.markdown("#### Historial de trabajos")
        st.dataframe(
            [
                {
                    "ID": job["id"],
                    "Estado": _STATE_LABELS.get(job["state"], job["state"]),
                    "Etapa": job.get("stage", ""),
                    "Mensaje": job.get("message", ""),
                    "Duración": _elapsed(job),
                    "Revisión": job.get("revision", ""),
                    "Error": job.get("error", ""),
                }
                for job in jobs
            ],
            width="stretch",
            hide_index=True,
        )
    export = store.export(loaded["id"])
    if export:
        st.markdown("#### Último video")
        st.caption(
            f"Revisión {export['revision_id']} · sha256 "
            f"{export.get('sha256', '')[:12]} · {export.get('size', 0) / 1024 / 1024:.1f} MB"
        )
        st.video(export["path"])
        st.download_button(
            "Descargar MP4",
            data=Path(export["path"]).read_bytes(),
            file_name=f"{loaded['id']}-{export['revision_id'][:8]}.mp4",
            mime="video/mp4",
            key="cartoon_download_render",
        )
    else:
        st.caption("Este episodio todavía no tiene un video exportado.")


def _render_approval(store: StudioStore, loaded: dict) -> None:
    st.subheader("Vista previa y aprobación")
    approval = store.approval(loaded["id"])
    export = approval.get("export")
    if not export:
        st.info("No hay video exportado. Renderiza el episodio antes de aprobarlo.")
        return
    st.video(export["path"])
    st.write(
        {
            "Estado": _APPROVAL_LABELS.get(approval["state"], approval["state"]),
            "Revisión": export["revision_id"],
            "sha256": export.get("sha256", ""),
            "Archivo": export["filename"],
        }
    )
    if approval.get("stale"):
        st.warning(
            "La aprobación anterior ya no aplica: el video o el contenido cambió. "
            "Revisa esta revisión y vuelve a aprobar."
        )
    record = approval.get("record")
    if record:
        st.caption(
            f"Última decisión: {record.get('status')} · "
            f"{_format_time(record.get('decided_at'))} · "
            f"revisor {record.get('reviewer') or 'sin identificar'}"
        )
        if record.get("note"):
            st.caption(f"Nota: {record['note']}")
    if approval["state"] == "approved":
        st.success("La revisión actual está aprobada. No se publicará automáticamente.")

    st.markdown("#### Revisión")
    reviewer = st.text_input(
        "Revisor (opcional)", value=loaded["settings"].get("reviewer", "")
    )
    note = st.text_area("Nota", height=80)
    columns = st.columns(3)
    if columns[0].button("Aprobar revisión", type="primary"):
        try:
            store.save_settings(loaded["id"], {"reviewer": reviewer})
            store.decide(
                loaded["id"],
                "approve",
                reviewer=reviewer,
                note=note,
                revision_id=export["revision_id"],
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", "Revisión aprobada")
            st.rerun()
    if columns[1].button("Solicitar cambios"):
        try:
            store.save_settings(loaded["id"], {"reviewer": reviewer})
            store.decide(
                loaded["id"],
                "request_changes",
                reviewer=reviewer,
                note=note,
                revision_id=export["revision_id"],
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("warning", "Cambios solicitados")
            st.rerun()
    if columns[2].button("Rechazar"):
        try:
            store.save_settings(loaded["id"], {"reviewer": reviewer})
            store.decide(
                loaded["id"],
                "reject",
                reviewer=reviewer,
                note=note,
                revision_id=export["revision_id"],
            )
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("warning", "Revisión rechazada")
            st.rerun()

    records = store.approvals(loaded["id"])
    if records:
        st.markdown("#### Historial de revisiones")
        st.dataframe(
            [
                {
                    "Fecha": _format_time(item.get("decided_at")),
                    "Estado": item.get("status"),
                    "Revisión": item.get("revision_id"),
                    "Revisor": item.get("reviewer") or "—",
                    "Nota": item.get("note", ""),
                    "sha256": (item.get("artifact_sha256") or "")[:12],
                }
                for item in reversed(records)
            ],
            width="stretch",
            hide_index=True,
        )
    st.caption(
        "La aprobación queda ligada a esta revisión, al sha256 del archivo y al "
        "manifiesto. Cualquier cambio posterior la invalida. No se publica en "
        "redes sociales en esta fase."
    )


def _render_library(store: StudioStore, loaded: dict) -> None:
    st.subheader("Biblioteca de videos exportados")
    entries = []
    for project in store.projects():
        if project.get("error"):
            continue
        for item in store.history(project["id"]):
            entries.append({**item, "project_id": project["id"], "title": project["title"]})
    if not entries:
        st.info("Todavía no hay videos exportados en storage/cartoon.")
        return
    entries.sort(key=lambda item: item.get("size", 0), reverse=True)
    st.dataframe(
        [
            {
                "Proyecto": item["project_id"],
                "Título": item["title"],
                "Revisión": item["revision_id"],
                "Archivo": item["filename"],
                "MB": round(item.get("size", 0) / 1024 / 1024, 2),
                "sha256": (item.get("sha256") or "")[:12],
            }
            for item in entries
        ],
        width="stretch",
        hide_index=True,
    )
    labels = [
        f"{item['project_id']} · {item['revision_id'][:8]} · {item['filename']}"
        for item in entries
    ]
    selected = st.selectbox("Video", labels, key="cartoon_library_select")
    item = entries[labels.index(selected)]
    st.video(item["path"])
    st.download_button(
        "Descargar MP4",
        data=Path(item["path"]).read_bytes(),
        file_name=f"{item['project_id']}-{item['revision_id'][:8]}.mp4",
        mime="video/mp4",
        key="cartoon_download_library",
    )


def _render_configuration(store: StudioStore, loaded: dict) -> None:
    st.subheader("Configuración del estudio")
    settings = loaded["settings"]
    st.caption(f"Almacenamiento local: {store.root}")
    st.caption(f"Proyecto actual: {loaded['path']}")
    st.caption(f"Manifiesto vigente: {loaded['manifest_sha256']}")
    with st.form("cartoon_studio_config"):
        fps = st.slider("FPS por defecto", 12, 30, int(settings.get("fps", 24)))
        crf = st.slider(
            "CRF por defecto", 14, 32, max(14, min(32, int(settings.get("crf", 20))))
        )
        mode = st.selectbox(
            "Modo por defecto",
            ["auto", "animation", "classic"],
            index=["auto", "animation", "classic"].index(settings.get("mode", "auto")),
        )
        submitted = st.form_submit_button("Guardar configuración")
    if submitted:
        try:
            store.save_settings(loaded["id"], {"fps": int(fps), "crf": int(crf), "mode": mode})
        except StudioError as exc:
            st.error(str(exc))
        else:
            _flash("success", "Configuración guardada")
            st.rerun()

    st.markdown("#### Datos del estudio")
    st.code(
        f"Proyectos: {store.root}\n"
        f"Manifiesto: {loaded['path']}\\cartoon.json\n"
        f"Revisiones: {loaded['path']}\\revisions\n"
        f"Backups del manifiesto: {loaded['path']}\\backups",
        language="text",
    )
    st.markdown("#### Equivalencia con la CLI")
    st.code(
        f"python -m app.services.cartoon_studio --project storage/cartoon/{loaded['id']} "
        f"build --mode {settings.get('mode', 'auto')} "
        f"--fps {settings.get('fps', 24)} --crf {settings.get('crf', 20)}"
        + (" --subtitles" if settings.get("subtitles") else ""),
        language="sh",
    )
    st.caption(
        "El panel y la CLI comparten los mismos manifiestos, revisiones y artefactos. "
        "La CLI no incluye la cola de trabajos del panel, pero sigue funcionando igual."
    )
    st.markdown("#### Limitaciones conocidas")
    st.markdown(
        "- El renderizado es CPU-only y secuencial por proyecto.\n"
        "- El editor de timeline cubre inicio, orden, peso y velocidad; no hay editor "
        "gráfico de keyframes ni campos de prioridad/aditivo por acción en el manifiesto.\n"
        "- La vista previa es un fotograma PNG; el MP4 se reproduce tras renderizar.\n"
        "- La aprobación no publica en redes sociales: solo registra la decisión local."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render() -> None:
    store = _store()
    manager = jobs_service.default_manager()
    _pending_project()
    _render_flash()
    st.markdown("### 🎬 Cartoon Studio 2D")
    st.caption(
        "Estudio local del motor 2D articulado: proyectos, escenas, narración, "
        "renderizado y aprobación. Sin GPU dedicada y sin publicación automática."
    )

    projects = store.projects()
    if not projects:
        st.info(
            "No hay proyectos en storage/cartoon. Crea uno desde la pestaña "
            "Proyectos o usa la CLI para generar un manifiesto."
        )
        _render_create_only(store)
        return

    ids = [project["id"] for project in projects]
    titles = {
        project["id"]: (
            f"{project['title']} ({project['id']})"
            if not project.get("error")
            else f"{project['id']} · manifiesto inválido"
        )
        for project in projects
    }
    current = st.session_state.get("cartoon_project")
    index = ids.index(current) if current in ids else 0
    selected = st.selectbox(
        "Proyecto / episodio",
        ids,
        index=index,
        format_func=lambda value: titles.get(value, value),
        key="cartoon_project_selector",
    )
    st.session_state["cartoon_project"] = selected
    try:
        loaded = store.load(selected)
    except StudioError as exc:
        st.error(str(exc))
        _render_projects(store, {"document": {}, "settings": {}, "id": selected}, projects)
        return

    tabs = st.tabs(
        [
            "Inicio",
            "Proyectos y episodios",
            "Personajes",
            "Editor de escenas",
            "Narración y subtítulos",
            "Renderizado",
            "Vista previa y aprobación",
            "Biblioteca",
            "Configuración",
        ]
    )
    with tabs[0]:
        _render_dashboard(store, manager, projects)
    with tabs[1]:
        _render_projects(store, loaded, projects)
    with tabs[2]:
        _render_characters(store)
    with tabs[3]:
        _render_scene_editor(store, loaded)
    with tabs[4]:
        _render_narration(store, loaded)
    with tabs[5]:
        _render_render_tab(store, manager, loaded)
    with tabs[6]:
        _render_approval(store, loaded)
    with tabs[7]:
        _render_library(store, loaded)
    with tabs[8]:
        _render_configuration(store, loaded)


def _render_create_only(store: StudioStore) -> None:
    st.markdown("#### Crear el primer episodio")
    with st.form("cartoon_create_first"):
        new_id = st.text_input("Identificador", placeholder="mi-episodio")
        title = st.text_input("Título")
        aspect = st.selectbox("Aspecto", ["9:16", "16:9", "1:1"])
        submitted = st.form_submit_button("Crear borrador")
    if submitted:
        try:
            created = store.create(new_id, title, aspect=aspect)
        except StudioError as exc:
            st.error(str(exc))
        else:
            st.session_state["cartoon_project_pending"] = created["project_id"]
            _flash("success", "Episodio creado")
            st.rerun()


__all__ = ["render"]
