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
- EBU R128 loudness normalization (loudnorm, -16 LUFS) at final encode
- Transition effects
- Quality presets (CPU/GPU)

---

## 4.5 Task Types

### 4.5.1 Task Definitions

| Task Type | Description |
|-----------|-------------|
| **视频生成任务 (Video Generation Task)** | A task initiated by clicking the "Generate Video" button on the web page. |
| **场景集成任务 (Scene Integration Task)** | A task initiated through the scene integration panel to generate the target video. |
| **Multi-Scene Building Task** | A task initiated by clicking the "Parse Script" button in the script settings panel, targeting multi-scene scripts. |

### 4.5.2 Task Level Classifications

| Task Level | Description |
|------------|-------------|
| **场景级任务 (Scene-level Task)** | Tasks within a single scene for generating scene videos, audio, and subtitles. |
| **目标视频级任务 (Target Video-level Task)** | Tasks that target the final deliverable video. |

> **Note**: Task types (e.g., 视频生成任务, 场景集成任务) refer to how tasks are initiated, while task levels (e.g., 场景级任务, 目标视频级任务) refer to the scope of the task. These are distinct classifications and both terminologies are valid.

---

## 4.6 Multi-Scene Service Logic

### 4.6.1 Hierarchical Structure

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Task Level      │     │ Multi-Scene     │     │ Scene Level     │
│ (start)         │────>│ Level           │────>│                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
          │                      │                      │
          v                      v                      v
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Task Management │     │ Script Parsing  │     │ Audio Generation│
│ (state.py)      │     │ (llm.py)        │     │ (voice.py)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
          │                      │                      │
          v                      v                      v
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Service Layer   │     │ Scene Terms    │     │ Subtitle Gen    │
│ (task.py)       │     │ (llm.py)        │     │ (subtitle.py)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
          │                      │                      │
          v                      v                      v
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Final Video     │     │ Scene Tags     │     │ Material Fetch  │
│ (video.py)      │     │ (llm.py)        │     │ (material.py)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
          │                      │                      │
          v                      v                      v
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Output:         │     │ Multi-Scene     │     │ Scene Video     │
│ final.mp4       │<────│ Combination     │<────│ (video.py)      │
└─────────────────┘     │ (video.py)      │     └─────────────────┘
                        └─────────────────┘
```

### 4.6.2 Core Functions

#### Task Level
- **start()**: Main task orchestration function, coordinates the entire video generation process
- **save_script_data()**: Saves script and terms to disk for persistence

#### Multi-Scene Level
- **generate_multi_scene_script()**: Generates multi-scene script from subject, converts existing script to multi-scene format, or uses user-provided scenes
- **generate_scene_terms()**: Generates search terms for each scene
- **generate_scene_tags()**: Generates tags for each scene based on script content and visual requirements
- **combine_all_scenes()**: Combines all scene videos into final video, handles duration matching

#### Scene Level
- **generate_scene_audio()**: Generates audio for a single scene
- **generate_scene_subtitle()**: Generates subtitles for a single scene
- **generate_scene_video()**: Coordinates the generation of a single scene video
- **build_scene_video()**: Builds video for a single scene, combines video clips with audio

### 4.6.3 Process Flow

1. **Script Generation**: Convert input subject or script into multi-scene format
2. **Scene Analysis**: Generate terms and tags for each scene
3. **Scene Processing**: For each scene:
   - Generate audio
   - Generate subtitles
   - Fetch video materials
   - Build scene video
4. **Multi-Scene Combination**: Combine all scene videos into final video
5. **Final Processing**: Add background music, apply EBU R128 loudness normalization (-16 LUFS), and finalize video

### 4.6.4 Key Features

- **Flexible Script Input**: Supports subject-only, existing script, or direct scene input
- **Scene-Level Customization**: Each scene can have its own keywords, visual requirements, and intro video
- **Intelligent Material Matching**: Uses scene-specific terms for better video material selection
- **Duration Management**: Ensures video duration matches audio duration
- **Error Handling**: Graceful handling of failures at scene level

### 4.6.5 Data Structures

#### Scene Structure
```python
{
    "id": "scene_1",
    "title": "Introduction",
    "script": "Welcome to our video about AI technology",
    "audio": "Welcome to our video about AI technology",
    "keywords": ["AI", "technology", "introduction"],
    "tags": ["AI Technology", "Introduction"],
    "visual": "Close-up of a computer screen showing AI interface",
    "intro_video": "path/to/intro.mp4"
}
```

#### Scene Result Structure
```python
{
    "scene_id": "scene_1",
    "scene_index": 0,
    "audio_file": "path/to/audio.mp3",
    "audio_duration": 15.5,
    "subtitle_path": "path/to/subtitle.srt",
    "combined_video_path": "path/to/combined.mp4"
}
```

---

## 5. Video Generation Pipeline

### 5.1 Complete Flow Diagram

#### 5.1.1 Single-Scene Flow

```
+-------------------------------------------------------------------------+
|                        SINGLE-SCENE VIDEO PIPELINE                      |
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
+-----------------------+-------------------------------------------+
|  7. Generate Final    |                                           |
|                       |                                           |
|  Input: combined.mp4  |  Dual encoding path:                     |
|        + subtitle.srt |  - No title → FFmpeg filter_complex      |
|        + bgm          |    (single streaming pass, ~3 min)       |
|  Output: final.mp4    |  - Has title → Hybrid FFmpeg+MoviePy     |
|                       |    1. FFmpeg: silence+pillarbox+subs+BGM |
|                       |       +loudnorm → temp file (~3 min)     |
|                       |    2. MoviePy: load temp + title overlay |
|                       |       → fast write (~1 min, ~4 min total)|
|                       |  - Fallback → MoviePy write_videofile   |
|                       |    with -af loudnorm in ffmpeg_params    |
|                       |                                           |
|  +-----------------+  |                                           |
|  | FFmpeg (base)   |  |                                           |
|  | MoviePy (title) |  |                                           |
|  +-----------------+  |                                           |
+----------+------------+                                           |
           |
           v
     +------------+
     |   END      |
     | (final.mp4)|
     +------------+
```

#### 5.1.2 Multi-Scene Flow

```
+-------------------------------------------------------------------------+
|                        MULTI-SCENE VIDEO PIPELINE                       |
+-------------------------------------------------------------------------+

     +----------+
     |   START  |
     | (Request)|
     +----+-----+
          |
          v
+-----------------------+
|  1. Generate Multi-   |
|     Scene Script      |
|                       |
|  Input: video_subject |
|  Output: scenes_list  |
|                       |
|  +---------------+    |
|  |  LLM Provider |    |
|  +---------------+    |
+----------+------------+
           |
           v
+-----------------------+
|  2. Generate Scene    |
|     Terms & Tags      |
|                       |
|  Input: scenes_list   |
|  Output: scene_terms  |
|                       |
|  +---------------+    |
|  |  LLM Provider |    |
|  +---------------+    |
+----------+------------+
           |
           v
+-----------------------+
|  3. Process Each      |
|     Scene             |
|                       |
|  For each scene:      |
|  - Generate Audio     |
|  - Generate Subtitle  |
|  - Get Materials      |
|  - Build Scene Video  |
|                       |
|  +---------------+    |
|  |  Scene Worker |    |
|  +---------------+    |
+----------+------------+
           |
           v
+-----------------------+
|  4. Combine All       |
|     Scenes            |
|                       |
|  Input: scene_videos  |
|  Output: combined.mp4 |
|                       |
|  +---------------+    |
|  | MoviePy +     |    |
|  | FFmpeg        |    |
|  +---------------+    |
+----------+------------+
           |
           v
+-----------------------+
|  5. Trim Video        |
|                       |
|  Input: combined.mp4  |
|        + audio.mp3    |
|  Output: trimmed.mp4  |
|                       |
|  +------------------+ |
|  | MoviePy          | |
|  +------------------+ |
+----------+------------+
           |
           v
+-----------------------+-------------------------------------------+
|  6. Generate Final    |                                           |
|                       |                                           |
|  Input: trimmed.mp4   |  Dual encoding path:                     |
|        + subtitles    |  - No title → FFmpeg filter_complex      |
|        + bgm          |    (single streaming pass, ~3 min)       |
|  Output: final.mp4    |  - Has title → Hybrid FFmpeg+MoviePy     |
|                       |    1. FFmpeg: silence+pillarbox+subs+BGM |
|                       |       +loudnorm → temp file (~3 min)     |
|                       |    2. MoviePy: load temp + title overlay |
|                       |       → fast write (~1 min, ~4 min total)|
|                       |  - Fallback → MoviePy write_videofile   |
|                       |    with -af loudnorm in ffmpeg_params    |
|                       |                                           |
|  +-----------------+  |                                           |
|  | FFmpeg (base)   |  |                                           |
|  | MoviePy (title) |  |                                           |
|  +-----------------+  |                                           |
+----------+------------+                                           |
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

#### 5.3.1 Video Generation Task Progress Definition

视频生成任务进度定义（阶段数 = n + 4，其中 n 为场景数）：

| Stage | Progress | Description |
|-------|----------|-------------|
| Task Preparation | 0-10% | Script generation only |
| Scene 1 Building | 10% ~ (70%/n + 10%) | Process first scene |
| Scene 2 Building | (70%/n + 10%) ~ (2×70%/n + 10%) | Process second scene |
| ... | ... | ... |
| Scene n Building | ((n-1)×70%/n + 10%) ~ 80% | Process scene n |
| Video Combination | 80-90% | Combine all scene videos |
| BGM Merging | 90-95% | Add background music |
| Subtitle Merging | 95-100% | Merge and add subtitles |

#### 5.3.2 Single-Scene Task

| Stage | Progress | Description |
|-------|----------|-------------|
| Task Preparation | 0-10% | Script generation |
| Scene 1 Building | 10-80% | Process the single scene (audio, subtitles, materials, video) |
| Video Combination | 80-90% | Combine video clips |
| BGM Merging | 90-95% | Add background music |
| Subtitle Merging | 95-100% | Add subtitles |

#### 5.3.3 Multi-Scene Task

| Stage | Progress | Description |
|-------|----------|-------------|
| Task Preparation | 0-10% | Multi-scene script generation |
| Scene 1 Building | 10% ~ (70%/n + 10%) | Process first scene |
| Scene 2 Building | (70%/n + 10%) ~ (2×70%/n + 10%) | Process second scene |
| ... | ... | ... |
| Scene n Building | ((n-1)×70%/n + 10%) ~ 80% | Process scene n |
| Video Combination | 80-90% | Combine all scene videos |
| BGM Merging | 90-95% | Add background music |
| Subtitle Merging | 95-100% | Merge and add subtitles |

### 5.4 Task Type Specific Flows

#### 5.4.1 视频生成任务 (Video Generation Task)
- **Initiation**: Web UI "Generate Video" button
- **Flow**: Full single-scene or multi-scene pipeline
- **Output**: Complete video with audio, subtitles, and BGM

#### 5.4.2 场景集成任务 (Scene Integration Task)
- **Initiation**: Scene integration panel
- **Flow**: Combines existing scene videos into target video
- **Key Steps**: Load scene videos → Combine scenes → Add BGM and subtitles
- **Output**: Integrated target video

**Progress Definition:**

| Stage | Progress | Description |
|-------|----------|-------------|
| Video Combination | 0-40% | Combine all scene videos |
| BGM Merging | 40-70% | Add background music |
| Subtitle Merging | 70-100% | Merge and add subtitles |

#### 5.4.3 Multi-Scene Building Task
- **Initiation**: Script settings panel "Parse Script" button
- **Flow**: Multi-scene pipeline with script parsing
- **Key Steps**: Parse script → Generate scenes → Process each scene → Combine scenes
- **Output**: Multi-scene video with cohesive narrative

### 5.5 Multi-Scene Mechanism

#### 5.5.1 Scene-Level Processing
- Each scene is processed independently
- Scene-specific audio, subtitles, and materials
- Scene-level error handling and recovery

#### 5.5.2 Scene Combination
- Maintains scene order and narrative flow
- Handles duration matching between scenes
- Applies smooth transitions between scenes

#### 5.5.3 Data Management
- Scene data is stored in structured format
- Scene results are aggregated for final combination
- Persistent storage of scene-level assets

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
