"""Director mode for the creative pipeline (optional top-level WebUI mode).

The Director panel is a thin HTTP client over the creative task API: it
submits creative tasks, polls task state, renders the stage view
(Brief -> Script -> Shot Plan -> Assets -> Rough Cut -> Review -> Final) and
exposes the rough-cut checkpoint actions. All pipeline execution happens in
the API service; this module holds no pipeline logic and leaves the standard
WebUI flow untouched.
"""

import os
import time
import tomllib

import requests
import streamlit as st

API_BASE = os.environ.get("MPT_CREATIVE_API_BASE", "http://api:8080").rstrip("/")
CONFIG_PATH = os.environ.get("MPT_CONFIG_PATH", "/MoneyPrinterTurbo/config.toml")

STATE_FAILED = -1
STATE_COMPLETE = 1
STATE_PROCESSING = 4
STATE_WAITING_FOR_DIRECTOR = 5

STAGES = ("Brief", "Script", "Shot Plan", "Assets", "Rough Cut", "Review", "Final")

DONE = "done"
ACTIVE = "active"
PENDING = "pending"
ERROR = "error"
NA = "na"

STATUS_MARKS = {DONE: "✅", ACTIVE: "🔄", PENDING: "⏳", ERROR: "❌", NA: "—"}

_STATE_LABELS = {
    STATE_FAILED: "Failed",
    STATE_COMPLETE: "Complete",
    STATE_PROCESSING: "Processing",
    STATE_WAITING_FOR_DIRECTOR: "Waiting for director",
}


def api_url(path):
    """Absolute URL for an API or static-file path served by the API."""
    if not path.startswith("/"):
        path = "/" + path
    return API_BASE + path


def _api(method, path, payload=None):
    """Call the creative task API. Returns (ok, data_or_message)."""
    url = api_url(path)
    try:
        response = requests.request(method, url, json=payload, timeout=30)
    except requests.RequestException as exc:
        return False, f"API unreachable at {API_BASE}: {exc}"
    if response.status_code >= 400:
        return False, f"API {response.status_code}: {response.text[:300]}"
    try:
        body = response.json()
    except ValueError:
        return True, None
    if isinstance(body, dict) and "data" in body:
        return True, body["data"]
    return True, body


def file_url(task_id, name):
    """URL of a file stored directly in the task directory."""
    return api_url(f"/tasks/{task_id}/{name}")


def task_file_path(task_id, path):
    """Path under /tasks/{id}/ for an absolute or relative asset path."""
    marker = f"tasks/{task_id}/"
    if marker in path:
        return f"/tasks/{task_id}/{path.split(marker, 1)[1]}"
    return f"/tasks/{task_id}/{path.lstrip('/')}"


def asset_url(task_id, path):
    """Browser URL for any task asset (timeline, shot plan or task field)."""
    if not path:
        return None
    if path.startswith("/tasks/"):
        return api_url(path)
    return api_url(task_file_path(task_id, path))


def list_tasks():
    """All tasks known to the API service."""
    ok, data = _api("GET", "/api/v1/tasks?page=1&page_size=100")
    if not ok or not isinstance(data, dict):
        return []
    return data.get("tasks", [])


def get_task(task_id):
    """Full task detail from the API, or None when unavailable."""
    ok, data = _api("GET", f"/api/v1/tasks/{task_id}")
    return data if ok and isinstance(data, dict) else None


def get_rough_cut(task_id):
    """Rough-cut timeline from the creative API, or None when absent."""
    ok, data = _api("GET", f"/api/v1/creative/tasks/{task_id}/rough_cut")
    if not ok or not isinstance(data, dict):
        return None
    return data.get("rough_cut")


def get_shot_plan(task_id):
    """Shot plan JSON stored in the task directory, or None when absent."""
    ok, data = _api("GET", f"/tasks/{task_id}/shot_plan.json")
    return data if ok and isinstance(data, dict) else None


def _config_voice():
    """Default TTS voice from the API config mounted into this container."""
    try:
        with open(CONFIG_PATH, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    voice = data.get("ui", {}).get("voice_name", "")
    return voice if isinstance(voice, str) else ""


def build_creative_params(subject, script, aspect, clip_duration, voice, subtitle_enabled, bgm_volume):
    """POST /api/v1/videos payload with creative_mode enabled."""
    voice = (voice or "").strip() or _config_voice()
    params = {
        "video_subject": subject,
        "video_script": script or "",
        "video_aspect": aspect,
        "video_concat_mode": "sequential",
        "video_clip_duration": int(clip_duration),
        "video_count": 1,
        "video_source": "pexels",
        "voice_volume": 1.0,
        "voice_rate": 1.0,
        "bgm_type": "random",
        "bgm_volume": float(bgm_volume),
        "subtitle_enabled": bool(subtitle_enabled),
        "font_size": 60,
        "creative_mode": True,
    }
    if voice:
        params["voice_name"] = voice
    return params


def submit_creative_task(params):
    """Submit a creative task. Returns (task_id, error)."""
    ok, data = _api("POST", "/api/v1/videos", payload=params)
    if not ok:
        return None, str(data)
    if not isinstance(data, dict) or not data.get("task_id"):
        return None, "no task_id in API response"
    return data["task_id"], None


def approve_task(task_id):
    """Approve the rough cut and start final assembly."""
    return _api("POST", f"/api/v1/creative/tasks/{task_id}/approve")


def resume_task(task_id):
    """Resume a paused task (rebuild rough cut and finalize)."""
    return _api("POST", f"/api/v1/creative/tasks/{task_id}/resume")


def reorder_shots(task_id, order):
    """Apply a new shot order to the rough cut."""
    return _api(
        "POST",
        f"/api/v1/creative/tasks/{task_id}/shots/reorder",
        payload={"order": [int(i) for i in order]},
    )


def set_shot_duration(task_id, index, duration):
    """Change a rough-cut shot duration (clamped server-side)."""
    return _api(
        "POST",
        f"/api/v1/creative/tasks/{task_id}/shots/{index}/duration",
        payload={"duration": float(duration)},
    )


def replace_shot_asset(task_id, index, asset_path):
    """Replace the asset of a rough-cut shot."""
    return _api(
        "PUT",
        f"/api/v1/creative/tasks/{task_id}/shots/{index}",
        payload={"asset_path": asset_path},
    )


def delete_shot(task_id, index):
    """Delete a shot from the rough cut."""
    return _api("DELETE", f"/api/v1/creative/tasks/{task_id}/shots/{index}")


def regenerate_shot(task_id, index, prompt=None, provider=None):
    """Regenerate a shot asset, optionally with a new prompt."""
    payload = {}
    if prompt:
        payload["prompt"] = prompt
    if provider:
        payload["provider"] = provider
    return _api(
        "POST",
        f"/api/v1/creative/tasks/{task_id}/shots/{index}/regenerate",
        payload=payload or None,
    )


def stage_statuses(task, shot_plan, timeline):
    """Artifact-driven per-stage status for the director view.

    A stage is done when its artifact exists on the task, so the mapping
    stays correct regardless of intermediate progress values.
    """
    state = task.get("state")
    statuses = {stage: PENDING for stage in STAGES}
    statuses["Brief"] = DONE
    if task.get("script"):
        statuses["Script"] = DONE
    if shot_plan and shot_plan.get("shots"):
        statuses["Shot Plan"] = DONE
    if timeline and timeline.get("shots"):
        statuses["Assets"] = DONE
    if state == STATE_WAITING_FOR_DIRECTOR:
        statuses["Rough Cut"] = ACTIVE
    elif state == STATE_COMPLETE:
        statuses["Rough Cut"] = DONE
    if task.get("combined_videos"):
        statuses["Review"] = DONE
    if state == STATE_COMPLETE and task.get("videos"):
        statuses["Final"] = DONE
    if state == STATE_FAILED:
        for stage in STAGES:
            if statuses[stage] == PENDING:
                statuses[stage] = ERROR
                break
    elif state == STATE_PROCESSING:
        for stage in STAGES:
            if statuses[stage] == PENDING:
                statuses[stage] = ACTIVE
                break
    return statuses


def render():
    """Director mode entry point. Called from webui/Main.py."""
    st.title("🎬 Director Mode")
    st.caption(
        "Creative pipeline: brief → script → shot plan → assets → rough cut → "
        "review → final. Tasks run on the API service; this panel drives them."
    )
    _sidebar()
    task_id = st.session_state.get("director_task_select")
    if not task_id:
        _render_empty()
        return
    _render_task(task_id)


def _render_empty():
    st.info("No creative task selected yet.")
    st.markdown(
        "Create one with the **New creative task** form in the sidebar, or pick "
        "an existing task from the list."
    )


def _sidebar():
    st.sidebar.header("Director")
    tasks = list_tasks()
    if not tasks:
        st.sidebar.warning("No tasks on the API service yet.")
    else:
        options = [t["task_id"] for t in tasks]
        if st.session_state.get("director_task_select") not in options:
            st.session_state.pop("director_task_select", None)
        labels = {
            t["task_id"]: f'{t["task_id"][:8]}… · state {t.get("state")} · {t.get("progress", 0)}%'
            for t in tasks
        }
        st.sidebar.selectbox(
            "Task",
            options,
            index=0,
            format_func=lambda tid: labels.get(tid, tid),
            key="director_task_select",
        )
    st.sidebar.divider()
    _new_task_form()


def _new_task_form():
    with st.sidebar.expander("New creative task"):
        subject = st.text_input("Topic", key="dir_new_subject")
        script = st.text_area(
            "Script (optional — the LLM writes one when empty)",
            key="dir_new_script",
        )
        aspect = st.selectbox("Aspect", ["16:9", "9:16", "1:1"], index=0, key="dir_new_aspect")
        clip = st.number_input("Clip duration (s)", min_value=2, max_value=30, value=4, key="dir_new_clip")
        voice = st.text_input(
            "Voice",
            value=_config_voice(),
            placeholder="API config default",
            key="dir_new_voice",
        )
        subtitles = st.checkbox("Subtitles", value=True, key="dir_new_subs")
        bgm_volume = st.slider("BGM volume", min_value=0.0, max_value=1.0, value=0.2, step=0.05, key="dir_new_bgm")
        if st.button("Create task", type="primary", key="dir_new_submit"):
            if not subject.strip():
                st.sidebar.error("Topic is required.")
                return
            params = build_creative_params(
                subject.strip(),
                script.strip(),
                aspect,
                int(clip),
                voice.strip(),
                bool(subtitles),
                float(bgm_volume),
            )
            task_id, error = submit_creative_task(params)
            if error:
                st.sidebar.error(f"Submit failed: {error}")
            else:
                st.session_state["director_task_select"] = task_id
                st.rerun()


def _render_task(task_id):
    task = get_task(task_id)
    if task is None:
        st.error(
            f"Task {task_id} is not on the API service. API restarts wipe "
            "in-memory task state; the files remain under storage/tasks/."
        )
        if st.button("Refresh task list"):
            st.rerun()
        return
    shot_plan = get_shot_plan(task_id)
    timeline = get_rough_cut(task_id)
    statuses = stage_statuses(task, shot_plan, timeline)

    _render_header(task)
    if task.get("state") == STATE_FAILED:
        st.error(f"Failed at stage “{task.get('failed_stage')}”: {task.get('error')}")

    for number, stage in enumerate(STAGES, start=1):
        _render_stage(stage, number, task, shot_plan, timeline, task_id, statuses)

    state = task.get("state")
    if state == STATE_PROCESSING:
        st.caption("⏳ Task is processing — the page refreshes every 5 s.")
        time.sleep(5)
        st.rerun()
    elif state == STATE_WAITING_FOR_DIRECTOR:
        if st.button("↻ Refresh (reload timeline from the API)"):
            st.rerun()


def _render_header(task):
    state = task.get("state")
    label = _STATE_LABELS.get(state, f"state {state}")
    progress = max(0, min(int(task.get("progress") or 0), 100))
    st.subheader(f"Task {str(task.get('task_id'))[:8]}… · {label} · {progress}%")
    st.progress(progress, text=f"{progress}%")


def _render_stage(stage, number, task, shot_plan, timeline, task_id, statuses):
    mark = STATUS_MARKS.get(statuses[stage], "⏳")
    with st.container(border=True):
        st.markdown(f"### {number}. {stage} · {mark} {statuses[stage]}")
        if stage == "Brief":
            _stage_brief(task, task_id)
        elif stage == "Script":
            _stage_script(task)
        elif stage == "Shot Plan":
            _stage_shot_plan(shot_plan)
        elif stage == "Assets":
            _stage_assets(task_id, timeline)
        elif stage == "Rough Cut":
            _stage_rough_cut(task, task_id, timeline)
        elif stage == "Review":
            _stage_review(task, task_id)
        else:
            _stage_final(task, task_id)


def _stage_brief(task, task_id):
    st.markdown(f"Creative task **{task_id}** submitted with `creative_mode: true`.")
    st.caption(
        "The brief (topic + optional script) drives the LLM script and shot "
        "plan. To change the brief, create a new task."
    )


def _stage_script(task):
    script = task.get("script")
    if script:
        st.markdown(f"```{script}```")
    else:
        st.info("No script yet — the LLM is still writing it.")


def _stage_shot_plan(shot_plan):
    if not shot_plan or not shot_plan.get("shots"):
        st.info("No shot plan yet.")
        return
    rows = [
        {
            "#": shot.get("index"),
            "segment": (shot.get("script_segment") or "")[:120],
            "source": shot.get("source_type"),
            "provider": shot.get("provider"),
            "duration": shot.get("duration"),
            "prompt": (shot.get("prompt") or "")[:160],
            "status": shot.get("status"),
        }
        for shot in shot_plan["shots"]
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _stage_assets(task_id, timeline):
    shots = (timeline or {}).get("shots") or []
    if not shots:
        st.info("No assets yet — material resolution is still running.")
        return
    for shot in shots:
        asset = shot.get("asset_path") or ""
        name = asset.rsplit("/", 1)[-1]
        st.markdown(f"**Shot {shot.get('index')}** · `{name}` · {shot.get('duration')} s")
        url = asset_url(task_id, asset)
        if url and name.lower().endswith((".mp4", ".mov", ".webm")):
            st.video(url)
        elif url:
            st.image(url, use_container_width=True)


def _stage_rough_cut(task, task_id, timeline):
    if not timeline or not timeline.get("shots"):
        st.info("No rough cut yet — the pipeline is still preparing shot segments.")
        return
    st.video(file_url(task_id, "rough_cut.mp4"))
    shots = timeline["shots"]
    rows = [
        {
            "#": shot.get("index"),
            "asset": (shot.get("asset_path") or "").rsplit("/", 1)[-1],
            "source": shot.get("source"),
            "in": shot.get("in"),
            "out": shot.get("out"),
            "duration": shot.get("duration"),
        }
        for shot in shots
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.metric("Total duration", f"{timeline.get('total_duration')} s")

    state = task.get("state")
    if state == STATE_WAITING_FOR_DIRECTOR:
        _rough_cut_actions(task_id, shots)
    elif state == STATE_COMPLETE:
        st.success("Rough cut approved — the final video was rendered.")
    elif state == STATE_PROCESSING:
        st.caption("A shot action is running — the rough cut rebuilds automatically.")


def _rough_cut_actions(task_id, shots):
    col_approve, col_resume, _ = st.columns(3)
    with col_approve:
        if st.button("✅ Approve rough cut", type="primary"):
            ok, message = approve_task(task_id)
            if ok:
                st.rerun()
            else:
                st.error(f"Approve failed: {message}")
    with col_resume:
        if st.button("▶ Resume (rebuild + finalize)"):
            ok, message = resume_task(task_id)
            if ok:
                st.rerun()
            else:
                st.error(f"Resume failed: {message}")

    st.divider()
    _reorder_controls(task_id, shots)

    for shot in shots:
        index = shot.get("index")
        asset_name = (shot.get("asset_path") or "").rsplit("/", 1)[-1]
        with st.expander(f"Shot {index} · {asset_name} · {shot.get('duration')} s"):
            prompt = shot.get("prompt")
            if prompt:
                st.caption(prompt)
            col_left, col_right = st.columns(2)
            with col_left:
                duration = st.number_input(
                    "Duration (s)",
                    min_value=0.5,
                    max_value=600.0,
                    value=float(shot.get("duration") or 4.0),
                    step=0.1,
                    key=f"dir_dur_{task_id}_{index}",
                )
                if st.button("Apply duration", key=f"dir_dur_ok_{task_id}_{index}"):
                    ok, message = set_shot_duration(task_id, index, duration)
                    if ok:
                        st.rerun()
                    else:
                        st.error(f"Duration failed: {message}")
            with col_right:
                new_prompt = st.text_input(
                    "New prompt for regenerate (blank = keep current)",
                    key=f"dir_prompt_{task_id}_{index}",
                )
                if st.button("Regenerate shot", key=f"dir_reg_ok_{task_id}_{index}"):
                    ok, message = regenerate_shot(task_id, index, prompt=new_prompt or None)
                    if ok:
                        st.rerun()
                    else:
                        st.error(f"Regenerate failed: {message}")
            if st.button("Delete shot", key=f"dir_del_ok_{task_id}_{index}"):
                ok, message = delete_shot(task_id, index)
                if ok:
                    st.rerun()
                else:
                    st.error(f"Delete failed: {message}")


def _reorder_controls(task_id, shots):
    indexes = [shot.get("index") for shot in shots]
    if len(indexes) < 2:
        return
    with st.expander(f"Reorder {len(indexes)} shots"):
        picks = []
        for row_start in range(0, len(indexes), 4):
            positions = list(range(row_start, min(row_start + 4, len(indexes))))
            cols = st.columns(len(positions))
            for position, col in zip(positions, cols):
                with col:
                    picks.append(
                        col.selectbox(
                            f"Position {position + 1}",
                            indexes,
                            index=position,
                            key=f"dir_order_{task_id}_{position}",
                        )
                    )
        if st.button("Apply order", key=f"dir_order_ok_{task_id}"):
            if len(set(picks)) != len(picks):
                st.warning("Each shot must appear exactly once in the order.")
            else:
                ok, message = reorder_shots(task_id, picks)
                if ok:
                    st.rerun()
                else:
                    st.error(f"Reorder failed: {message}")


def _stage_review(task, task_id):
    combined = task.get("combined_videos") or []
    if not combined:
        st.info("No review video yet — it renders after the rough cut is approved.")
        return
    st.video(asset_url(task_id, combined[0]))
    st.caption("Combined video: cut + voiceover (no BGM, no subtitles).")
    st.link_button(
        "Download Premiere handoff (.zip)",
        f"{API_BASE}/api/v1/creative/tasks/{task_id}/premiere",
    )


def _stage_final(task, task_id):
    videos = task.get("videos") or []
    if not videos:
        st.info("No final video yet.")
        return
    url = asset_url(task_id, videos[0])
    st.video(url)
    st.link_button("Download final video", url)
    st.link_button(
        "Download Premiere handoff (.zip)",
        f"{API_BASE}/api/v1/creative/tasks/{task_id}/premiere",
    )
    audio = task.get("audio_file")
    if audio:
        st.audio(asset_url(task_id, audio))
    subtitle = task.get("subtitle_path")
    if subtitle:
        _stage_subtitles(task_id, subtitle)


def _stage_subtitles(task_id, subtitle):
    url = asset_url(task_id, subtitle)
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            st.code(response.text[:4000])
    except requests.RequestException:
        pass
    st.link_button("Download subtitles (.srt)", url)
