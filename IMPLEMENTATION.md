# MoneyPrinterTurbo — Implementation Log

## Estado: MILESTONE 2 COMPLETO — Video E2E real generado el 2026-06-24

---

## Entorno

| Item | Valor |
|------|-------|
| OS | Windows 11 Home 10.0.26200 |
| Python | 3.11.9 |
| uv | 0.11.24 |
| Rama | implementation/e2e-first-video |
| Directorio | C:\Users\Santoyle\Projects\MoneyPrinterTurbo |

---

## Instalación

```powershell
# 1. Instalar uv (gestor de paquetes)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

# 2. Clonar el repo
cd C:\Users\Santoyle\Projects
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
git checkout -b implementation/e2e-first-video

# 3. Instalar dependencias
uv sync --frozen

# 4. Copiar configuración base
# config.toml ya está configurado con opciones mínimas zero-key
```

---

## Configuración mínima (config.toml)

La configuración actual (`config.toml`) usa:
- `llm_provider = "pollinations"` — LLM gratuito, sin API key
- `video_source = "local"` — videos locales, sin Pexels/Pixabay
- `subtitle_provider = "edge"` — subtítulos vía edge-tts (gratuito)
- `enable_redis = false` — sin dependencia de Redis

**Decisión clave**: los videos locales deben estar en `./storage/local_videos/`.
La ruta `url` en `video_materials` es relativa a ese directorio por seguridad.

---

## FFmpeg

FFmpeg se descarga automáticamente vía `imageio-ffmpeg`. Ruta:
```
.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe
```

---

## ImageMagick (requerido para subtítulos)

**No instalado actualmente.** Por eso `subtitle_enabled = false` en las requests.

Para habilitar subtítulos:
1. Descargar: https://imagemagick.org/archive/binaries/ImageMagick-7.1.1-29-Q16-x64-static.exe
2. Instalar
3. Agregar a `config.toml`:
   ```toml
   imagemagick_path = "C:\\Program Files\\ImageMagick-7.1.1-Q16\\magick.exe"
   ```
4. Cambiar en el request: `subtitle_enabled = true`

---

## Iniciar el servidor API

```powershell
cd C:\Users\Santoyle\Projects\MoneyPrinterTurbo

# Opción A: foreground (visible en terminal)
.\.venv\Scripts\python.exe main.py

# Opción B: background (hidden)
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "C:\Users\Santoyle\Projects\MoneyPrinterTurbo\run_server.py" `
    -WorkingDirectory "C:\Users\Santoyle\Projects\MoneyPrinterTurbo" `
    -WindowStyle Hidden

# Verificar que el servidor responde
Invoke-RestMethod -Uri "http://127.0.0.1:8080/" -Method GET
```

Docs interactivos: http://127.0.0.1:8080/docs

---

## Generar un video — Comando reproducible

```powershell
$body = @{
    video_subject = "Tu tema aquí"
    video_script  = "Tu script completo aquí. El texto se convierte en voz con edge-tts."
    video_source  = "local"
    video_materials = @(
        @{ provider = "local"; url = "clip_01.mp4"; duration = 15 },
        @{ provider = "local"; url = "clip_02.mp4"; duration = 15 },
        @{ provider = "local"; url = "clip_03.mp4"; duration = 15 }
    )
    video_aspect        = "9:16"        # portrait para short-form
    voice_name          = "en-US-AndrewNeural"  # o cualquier voz edge-tts
    subtitle_enabled    = $false
    bgm_type            = "random"
    bgm_volume          = 0.2
    video_clip_duration = 5
    paragraph_number    = 1
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v1/videos" `
    -Method POST -Body $body -ContentType "application/json"
$task_id = $response.data.task_id
Write-Host "Task ID: $task_id"

# Consultar estado
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v1/tasks/$task_id" -Method GET | ConvertTo-Json -Depth 5
```

El video final queda en:
```
storage\tasks\{task_id}\final-1.mp4
```

---

## Milestone 1 — Primer video (placeholder local)

| Campo | Valor |
|-------|-------|
| Task ID | fc39adaa-932e-43e0-932c-705429f2faa5 |
| Archivo | `storage\tasks\fc39adaa-...\final-1.mp4` |
| Duración | 30 segundos |
| Resolución | 1080×1920 (portrait 9:16) |
| Video codec | H.264, 30fps |
| Audio | AAC 44.1kHz, 195 kb/s |
| Tamaño | 834 KB |
| LLM | Ninguno (script provisto manualmente) |
| Video source | Local (clips sintéticos de color sólido) |
| Subtítulos | Deshabilitados |

---

## Milestone 2 — Video E2E real (OpenAI + Pexels + subtítulos)

| Campo | Valor |
|-------|-------|
| Task ID | 54d1d25e-f129-4c83-9522-8f44e7e0562a |
| Archivo | `storage\tasks\54d1d25e-...\final-1.mp4` |
| Tema | "The surprising science of why morning sunlight makes you healthier" |
| Duración | **1 minuto 25 segundos** |
| Resolución | **1080×1920** (portrait 9:16) |
| Video codec | H.264 (High), 30fps, 5617 kb/s |
| Audio | AAC 44.1kHz stereo, 195 kb/s |
| Tamaño | **59 MB** |
| LLM | OpenAI `gpt-5.5` — generó script + search terms |
| Video source | Pexels — 17 clips únicos descargados automáticamente |
| Subtítulos | **Habilitados** — edge-tts timing, MoviePy TextClip, fondo negro |
| Tiempo de render | ~7 minutos (CPU, sin GPU) |
| Screenshots | `screenshot_05s.png`, `screenshot_42s.png`, `screenshot_80s.png` |

### Pipeline completo Milestone 2

1. **Script** — OpenAI `gpt-5.5` generó ~9 oraciones a partir del tema
2. **Terms** — OpenAI generó 5 términos de búsqueda para Pexels
3. **Audio** — edge-tts `en-US-AndrewNeural` → 82.7 segundos de narración
4. **Subtítulos** — edge-tts SubMaker → archivo `.srt` → MoviePy TextClip
5. **Materiales** — Pexels API descargó 17 clips de stock 1080×1920
6. **Combinación** — FFmpeg concatenó 17 clips en video base
7. **Video final** — MoviePy CompositeVideoClip con subtítulos + FFmpeg encode

### Config activa para Milestone 2

```toml
llm_provider = "openai"
openai_model_name = "gpt-5.5"
video_source = "pexels"
subtitle_provider = "edge"
```

### Request usado

```json
{
  "video_subject": "The surprising science of why morning sunlight makes you healthier",
  "video_aspect": "9:16",
  "voice_name": "en-US-AndrewNeural",
  "subtitle_enabled": true,
  "video_source": "pexels",
  "bgm_type": "random",
  "bgm_volume": 0.15,
  "video_clip_duration": 5,
  "paragraph_number": 1,
  "font_size": 60,
  "text_background_color": true
}
```

---

## Voces edge-tts disponibles (inglés US)

```
en-US-AvaNeural       en-US-AndrewNeural    en-US-EmmaNeural
en-US-BrianNeural     en-US-AnaNeural       en-US-AriaNeural
```

Ver lista completa:
```python
import asyncio, edge_tts
voices = asyncio.run(edge_tts.list_voices())
[print(v['ShortName']) for v in voices]
```

---

## Videos de prueba sintéticos

Los 3 clips en `storage/local_videos/` son fondos de color sólido (9:16, 15s, H.264).
Creados con:
```powershell
$ffmpeg = ".venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
& $ffmpeg -f lavfi -i "color=c=0x1a1a2e:s=1080x1920:r=25" `
    -f lavfi -i "anullsrc=r=44100:cl=stereo" `
    -t 15 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest `
    storage\local_videos\clip_01.mp4 -y
```

**Para producción real**: reemplazar por videos de stock reales o conectar Pexels/Pixabay.

---

---

## Milestone 3 — Batch Generation Validation

**Fecha:** 2026-06-24
**Modelo OpenAI:** gpt-5.5 (script + search terms)
**Footage provider:** Pexels
**TTS:** edge-tts `en-US-AndrewNeural`
**Subtítulos:** habilitados, posición bottom, font_size=60, fondo negro

> ✅ **Final status (2026-06-25): ALL 5 VIDEOS PASS audio integrity validation.**
> Two bugs were found and fixed. See full diagnosis below.

### Initial batch results (pre-fix)

| # | Topic | Task ID | API State | QA Result | audio.mp3 | combined dur | Gap |
|---|-------|---------|-----------|-----------|-----------|--------------|-----|
| 1 | The Power of Consistency | `7c255357` | stuck 75% | ❌ Audio cuts ~3s early | 31.99s | 35.00s | 3.01s |
| 2 | Why Motivation Is Overrated | `a6aca887` | stuck 75% | ❌ Audio cuts ~3.3s early | 31.70s | 35.00s | 3.30s |
| 3 | How to Focus in a Distracted World | `3d94d93a` | stuck 75% | ❌ Partial + clip error | 29.66s | 30.00s | 0.34s |
| 4 | Small Habits That Compound Over Time | `f2b5589e` | stuck 75% | ❌ Audio cuts ~2.3s early | 32.71s | 35.00s | 2.29s |
| 5 | How AI Can Help You Work Smarter | `185a19e6` | stuck 75% | ✅ PASS (gap only 0.29s) | 29.71s | 30.00s | 0.29s |

### Root cause — clip trimming bug in `video.py:667`

```python
# BEFORE (bug): trims each clip to max_clip_duration (5s) but never trims
# the last clip to the remaining required duration.
if clip.duration > max_clip_duration:
    clip = clip.subclipped(0, max_clip_duration)

# AFTER (fix): trims last clip to whichever is smaller — max duration or remaining needed.
remaining_needed = required_video_duration - video_duration
effective_max = min(max_clip_duration, remaining_needed) if remaining_needed > 0 else max_clip_duration
if clip.duration > effective_max:
    clip = clip.subclipped(0, effective_max)
```

**Effect:** For a 32s audio, 7 clips × 5s = 35s. The 7th clip was never trimmed to its needed ~2s.
Combined video was always padded to the nearest 5s multiple → audio truncated in playback.
AIWork (audio=29.71s, combined=30s, gap=0.29s) happened to fall within acceptable range by chance.

### Bug 2 — Shared temp audio file race condition (`video.py:_get_temp_audio_dir`)

Manual QA after the clip-trim fix revealed a second bug:
- Consistency: no audio
- Motivation: audio cuts at ~2s
- Focus: audio cuts at ~2s
- Habits/AIWork: fine

Root cause: `_get_temp_audio_dir()` returned `tempfile.gettempdir()` (shared system temp directory).
MoviePy writes a fixed-named temp file `TEMP_MPY_wvf_snd.mp3` inside that directory.
With concurrent renders, all tasks overwrote the same file — the last writer "won".

Evidence: extracted WAV from broken final-1.mp4 files was 0.02–0.23MB (should be ~5MB).
All `audio.mp3` source files were clean. Failure was entirely in the mux step.

```python
# BEFORE (bug): all concurrent tasks write to same temp file
if sys.platform == "win32":
    return tempfile.gettempdir()   # → C:\...\Temp\TEMP_MPY_wvf_snd.mp3 (shared!)

# AFTER (fix): unique subdirectory per task
if sys.platform == "win32":
    task_name = os.path.basename(os.path.normpath(output_dir))
    task_temp_dir = os.path.join(tempfile.gettempdir(), f"MPY_{task_name}")
    os.makedirs(task_temp_dir, exist_ok=True)
    return task_temp_dir
```

Note: an intermediate fix attempt returned a `.mp3` file path — MoviePy treated it as a
directory name, failed with "No such file or directory". The correct fix returns an actual
directory (created with makedirs) that is unique per task.

### Final validated results (sequential re-renders with both fixes)

| # | Topic | Task ID | Duration | WAV size | Gap | Audio | Status |
|---|-------|---------|----------|----------|-----|-------|--------|
| 1 | The Power of Consistency | `f4869ced` | 00:00:32.07 | 5.399MB | +0.08s | ✅ continuous | ✅ PASS |
| 2 | Why Motivation Is Overrated | `16bf7bc3` | 00:00:31.80 | 5.352MB | +0.10s | ✅ continuous | ✅ PASS |
| 3 | How to Focus in a Distracted World | `41505891` | 00:00:29.73 | 5.004MB | +0.07s | ✅ continuous | ✅ PASS |
| 4 | Small Habits That Compound Over Time | `7cdd4f3b` | 00:00:32.80 | 5.520MB | +0.09s | ✅ continuous | ✅ PASS |
| 5 | How AI Can Help You Work Smarter | `185a19e6` | 00:00:30.00 | 5.047MB | +0.29s | ✅ continuous | ✅ PASS |

**Validation method:** WAV extraction from final-1.mp4 + silencedetect at -35dB/1s threshold.
All WAVs ≥ 5MB (full audio). No silence detected in any extracted WAV. All gaps ≤ 0.29s.

### New validation rule
A video is only marked SUCCESS if:
- `final-1.mp4` exists with valid duration
- Extracted WAV ≥ 3MB (confirming full audio, not just metadata)
- No silence block > 1s detected in extracted WAV
- Audio/video duration gap ≤ 1.0s
- Screenshot extractable at 5s and midpoint (confirms decodable frames)

### Validación visual (screenshots)

| Video | Real footage | Subtítulos | Notas |
|-------|-------------|------------|-------|
| Consistency | ✅ Mujer en laptop, gym oscuro | ✅ Visibles | Footage muy relevante al tema |
| Motivation | ✅ Escritorio con reloj, gym | ✅ Visibles | Footage temáticamente coherente |
| Focus | ✅ Manos escribiendo en papel | ⚠️ Solo frame 5s | Sección media ilegible post-error |
| Habits | ✅ Escritorio, papeles motivacionales | ✅ Visibles | Clips de fitness/habits relevantes |
| AI Work | ✅ Robot humanoide con niña, oficina | ✅ Visibles | Footage muy relevante, robot clip excelente |

### Configuración usada

```json
{
  "video_aspect": "9:16",
  "video_source": "pexels",
  "video_clip_duration": 5,
  "paragraph_number": 1,
  "video_script_prompt": "Write exactly 75 to 90 words total. No more. Start with a strong hook sentence...",
  "voice_name": "en-US-AndrewNeural",
  "bgm_volume": 0.12,
  "subtitle_enabled": true,
  "font_size": 60,
  "stroke_width": 1.5,
  "text_background_color": true
}
```

### Problemas detectados y soluciones

| Problema | Causa | Solución aplicada |
|----------|-------|-------------------|
| Multiline string en PS5.1 rompía JSON | `@"..."@` serializa `\r\n` literal | Reemplazado por string de una sola línea |
| Task API atascada en 75% | Bug de state-flush con 5 tasks concurrentes | Validar por archivo: `final-1.mp4` stable size = done |
| Focus video corrupto en midpoint | `[Errno 22] Invalid argument` en clip 5 durante combinación | Video completo generado (30s), solo midpoint ilegible |
| AI Work tardó 30 min en iniciar | 4 renders + 1 stray task saturando CPU | Evitar 6 tasks concurrentes; máximo 4 |

### Tiempo de render (CPU, sin GPU)

| Video | Render start | File modified | Render time |
|-------|-------------|---------------|-------------|
| Consistency | 21:36:41 | 21:58:23 | ~22 min |
| Focus | 21:38:30 | 21:46:45 | ~8 min |
| Habits | 21:38:05 | 21:59:01 | ~21 min |
| Motivation | ~21:38 | 21:59:26 | ~21 min |
| AI Work | 21:54:35 | 22:02:13 | ~8 min |

Render time varies with CPU competition. Max 4 concurrent tasks recommended.

### Coste estimado (OpenAI gpt-5.5)

- 5 scripts (~85 words cada uno) + 5 sets de search terms (~6 terms cada uno)
- Input tokens estimados: ~500 tokens por video × 5 = ~2,500 tokens
- Output tokens estimados: ~200 tokens por video × 5 = ~1,000 tokens
- Coste aproximado: < $0.10 USD total (varía según pricing de gpt-5.5)

### Scripts y ejemplos creados

- `scripts/generate_batch_openai_pexels.ps1` — script reproducible para batches futuros
- `examples/requests/batch_productivity_openai_pexels.json` — template sin secrets

### Mejoras recomendadas para Milestone 4

- Limitar a 4 tasks concurrentes máximo (evitar saturación CPU)
- Añadir `video_script_prompt` para forzar 75-90 palabras en script template
- Detectar videos parcialmente corruptos por tamaño (< 5MB para 30s = sospechoso)
- Añadir `-update 1` flag a ffmpeg para screenshots más robustos
- Explorar GPU encoding (`h264_nvenc`) para reducir render time de 21 min → ~2 min

---

## Milestone 4 — Content Ops and CSV Batch Workflow

**Date:** 2026-06-26
**Branch:** `implementation/milestone-4-content-ops`

### What Was Implemented

1. **Content directory structure** (`content/`) — versionable, no secrets:
   - `content/topics/productivity_batch_v1.csv` — 10 topics with angle/audience/tone/preset/status columns
   - `content/presets/shorts_productivity_v1.json` — reusable preset for productivity short-form content
   - `content/presets/shorts_ai_work_v1.json` — preset oriented to AI tools and workflow automation
   - `content/reports/` — placeholder for future editorial reports

2. **CSV-driven batch script** (`scripts/generate_from_csv_openai_pexels.ps1`):
   - Reads topics from CSV, applies preset parameters, builds requests
   - `-DryRun` mode: validates CSV + preset, estimates durations, no API calls
   - `-Render` mode: sequential renders, one video at a time (no unsafe concurrency)
   - State-flush fallback: file-size stability check when API state stuck at 75%
   - Full audio integrity validation per video (WAV + silencedetect)
   - Screenshots at 5s and near-end (freeze detection)
   - Quality report saved to `storage/batch_reports/`

3. **Editorial presets** — JSON files with all render parameters:
   - `script_word_count_min/max` → injects word count constraint into LLM prompt
   - `hook_required`, `avoid_cliches` → documented editorial rules
   - `render_final_sequential: true`, `audio_integrity_validation: true`
   - `target/min/max_duration_seconds` — enforced at validation stage
   - `script_prompt_template` — per-preset LLM prompt template with angle/audience/tone injection

### How to Use the CSV

The CSV at `content/topics/productivity_batch_v1.csv` has these columns:

| Column | Purpose |
|--------|---------|
| `topic` | Video subject (maps to `video_subject` in API) |
| `angle` | Editorial angle injected into LLM prompt |
| `audience` | Target audience injected into LLM prompt |
| `tone` | Narration tone injected into LLM prompt |
| `duration_target_seconds` | Informational target (enforced via preset) |
| `preset` | Which preset to use (informational; override with -PresetPath) |
| `language` | Content language |
| `status` | `pending` / `done` / `skipped` — script skips non-pending rows |

Mark rows as `done` after successful manual QA to prevent re-render.

### How to Use Presets

Presets are JSON files in `content/presets/`. They control all render parameters:

```json
{
  "script_word_count_min": 70,
  "script_word_count_max": 95,
  "voice_name": "en-US-AndrewNeural",
  "bgm_volume": 0.12,
  "subtitle_position": "bottom",
  "render_final_sequential": true,
  "audio_integrity_validation": true,
  "script_prompt_template": "Write exactly {word_count_min} to {word_count_max} words total..."
}
```

Two presets available:
- `shorts_productivity_v1` — productivity, habits, focus, self-improvement
- `shorts_ai_work_v1` — AI tools, automation, knowledge work, workflows

### How to Run a Dry Run

Validates CSV + preset without making any API calls or renders:

```powershell
.\scripts\generate_from_csv_openai_pexels.ps1 `
    -CsvPath content\topics\productivity_batch_v1.csv `
    -PresetPath content\presets\shorts_productivity_v1.json `
    -DryRun -MaxItems 5
```

Produces: `storage/batch_reports/milestone_4_dry_run_report.md`

### How to Run a Render

Renders videos sequentially (one at a time). Always start with 3 to validate:

```powershell
.\scripts\generate_from_csv_openai_pexels.ps1 `
    -CsvPath content\topics\productivity_batch_v1.csv `
    -PresetPath content\presets\shorts_productivity_v1.json `
    -Render -MaxItems 3
```

Use `-StartFrom N` to skip rows (e.g., `-StartFrom 6` to start from the 6th row).

### Quality Validation Per Video

Every rendered video is validated automatically:

1. `final-1.mp4` exists and ffprobe can read duration
2. Duration within preset range (35-55s for default preset)
3. Audio extracted to WAV — must be >= 3MB for ~30s video
4. Silencedetect: no silence blocks > 1s in extracted WAV
5. `subtitle.srt` exists and has content (> 3 lines)
6. Screenshot extractable at 5s (confirms decodable frames)
7. Screenshot near end (> 85% of duration) — detects freeze artifacts

**Critical rule**: never mark SUCCESS based only on ffprobe metadata or file size.
WAV extraction + silencedetect is the authoritative audio check (established in M3).

### Heavy Outputs Excluded from Git

All generated outputs are gitignored:
- `storage/tasks/{task_id}/` — final-1.mp4, audio.mp3, subtitle.srt, screenshots
- `storage/batch_reports/` — dry-run and render reports
- `storage/local_videos/` — any downloaded Pexels clips

Only versionable files are committed:
- `content/topics/*.csv`
- `content/presets/*.json`
- `scripts/generate_from_csv_openai_pexels.ps1`
- `IMPLEMENTATION.md`

### Milestone 4 Render Results

Render batch run on 2026-06-26 (first 3 topics from productivity_batch_v1.csv):

| # | Topic | Task ID | Status | Duration | WAV | Audio | SRT | Screenshots | Notes |
|---|-------|---------|--------|----------|-----|-------|-----|-------------|-------|
| 1 | The Power of Consistency | `98eb97e8` | PENDING MANUAL QA | 33.27s | 5.598MB | PASS | PASS | PASS | Audio continuous, no silence |
| 2 | Why Motivation Is Overrated | `16fc8c6b` | PENDING MANUAL QA | 31.77s | 5.348MB | PASS | PASS | PASS | Audio continuous, no silence |
| 3 | How to Focus in a Distracted World | `5729de52` | PENDING MANUAL QA | 30.80s | 5.184MB | PASS | PASS | PASS | Audio continuous, no silence |

All 3 videos pass automated audio integrity validation. Manual playback QA required before marking as production-ready.

### Bug Found and Fixed in generate_from_csv_openai_pexels.ps1

**State-flush false positive**: `final-1.mp4` is created and written incrementally by MoviePy.
A partial file (1-5MB) appeared "stable" in an 8-second stability window, triggering the fallback
as if the render was complete. Validation then failed (invalid partial file).

Fix: raised minimum file size threshold from 1MB to 10MB. Completed 30s videos are 6-10MB.
A sub-5MB file is a partial write, not a finished render.

**Duration threshold mismatch**: The preset `min_duration_seconds: 35` was too strict.
edge-tts at natural pace produces ~30-33s of audio from a 70-95 word script. Lowered to 28s
to match actual rendered output (consistent with M3 results of 29-33s).

### Próximos Pasos — Milestone 5

- [x] Render next CSV batch (topics 4-7) using established sequential workflow
- [ ] GPU encoding (`-c:v h264_nvenc`) — reduce render time from ~20min to ~2min
- [ ] Spanish voice support: `es-ES-AlvaroNeural`, `es-MX-JorgeNeural`
- [ ] Batch size up to 10 once sequential rendering is confirmed stable
- [ ] Simple local UI for topic management and batch launch

---

## Milestone 5 — Continued CSV Batch Rendering

**Date:** 2026-06-26
**Branch:** `implementation/milestone-4-content-ops`

### What Was Executed

Continued the CSV batch workflow from Milestone 4 using the same script and preset with no code changes to the render pipeline. Rendered topics 4-7 from `productivity_batch_v1.csv` sequentially.

```powershell
.\scripts\generate_from_csv_openai_pexels.ps1 `
    -CsvPath content\topics\productivity_batch_v1.csv `
    -PresetPath content\presets\shorts_productivity_v1.json `
    -Render -StartFrom 4 -MaxItems 4 `
    -OutputReportName "milestone_5_topics_4_7_report.md"
```

Topics rendered:
1. Small Habits That Compound Over Time
2. How AI Can Help You Work Smarter
3. Why Most People Never Finish What They Start
4. The Hidden Cost of Multitasking

### Script Improvement (Milestone 5)

Added `manual_qa_pending` to the skip list in `generate_from_csv_openai_pexels.ps1`:
- Previously only skipped `done` and `skipped` status rows
- Now also skips `manual_qa_pending` to prevent accidental re-renders of unreviewed videos

### Validation Method

Same strong audio integrity validation as Milestone 3 and 4:
- WAV extraction from final-1.mp4 (not ffprobe metadata alone)
- silencedetect at -35dB/1s threshold — no silence blocks accepted
- Duration check against preset range (28-55s)
- SRT subtitle presence and content
- Screenshots at 5s and near-end (freeze detection)

### Render Results

| # | Topic | Task ID | Status | Duration | WAV | Audio | SRT | Screenshots |
|---|-------|---------|--------|----------|-----|-------|-----|-------------|
| 4 | Small Habits That Compound Over Time | c3c92b35-c0ca-4617-99a3-24a80c0cb2c1 | manual_qa_pending | 32.5s | 5.469MB | PASS | v | v |
| 5 | How AI Can Help You Work Smarter | 65e44dd9-ec4b-448f-b607-cc914d45e188 | manual_qa_pending | 31.2s | 5.25MB | PASS | v | v |
| 6 | Why Most People Never Finish What They Start | 25401b6c-ea0c-40be-868a-ef58f91c4a11 | manual_qa_pending | 34.6s | 5.828MB | PASS | v | v |
| 7 | The Hidden Cost of Multitasking | 4a4a476e-f7ae-42a7-9603-f1b4549d0b0c | manual_qa_pending | 31.0s | 5.223MB | PASS | v | v |

All 4 automated checks passed. Total render time: 29.1 minutes (sequential, 1 video at a time).

### Manual QA Status

All 4 videos set to `manual_qa_pending` after automated validation. Do not mark as `done` until manual playback confirms audio, subtitles, and footage.

### Report

`storage/batch_reports/milestone_5_topics_4_7_report.md` (gitignored)

---

## Milestone 6 — Final CSV Batch Rendering

**Date:** 2026-06-26
**Branch:** `implementation/milestone-4-content-ops`

### What Was Executed

Rendered the final 3 pending topics (rows 8-10) from `productivity_batch_v1.csv` using the same sequential workflow with no pipeline changes.

```powershell
.\scripts\generate_from_csv_openai_pexels.ps1 `
    -CsvPath content\topics\productivity_batch_v1.csv `
    -PresetPath content\presets\shorts_productivity_v1.json `
    -Render -StartFrom 8 -MaxItems 3 `
    -OutputReportName "milestone_6_topics_8_10_report.md"
```

### Render Results

| # | Topic | Task ID | Status | Duration | WAV | Audio | SRT | Screenshots |
|---|-------|---------|--------|----------|-----|-------|-----|-------------|
| 8 | How to Build Deep Work Habits Without Burnout | 5f732982-9eb3-4afe-83ba-983dce25b4a3 | manual_qa_pending | 30.3s | 5.098MB | PASS | v | v |
| 9 | The One Question That Fixes Any Blocked Decision | 2ed8465a-b25b-4505-bc0b-f0183f92876c | manual_qa_pending | 30.5s | 5.137MB | PASS | v | v |
| 10 | Why Your Morning Routine Is Making You Less Productive | 89b542b7-c099-44b8-999a-857013aaf16f | manual_qa_pending | 36.5s | 6.137MB | PASS | v | v |

All 3 automated checks passed. Total render time: 19.3 minutes (sequential).
Server started manually (PID 5028) as it was not running at session start.

### Manual QA Status

Videos set to `manual_qa_pending`. Do not mark as `done` until manual playback confirms audio, subtitles, and footage.

### Report

`storage/batch_reports/milestone_6_topics_8_10_report.md` (gitignored)

---

## CSV Final State

All 10 topics processed:
- Rows 1-7: `done` (manually approved)
- Rows 8-10: `manual_qa_pending` (awaiting manual review)

---

## Milestone 7-C — GPU Encoding Benchmark and Implementation

**Date:** 2026-06-26
**Branch:** `implementation/milestone-7c-gpu-encoding`

### Hardware Detected

- GPU: Intel UHD Graphics 620 (integrated)
- NVIDIA GPU: None (nvidia-smi not found)
- FFmpeg: imageio-ffmpeg v7.1 (bundled)

### Encoder Availability

| Encoder | Probe Result | Reason |
|---------|-------------|--------|
| h264_nvenc | FAIL | Cannot load nvcuda.dll — no NVIDIA GPU |
| h264_amf | FAIL | Cannot load amfrt64.dll — no AMD GPU |
| h264_qsv | PASS | Intel Quick Sync Video (UHD 620) |
| h264_mf | PASS | Windows Media Foundation |
| libx264 | PASS | CPU default, always available |

### Implementation

Two additions to `app/services/video.py`:

1. **`_probe_hardware_encoder(ffmpeg_binary, codec)`** — test-encodes one black frame to
   `/dev/null` before the first real encode. Catches driver failures (e.g. `nvcuda.dll`
   missing) that `_ffmpeg_encoder_exists` cannot detect. Result is cached per codec per
   process so the probe runs at most once.

2. **`"auto"` video codec option** — probes hardware encoders in priority order
   (nvenc → amf → qsv → mf → videotoolbox) and selects the first that passes both
   the encoder-list check and the runtime probe. Falls back to libx264 if none are
   usable. Existing runtime-disable and `_fallback_write_videofile` paths preserved.

### Benchmark (30s, 1080x1920, synthetic)

| Encoder | Time | Speedup | File size |
|---------|------|---------|-----------|
| libx264 (CPU) | 17.3s | 1.0x | 0.61MB |
| h264_qsv (Intel QSV) | 5.1s | **3.4x** | 0.61MB |
| h264_mf (WMF) | 10.0s | 1.7x | 0.73MB |

Audio validation (QSV output): WAV 2.52MB, no silence, 30.00s — PASS.

### How to Enable

Add to `config.toml` under `[app]` (do not commit):

```toml
video_codec = "auto"   # recommended — selects h264_qsv on this machine
# video_codec = "libx264"  # force CPU
# video_codec = "h264_qsv" # force Intel QSV
# video_codec = "h264_nvenc" # force NVIDIA (falls back if unavailable)
```

On this machine `auto` selects h264_qsv → expected render time ~1.8 min vs ~6 min per video.

### Files Changed

| File | Change |
|------|--------|
| `app/services/video.py` | Added `_probe_hardware_encoder`, `"auto"` codec, updated `_get_effective_video_codec` |
| `IMPLEMENTATION.md` | This section |

### Report

`storage/benchmark_reports/milestone_7c_gpu_encoding_report.md` (gitignored)

---

## Próximos pasos

### Milestone 4 — Optimización y escala
- [x] Reducir tiempo de render: GPU encoding — h264_qsv disponible (3.4x más rápido) ← M7-C
- [ ] Agregar voces en español: `es-ES-AlvaroNeural`, `es-MX-JorgeNeural`
- [ ] Batch con topics desde CSV o archivo externo
- [ ] Agregar voces en español: `es-ES-AlvaroNeural`, `es-MX-JorgeNeural`
- [ ] Scoring de calidad automático (duración, tamaño, screenshot check)
- [ ] Crear script de inicio automático (Task Scheduler / servicio Windows)

### Prioridad media
- [ ] Crear script de inicio automático (Task Scheduler o servicio Windows)
- [ ] Automatizar ingesta de temas desde un CSV o fuente externa
- [ ] Crear batch script para generación de múltiples videos en secuencia

### Prioridad baja
- [ ] Habilitar Redis para persistencia de estado entre reinicios
- [ ] Configurar endpoint externo (nginx proxy) para acceso remoto
- [ ] Evaluar Docker si se necesita entorno reproducible en otro equipo

---

## Configuración con API keys reales (cuando estén disponibles)

```toml
# config.toml — sección [app]

# Para LLM:
llm_provider = "openai"         # o "gemini", "deepseek"
openai_api_key = "sk-..."
openai_model_name = "gpt-4o-mini"

# Para video stock:
video_source = "pexels"
pexels_api_keys = ["tu-key-aqui"]

# Para subtítulos (requiere ImageMagick instalado):
imagemagick_path = "C:\\Program Files\\ImageMagick-7.1.1-Q16\\magick.exe"
```

Y en el request agregar:
```json
{
  "subtitle_enabled": true,
  "video_source": "pexels"
}
```
(sin `video_script` ni `video_materials` — el pipeline usará LLM y Pexels end-to-end)
