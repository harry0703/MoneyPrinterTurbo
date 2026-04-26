# 2026-04-02 PR 合并与验证记录

## 本次已合并并推送的 PR

- `#837` `fix: update google-generativeai version for response_modalities support`
- `#835` `fix: add missing pydub dependency to requirements.txt`
- `#850` `feat: support reading subtitle position from config file`
- `#838` `feat: add MiniMax as LLM provider`
- `#811` `refactor: optimize codebase for better performance and reliability`
- `#848` `feat: support GPU acceleration for faster-whisper in Docker`
- `#843` `feat: Add Upload-Post integration for cross-posting to TikTok/Instagram`

## 合并后的主线提交

- TTS 与字幕修复基线提交：`953a6c0` `fix: restore edge tts synthesis and readable subtitles`
- 当前主线提交：`1f8a746`

## 合并时的验证结论

### 已通过

- `#837`
  - 依赖升级后可正常导入
  - `google-generativeai==0.8.6` 已生效
- `#835`
  - `pydub==0.25.1` 已生效
- `#850`
  - `subtitle_position` 与 `custom_position` 可从配置文件读取
- `#838`
  - MiniMax provider 接线正常
  - 使用 mock 调用验证 `_generate_response` 通过
- `#811`
  - 主线导入正常
  - 抽样单测通过
- `#848`
  - `docker compose -f docker-compose.yml -f docker-compose.gpu.yml config` 可正常解析
- `#843`
  - Upload-Post 服务导入和 mock 上传调用通过
  - 与前面 PR 叠加时仅在 `config.example.toml` 存在配置段落冲突，已手工保留两边内容

### 已拒绝并关闭

- `#852`
  - 能恢复音频，但会破坏字幕链路，并删除仍被 WebUI 调用的 Gemini 逻辑
- `#787`
  - 不能解决当前 `403` 场景
- `#841`
  - 与当前主线 TTS/字幕修复冲突，且收益已被更小 PR 覆盖
- `#824`
  - ModelsLab 路径能出音频，但字幕链路失败，无法产出可用 SRT
- `#840`
  - 后端加入 `video_source="ai"`，但 WebUI 仍不支持该值，端到端不可用
- `#826`
  - 与当前主线 `voice.py` 和依赖变更冲突，未通过合并验证
- `#751`
- `#749`
- `#742`
- `#705`
  - 以上 4 个 PR 在当前主线下均为 `DIRTY`，未通过合并验证

## 冒烟测试记录

### 服务重启

- API：`http://127.0.0.1:8080/docs`
- WebUI：`http://127.0.0.1:8501`

### 第一次完整视频任务

- 任务号：`ced0b190-dd72-489c-b978-2761740933db`
- 结果：失败
- 结论：
  - API 默认 `video_transition_mode=null`
  - 视频拼接阶段在 `app/services/video.py` 中直接访问 `video_transition_mode.value`
  - 导致任务线程异常退出，任务状态停留在 `state=4, progress=75`

### 第二次完整视频任务

- 任务号：`8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d`
- 提交方式：
  - `POST /api/v1/videos`
  - 使用本地素材 `/Users/harry/Projects/Python/MoneyPrinterTurbo/test/resources/1.png`
  - 显式指定 `video_transition_mode="FadeIn"`
- 结果：成功
- 任务状态：`state=1, progress=100`

### 第二次任务产物

- 音频：`/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/audio.mp3`
  - 时长：`8.952s`
  - 大小：`53712 bytes`
- 拼接视频：`/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/combined-1.mp4`
  - 时长：`9.000s`
  - 大小：`177666 bytes`
- 成片：`/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/final-1.mp4`
  - 时长：`9.000s`
  - 大小：`352810 bytes`
- 字幕：`/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/subtitle.srt`

### 第二次任务字幕样本

```srt
1
00:00:00,100 --> 00:00:03,300
这是一次主线合并后的完整冒烟测试

2
00:00:03,875 --> 00:00:05,350
我们要确认语音

3
00:00:05,575 --> 00:00:08,375
字幕和视频成片都能正常生成
```

## 当前仍需关注的风险

- `#843` 仅做了 mock 验证，尚未使用真实 Upload-Post 密钥联调
- `#848` 仅验证了 Docker GPU 配置解析，尚未在真实 GPU 环境运行
- 当前 API 默认 `video_transition_mode=null` 时，完整视频任务仍存在回归风险
