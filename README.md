# Clipp Engine

MoneyPrinterTurbo fork — AI video generation engine for Clipp.

## What This Is

This is a fork of [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) with
Clipp-specific Railway deployment files added. It handles:

- AI script generation (Pollinations/DeepSeek/Gemini/OpenAI)
- Text-to-speech voice synthesis (Edge TTS — 100+ voices)
- Stock footage sourcing (Pexels + Pixabay)
- Video assembly (FFmpeg)
- Subtitle burning (FFmpeg drawtext)
- Background music mixing

## Clipp-Added Files

These files were added to the MPT fork for Railway deployment:

```
Dockerfile              Production container (Python 3.11 + FFmpeg + ImageMagick)
railway.toml            Railway service configuration
clipp_auth.py           Internal secret header middleware
config.toml.template    Placeholder (config generated at startup)
railway/
  start.sh              Startup script: validates env → generates config → starts MPT
  generate-config.sh    Writes config.toml from environment variables
```

## Required Modification to main.py

After forking MPT, add this to `main.py`:

```python
from clipp_auth import ClippAuthMiddleware

# After: app = FastAPI(...)
app.add_middleware(ClippAuthMiddleware)
```

This validates `X-Clipp-Internal-Secret` on every request, ensuring only
the Clipp web service can call the engine.

## Deploy to Railway

1. Fork MoneyPrinterTurbo on GitHub
2. Add all files from this directory to the fork root
3. Add `app.add_middleware(ClippAuthMiddleware)` to `main.py`
4. Push to GitHub
5. In Railway: New Service → GitHub Repo → select your fork
6. Set environment variables (see below)
7. Deploy

## Environment Variables

Set these in the Railway engine service:

| Variable | Required | Description |
|---|---|---|
| `INTERNAL_API_SECRET` | ✓ | Must match `CLIPP_ENGINE_SECRET` in web service |
| `PEXELS_API_KEYS` | ✓ | Comma-separated Pexels API keys |
| `LLM_PROVIDER` | ✓ | `pollinations` (free) or `deepseek`/`openai`/`gemini` |
| `DEFAULT_VOICE` | | Default TTS voice (default: `en-US-AriaNeural`) |
| `DEEPSEEK_API_KEY` | | Required if `LLM_PROVIDER=deepseek` |
| `OPENAI_API_KEY` | | Required if `LLM_PROVIDER=openai` |
| `GEMINI_API_KEY` | | Required if `LLM_PROVIDER=gemini` |
| `PIXABAY_API_KEYS` | | Optional backup footage source |

## Architecture

```
clipp-web (Railway) ──[X-Clipp-Internal-Secret]──► clipp-engine (Railway)
                      private networking only         │
                                                      ▼
                                               FFmpeg + MPT
                                                      │
                                                      ▼
                                           Video file in memory
                                                      │
                         clipp-web ◄── downloads ─────┘
                              │
                              ▼
                       Uploads to R2 (private)
```

Private networking means the engine is never reachable from the internet —
only from within the same Railway project.
