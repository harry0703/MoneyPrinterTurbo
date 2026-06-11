---
name: moneyprinterturbo-expert
description: >-
  Expert knowledge of the MoneyPrinterTurbo codebase: the full AI short-video
  generation pipeline (LLM script -> search terms -> TTS audio -> subtitles ->
  stock-video sourcing -> clipping/concat -> final compositing), its FastAPI
  service, Streamlit WebUI, configuration system, and deployment. Use when
  working on, debugging, extending, or explaining anything in this repository:
  adding LLM/TTS/video-source providers, fixing subtitle timing, changing video
  composition, configuring config.toml, task/state management, or Docker setup.
---

# MoneyPrinterTurbo Expert

MoneyPrinterTurbo generates complete short videos (9:16, 16:9 or 1:1) from a
single subject string: an LLM writes the script, TTS narrates it, subtitles are
aligned to the speech, stock footage is fetched and cut to match the audio, and
everything is composited with MoviePy/FFmpeg into `final-{n}.mp4`.

## Mental model (read this first)

One orchestrator drives everything: `app/services/task.py::start(task_id, params, stop_at="video")`.
It runs the stages below in order, persisting progress into a state store after
each one. `stop_at` checkpoints (`script`, `terms`, `audio`, `subtitle`,
`materials`, `video`) let callers run a partial pipeline (this is how the
`/audio` and `/subtitle` API endpoints reuse the same code path).

| # | Stage | Service / key function | Output |
|---|-------|------------------------|--------|
| 1 | Script | `llm.py::generate_script()` | plain-text script |
| 2 | Search terms | `llm.py::generate_terms()` | JSON list of English terms |
| 3 | TTS audio | `voice.py::tts()` | `audio.mp3` + `SubMaker` timings |
| 4 | Subtitles | `voice.py::create_subtitle()` or `subtitle.py::create()` (whisper) | `subtitle.srt` |
| 5 | Materials | `material.py::download_videos()` | cached stock clips |
| 6 | Combine | `video.py::combine_videos()` | `combined-{n}.mp4` |
| 7 | Composite | `video.py::generate_video()` | `final-{n}.mp4` |

All task artifacts live in `storage/tasks/{task_id}/`. Stock-video cache lives
in `storage/cache_videos/` (configurable via `material_directory`).

The single source of truth for request parameters is
`app/models/schema.py::VideoParams` (Pydantic). Enums: `VideoAspect`
(`16:9`→1920x1080, `9:16`→1080x1920, `1:1`), `VideoConcatMode`
(`random`/`sequential`), `VideoTransitionMode` (`Shuffle`, `FadeIn`, `FadeOut`,
`SlideIn`, `SlideOut`). Task states in `app/models/const.py`: `-1` failed,
`4` processing, `1` complete.

## Entry points

- **WebUI**: `streamlit run webui/Main.py` (port 8501). i18n JSON in
  `webui/i18n/` (de, en, pt, ru, tr, vi, zh).
- **API**: `python main.py` → uvicorn/FastAPI on port 8080 (`app/asgi.py`,
  routes in `app/router.py` + `app/controllers/v1/video.py`).
- **CLI**: `cli.py`.

## Reference files (load on demand)

- **[pipeline.md](pipeline.md)** — deep dive into every stage: LLM prompt
  engineering, all TTS providers and SubMaker subtitle alignment, whisper
  fallback + Levenshtein correction, material sourcing, clip
  selection/letterboxing/transitions, FFmpeg concat, final compositing and
  subtitle rendering.
- **[configuration.md](configuration.md)** — full `config.toml` reference:
  20+ LLM providers, TTS/voice naming conventions, video sources and API keys,
  whisper, redis, proxy, codec settings.
- **[api-and-webui.md](api-and-webui.md)** — REST endpoints, task queue and
  concurrency limits, memory vs redis task managers, state store, Streamlit UI
  structure and i18n.
- **[patterns.md](patterns.md)** — reusable engineering techniques this repo
  teaches: thread-safe API key rotation, hardware-codec fallback with runtime
  detection, TTS streaming timeout via daemon thread + queue, duration
  estimation for no-voice mode, subtitle/script alignment, rounded subtitle
  backgrounds with PIL.
- **[recipes.md](recipes.md)** — step-by-step guides: run locally / via
  Docker, add a new LLM provider, add a new TTS provider, add a new stock
  video source, add a transition effect, debug common failures.

## Conventions and gotchas (always relevant)

- Config is read once from `config.toml` at repo root by
  `app/config/config.py`; copy `config.example.toml` to start. Never commit
  real API keys.
- `PYTHONPATH` must include the repo root; FFmpeg binary resolution order is
  `IMAGEIO_FFMPEG_EXE` env var → system PATH → bundled imageio_ffmpeg.
- Subtitle fonts come from `resource/fonts/` (default `STHeitiMedium.ttc`);
  BGM from `resource/songs/` (`bgm_type = "random"` picks one at random).
- Docker images patch the ImageMagick `policy.xml` — required for MoviePy text
  rendering; replicate this in any new image.
- File uploads/downloads must go through
  `app/utils/file_security.py::resolve_path_within_directory()` to prevent
  path traversal. Keep this invariant when adding endpoints.
- Hardware encoders (`h264_nvenc`, `h264_amf`, `h264_qsv`, ...) are optional;
  every write path must keep the automatic `libx264` fallback
  (`video.py::_write_videofile_with_codec_fallback`).
- Tests live in `test/services/`; run with `pytest` from the repo root.
