# AGENTS.md

Instructions for any AI coding assistant working in this repository (Codex, Cursor, Copilot,
Gemini CLI, Claude Code, Aider, etc.). This file and `.agents/` are the single source of truth;
tool-specific folders (such as `.claude/`) only hold thin adapters that point back here.

## Commands

Dependencies are pinned in `pyproject.toml` + `uv.lock` (`requirements.txt` is legacy). Python 3.11+.
`flake.nix` provides a dev shell (python311, uv, ffmpeg): `nix develop`, then `uv sync --frozen`.
When the `.venv` was created by the Nix Python, run project Python inside the shell
(`nix develop --command ...`), otherwise numpy fails to load `libstdc++.so.6`.

```sh
uv sync --frozen                      # install (add --extra twelvelabs for the optional integration)
cp config.example.toml config.toml    # required runtime config (API keys, providers)

./webui.sh                            # Streamlit WebUI (webui/Main.py), default 127.0.0.1:8501
python main.py                        # FastAPI server (app.asgi:app), docs at /docs
uv run python cli.py --help           # CLI (also `mpt cli`, `mpt webui` once packaged)

# CI equivalents
uv run ruff check app cli.py main.py webui test docs/skill
uv run python -X utf8 -m pytest -q test
uv run python -X utf8 -m coverage run -m pytest -q test && uv run python -m coverage report   # fail_under = 70
```

## Architecture

Three front ends share one pipeline: FastAPI (`app/asgi.py`, routers in `app/controllers/v1`),
Streamlit WebUI (`webui/Main.py`, i18n JSON in `webui/i18n/`) and CLI (`cli.py`). All of them end
up in `app/services/task.py::start()` → `_run_pipeline`. Keep new behavior in the service layer so
all three paths get it.

Pipeline stages (`app/services/`): script and search terms (`llm.py`) → TTS (`voice.py`) →
subtitles (`subtitle.py`) → stock/AI material (`material.py` and provider modules) → compositing
(`video.py`, `video_project.py`) → optional BGM and cross-posting (`bgm.py`, `upload_post.py`).
`stop_at` halts early (e.g. script-only or voice preview).

- LLM providers are pluggable (`app/models/llm_provider.py`, `llm.py`); no provider is privileged.
  Music providers register in `_VIDEO_MUSIC_PROVIDERS` in `task.py`.
- Task state: `app/services/state.py` (memory and Redis); queueing in `app/controllers/manager/`.
- Config: `app/config/config.py`; writes are blocked while a video task holds `runtime_config_lock`.
- Resource paths go through `app/paths.py` (source checkout vs. pip install).
- `allow_server_file_input` in `task.start()` is CLI-only; file helpers in `app/utils/file_security.py`.

Code comments and docstrings are mostly in Chinese; follow the surrounding language. When adding
WebUI strings, update every `webui/i18n/*.json`. More docs: `docs/`, `test/README.md`.

## Produção de vídeo com agentes (`.agents/`)

Fluxo para produzir um vídeo sobre qualquer assunto, do tema ao arquivo final: pesquisa com fonte
→ roteiro criticado → narração na duração alvo → clipes reais sincronizados frase a frase → render.

- `.agents/skills/video/SKILL.md` — orquestração (formato aberto de skill: frontmatter + Markdown),
  com os scripts `srt_to_timing.py` e `build_timeline.py` (só biblioteca padrão do Python + ffmpeg).
- `.agents/roles/` — um arquivo por papel. Ferramentas com subagentes delegam cada papel a um;
  as demais executam os papéis em sequência.
- `.agents/pipeline.md` — pasta do projeto, etapas e contratos de arquivo.
- `.agents/playbooks/` — `yt-dlp.md`, `ffmpeg-timeline.md`, `moneyprinter.md`.

| Papel | Função |
|---|---|
| `pesquisador` | fatos com fonte, material visual por bloco, roteiro |
| `cacador-de-clipes` | assiste os vídeos e escolhe o trecho de cada cena |
| `editor-de-clipes` | gera os clipes no formato do vídeo com `build_timeline.py` |
| `montador-mpt` | roda o MoneyPrinterTurbo (áudio, tempos, render) |
| `critico` | aponta falhas e buracos (conteúdo e visual), não edita |
| `sugestor-de-pauta` | propõe casos, dados, ganchos e cenas que enriquecem o vídeo |

Para usar: peça ao seu assistente "siga `.agents/skills/video/SKILL.md` para um vídeo sobre <tema>".
Requisitos do assistente: terminal, busca na web e capacidade de ver imagens (para conferir
quadros); sem visão, ele deve pedir ao usuário para conferir as prévias.
