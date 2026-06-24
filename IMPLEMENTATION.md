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

### Resultados del batch

| # | Topic | Task ID | Status | Duration | Size | Path |
|---|-------|---------|--------|----------|------|------|
| 1 | The Power of Consistency | `7c255357` | ✅ Complete | 00:00:35 | 9.6 MB | `storage/tasks/7c255357.../final-1.mp4` |
| 2 | Why Motivation Is Overrated | `a6aca887` | ✅ Complete | 00:00:35 | 9.8 MB | `storage/tasks/a6aca887.../final-1.mp4` |
| 3 | How to Focus in a Distracted World | `3d94d93a` | ⚠️ Partial | 00:00:30 | 4.3 MB | `storage/tasks/3d94d93a.../final-1.mp4` |
| 4 | Small Habits That Compound Over Time | `f2b5589e` | ✅ Complete | 00:00:35 | 11.2 MB | `storage/tasks/f2b5589e.../final-1.mp4` |
| 5 | How AI Can Help You Work Smarter | `185a19e6` | ✅ Complete | 00:00:30 | 8.3 MB | `storage/tasks/185a19e6.../final-1.mp4` |

**Videos intentados:** 5 | **Exitosos:** 4 | **Parciales:** 1 | **Fallidos:** 0

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

## Próximos pasos

### Milestone 4 — Optimización y escala
- [ ] Reducir tiempo de render: GPU encoding (`-c:v h264_nvenc`) o máx 4 tasks concurrentes
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
