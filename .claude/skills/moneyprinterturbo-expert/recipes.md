# Recipes

## Run locally

```bash
cp config.example.toml config.toml   # fill llm_provider + key, pexels_api_keys
uv sync                              # or: pip install -r requirements.txt
streamlit run webui/Main.py          # WebUI on :8501
python main.py                       # or API on :8080 (docs at /docs)
pytest                               # tests in test/services/
```

Requires FFmpeg on PATH (or `IMAGEIO_FFMPEG_EXE`) and, for subtitle
rendering outside Docker, ImageMagick with a permissive policy.

## Run with Docker

```bash
docker compose up                    # webui :8501 (docker-compose.gpu.yml for CUDA whisper)
# mount config + storage:
#   -v $(pwd)/config.toml:/MoneyPrinterTurbo/config.toml
#   -v $(pwd)/storage:/MoneyPrinterTurbo/storage
```

The Dockerfile patches ImageMagick `policy.xml` (required by MoviePy text) and
sets `PYTHONPATH=/MoneyPrinterTurbo`. Keep both in derived images.

## Generate a video via API

```bash
curl -X POST http://localhost:8080/api/v1/videos -H 'Content-Type: application/json' -d '{
  "video_subject": "the history of coffee",
  "video_aspect": "9:16",
  "voice_name": "en-US-JennyNeural-Female",
  "subtitle_enabled": true
}'
# -> {"task_id": "..."}; poll GET /api/v1/tasks/{task_id}; download final-1.mp4 via /download
```

## Add a new LLM provider

1. `app/services/llm.py::_generate_response()` — add a branch keyed on
   `llm_provider`. If the provider is OpenAI-compatible, reuse the OpenAI SDK
   with `base_url`; copy an existing branch (e.g. deepseek) as template.
2. `config.example.toml` — add `{name}_api_key`, `{name}_model_name`,
   `{name}_base_url` with comments.
3. WebUI: add the provider to the provider list in `webui/Main.py` so it's
   selectable, and config hints if needed.
4. Strip provider-specific noise (e.g. `<think>` blocks) in the shared
   post-processing, not per branch.
5. Add a test in `test/services/test_llm.py` mocking the HTTP/SDK call.

## Add a new TTS provider

1. `app/services/voice.py` — write `myengine_tts(text, voice_name, voice_rate, voice_file, voice_volume) -> SubMaker | None`.
2. Choose a voice-name prefix (`myengine:VoiceName-Female`) and route it in
   `tts()`; add the voices to the voice-list helpers so the WebUI picker shows
   them (gender suffix is used for filtering).
3. If the engine gives no word timings, call
   `populate_legacy_submaker_with_full_text(sub_maker, text, audio_duration)`
   after synthesis so subtitle generation keeps working.
4. Config keys in `config.example.toml`; test in `test/services/test_voice.py`.

## Add a new stock-video source

1. `app/services/material.py` — implement
   `search_videos_mysource(search_term, minimum_duration, video_aspect) -> List[MaterialInfo]`
   mapping the API response to `MaterialInfo(provider, url, duration)`. Filter
   by orientation server-side when the API supports it.
2. Register it in `download_videos()`'s source dispatch and use
   `get_api_key("mysource_api_keys")` for key rotation.
3. Add `mysource_api_keys = []` to `config.example.toml`, the source option in
   `webui/Main.py`, and a `VideoParams.video_source` mention in
   `app/models/schema.py` docs.
4. Test with mocked HTTP in `test/services/test_material.py`.

## Add a transition effect

1. `app/services/utils/video_effects.py` — add `mytransition_transition(clip, t=1)`
   using MoviePy effects.
2. Add the enum member to `VideoTransitionMode` in `app/models/schema.py`.
3. Wire the case in `combine_videos()`'s transition dispatch
   (`app/services/video.py`) — `Shuffle` mode picks randomly among available
   transitions, so new ones join it automatically if added to its pool.
4. Expose in WebUI transition selector.

## Debug common failures

| Symptom | Likely cause / fix |
|---|---|
| Task stuck at progress 10–20 | LLM provider error: check key/model/base_url; `generate_terms` retries 5x on malformed JSON — see logs |
| TTS hangs then fails | edge-tts network stall; watchdog raises after `edge_tts_timeout` (raise it, or switch voice/provider) |
| Subtitles empty or misaligned | wrong `subtitle_provider`; for non-edge voices ensure legacy SubMaker population ran; whisper needs the model download on first run |
| No materials found | term too niche (terms must be English), aspect filter excludes results, or API key quota — try another source or add keys for rotation |
| `final-*.mp4` write fails | hardware codec unavailable → should auto-fallback to libx264; if it doesn't, set `video_codec = "libx264"` |
| Text rendering crash in Docker-derived images | ImageMagick policy.xml not patched |
| Ollama unreachable from container | use `host.docker.internal` or rely on the container auto-detection in `app/config/config.py` |
| 429 from POST /videos | queue full: raise `max_concurrent_tasks` / `max_queued_tasks` or wait |
| Import errors running scripts directly | `PYTHONPATH` must include repo root |
