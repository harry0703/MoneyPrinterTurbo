# Configuration reference (`config.toml`)

Loaded once at startup by `app/config/config.py` from the repo root. Start
from `config.example.toml`. Values are exposed as `config.app`, `config.azure`,
`config.whisper`, `config.proxy`, `config.ui` dictionaries.

## `[app]` core

```toml
[app]
video_source = "pexels"        # pexels | pixabay | coverr | local
llm_provider = "openai"        # see provider table below
subtitle_provider = "edge"     # edge (SubMaker) | whisper (faster_whisper)
video_codec = "libx264"        # or h264_nvenc / h264_amf / h264_qsv /
                               # h264_mf / h264_videotoolbox (auto-fallback to libx264)
material_directory = ""        # "" = ./storage/cache_videos ; "task" = per-task dir ; or absolute path
edge_tts_timeout = 30          # seconds; 0 disables the streaming watchdog
tls_verify = true              # disable only behind trusted intercepting proxies
listen_host = "0.0.0.0"        # API server
listen_port = 8080
max_concurrent_tasks = 5       # parallel pipeline executions
max_queued_tasks = 100         # beyond this the API returns 429
enable_redis = false           # task/state persistence (see below)
endpoint = ""                  # external base URL used in returned video links
hide_config = false            # hide config section in WebUI
```

## Stock-video API keys

Each accepts a single string or a list (round-robin rotation, thread-safe):

```toml
pexels_api_keys = ["key1", "key2"]   # https://www.pexels.com/api/
pixabay_api_keys = []                # https://pixabay.com/api/docs/
coverr_api_keys = []                 # free tier ~50 req/h, mostly 16:9
```

## LLM providers

Set `llm_provider`, then fill that provider's keys. Pattern is always
`{provider}_api_key`, `{provider}_model_name`, `{provider}_base_url`
(base_url optional for hosted defaults).

| Provider | Notes |
|---|---|
| `openai` | default model `gpt-4o-mini`; custom `openai_base_url` makes this work with any OpenAI-compatible server |
| `azure` | plus `azure_api_version` (e.g. `2024-02-15-preview`) |
| `gemini` | direct Google SDK, default `gemini-2.5-flash` |
| `qwen` | DashScope SDK, e.g. `qwen-max` |
| `deepseek`, `moonshot`, `minimax`, `mimo`, `modelscope`, `siliconflow`, `aihubmix`, `oneapi`, `cloudflare`, `litellm`, `grok`, `groq`, `ernie` | OpenAI-compatible or dedicated branches in `llm.py::_generate_response()` |
| `ollama` | local; `ollama_base_url` + `ollama_model_name`. Inside Docker the code auto-detects containers (`/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup` markers) and rewrites localhost to `host.docker.internal` / the gateway IP |
| `g4f` | free reverse-engineered providers; disabled unless explicitly opted in |
| `pollinations` | free, API key optional |

## TTS / voice

```toml
voice_name = "zh-CN-XiaoxiaoNeural-Female"  # edge-tts (free) — default engine
# voice_name = "siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex"
# voice_name = "gemini:Zephyr-Female"
# voice_name = "mimo:Mia-Female"
voice_rate = 1.0      # speed multiplier
voice_volume = 1.0

[azure]               # only for azure_tts_v2 (paid Azure Speech)
speech_key = ""
speech_region = ""
```

Voice-name prefix selects the engine (see pipeline.md §3). Gender suffix
(`-Female`/`-Male`) is used for UI filtering.

## Subtitles (whisper fallback)

```toml
[whisper]
model_size = "large-v3"   # any faster-whisper size
device = "CPU"            # or CUDA (use Dockerfile.gpu)
compute_type = "int8"     # int8 | float16 | int8_float16
```

## Redis (optional task persistence)

```toml
enable_redis = true
redis_host = "localhost"
redis_port = 6379
redis_db = 0
redis_password = ""
```

Switches both the task manager (`redis_manager.py`) and the state store
(`state.py::RedisState`) from in-memory to Redis hashes — required if you run
multiple API workers or want tasks to survive restarts.

## Proxy and UI

```toml
[proxy]
http = "http://host:port"
https = "http://host:port"

[ui]
hide_log = false
subtitle_position = "bottom"   # top | center | bottom | custom
custom_position = 70.0         # percent from top when "custom"
```

## Environment variables

- `IMAGEIO_FFMPEG_EXE` — explicit FFmpeg binary path (highest priority in
  `utils.get_ffmpeg_binary()`).
- `PYTHONPATH` — must include the repo root (Docker sets `/MoneyPrinterTurbo`).
