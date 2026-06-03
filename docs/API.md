# MoneyPrinterTurboCN 后端 API 文档

## 概述

MoneyPrinterTurboCN 提供了一套完整的 RESTful API 接口，用于视频生成、配置管理、任务管理等功能。

**基础 URL**: `http://localhost:8000`

**API 前缀**: `/api/v1`

---

## 目录

- [健康检查](#健康检查)
- [任务管理](#任务管理)
- [脚本生成](#脚本生成)
- [配置管理](#配置管理)
- [语音服务](#语音服务)
- [日志服务](#日志服务)
- [资源管理](#资源管理)

---

## 健康检查

### 1. Ping

检查服务可用性。

**端点**: `GET /api/ping`

**标签**: Health Check

**响应示例**:
```json
"pong"
```

### 2. 获取版本信息

获取服务的名称和版本信息。

**端点**: `GET /api/version`

**标签**: Health Check

**响应示例**:
```json
{
  "name": "MoneyPrinterTurboCN",
  "version": "1.2.59",
  "code": 0,
  "message": "success"
}
```

---

## 任务管理

### 1. 生成视频

创建一个新的视频生成任务。

**端点**: `POST /api/v1/videos`

**摘要**: Generate a short video

**请求体** (`TaskVideoRequest`):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| video_subject | string | 否 | 视频主题 |
| video_script | string | 否 | 视频脚本 |
| video_terms | string \| array | 否 | 视频关键词 |
| video_aspect | string | 否 | 视频比例 (16:9, 9:16, 1:1, 3:4) |
| video_concat_mode | string | 否 | 视频拼接模式 (random, sequential) |
| video_transition_mode | string | 否 | 过渡模式 (None, Shuffle, FadeIn, FadeOut, SlideIn, SlideOut) |
| video_clip_duration | integer | 否 | 视频剪辑时长（秒） |
| video_count | integer | 否 | 视频数量 |
| video_source | string | 否 | 视频来源 (pexels, pixabay, local) |
| video_style | string | 否 | 视频风格 |
| voice_name | string | 否 | 语音名称 |
| voice_volume | float | 否 | 语音音量 (0.1-2.0) |
| voice_rate | float | 否 | 语音语速 (0.5-2.0) |
| voice_emotion | string | 否 | 语音情感 |
| tts_server | string | 否 | TTS 服务器 (azure-tts-v1, azure-tts-v2, siliconflow, gemini-tts, coze-tts) |
| bgm_type | string | 否 | BGM 类型 (random) |
| bgm_file | string | 否 | BGM 文件路径 |
| bgm_volume | float | 否 | BGM 音量 (0.1-2.0) |
| subtitle_enabled | boolean | 否 | 是否启用字幕 |
| subtitle_position | string | 否 | 字幕位置 (top, bottom, center) |
| font_name | string | 否 | 字体名称 |
| text_fore_color | string | 否 | 字幕前景色 (#FFFFFF) |
| text_background_color | boolean \| string | 否 | 字幕背景色 |
| font_size | integer | 否 | 字体大小 |
| stroke_color | string | 否 | 描边颜色 |
| stroke_width | float | 否 | 描边宽度 |
| scenes | array | 否 | 多场景数据 |
| language | string | 否 | 语言 (zh, en) |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558"
  }
}
```

### 2. 仅生成字幕

创建一个仅生成字幕的任务。

**端点**: `POST /api/v1/subtitle`

**摘要**: Generate subtitle only

**请求体** (`SubtitleRequest`):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| video_script | string | 是 | 视频脚本 |
| video_language | string | 否 | 视频语言 |
| voice_name | string | 否 | 语音名称 |
| voice_volume | float | 否 | 语音音量 |
| voice_rate | float | 否 | 语音语速 |
| bgm_type | string | 否 | BGM 类型 |
| bgm_file | string | 否 | BGM 文件路径 |
| bgm_volume | float | 否 | BGM 音量 |
| subtitle_position | string | 否 | 字幕位置 |
| font_name | string | 否 | 字体名称 |
| text_fore_color | string | 否 | 字幕前景色 |
| text_background_color | boolean \| string | 否 | 字幕背景色 |
| font_size | integer | 否 | 字体大小 |
| stroke_color | string | 否 | 描边颜色 |
| stroke_width | float | 否 | 描边宽度 |
| video_source | string | 否 | 视频来源 |
| subtitle_enabled | string | 否 | 是否启用字幕 |

### 3. 仅生成音频

创建一个仅生成音频的任务。

**端点**: `POST /api/v1/audio`

**摘要**: Generate audio only

**请求体** (`AudioRequest`):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| video_script | string | 是 | 视频脚本 |
| video_language | string | 否 | 视频语言 |
| voice_name | string | 否 | 语音名称 |
| voice_volume | float | 否 | 语音音量 |
| voice_rate | float | 否 | 语音语速 |
| bgm_type | string | 否 | BGM 类型 |
| bgm_file | string | 否 | BGM 文件路径 |
| bgm_volume | float | 否 | BGM 音量 |
| video_source | string | 否 | 视频来源 |

### 4. 获取所有任务

分页获取所有任务列表。

**端点**: `GET /api/v1/tasks`

**摘要**: Get all tasks

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | integer | 否 | 1 | 页码 |
| page_size | integer | 否 | 10 | 每页数量 |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "tasks": [
      {
        "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
        "status": "completed",
        "progress": 100,
        "videos": ["http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/final-1.mp4"]
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 10
  }
}
```

### 5. 获取单个任务状态

根据任务 ID 查询任务状态和详细信息。

**端点**: `GET /api/v1/tasks/{task_id}`

**摘要**: Query task status

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | string | 是 | 任务 ID |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
    "status": "completed",
    "progress": 100,
    "videos": [
      "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/final-1.mp4"
    ],
    "combined_videos": [
      "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/combined-1.mp4"
    ]
  }
}
```

### 6. 删除任务

删除指定的任务及其相关文件。

**端点**: `DELETE /api/v1/tasks/{task_id}`

**摘要**: Delete a generated short video task

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | string | 是 | 任务 ID |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": null
}
```

### 7. 取消任务

取消正在运行的任务。

**端点**: `POST /api/v1/tasks/{task_id}/cancel`

**摘要**: Cancel a running task

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | string | 是 | 任务 ID |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": null
}
```

---

## 脚本生成

### 1. 生成视频脚本

根据主题生成视频脚本。

**端点**: `POST /api/v1/scripts`

**摘要**: Create a script for the video

**请求体** (`VideoScriptRequest`):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| video_subject | string | 是 | 视频主题 |
| video_language | string | 否 | 视频语言 |
| paragraph_number | integer | 否 | 段落数量 |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "video_script": "春天的花海，是大自然的一幅美丽画卷..."
  }
}
```

### 2. 生成视频关键词

根据脚本生成视频搜索关键词。

**端点**: `POST /api/v1/terms`

**摘要**: Generate video terms based on the video script

**请求体** (`VideoTermsRequest`):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| video_subject | string | 否 | 视频主题 |
| video_script | string | 否 | 视频脚本 |
| amount | integer | 否 | 关键词数量 |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "video_terms": ["sky", "tree", "flower"]
  }
}
```

### 3. 解析脚本为场景

将视频脚本解析为多场景格式。

**端点**: `POST /api/v1/parse-script`

**摘要**: Parse video script into scenes

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| video_script | string | 是 | 视频脚本 |
| language | string | 否 | 语言 |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "status": "success",
    "scenes": [
      {
        "id": "scene_1",
        "script": "春天的花海...",
        "camera": "",
        "start_time": 0.0,
        "end_time": 5.0,
        "title": "场景1",
        "keywords": ["flower", "spring"],
        "video_clips": null,
        "audio_file": null,
        "subtitle_file": null
      }
    ],
    "evaluation": {}
  }
}
```

---

## 配置管理

### 1. 获取配置

获取当前的配置信息。

**端点**: `GET /api/v1/config`

**摘要**: Get configuration

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "ui": {
      "hide_log": false,
      "language": "zh"
    },
    "app": {
      "llm_provider": "deepseek",
      "video_source": "pexels",
      "use_gpu": true,
      "pexels_api_keys": ["Ra5z3Yw0ZUwPy..."],
      "pixabay_api_keys": ["54923197-..."],
      "openai_api_key": "",
      "openai_base_url": "",
      "openai_model_name": "gpt-3.5-turbo",
      "moonshot_api_key": "sk-5ZAQbXRl...",
      "moonshot_base_url": "https://api.moonshot.cn/v1",
      "moonshot_model_name": "moonshot-v1-128k",
      "deepseek_api_key": "sk-0b0650da992d...",
      "deepseek_base_url": "https://api.deepseek.com",
      "deepseek_model_name": "deepseek-chat"
    },
    "azure": {
      "speech_region": "",
      "speech_key": ""
    },
    "siliconflow": {
      "api_key": "sk-ehmjzsdq..."
    },
    "coze": {
      "api_key": "sat_5QQV8lPJC..."
    },
    "whisper": {
      "device": "GPU"
    }
  }
}
```

### 2. 更新配置

更新配置信息。

**端点**: `PUT /api/v1/config`

**摘要**: Update configuration

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ui | object | 否 | UI 配置 |
| azure | object | 否 | Azure TTS 配置 |
| siliconflow | object | 否 | SiliconFlow 配置 |
| coze | object | 否 | Coze 配置 |

**请求示例**:
```json
{
  "ui": {
    "language": "zh",
    "hide_log": false
  },
  "azure": {
    "speech_region": "eastasia",
    "speech_key": "your-api-key"
  }
}
```

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "message": "Config saved successfully"
  }
}
```

---

## 语音服务

### 1. 获取语音列表

获取可用语音列表。

**端点**: `GET /api/v1/voices`

**摘要**: Get voice list based on TTS server

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| tts_server | string | 否 | azure-tts-v1 | TTS 服务器类型 |
| force_refresh | boolean | 否 | false | 是否强制刷新缓存 |

**TTS 服务器类型**:
- `azure-tts-v1`: Azure TTS v1
- `azure-tts-v2`: Azure TTS v2
- `siliconflow`: SiliconFlow TTS
- `gemini-tts`: Google Gemini TTS
- `coze-tts`: Coze TTS

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "voices": [
      "zh-CN-XiaoxiaoNeural",
      "zh-CN-YunxiNeural",
      "en-US-JennyNeural"
    ]
  }
}
```

### 2. 预览语音

生成并返回语音预览。

**端点**: `POST /api/v1/audio/preview`

**摘要**: Preview audio (play voice)

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 要合成的文本 |
| voice_name | string | 是 | 语音标识符 |
| voice_rate | float | 否 | 语音速度 (0.5-2.0) |
| voice_volume | float | 否 | 语音音量 (0.1-2.0) |
| voice_emotion | string | 否 | 语音情感（用于 Coze TTS） |

**响应**: 音频文件 (audio/mp3)

---

## 日志服务

### 1. 获取日志

获取任务日志。

**端点**: `GET /api/v1/logs`

**摘要**: Get logs

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| level | string | 否 | null | 日志级别过滤 (INFO, WARNING, ERROR) |
| task_id | string | 否 | null | 任务 ID 过滤 |
| limit | integer | 否 | 100 | 返回日志数量 |
| offset | integer | 否 | 0 | 分页偏移量 |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "logs": [
      {
        "timestamp": "2024-01-15 10:30:00",
        "level": "INFO",
        "message": "Task started",
        "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558"
      }
    ],
    "total": 1
  }
}
```

### 2. 清除日志

清除所有日志。

**端点**: `DELETE /api/v1/logs`

**摘要**: Clear logs

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "message": "Logs cleared successfully"
  }
}
```

---

## 资源管理

### 1. 获取 BGM 列表

获取本地 BGM 文件列表。

**端点**: `GET /api/v1/musics`

**摘要**: Retrieve local BGM files

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "files": [
      {
        "name": "output013.mp3",
        "size": 1891269,
        "file": "/MoneyPrinterTurbo/resource/songs/output013.mp3"
      }
    ]
  }
}
```

### 2. 上传 BGM 文件

上传 BGM 文件到 songs 目录。

**端点**: `POST /api/v1/musics`

**摘要**: Upload the BGM file to the songs directory

**请求体**: `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | MP3 文件 |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "file": "/MoneyPrinterTurbo/resource/songs/example.mp3"
  }
}
```

### 3. 获取视频素材列表

获取本地视频素材列表。

**端点**: `GET /api/v1/video_materials`

**摘要**: Retrieve local video materials

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "files": [
      {
        "name": "example.mp4",
        "size": 12345678,
        "file": "/MoneyPrinterTurbo/resource/videos/example.mp4"
      }
    ]
  }
}
```

### 4. 上传视频素材

上传视频素材到本地视频目录。

**端点**: `POST /api/v1/video_materials`

**摘要**: Upload the video material file to the local videos directory

**请求体**: `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 视频文件 (mp4, mov, avi, flv, mkv, jpg, jpeg, png) |

**响应示例**:
```json
{
  "status": 200,
  "message": "success",
  "data": {
    "file": "/MoneyPrinterTurbo/resource/videos/example.mp4"
  }
}
```

### 5. 流式播放视频

流式播放视频文件（支持断点续传）。

**端点**: `GET /api/v1/stream/{file_path}`

**摘要**: Stream video with range support

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file_path | string | 是 | 文件路径 |

**响应**: 视频文件流 (video/mp4)

### 6. 下载视频

下载视频文件。

**端点**: `GET /api/v1/download/{file_path}`

**摘要**: Download video

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file_path | string | 是 | 文件路径，例如: /cd1727ed-3473-42a2-a7da-4faafafec72b/final-1.mp4 |

**响应**: 视频文件下载

---

## 通用响应格式

所有 API 响应都遵循以下格式：

```json
{
  "status": 200,
  "message": "success",
  "data": { ... }
}
```

**状态码说明**:

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 错误处理

当发生错误时，响应格式如下：

```json
{
  "status": 400,
  "message": "Error message description",
  "data": null
}
```

---

## CORS 跨域支持

API 支持 CORS 跨域请求，可以通过环境变量 `CORS_ALLOWED_ORIGINS` 配置允许的源，默认允许所有源。

---

## 认证

当前 API 未启用认证（代码中已注释掉认证依赖项）。如需启用，请修改 `app/controllers/v1/video.py` 中的 router 配置。

---

## 附录

### 视频比例枚举

| 值 | 说明 |
|----|------|
| 16:9 | 横屏（西瓜视频） |
| 9:16 | 竖屏（抖音） |
| 1:1 | 方形（Instagram） |
| 3:4 | 竖屏（小红书） |

### 视频拼接模式

| 值 | 说明 |
|----|------|
| random | 随机拼接 |
| sequential | 顺序拼接 |

### 过渡模式

| 值 | 说明 |
|----|------|
| None | 无过渡 |
| Shuffle | 随机打乱 |
| FadeIn | 淡入 |
| FadeOut | 淡出 |
| SlideIn | 滑入 |
| SlideOut | 滑出 |

### 任务状态

| 值 | 说明 |
|----|------|
| pending | 等待中 |
| running | 运行中 |
| completed | 已完成 |
| failed | 失败 |
| cancelled | 已取消 |

### TTS 服务器类型

| 值 | 说明 |
|----|------|
| azure-tts-v1 | Azure TTS v1 |
| azure-tts-v2 | Azure TTS v2 |
| siliconflow | SiliconFlow TTS |
| gemini-tts | Google Gemini TTS |
| coze-tts | Coze TTS |

### LLM 提供商

| 值 | 说明 |
|----|------|
| openai | OpenAI |
| moonshot | 月之暗面 |
| azure | Azure OpenAI |
| qwen | 通义千问 |
| deepseek | DeepSeek |
| gemini | Google Gemini |
| ollama | Ollama |
| g4f | GPT4Free |
| oneapi | OneAPI |
| cloudflare | Cloudflare Workers AI |
| ernie | 百度文心一言 |
| modelscope | 魔搭社区 |
| pollinations | Pollinations AI |
