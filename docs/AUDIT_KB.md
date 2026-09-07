# MoneyPrinterTurbo Audit Knowledge Base

## Purpose
This document is a deep audit of how the project works end-to-end, including API surface, core flows, configuration, integrations, storage, and risk notes. It is intended as a technical knowledge base to support maintenance and changes.

## Architecture Overview
- FastAPI service with versioned controllers and async task execution.
- Layered structure: controllers -> services -> integrations -> storage.
- Web UI served as static files from the resource bundle.

Key modules:
- API router: [app/router.py](app/router.py)
- FastAPI app + static mounts: [app/asgi.py](app/asgi.py)
- Task orchestration: [app/services/task.py](app/services/task.py)
- Video composition: [app/services/video.py](app/services/video.py)
- TTS + subtitles: [app/services/voice.py](app/services/voice.py), [app/services/subtitle.py](app/services/subtitle.py)
- Avatar/lipsync: [app/services/character_image.py](app/services/character_image.py), [app/services/character_lipsync.py](app/services/character_lipsync.py), [app/services/character_overlay.py](app/services/character_overlay.py)
- Integrations: [app/integrations/provider_router.py](app/integrations/provider_router.py) and [app/integrations/](app/integrations/)

## Public Surface Area

### Static mounts
- /tasks -> storage/tasks (generated assets) via [app/asgi.py](app/asgi.py)
- / -> resource/public (web UI) via [app/asgi.py](app/asgi.py)

### API base router
- Root router includes external and v1 routers via [app/router.py](app/router.py)

### API endpoints (current)
External endpoints:
- POST /api/external/generate -> provider router (single provider)
- POST /api/external/render-final -> provider router (shotstack default)
  - Source: [app/controllers/external.py](app/controllers/external.py)

V1 endpoints:
- POST /api/v1/videos -> create video task
- POST /api/v1/subtitle -> subtitle-only task
- POST /api/v1/audio -> audio-only task
- GET /api/v1/tasks -> list tasks (pagination)
- GET /api/v1/tasks/{task_id} -> task status
- DELETE /api/v1/tasks/{task_id} -> delete task
- GET /api/v1/musics -> list local BGM
- POST /api/v1/musics -> upload BGM
- GET /api/v1/video_materials -> list local materials
- POST /api/v1/video_materials -> upload materials
- GET /api/v1/stream/{file_path} -> stream task file (range requests)
- GET /api/v1/download/{file_path} -> download task file
  - Source: [app/controllers/v1/video.py](app/controllers/v1/video.py)

LLM endpoints:
- POST /api/v1/scripts -> generate script
- POST /api/v1/terms -> generate terms
  - Source: [app/controllers/v1/llm.py](app/controllers/v1/llm.py)

### Auth model
- API key auth is defined but not enabled; the dependency is commented out.
  - Source: [app/controllers/v1/video.py](app/controllers/v1/video.py), [app/controllers/v1/llm.py](app/controllers/v1/llm.py), [app/controllers/base.py](app/controllers/base.py)

### Request headers used
- x-task-id: request correlation id
- x-api-key: optional auth key (disabled unless dependency is enabled)
  - Source: [app/controllers/base.py](app/controllers/base.py)

## Task Lifecycle (Video Generation)

### High-level flow
1. Controller creates task and enqueues background work.
2. Task pipeline resolves script -> terms -> audio -> subtitles -> materials -> video composition.
3. Results saved under storage/tasks/{task_id or slug__uuid} and reported via state.

### Function-level trace (main path)
- Controller entry -> create_task: [app/controllers/v1/video.py](app/controllers/v1/video.py)
  - Creates task_id and request_id
  - Enqueues task_manager.add_task to start task

- Task pipeline entry -> start: [app/services/task.py](app/services/task.py)
  1) _apply_avatar_bridge
     - If avatar_image_file set, enables character overlay + lipsync.
  2) generate_script
     - Uses NarrationSourceService for pdf/text; falls back to LLM.
  3) generate_terms
     - Uses LLM if not provided and source is not local.
  4) generate_audio
     - Uses custom audio if present; otherwise TTS.
  5) generate_subtitle
     - Edge subtitle maker or Whisper fallback.
  6) get_video_materials
     - Pexels/Pixabay/local or external providers.
  7) resolve_cover_image_path
     - Optional cover generation.
  8) generate_final_videos
     - combine_videos + generate_video for each output.
  9) update task state, store final paths.

### Stop points
- stop_at can short-circuit at: script, terms, audio, subtitle, materials, video.
  - Source: [app/services/task.py](app/services/task.py)

## Storage Layout
- storage/tasks/ -> task output directories (slug__uuid)
- storage/cache_videos/ -> cached stock videos
- storage/generated/ -> external provider assets
- storage/local_videos/ -> uploaded materials
- resource/public/ -> web UI
- resource/fonts/ -> fonts
- resource/songs/ -> BGM and copyright_free
  - Source: [app/utils/utils.py](app/utils/utils.py)

## Avatar + LipSync Pipeline

### Enablement
- avatar_image_file (input) triggers _apply_avatar_bridge:
  - Sets character_overlay_enabled and character_lipsync_enabled
  - Maps avatar_position + offsets to character_custom_x/y
  - Source: [app/services/task.py](app/services/task.py)

### Image preparation
- Validates file type, size, dimensions
- Optional background removal and transparent-edge crop
  - Source: [app/services/character_image.py](app/services/character_image.py)

### LipSync analysis
- RMS-based envelope on audio, with smoothing and visual lead
- Returns timeline of LipSyncFrame with openness per window
  - Source: [app/services/character_lipsync.py](app/services/character_lipsync.py)

### Overlay composition
- Scales character image to canvas
- Calculates position and mouth region
- Builds mask + animation frames
- Handles manual mouth mapping and face detection (if cv2 available)
  - Source: [app/services/character_overlay.py](app/services/character_overlay.py)

### Composition order
- Layer order: base video -> character (behind by default) -> subtitles -> character (optional front)
  - Source: [app/services/video.py](app/services/video.py)

## Video Composition

### Combine clips
- Clips are subclipped, resized, transitions applied, temp clips saved, then ffmpeg concat.
- Handles looping to match audio duration.
  - Source: [app/services/video.py](app/services/video.py)

### Final render
- Adds cover intro (optional)
- Adds subtitles
- Adds avatar overlay
- Mixes narration + BGM
- Writes MP4 (H.264 + AAC)
  - Source: [app/services/video.py](app/services/video.py)

## Subtitles

### Edge TTS subtitle path
- edge_tts SubMaker cues are merged into script-aligned lines
- Fallback to legacy SubMaker offsets when needed
- Aligns subtitle duration to audio duration
  - Source: [app/services/voice.py](app/services/voice.py)

### Whisper subtitle path
- Uses faster-whisper; splits on punctuation
- Corrects subtitles to match the script
  - Source: [app/services/subtitle.py](app/services/subtitle.py)

## Integrations: External Providers

Entry points:
- Provider routing and fallback: [app/integrations/provider_router.py](app/integrations/provider_router.py)
- Shared helpers: [app/integrations/common.py](app/integrations/common.py)

Providers (requirements and flow):
- D-ID (avatar video): needs imageUrl + script, Basic auth header, polls /talks/{id} until ready.
  - [app/integrations/did.py](app/integrations/did.py)
- HeyGen (avatar video): needs script, uses avatar_id and voice_id in metadata, polls status endpoint.
  - [app/integrations/heygen.py](app/integrations/heygen.py)
- GetImg (image/video): prompt required; image output uses text-to-image endpoint; can return immediate URL or polling.
  - [app/integrations/getimg.py](app/integrations/getimg.py)
- FAL (video/image): prompt required; queue-based, poll status URL then fetch response URL.
  - [app/integrations/fal.py](app/integrations/fal.py)
- Stability (image): prompt required; returns image binary or base64 payload.
  - [app/integrations/stability.py](app/integrations/stability.py)
- Replicate (image/video): prompt or imageUrl required, metadata.version required, poll predictions.
  - [app/integrations/replicate.py](app/integrations/replicate.py)
- Shotstack (final render): templateId or assets required; polls render ID.
  - [app/integrations/shotstack.py](app/integrations/shotstack.py)
- BannerBear (template render): templateId required; polls render status.
  - [app/integrations/bannerbear.py](app/integrations/bannerbear.py)

Fallback order for external video_source:
- getimg -> fal -> stability -> replicate
  - Source: [app/integrations/provider_router.py](app/integrations/provider_router.py)

## Configuration and Secrets

### Config loading order
1. .env (if exists)
2. config.toml (copied from config.example.toml if missing)
3. Code defaults
  - Source: [app/config/config.py](app/config/config.py)

### Key config areas (excerpt)
- app.video_source, app.subtitle_provider, app.edge_tts_timeout, app.tls_verify
- app.pexels_api_keys, app.pixabay_api_keys
- app.enable_redis, app.redis_host, app.redis_port, app.max_concurrent_tasks
- app.endpoint (public download base)
- whisper.model_size, whisper.device, whisper.compute_type
- ui.subtitle_position, ui.custom_position
- upload_post settings
  - Source: [config.example.toml](config.example.toml)

### API key resolution
- Uses config first, then environment variable fallback
  - Source: [app/integrations/api_key_resolver.py](app/integrations/api_key_resolver.py)

## Task State and Concurrency
- In-memory or Redis task store based on enable_redis.
- Task manager (in-memory or Redis) controls max_concurrent_tasks.
  - Source: [app/controllers/v1/video.py](app/controllers/v1/video.py), [app/services/state.py](app/services/state.py)

## Security, Performance, Reliability Notes

### Security
- Upload filename sanitization to prevent traversal in upload endpoints.
  - [app/controllers/v1/video.py](app/controllers/v1/video.py)
- Task file access enforced by path normalization and base-dir constraint.
  - [app/controllers/v1/video.py](app/controllers/v1/video.py)
- TLS verification defaulted to true for Pexels/Pixabay and downloads.
  - [app/services/material.py](app/services/material.py)

### Performance
- ffmpeg concat used to avoid repeated re-encoding.
  - [app/services/video.py](app/services/video.py)
- MoviePy resource cleanup to reduce memory pressure.
  - [app/services/video.py](app/services/video.py)
- Lipsync analysis uses windowed RMS and caps audio size.
  - [app/services/character_lipsync.py](app/services/character_lipsync.py)

### Reliability
- Subtitle generation falls back to Whisper if edge path fails.
  - [app/services/task.py](app/services/task.py), [app/services/voice.py](app/services/voice.py)
- External provider polling timeouts and status normalization.
  - [app/integrations/common.py](app/integrations/common.py)
- External material fallback if Pexels/Pixabay/local fail.
  - [app/services/task.py](app/services/task.py)

## Known Risk Areas and Change Impact
- API key auth is disabled by default; enabling requires uncommenting dependencies.
- External providers require correct metadata (HeyGen avatar_id/voice_id, Replicate version).
- task_dir naming uses slug__uuid; direct file paths must use resolved task name.
- character overlay can be disabled if avatar_image_file is not inside storage/tasks.
- MoviePy operations are CPU intensive; max_concurrent_tasks should be tuned.

## Quick Entry Points for Debugging
- Task orchestration: [app/services/task.py](app/services/task.py)
- External provider failures: [app/integrations/provider_router.py](app/integrations/provider_router.py) + provider modules
- Avatar/lipsync missing: [app/services/task.py](app/services/task.py) -> _apply_avatar_bridge
- Subtitles mismatch: [app/services/voice.py](app/services/voice.py) and [app/services/subtitle.py](app/services/subtitle.py)
- Media fetch issues: [app/services/material.py](app/services/material.py)

## Output Checklist (for future edits)
- Validate config keys against config.example.toml when adding new parameters.
- Ensure any new endpoint is included in root router.
- For new providers, implement in app/integrations and add to provider_router map.
- Update task state and storage paths consistently.
