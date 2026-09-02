1. 核心函数分析
1.1 generate_script（文案生成）
文件: app/services/llm.py

函数名: generate_script

输入参数:

video_subject: str（必填，视频主题）

language: str = ""（语言，默认自动检测）

paragraph_number: int = 1（段落数量）

video_script_prompt: str = ""（附加要求）

custom_system_prompt: str = ""（自定义系统提示词）

app_config（可选配置对象）

手工文案传入方式:

本函数不处理手工文案。当使用 CLI 时，手工文案通过 --video-script 参数直接传入 VideoParams.video_script，流水线在脚本阶段会优先使用 video_script 而跳过 generate_script。

内部处理流程:

规范化段落数（_normalize_script_paragraph_number）
限制自定义提示词长度（_limit_script_text）
构造 LLM 提示词（build_script_prompt）
调用 LLM 服务生成脚本文本
返回脚本文本
输出: 返回一个字符串（str），即最终脚本内容。关键词生成在后续 generate_terms 阶段单独完成。

1.2 generate_audio / tts（语音合成）
文件: app/services/voice.py

函数名: tts（核心调度函数，上层封装为 generate_audio）

调用关系:

text
task.generate_audio
  -> voice.tts
    -> voice.azure_tts_v1 (Edge TTS)
    -> 或其他 provider
输入参数:

text: str（待合成文本）

voice_name: str（音色标识，决定 TTS Provider）

voice_rate: float（语速，1.0 为正常）

voice_file: str（输出音频文件路径）

voice_volume: float = 1.0（音量）

手工文案传入方式: 本函数接收 text 参数，文案由上层（CLI/WebUI/API）从 VideoParams.video_script 提取后传入。

Edge TTS 调用位置:

位于 azure_tts_v1 函数内，使用 edge_tts 库。

步骤：

create_edge_tts_communicate 构造 edge_tts.Communicate 对象（兼容新旧版本）
stream_edge_tts_chunks 获取音频流并收集边界事件（WordBoundary）用于字幕
默认超时 30 秒，可通过 config.app["edge_tts_timeout"] 调整；设置 ≤0 表示禁用超时
其他 TTS Provider:

支持 Azure V2、SiliconFlow、Gemini、MiniMax、ElevenLabs、Chatterbox、Fish Audio、MiMo 等，根据 voice_name 前缀分发。

无配音模式:

当 voice_name 为 no-voice 或 none 时，不调用真实 TTS，生成静音音频并构造模拟 SubMaker 供字幕链路使用。

输出:

生成音频文件到 voice_file 路径

返回 SubMaker 对象（包含字幕时间轴信息），失败返回 None

与字幕生成的关系:

返回的 SubMaker 会传递给 create_subtitle，结合原始脚本文本生成 SRT 字幕。

Edge TTS 返回细粒度 cues，create_subtitle 将其聚合为按脚本断句的 SRT 片段。

1.3 字幕生成
文件: app/services/subtitle.py

主要函数:

create(audio_file, subtitle_file)：使用 faster-whisper 生成字幕（仅在配置 subtitle_provider="whisper" 时调用）

correct(subtitle_file, video_script)：基于脚本校正 SRT 字幕

file_to_subtitles(filename)：读取 SRT 文件

辅助函数：levenshtein_distance、similarity 等

输入:

audio_file：音频文件路径

subtitle_file：输出字幕文件路径（可选）

video_script：原始脚本文本（用于校正）

内部处理流程（Whisper 路径）:

从 config.whisper 读取模型设置
加载模型（不可用时跳过）
调用 model.transcribe 识别音频，获取词级时间戳
根据标点切分句子，生成临时字幕列表
写入 SRT 文件
调用 correct 进行文本校正
Edge 字幕路径：

由 voice.py 中的 create_subtitle 直接处理 SubMaker，生成 SRT，无需 Whisper。

注意：Edge 字幕失败不会自动回退到 Whisper；只有显式配置 subtitle_provider="whisper" 才会使用 Whisper 路径。

输出:

SRT 字幕文件；create（Whisper）返回文件路径或空字符串，create_subtitle（Edge）直接写文件。

1.4 素材预处理（preprocess_video）
文件: app/services/video.py（经代码确认）

函数名: preprocess_video(materials: List[MaterialInfo], clip_duration=4)

输入:

materials：素材信息列表（MaterialInfo 对象，包含 url 等字段）

clip_duration：图片素材生成的视频时长，默认 4 秒

内部处理流程:

空列表直接返回
遍历素材：
跳过 url 为空的项
使用安全路径解析，限制在 storage/local_videos 目录
根据扩展名判断图片或视频
图片：打开并检查分辨率，渲染为缩放视频（render_image_zoom_video），更新 material.url 为新视频路径
视频：打开检查分辨率，低于最低要求则跳过
处理完成后将素材加入 valid_materials
输出: 返回通过校验的素材列表（图片已转为视频，视频 URL 解析为绝对路径）

注意：所有素材在检查后均关闭资源，避免句柄泄漏。

1.5 视频合成（combine_videos）与后续处理
文件: app/services/video.py

函数名: combine_videos

输入参数:

combined_video_path：中间视频输出路径

video_paths：素材视频路径列表

audio_file：旁白音频文件路径（用于计算时长，但不在此函数中加入音频）

video_aspect：画面比例

video_concat_mode：拼接模式

video_transition_mode：转场模式

max_clip_duration：每个片段最大时长

threads：FFmpeg 线程数

clip_speed：播放速度

video_fit_mode：适配模式

内部处理流程:

读取音频时长，计算所需视频总时长（音频时长 + 安全余量）
确定目标分辨率
遍历素材路径，按 source_clip_duration = max_clip_duration * clip_speed 切分子片段
优先去重素材来源
对每个子片段：裁剪、变速、适配画布、应用转场、限制时长、写入临时文件
累计时长，若不足则循环片段补足
使用 ffmpeg 合并临时片段为无声中间视频
删除临时文件，返回中间视频路径
输出: 生成一个无声的中间视频文件（例如 combined-1.mp4），不包含旁白、字幕、BGM。

后续阶段：generate_video 函数负责将旁白、字幕、BGM 合成到中间视频上，输出最终 final-1.mp4。

关键辅助函数:

_get_required_video_duration

_open_video_clip_quietly

_fit_clip_to_canvas

_write_videofile_with_codec_fallback

concat_video_clips_with_ffmpeg

编码器通过 _get_configured_video_codec() 获取，支持自动回退

2. 数据流图（修正版）
text
用户输入
   ├── 手工文案（零 Key 模式）→ CLI --video-script → VideoParams.video_script
   │
   └── 主题（自动模式）→ CLI --video-subject → generate_script() → script
                                                          ↓
                                               generate_terms() → terms

script  (以及 terms)
   ↓
generate_audio / tts(script, voice_name, ...)
   │
   ├── no-voice → 静音音频 + 模拟 SubMaker
   └── Edge TTS (或其他 provider) → audio.mp3 + SubMaker
   ↓
create_subtitle(SubMaker, script)  →  subtitle.srt    (Edge 字幕路径)
   或
   (若配置 subtitle_provider="whisper") → subtitle.create(audio.mp3) → subtitle.srt → correct()
   ↓
素材获取与预处理
   ├── 本地素材 (video_source="local") → preprocess_video(materials) → valid_materials
   └── 在线素材 (pexels 等) → get_videos(terms, aspect) → video_paths
   ↓
video_paths (list)
   ↓
combine_videos(video_paths, audio_duration, aspect, ...) → 中间无声视频 (combined-1.mp4)
   ↓
generate_video(中间视频, audio.mp3, subtitle.srt, bgm...) → final-1.mp4
   ↓
最终输出
3. 变量名清单（保持原样，已确认）
变量名	含义	示例路径
script	脚本文本	从 VideoParams.video_script 获取
audio_file	旁白音频	storage/tasks/<task_id>/audio.mp3
subtitle_file	字幕文件	storage/tasks/<task_id>/subtitle.srt
video_paths	素材路径列表	["storage/local_videos/1.mp4", ...]
combined_video_path	中间无声视频	storage/tasks/<task_id>/combined-1.mp4
final_video_path	最终视频	storage/tasks/<task_id>/final-1.mp4
4. CLI 参数清单与调用链
4.1 CLI 参数表（精简版，仅列零 Key 相关常用项）
参数	默认值	说明
--video-script	""	手工脚本文本，提供时跳过 LLM
--video-source	"pexels"	素材来源，使用 local 时启用本地素材
--video-materials	""	本地素材路径，逗号分隔
--voice-name	None	音色标识，默认 Edge 中文音色；no-voice 为静音
--video-aspect	"9:16"	画面比例
--bgm-type	None	背景音乐模式，none 关闭
--video-transition-mode	None	转场模式，none 关闭
--subtitle-enabled	None	字幕开关，默认开启
完整参数表见 cli.py 的 parse_args 函数。

4.2 调用链
parse_args() 解析命令行

build_video_params(args) 合并参数，得到 VideoParams

prepare_cli_files(params) 校验并预处理本地文件（素材、音频、字体等）

app.services.task.start(task_id, params, stop_at, allow_server_file_input=True) 启动流水线

依次执行：脚本、关键词、音频、字幕、素材、视频合成

返回结果 JSON，退出码 0 成功，1 失败，2 参数错误

4.3 零 Key 成片命令（已更新为 uv run）
注意：以下路径仅为示例，请替换为实际本地素材路径。仓库中默认不包含这些示例文件。

powershell
uv run python cli.py --video-script "在今天的视频里，我们会介绍三个提高效率的小工具。第一个工具可以帮你自动整理日程。第二个工具擅长生成会议摘要。第三个工具能跨设备同步剪贴板。现在让我们逐一来看。" --video-source local --video-materials "storage/materials/demo/1.mp4,storage/materials/demo/2.mp4" --video-aspect 9:16 --bgm-type none --video-transition-mode none
如果脚本较长，可以先存入文件再读取：

powershell
$script = Get-Content -Raw storage/scripts/demo_script.txt
uv run python cli.py --video-script $script --video-source local --video-materials "storage/materials/demo/1.mp4,storage/materials/demo/2.mp4" --video-aspect 9:16 --bgm-type none
预期输出：storage/tasks/<task_id>/final-1.mp4（含旁白、字幕、画面），可正常播放。

