# Practical examples

Copy-paste-ready, verified against the current code. All API examples assume
`python main.py` running on `:8080`.

## 1. CLI: one-shot video from the terminal

```bash
# Full pipeline, portrait short with subtitles (defaults: pexels, 9:16)
python cli.py --video-subject "the history of coffee"

# English voice, landscape, 2 variants
python cli.py --video-subject "deep sea creatures" \
  --video-aspect "16:9" \
  --voice-name "en-US-JennyNeural-Female" \
  --video-count 2

# Use your own footage instead of stock APIs
python cli.py --video-subject "my product demo" \
  --video-source local \
  --video-materials "./storage/cache_videos/a.mp4,./storage/cache_videos/b.mp4"

# Partial pipeline: stop after TTS (script + audio only)
python cli.py --video-subject "stoic philosophy" --stop-at audio

# Provide your own script and search terms (skips both LLM calls)
python cli.py --video-subject "morning routine" \
  --video-script "Wake up early. Drink water. Move your body..." \
  --video-terms "sunrise,exercise,healthy breakfast" \
  --no-subtitle-enabled
```

## 2. API: generate, poll, download

```bash
# Submit
TASK=$(curl -s -X POST http://localhost:8080/api/v1/videos \
  -H 'Content-Type: application/json' -d '{
    "video_subject": "5 facts about the ocean",
    "video_aspect": "9:16",
    "video_concat_mode": "random",
    "video_transition_mode": "FadeIn",
    "video_clip_duration": 4,
    "voice_name": "en-US-GuyNeural-Male",
    "voice_rate": 1.1,
    "bgm_type": "random",
    "bgm_volume": 0.15,
    "subtitle_enabled": true,
    "subtitle_position": "custom",
    "custom_position": 75,
    "font_size": 70,
    "text_fore_color": "#FFFFFF",
    "stroke_width": 2,
    "paragraph_number": 2
  }' | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['task_id'])")

# Poll (state: 4=processing, 1=complete, -1=failed)
curl -s http://localhost:8080/api/v1/tasks/$TASK | python3 -m json.tool

# When complete, the task payload lists artifact URLs; stream or download:
curl -s "http://localhost:8080/api/v1/download/tasks/$TASK/final-1.mp4" -o final.mp4
```

Audio-only and subtitle-only products use the same pipeline with checkpoints:

```bash
# TTS narration only (no video) — POST /audio
curl -s -X POST http://localhost:8080/api/v1/audio \
  -H 'Content-Type: application/json' \
  -d '{"video_script": "Discipline beats motivation. Here is why...",
       "voice_name": "en-US-JennyNeural-Female", "voice_rate": 1.0}'

# SRT subtitle file only — POST /subtitle
curl -s -X POST http://localhost:8080/api/v1/subtitle \
  -H 'Content-Type: application/json' \
  -d '{"video_script": "Discipline beats motivation. Here is why...",
       "voice_name": "en-US-JennyNeural-Female"}'
```

## 3. Python: drive the pipeline in-process (how cli.py does it)

```python
from app.models.schema import VideoParams, MaterialInfo
from app.services import task as tm
from app.utils import utils

params = VideoParams(
    video_subject="why cats sleep so much",
    video_aspect="9:16",
    voice_name="en-US-JennyNeural-Female",
    subtitle_enabled=True,
    paragraph_number=1,
)
task_id = utils.get_uuid()
result = tm.start(task_id, params, stop_at="video")
# artifacts in storage/tasks/{task_id}/: audio.mp3, subtitle.srt,
# combined-1.mp4, final-1.mp4
```

Run individual stages for testing:

```python
from app.services import llm, voice

script = llm.generate_script(video_subject="urban gardening", language="en",
                             paragraph_number=1)
terms = llm.generate_terms(video_subject="urban gardening",
                           video_script=script, amount=5)

sub_maker = voice.tts(text=script,
                      voice_name="en-US-JennyNeural-Female",
                      voice_rate=1.0,
                      voice_file="/tmp/narration.mp3",
                      voice_volume=1.0)
duration = voice.get_audio_duration(sub_maker)
```

## 4. config.toml presets

**Zero-cost stack** (no paid keys at all — Pexels key is free):

```toml
[app]
llm_provider = "pollinations"      # free LLM, key optional
video_source = "pexels"
pexels_api_keys = ["your-free-pexels-key"]
subtitle_provider = "edge"         # free, uses edge-tts word boundaries
voice_name = "en-US-JennyNeural-Female"   # edge-tts = free
```

**Fully local / offline-ish stack** (own LLM, own footage, local ASR):

```toml
[app]
llm_provider = "ollama"
ollama_base_url = "http://localhost:11434"  # auto-rewritten inside Docker
ollama_model_name = "llama3.1"
video_source = "local"
material_directory = "/data/my-footage"
subtitle_provider = "whisper"

[whisper]
model_size = "large-v3"
device = "CUDA"
compute_type = "float16"
```

**Production API server** (persistence + GPU encode + bigger queue):

```toml
[app]
enable_redis = true
redis_host = "redis"
max_concurrent_tasks = 8
max_queued_tasks = 500
video_codec = "h264_nvenc"   # auto-falls back to libx264 if unavailable
endpoint = "https://videos.example.com"   # external URLs in task responses
```

## 5. Styling and prompt customization

**Branded subtitles** (rounded background, custom position):

```json
{
  "video_subject": "product launch teaser",
  "font_name": "MicrosoftYaHeiBold.ttc",
  "font_size": 64,
  "text_fore_color": "#FFD700",
  "text_background_color": "#1A1A2E",
  "rounded_subtitle_background": true,
  "stroke_color": "#000000",
  "stroke_width": 0,
  "subtitle_position": "bottom"
}
```

**Controlling the script with prompts** (`custom_system_prompt` replaces the
default system role entirely; keep the format constraints or TTS/subtitles
will choke on markdown):

```json
{
  "video_subject": "intermittent fasting",
  "paragraph_number": 3,
  "video_script_prompt": "Hook the viewer in the first sentence. End with a question.",
  "custom_system_prompt": "You are a punchy fitness influencer. Write spoken-word video narration. Plain text only: no markdown, no titles, no stage directions. Respond in the language of the subject."
}
```

**Reuse an existing narration** (skips TTS entirely; note subtitles are
disabled in this path — `generate_subtitle()` returns early when there is no
SubMaker):

```json
{
  "video_subject": "podcast highlight",
  "custom_audio_file": "/MoneyPrinterTurbo/storage/my-narration.mp3",
  "video_terms": "microphone,studio,conversation"
}
```

## 6. Quick smoke test without burning API quota

```bash
# Stop after the script stage: only one LLM call, no TTS/downloads/encode
python cli.py --video-subject "test subject" --stop-at script

# Then inspect storage/tasks/<task_id>/ — script and terms are persisted
# in the task state (GET /api/v1/tasks/<task_id> shows them too).
pytest test/services/test_llm.py -q   # provider wiring without real video work
```
