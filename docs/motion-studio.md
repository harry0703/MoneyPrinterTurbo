# Motion Studio

Motion Studio makes motion-graphics Shorts with a talking host. Instead of stitching stock clips, it
animates big text, numbers and cards in time with each spoken word, and a character (your 3D model or
image) speaks every line. It runs inside MoneyPrinterTurbo's API server and opens in your browser.

You give it:

1. a **character**: a `.glb` 3D model, an image, or none;
2. a **script writer**: your AI provider, model and API key;
3. a **brief**: title, topic, key points and a voice.

It writes the script and scene plan, records the voice, renders a 1080x1920 MP4, and hands you a
YouTube upload kit.

## Quick start

```bash
# 1. Install the optional renderer (drives headless Chrome)
uv pip install playwright
# Uses your installed Google Chrome. Without Chrome, also run:
playwright install chromium

# 2. Start the API server
python main.py

# 3. Open the studio
#    http://127.0.0.1:8080/studio/
```

A 45-second video takes about 1.5 to 4 minutes, depending on the machine. One video renders at a
time; up to three can wait in the queue.

## Characters

| You upload | What it does |
|---|---|
| A `.glb` rigged like the sample penguin: nodes named `root`, `body`, `head`, `beak`, `jaw`, `eyeL`, `eyeR`, `wingL`, `wingR` (optional `Brow_L`/`Brow_R`, `Cheek_*`) | The jaw follows the voice loudness every frame; it blinks, glances, nods on stressed words, raises its brows on emphasis, and gestures when something appears on screen. |
| Any other `.glb` | Fitted to the frame. It plays the model's idle animation if it has one, and bobs, turns, squashes with the voice and reacts to moods. |
| A transparent PNG | Stands on the sticker disc as a cut-out, bounces with the voice, tilts per phrase. |
| A photo (JPG, PNG, WebP) | A round portrait on the disc, with the same motion. |
| No character | Captions use the full width. |

A still image can't lip-sync; only rigged models move a mouth. Limits: GLB up to 50 MB, images up to
10 MB. Draco- or meshopt-compressed GLBs are rejected: export without compression.

**Saved characters:** put files in `storage/motion/characters/` and they appear under *Saved*.
That folder is gitignored, so models you aren't allowed to redistribute stay on your machine.

## Script writer and your API key

Providers: OpenAI, Anthropic, Google Gemini, OpenRouter, DeepSeek, Ollama (local, no key) and any
OpenAI-compatible endpoint (base URL). Calls go through LiteLLM, which MoneyPrinterTurbo already
depends on. The model field is free text; the suggestions are only a starting point.

The key you paste goes from the studio to this server and straight to the provider for that video.
It is never written to disk, logged, returned by the API or kept after the job's script is written,
and the studio keeps it in memory only (not in local storage). Provider error messages are scrubbed
of anything key-like before they are shown.

The AI is told to use only facts from your brief or common knowledge and never to invent statistics,
so put the numbers you want on screen in the description. For money, health or legal topics it adds
an "information only" line to the outro.

## Voices and languages

Edge TTS (free, no key): Hindi, English (India and US), Marathi, Simplified Chinese, Spanish and
Brazilian Portuguese voices. The script is written in the voice's language. Hindi scripts keep common
English terms in English letters.

## Publishing to YouTube

YouTube offers no way for another site to attach a video or prefill the upload form. **Upload to
YouTube** therefore does three things in one click: opens YouTube Studio's uploader in a new tab,
copies the description and hashtags, and downloads the MP4. The studio shows the title and
description with copy buttons; drop the file into YouTube and paste.

YouTube demonetizes mass-produced "inauthentic" content. Review each video and post at a human pace.

## Security notes

- Every `/api/v1/motion` route uses the same `app.api_key` check as the rest of the API. When a key is
  set, the studio asks for it once per tab.
- `listen_host` defaults to `0.0.0.0`, which exposes the server to your network. On shared networks
  set `listen_host = "127.0.0.1"` or `app.api_key`, and remember that over plain HTTP your provider key
  crosses the network unencrypted: use the studio on the same machine or behind HTTPS.
- Uploads are checked by extension, size and file signature and stored under server-generated names.
- AI-written text is rendered as text (`textContent`), never as HTML.
- The renderer serves only the engine folder and the current job's folder, on a random localhost port.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/motion/options` | Providers, voices, saved characters, renderer status |
| POST | `/api/v1/motion/characters` | Upload a character (multipart `file`) |
| GET | `/api/v1/motion/characters/{id}` | Character file |
| POST | `/api/v1/motion/jobs` | Start a video: `{title, topic, description, voice, character_id, llm: {provider, model, api_key, base_url}}` |
| GET | `/api/v1/motion/jobs/{id}` | Status, progress, ETA, error, result (duration, YouTube title, description, hashtags) |
| POST | `/api/v1/motion/jobs/{id}/cancel` | Cancel |
| GET | `/api/v1/motion/jobs/{id}/video` | Download the MP4 |

Job status lives in memory: restarting the server forgets the list, but files stay in
`storage/motion/jobs/<id>/` (`video.mp4`, `youtube.json`, `storyboard.json`, `render.log`).

## How it works

```
writer.py    LLM -> storyboard JSON (beats with a layout, mood and emphasis word), validated, one repair round
speech.py    Edge TTS per beat -> one audio track, exact beat times, per-frame loudness
renderer.py  headless Chrome plays resource/motion/auto.html; every frame is piped into ffmpeg
```

Scene layouts: `hook`, `big_number` (counts up), `compare`, `list`, `statement`, `outro`. Text shrinks to
fit its box. The look ("sticker pop": lilac stage, ink outlines, lime and coral) lives in
`resource/motion/base.css`.

## Development

```bash
cd webui-studio
npm install
npm run dev      # Vite on :5173, proxies /api and /motion-engine to python main.py on :8080
npm run build    # writes resource/public/studio (committed, so Python-only users need no Node)

# Render a ready-made storyboard without an LLM (checks voice, engine, host, renderer):
python scripts/motion_smoke.py test/resources/motion_storyboard.json hi-IN-MadhurNeural path/to/character.glb

# Tests
python -X utf8 -m pytest -q test/services/test_motion.py
```

## Third-party assets

- three.js r178 (MIT), vendored in `resource/motion/vendor/three` with its license.
- Phosphor Icons (MIT): the studio uses `@phosphor-icons/react`; the engine inlines the bold check and X paths.
- Baloo 2 (SIL OFL 1.1), `resource/motion/fonts` with its license; the studio bundles Baloo 2 and
  Mukta (both OFL) through Fontsource.
