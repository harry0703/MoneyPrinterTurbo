# AGENTS.md

Universal instructions for any AI coding agent working in this repo (OpenAI Codex CLI, Aider, Continue, Zed, Cursor, etc). Claude Code reads `CLAUDE.md` instead but should stay consistent with this file.

## Project overview

MoneyPrinterTurbo generates short videos from a topic or keywords: it writes the script, synthesizes voiceover, matches or generates video/image material, produces subtitles and background music, and composes the final clip. It's used through a Streamlit WebUI, a FastAPI REST API, or a CLI, and can auto-publish finished videos to TikTok/Instagram/YouTube Shorts.

## Tech stack

- **Language/runtime:** Python 3.11+
- **API:** FastAPI + uvicorn (`main.py`)
- **WebUI:** Streamlit (`webui/Main.py`), with per-locale strings in `webui/i18n/*.json`
- **Video/audio:** MoviePy + FFmpeg for composition; `faster-whisper` for subtitle timing
- **LLM/TTS/material providers:** many interchangeable providers behind small registries — see Directory map
- **Package/env management:** `uv` (dependencies in `pyproject.toml`, pinned in `uv.lock`)
- **Tests/lint:** `pytest` + `coverage`, `ruff`
- **Deployment:** Docker (`Dockerfile`, `Dockerfile.gpu`, `docker-compose*.yml`)

## Setup

```bash
uv sync                      # install deps (or: pip install -e . && pip install pytest ruff coverage)
cp config.example.toml config.toml
python main.py                # start the FastAPI server
./webui.sh                    # start the Streamlit WebUI (webui.bat on Windows)
```

## Commands

| Task | Command |
|---|---|
| Install | `uv sync` |
| Dev server (API) | `python main.py` |
| Dev server (WebUI) | `./webui.sh` (Windows: `webui.bat`) |
| Test | `pytest test/` |
| Lint | `ruff check .` |
| Build (Docker) | `docker build -t moneyprinterturbo .` |

## Conventions

- Prefer editing existing files over creating new ones.
- No premature abstraction — don't build for hypothetical future requirements.
- Match existing code style in the file you're editing over imposing a new one; many existing comments are in Chinese explaining non-obvious *why* — follow that pattern in adjacent code rather than translating it.
- Write tests for new behavior; run `pytest test/` before calling a task done.
- Don't commit secrets, `.env` files, `config.toml`, or credentials.
- Adding an LLM/TTS/material provider almost always means adding one registry entry plus locale strings, not new branching logic — see Directory map.

## Boundaries

- Ask before: deleting data, force-pushing, changing CI/CD, upgrading major dependencies.
- Never: commit directly to `main`/`master` without review, disable tests to make CI pass, hardcode secrets.

## Directory map

- `app/models/llm_provider.py` — the LLM provider registry (single source of truth: id, adapter, default model/URL, required fields); `app/services/llm.py` implements the adapters and script/keyword/social-metadata generation.
- `app/services/voice.py` — TTS providers; `app/services/material.py` — stock/AI video and image sourcing; `app/services/video.py` — composition; `app/services/subtitle.py` — subtitle generation.
- `app/controllers/v1/` — FastAPI route handlers; `app/models/schema.py` — Pydantic request/response models.
- `webui/Main.py` — the Streamlit app; `webui/i18n/en.json` and `webui/i18n/zh.json` are the two fully-maintained locales (other locales fall back to English for supplementary strings — see `ENGLISH_FALLBACK_KEYS` in `test/services/test_webui_i18n.py`).
- `cli.py` — CLI entrypoint; `main.py` — FastAPI entrypoint.
- `test/services/` — the pytest suite (one file per service/feature area).
- `docs/skill/` — a standalone installer/runner script (`mpt_agent.py`) that lets an AI agent install and drive this project as a packaged "Skill", independent of this repo's own dev tooling.
- `config.example.toml` — config template; real config lives in a gitignored `config.toml`.
