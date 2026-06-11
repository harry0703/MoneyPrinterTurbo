# API, task management and WebUI

## FastAPI service

`main.py` → uvicorn → `app/asgi.py` → `app/router.py` → controllers in
`app/controllers/v1/` (`video.py`, `llm.py`, `base.py`) plus `ping.py`.
Default port 8080; interactive docs at `/docs`.

### Endpoints (`app/controllers/v1/video.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/videos` | full pipeline (`TaskVideoRequest` ≈ `VideoParams`) |
| POST | `/api/v1/audio` | pipeline with `stop_at="audio"` (script+TTS only) |
| POST | `/api/v1/subtitle` | pipeline with `stop_at="subtitle"` |
| GET | `/api/v1/tasks` | paginated task list (`page`, `page_size`) |
| GET | `/api/v1/tasks/{task_id}` | state, progress, artifact URLs |
| DELETE | `/api/v1/tasks/{task_id}` | delete task + artifacts |
| GET/POST | `/api/v1/musics` | list / upload BGM (MP3) |
| GET/POST | `/api/v1/video_materials` | list / upload local materials |
| GET | `/api/v1/stream/{file_path}` | range-aware video streaming |
| GET | `/api/v1/download/{file_path}` | file download |

All file-path endpoints sanitize input through
`app/utils/file_security.py::resolve_path_within_directory()` — never bypass
it when adding endpoints.

Also: `app/controllers/v1/llm.py` exposes script/terms generation directly
(used by the WebUI "generate script" button).

## Task queue and managers — `app/controllers/manager/`

- `base_manager.py` defines the queue contract: at most
  `max_concurrent_tasks` pipelines run in parallel; up to `max_queued_tasks`
  wait; beyond that the API answers **429**.
- `memory_manager.py` (default): in-process dict + threads. Single worker
  only; tasks are lost on restart.
- `redis_manager.py` (when `enable_redis = true`): Redis-backed, suitable for
  multiple workers / restarts.
- Enqueueing: `task_manager.add_task(tm.start, task_id=..., params=..., stop_at=...)`.

## State store — `app/services/state.py`

`BaseState` (ABC) → `MemoryState` / `RedisState`, selected by config.

```python
sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50,
                     script=..., terms=..., videos=[...], combined_videos=[...],
                     audio_file=..., subtitle_path=...)
sm.state.get_task(task_id)
sm.state.get_all_tasks(page, page_size)
```

States: `-1` failed, `4` processing, `1` complete (`app/models/const.py`).
RedisState serializes values to strings and restores types via
`_convert_to_original_type()`.

## WebUI — `webui/Main.py` (Streamlit, port 8501)

- Launch scripts: `webui.sh` / `webui.bat`; Docker compose runs it as the
  default service.
- Single-page form mirroring `VideoParams`: subject, optional custom
  script/prompt/system-prompt, video source/aspect/concat/transition, voice
  picker (filtered by language + engine prefix), BGM, full subtitle styling.
- Generates via direct service calls (same process), shows logs unless
  `ui.hide_log`, previews finished videos, paginates task history.
- **i18n**: `webui/i18n/{de,en,pt,ru,tr,vi,zh}.json`, loaded by
  `utils.load_locales()`; UI language auto-detected from system locale and
  switchable in the header. When adding UI strings, add the key to **all**
  locale files (tests in `test/services/test_webui_i18n.py` check consistency).
- Session state keys: `video_subject`, `video_script`, `video_terms`,
  `video_script_prompt`, `custom_system_prompt`, `use_custom_system_prompt`,
  `ui_language`, `local_video_materials`.
