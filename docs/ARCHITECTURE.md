# MoneyPrinterTurboCN Architecture Document

## 1. Project Overview

**MoneyPrinterTurboCN** is an automated short video generation system that leverages AI to create videos from topics or keywords. The system automatically generates video scripts, retrieves video materials, creates subtitles, adds background music, and synthesizes high-quality short videos.

### Key Features
- Multi-LLM Provider Support (OpenAI, Azure, Gemini, Qwen, DeepSeek, etc.)
- Multiple TTS Engines (Azure TTS V1/V2, SiliconFlow, Gemini, Coze)
- Video Material Sources (Pexels, Pixabay, Local)
- Subtitle Generation (Edge TTS, Whisper)
- Web UI and REST API interfaces
- Docker containerization support

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
+-------------------------------------------------------------------------+
|                           User Interface Layer                          |
+-------------------------------------------------------------------------+
|                                                                         |
|   +---------------------+         +-----------------+                   |
|   |      Web UI         |         |      REST API   |                   |
|   |   (Streamlit)       |         |     (FastAPI)   |                   |
|   |                     |         |                 |                   |
|   |  • Main.py          |         |  • /videos      |                   |
|   |  • i18n support     |         |  • /audio       |                   |
|   |  • Real-time config |         |  • /subtitle    |                   |
|   +--------+------------+         +--------+--------+                   |
|            |                               |                            |
+------------+-------------------------------+----------------------------+
             |                               |
             v                               v
+-------------------------------------------------------------------------+
|                         Application Layer                               |
+-------------------------------------------------------------------------+
|                                                                         |
|   +---------------------------------------------------------+           |
|   |                        Task Manager                     |           |
|   |  +----------------------+    +---------------------+    |           |
|   |  |  InMemoryTaskManager |    |  RedisTaskManager   |    |           |
|   |  |  (Default)           |    |  (Distributed)      |    |           |
|   |  +----------------------+    +---------------------+    |           |
|   +---------------------------------------------------------+           |
|                                                                         |
|   +---------------------------------------------------------+           |
|   |                      Task Service (task.py)             |           |
|   |                                                         |           |
|   |  start() -> generate_script -> generate_terms ->        |           |
|   |   generate_audio -> generate_subtitle ->                |           |
|   |   get_materials -> generate_video ->                    |           |
|   |   generate_subtitle -> get_materials -> generate_video  |           |
|   +---------------------------------------------------------+           |
|                                                                         |
+-------------------------------------------------------------------------+
             |
             v
+-------------------------------------------------------------------------+
|                           Service Layer                                 |
+-------------------------------------------------------------------------+
|                                                                         |
|  +---------+ +---------+ +----------+ +----------+ +---------+          |
|  |  LLM    | | Voice   | | Material | | Subtitle | | Video   |          |
|  | Service | | Service | | Service  | | Service  | | Service |          |
|  +----+----+ +----+----+ +----+-----+ +----+-----+ +---+-----+          |
|       |         |         |         |         |                         |
+-------+---------+---------+---------+---------+-------------------------+
        |         |         |         |         |
        v         v         v         v         v
+-------------------------------------------------------------------------+
|                        External Services & Resources                    |
+-------------------------------------------------------------------------+
|                                                                         |
|  +-----------------+  +--------------------+  +------------------+      |
|  |   LLM Providers |  |   TTS Providers    |  |  Video Sources   |      |
|  |                 |  |                    |  |                  |      |
|  |  • OpenAI       |  |  • Azure TTS V1/V2 |  |  • Pexels API    |      |
|  |  • Azure OpenAI |  |  • SiliconFlow     |  |  • Pixabay API   |      |
|  |  • Gemini       |  |  • Gemini TTS      |  |  • Local Files   |      |
|  |  • Qwen         |  |  • Coze TTS        |  |                  |      |
|  |  • DeepSeek     |  |  • Edge TTS        |  |                  |      |
|  |  • Moonshot     |  |                    |  |                  |      |
|  |  • Ollama       |  |                    |  |                  |      |
|  |  • G4F          |  |                    |  |                  |      |
|  +-----------------+  +--------------------+  +------------------+      |
|                                                                         |
|  +------------------+  +-----------------+                              |
|  |  Subtitle Engine |  |   Media Tools   |                              |
|  |                  |  |                 |                              |
|  |  • Whisper       |  |  • FFmpeg       |                              |
|  |  • Edge TTS      |  |  • ImageMagick  |                              |
|  |                  |  |  • MoviePy      |                              |
|  +------------------+  +-----------------+                              |
|                                                                         |
+-------------------------------------------------------------------------+
```

---

## 3. Directory Structure

```
MoneyPrinterTurboCN/
├── app/                          # Main application package
│   ├── config/                   # Configuration management
│   │   ├── __init__.py          # Config initialization & logging
│   │   └── config.py            # Config loading & saving
│   │
│   ├── controllers/              # API controllers
│   │   ├── manager/             # Task managers
│   │   │   ├── base_manager.py  # Abstract base manager
│   │   │   ├── memory_manager.py # In-memory task manager
│   │   │   └── redis_manager.py  # Redis-based task manager
│   │   ├── v1/                  # API v1 endpoints
│   │   │   ├── base.py          # Base router utilities
│   │   │   ├── llm.py           # LLM API endpoints
│   │   │   └── video.py         # Video API endpoints
│   │   ├── base.py              # Common controller utilities
│   │   └── ping.py              # Health check endpoint
│   │
│   ├── models/                   # Data models
│   │   ├── const.py             # Constants (task states, etc.)
│   │   ├── exception.py         # Custom exceptions
│   │   └── schema.py            # Pydantic models
│   │
│   ├── services/                 # Business logic services
│   │   ├── llm.py               # LLM service (script/terms generation)
│   │   ├── voice.py             # TTS service (audio generation)
│   │   ├── material.py          # Material service (video download)
│   │   ├── subtitle.py          # Subtitle service
│   │   ├── video.py             # Video processing service
│   │   ├── task.py              # Task orchestration service
│   │   ├── state.py             # Task state management
│   │   └── utils/               # Service utilities
│   │       └── video_effects.py # Video transition effects
│   │
│   ├── utils/                    # Utility functions
│   │   └── utils.py             # Common utilities
│   │
│   ├── asgi.py                   # ASGI application setup
│   └── router.py                 # API router configuration
│
├── webui/                        # Streamlit Web UI
│   ├── Main.py                   # Main UI entry point
│   └── i18n/                     # Internationalization
│       ├── en.json               # English
│       ├── zh.json               # Chinese
│       └── ...                   # Other languages
│
├── resource/                     # Static resources
│   ├── fonts/                    # Font files
│   ├── songs/                    # Background music
│   └── public/                   # Public assets
│
├── docs/                         # Documentation
├── test/                         # Test files
│
├── main.py                       # API server entry point
├── config.example.toml           # Configuration template
├── docker-compose.yml            # Docker compose config
├── Dockerfile                    # Docker image definition
├── webui.bat                     # Windows launch script
├── webui.sh                      # Linux/Mac launch script
└── requirements.txt              # Python dependencies
```

---

## 4. Core Components

### 4.1 Configuration System (`app/config/`)

The configuration system uses TOML format and supports:
- Multiple LLM provider configurations
- TTS service settings
- Video processing parameters
- UI preferences persistence

```python
# Configuration loading flow
config.toml → load_config() → _cfg dict → Module-level variables
                                    ↓
                              save_config() → config.toml
```

### 4.2 Task Management System

Two task manager implementations:

| Manager | Use Case | Features |
|---------|----------|----------|
| `InMemoryTaskManager` | Single instance, development | Simple, no external dependencies |
| `RedisTaskManager` | Distributed, production | Scalable, persistent, multi-instance |

### 4.3 Service Layer

#### LLM Service (`app/services/llm.py`)
- Script generation from topic
- Search terms extraction
- Multi-provider support with fallback

#### Voice Service (`app/services/voice.py`)
- TTS audio generation
- Multiple TTS provider support
- Subtitle synchronization
- Audio duration calculation

#### Material Service (`app/services/material.py`)
- Video search from Pexels/Pixabay
- Video download and caching
- Local material support

#### Video Service (`app/services/video.py`)
- Video clip combination
- Subtitle overlay
- Audio mixing
- Transition effects
- Quality presets (CPU/GPU)

---

## 5. Video Generation Pipeline

### 5.1 Complete Flow Diagram

```
+-------------------------------------------------------------------------+
|                        VIDEO GENERATION PIPELINE                        |
+-------------------------------------------------------------------------+

     +----------+
     |   START  |
     | (Request)|
     +----+-----+
          |
          v
+-----------------------+
|   1. Generate Script  |
|                       |
|  Input: video_subject |
|  Output: video_script |
|                       |
|  +---------------+    |
|  |  LLM Provider |    |
|  | (OpenAI/etc)  |    |
|  +---------------+    |
+----------+------------+
           |
           v
+----------------------+
|   2. Generate Terms  |
|                      |
|  Input: video_script |
|  Output: video_terms |
|                      |
|  +---------------+   |
|  |  LLM Provider |   |
|  +---------------+   |
+----------+-----------+
           |
           v
+---------------------+
|   3. Generate Audio  |
|                      |
|  Input: video_script |
|  Output: audio.mp3   |
|        + sub_maker   |
|                      |
|  +-----------------+ |
|  |  TTS Provider   | |
|  | (Azure/Coze/etc)| |
|  +-----------------+ |
+----------+-----------+
           |
           v
+-----------------------+
|  4. Generate Subtitle |
|                       |
|  Input: audio_file    |
|        + sub_maker    |
|  Output: subtitle.srt |
|                       |
|  +---------------+    |
|  | Edge TTS /    |    |
|  | Whisper       |    |
|  +---------------+    |
+----------+------------+
           |
           v
+----------------------+
|  5. Get Materials    |
|                      |
|  Input: video_terms  |
|  Output: video_files |
|                      |
|  +---------------+   |
|  | Pexels /      |   |
|  | Pixabay /     |   |
|  | Local         |   |
|  | Pixabay /     |   |
|  | Local         |   |
|  +---------------+   |
+----------+-----------+
           |
           v
+-----------------------+
|  6. Combine Videos    |
|                       |
|  Input: video_files   |
|        + audio_file   |
|  Output: combined.mp4 |
|                       |
|  +------------------+ |
|  | MoviePy + FFmpeg | |
|  +------------------+ |
+----------+------------+
           |
           v
+-----------------------+
|  7. Generate Final    |
|                       |
|  Input: combined.mp4  |
|        + subtitle.srt |
|        + bgm          |
|  Output: final.mp4    |
|                       |
|  +---------------+    |
|  | MoviePy +     |    |
|  | SubtitlesClip |    |
|  +---------------+    |
+----------+------------+
           |
           v
     +------------+
     |   END      |
     | (final.mp4)|
     +------------+
```

### 5.2 Task State Machine

```
+---------+     +------------+     +----------+
| PENDING |---->| PROCESSING |---->| COMPLETE |
+---------+     +-----+------+     +----------+
                      |
                      | Error
                      v
                 +---------+
                 | FAILED  |
                 +---------+
```

### 5.3 Progress Tracking

| Stage | Progress | Description |
|-------|----------|-------------|
| Script Generation | 5-10% | LLM generates video script |
| Terms Generation | 10-20% | LLM extracts search terms |
| Audio Generation | 20-35% | TTS creates audio file |
| Subtitle Generation | 35-40% | Create subtitle file |
| Material Download | 40-50% | Download video clips |
| Video Combination | 50-75% | Combine clips with audio |
| Final Generation | 75-100% | Add subtitles and BGM |

---

## 6. API Endpoints

### 6.1 Video Generation API

| Endpoint           | Method | Description             |
|--------------------|--------|-------------------------|
| `/videos`          | POST   | Generate complete video |
| `/audio`           | POST   | Generate audio only     |
| `/subtitle`        | POST   | Generate subtitle only  |
| `/tasks/{task_id}` | GET    | Query task status       |
| `/tasks/{task_id}` | DELETE | Cancel/delete task      |

### 6.2 Background Music API

| Endpoint      | Method | Description              |
|---------------|--------|--------------------------|
| `/bgm/list`   | GET    | List available BGM files |
| `/bgm/upload` | POST   | Upload custom BGM        |

### 6.3 Request/Response Example

```json
// POST /videos
{
  "video_subject": "AI technology trends 2024",
  "video_aspect": "16:9",
  "voice_name": "zh-CN-XiaoxiaoNeural-Female",
  "bgm_type": "random",
  "subtitle_enabled": true
}

// Response
{
  "code": 200,
  "data": {
    "task_id": "uuid-string"
  }
}
```

---

## 7. TTS Provider Architecture

```
+-------------------------------------------------------------------------+
|                         TTS SERVICE ARCHITECTURE                        |
+-------------------------------------------------------------------------+

                    +-----------------+
                    |   voice.tts()   |
                    |   Main Entry    |
                    +--------+--------+
                             |
           +-----------------+-----------------+
           |                 |                 |
           v                 v                 v
    +-----------+    +-------------+    +-----------+
    | Azure TTS |    | SiliconFlow |    | Gemini    |
    |   V1/V2   |    |    TTS      |    |    TTS    |
    +-----+-----+    +------+------+    +-----+-----+
          |                 |                 |
          |                 |                 |
          v                 v                 v
    +----------+       +----------+     +------------+
    | Edge TTS |       | API Call |     | Gemini API |
    | (Free)   |       |          |     |            |
    +----------+       +----------+     +------------+

           +-----------------+-----------------+
           |                 |                 |
           v                 v                 v
     +-----------+    +-----------+    +------------+
     | Coze TTS  |    | Azure TTS |    | Edge TTS   |
     | (Chinese) |    |     V2    |    | (Fallback) |
     +-----+-----+    +-----+-----+    +------------+
          |                 |
          v                 v
    +------------+    +-----------+
    | Coze API   |    | Azure SDK |
    | + Emotions |    |           |
    +------------+    +-----------+


+-------------------------------------------------------------------------+
|                         VOICE LIST SOURCES                              |
+-------------------------------------------------------------------------+
|                                                                         |
|  +---------------+  +---------------+  +---------------+                |
|  |  Azure Voices |  | SiliconFlow   |  |   Gemini      |                |
|  |  (Hardcoded)  |  |  (Hardcoded)  |  |  (Hardcoded)  |                |
|  |               |  |               |  |               |                |
|  | ~400+ voices  |  |  8 voices     |  |  15 voices    |                |
|  +---------------+  +---------------+  +---------------+                |
|                                                                         |
|  +-----------------+  +-------------------------------------+           |
|  |   Coze Voices   |  |          Source Priority            |           |
|  |  (API + llback) |  |                                     |           |
|  |                 |  |  1. API (if key available)          |           |
|  | API: ~50+       |  |  2. Cached (if valid, < 1 hour old) |           |
|  | Default: 10     |  |  3. Hardcoded default list          |           |
|  +-----------------+  +-------------------------------------+           |
|                                                                         |
+-------------------------------------------------------------------------+
```

---

## 8. LLM Provider Architecture

```
+-------------------------------------------------------------------------+
|                           LLM SERVICE ARCHITECTURE                      |
+-------------------------------------------------------------------------+

                    +--------------------+
                    |    llm.py          |
                    | _generate_response |
                    +---------+----------+
                              |
    +----------+---------+-----------+---------+------------+
    |          |         |           |         |            |
    v          v         v           v         v            v
+--------+ +-------+ +--------+   +------+ +----------+ +--------+
| OpenAI | | Azure | | Gemini |   | Qwen | | DeepSeek | | Ollama |
|        | |OpenAI | |        |   |      | |          | |        |
+--------+ +-------+ +--------+   +------+ +----------+ +--------+
    |          |         |           |           |           |
    v          v         v           v           v           v
+--------+ +-------+ +--------+ +---------+ +----------+ +--------+
| OpenAI | | Azure | | Google | | Alibaba | | DeepSeek | | Local  |
|  API   | |  API  | |  API   | |  API    | |  API     | | Model  |
+--------+ +-------+ +--------+ +---------+ +----------+ +--------+

     +-----------+-------------+-------------+-------------+
     |           |             |             |             |
     v           v             v             v             v
+----------+ +--------+    +--------+  +------------+ +---------+
| Moonshot | | OneAPI |    |  G4F   |  | Cloudflare | | Ernie   |
|          | |        |    | (Free) |  |            | | (Baidu) |
+----------+ +--------+    +--------+  +------------+ +---------+


Functions:
+-------------------------------------------------------------------------+
|                                                                         |
|  generate_script(video_subject, language, paragraph_number)             |
|      +-- Uses LLM to generate video script from topic                   |
|                                                                         |
|  generate_terms(video_subject, video_script, amount)                    |
|      +-- Uses LLM to extract search terms for video materials           |
|                                                                         |
+-------------------------------------------------------------------------+
```

---

## 9. Deployment Architecture

### 9.1 Local Development

```
+-------------------------------------------------+
|                  Local Development              |
+-------------------------------------------------+
|                                                 |
|  Option 1: Web UI (Streamlit)                   |
|  +-----------------------------------------+    |
|  |  webui.bat / webui.sh                   |    |
|  |     +-- streamlit run webui/Main.py     |    |
|  |         +-- http://localhost:8501       |    |
|  +-----------------------------------------+    |
|                                                 |
|  Option 2: API Server (FastAPI)                 |
|  +-----------------------------------------+    |
|  |  python main.py                         |    |
|  |     +-- uvicorn app.asgi:app            |    |
|  |         +-- http://localhost:8080       |    |
|  |         +-- http://localhost:8080/docs  |    |
|  +-----------------------------------------+    |
|                                                 |
+-------------------------------------------------+
```

### 9.2 Docker Deployment

```
+-------------------------------------------------+
|                  Docker Deployment              |
+-------------------------------------------------+
|                                                 |
|  +-----------------------------------------+    |
|  |             docker-compose.yml          |    |
|  +-----------------------------------------+    |
|                      |                          |
|          +-----------+------------+             |
|          v                        v             |
|  +-----------------+      +----------------+    |
|  |   webui service |      |    api service  |   |
|  |                 |      |                 |   |
|  | Port: 8502:8501 |      | Port: 8080:8080 |   |
|  | Streamlit UI    |      | FastAPI REST    |   |
|  +--------+--------+      +--------+--------+   |
|           |                         |           |
|           +------------+------------+           |
|                        |                        |
|                        v                        |
|              +-------------------+              |
|              |  Volume Mount     |              |
|              |  ./:/MoneyPrinter |              |
|              |  TurboCN          |              |
|              |                   |              |
|              |  (Code sync)      |              |
|              +-------------------+              |
|                                                 |
+-------------------------------------------------+
```

---

## 10. Data Flow Summary

```
+-------------------------------------------------------------------------+
|                             DATA FLOW                                   |
+-------------------------------------------------------------------------+

User Input (Topic/Script)
         |
         v
+-----------------+
|  Video Subject  | -----------------------------------------------+
|  (e.g., "AI")   |                                                |
+--------+--------+                                                |
         |                                                         |
         v                                                         |
+-----------------+                                                |
|  LLM Service    |                                                |
|                 |                                                |
|  Script: 500+   |                                                |
|  words          |                                                |
+--------+--------+                                                |
         |                                                         |
         v                                                         |
+-----------------+                                                |
|  TTS Service    |                                                |
|                 |                                                |
|  Audio: 2-3 min |                                                |
|  Subtitle: SRT  |                                                |
+--------+--------+                                                |
         |                                                         |
         v                                                         |
+-----------------+      +-----------------+                       |
| Search Terms    |<-----|  LLM Service    |<----------------------+
| (5-10 keywords) |      |                 |
+--------+--------+      +-----------------+
         |
         v
+-----------------+
| Material Service|
|                 |
| Pexels/Pixabay  |
| 10-20 clips     |
+--------+--------+
         |
         v
+-----------------+
| Video Service   |
|                 |
| Combine clips   |
| Add audio       |
| Add subtitles   |
| Add BGM         |
+--------+--------+
         |
         v
+-----------------+
|  Final Video    |
|                 |
|  MP4 (1080p)    |
|  2-3 minutes    |
|  With subtitles |
+-----------------+
```

---

## 11. Key Design Patterns

### 11.1 Service Layer Pattern
- Business logic separated from presentation
- Each service handles a specific domain
- Services communicate through well-defined interfaces

### 11.2 Strategy Pattern (TTS/LLM)
- Multiple providers for same functionality
- Runtime selection based on configuration
- Easy to add new providers

### 11.3 Task Manager Pattern
- Abstract base manager
- Multiple implementations (Memory/Redis)
- Concurrent task execution with limits

### 11.4 State Management
- Centralized task state tracking
- Progress updates during processing
- Error handling and recovery

---

## 12. Configuration Reference

### 12.1 Essential Configuration

```toml
# LLM Provider
[app]
llm_provider = "openai"
openai_api_key = "sk-xxx"
openai_model_name = "gpt-4o-mini"

# TTS Provider
[azure]
speech_key = "xxx"
speech_region = "eastasia"

[siliconflow]
api_key = "xxx"

[coze]
api_key = "xxx"

# Video Sources
[app]
video_source = "pexels"
pexels_api_keys = ["xxx"]

# UI Settings
[ui]
language = "zh"
tts_server = "azure-tts"
voice_name = ""
```

---

## 13. Error Handling

### 13.1 Task Failure Scenarios

| Stage             | Possible Failures     | Recovery                      |
|-------------------|-----------------------|-------------------------------|
| Script Generation | API error, rate limit | Retry with different provider |
| Terms Generation  | API error             | Use default terms             |
| Audio Generation  | TTS error, network    | Fallback to Edge TTS          |
| Material Download | API limit, no results | Use alternative source        |
| Video Processing  | FFmpeg error          | Log and retry                 |

### 13.2 Logging

All services use `loguru` for logging:
- Console output with colors
- File rotation (configurable)
- Log levels: DEBUG, INFO, WARNING, ERROR

---

## 14. Future Enhancements

1. **Distributed Task Queue**: Celery integration for better scalability
2. **Caching Layer**: Redis caching for API responses
3. **Monitoring**: Prometheus/Grafana integration
4. **Multi-language Support**: Enhanced i18n for more languages
5. **Custom Models**: Support for fine-tuned LLM models
6. **Video Templates**: Pre-defined video styles and templates

---

*Document generated: 2026-03-20*
*Version: 1.0.0*
