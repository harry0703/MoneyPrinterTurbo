## generate_script 函数分析
- 文件: app/services/llm.py
- 函数名: generate_script
- 输入参数:
  - video_subject: str (必填，视频主题)
  - language: str = "" (语言)
  - paragraph_number: int = 1 (段落数量)
  - video_script_prompt: str = "" (自定义脚本提示词，附加要求)
  - custom_system_prompt: str = "" (自定义系统提示词)
  - app_config: 配置对象 (可选)
- 手工文案传入方式:
  - 该函数签名中没有直接的手工文案参数（如 script_file 或 script_content）。
  - 手工文案很可能由上层调用（如 main.py 的 CLI 参数 --script_file 读取文件后）直接作为 script 使用，或绕过此函数。
  - 可通过 video_script_prompt 传递额外指令，但它不是完整文案，只是附加提示。
- 内部处理流程:
  1. 调用 _normalize_script_paragraph_number 规范化段落数。
  2. 调用 _limit_script_text 限制自定义提示词长度。
  3. 调用 build_script_prompt 构造 LLM 提示词。
  4. 记录日志信息。
  5. （后续代码未展示，但根据返回类型推测会调用 LLM 服务生成脚本文本）
- 输出: 返回一个字符串（str），即最终生成的视频脚本文案，而非包含关键词的字典。




## generate_voice / TTS 函数分析
- 文件: app/services/voice.py
- 函数名: `tts`（核心调度函数，上层可能封装为 `generate_voice`）
- 输入参数:
  - `text`: str（待合成的文本）
  - `voice_name`: str（声音名称，决定使用哪个 TTS Provider）
  - `voice_rate`: float（语速，1.0 为正常）
  - `voice_file`: str（输出音频文件路径）
  - `voice_volume`: float = 1.0（音量，可选）
- 手工文案传入方式:
  - 该函数不直接处理手工文案，只接收 `text` 参数，文案由上层（如 CLI/WebUI/API）从手工输入或 LLM 生成后传入。
- Edge TTS 调用位置:
  - 位于 `azure_tts_v1` 函数中，使用 `edge_tts` 库。
  - 关键步骤：
    1. 调用 `create_edge_tts_communicate` 构造 `edge_tts.Communicate` 对象（兼容新旧版本）。
    2. 通过 `stream_edge_tts_chunks` 获取音频流，同时收集边界事件（WordBoundary）用于字幕。
    3. 默认超时 30 秒，可通过 `config.app["edge_tts_timeout"]` 调整，设置 ≤0 表示禁用超时。
- 其他 TTS Provider:
  - 支持 Azure V2（`azure_tts_v2`）、SiliconFlow、Gemini、MiniMax、ElevenLabs、Chatterbox、Fish Audio、MiMo 等。
  - 根据 `voice_name` 的前缀判断使用哪个 Provider（如 `siliconflow:`、`gemini:`、`minimax:` 等）。
- 无配音模式:
  - 当 `voice_name` 为 `no-voice` 或 `none` 时，不调用真实 TTS，而是生成一段静音音频，并根据文本长度估算时长，同时构造假的 SubMaker 供字幕链路使用。
- 输出:
  - 生成音频文件到 `voice_file` 路径。
  - 返回一个 `SubMaker` 对象（包含字幕时间轴信息，可能是真实边界或按文本断句生成的模拟数据），用于后续 `create_subtitle` 生成 SRT 字幕；失败返回 `None`。
- 与字幕生成的关系:
  - 返回的 `SubMaker` 对象会传递给 `create_subtitle` 函数，结合原始脚本文本生成 SRT 字幕文件。
  - Edge TTS 返回细粒度 cues，`create_subtitle` 会将其聚合为按脚本断句的 SRT 片段。




  ## 字幕生成函数分析（subtitle.py）
- 文件: app/services/subtitle.py
- 主要函数:
  - `create(audio_file, subtitle_file)`：使用 faster-whisper 生成字幕（当启用 Whisper 时）
  - `correct(subtitle_file, video_script)`：基于脚本文本校正 SRT 字幕，解决 TTS 与识别文本不一致的问题
  - `file_to_subtitles(filename)`：读取 SRT 文件为内部格式
  - 辅助函数：`levenshtein_distance`, `similarity` 等用于文本匹配
- 输入:
  - `audio_file`: 音频文件路径
  - `subtitle_file`: 输出的字幕文件路径（可选，默认为 `{audio_file}.srt`）
  - `video_script`: 视频原始脚本（用于校正）
- 内部处理流程:
  1. 配置 Whisper 模型（从 `config.whisper` 读取 `model_size`, `device`, `compute_type`）
  2. 如果 Whisper 不可用或未安装，跳过生成，返回空字符串
  3. 调用 `model.transcribe` 识别音频，获取分段、词级时间戳
  4. 根据词级时间戳和标点切分句子，生成临时字幕列表
  5. 将字幕列表写入 SRT 文件
  6. 如果提供了 `video_script`，调用 `correct` 进行文本校正：逐句匹配脚本与字幕，合并或替换字幕文本
- 输出:
  - 生成 SRT 字幕文件到指定路径
  - `create` 函数返回字幕文件路径（若失败返回空字符串）
- 与其他模块关系:
  - TTS 返回的 SubMaker 对象也可能直接被 `create_subtitle` 处理（在 voice.py 中），而这里的 `create` 是独立的 Whisper 识别路径
  - 校正逻辑依赖 `utils.split_string_by_punctuations` 和 `utils.normalize_script_for_subtitle_matching`

## 素材预处理函数分析（preprocess_video）
- 文件: 从代码推断位于 `app/services/material.py` 或 `app/services/video.py`
- 函数名: `preprocess_video(materials: List[MaterialInfo], clip_duration=4)`
- 输入:
  - `materials`: 素材信息列表，每个元素包含 `url` 等字段
  - `clip_duration`: 图片素材生成的视频片段时长，默认 4 秒
- 内部处理流程:
  1. 如果 `materials` 为空，直接返回空列表
  2. 遍历每个素材：
     - 跳过 `url` 为空的素材
     - 使用安全路径解析，确保本地素材限制在 `storage/local_videos` 目录内
     - 根据扩展名判断是图片还是视频
     - 如果是图片，调用 `_open_image_clip_with_fallback` 打开并检查分辨率，然后渲染成缩放视频（`render_image_zoom_video`），更新 `material.url` 为生成的视频文件路径
     - 如果是视频，调用 `_open_video_clip_quietly` 打开检查分辨率
     - 如果分辨率低于最低要求（`_MIN_MATERIAL_DIMENSION`），跳过并记录警告
     - 成功处理后将素材加入 `valid_materials`
- 输出:
  - 返回通过校验并可能被转换过的素材列表（图片已被转为视频，视频 URL 已解析为绝对路径）
- 注意:
  - 该函数是本地素材专用的预处理；在线素材可能在下载阶段已完成类似处理
  - 所有素材在检查后都会关闭资源，避免句柄泄漏

## 视频合成函数分析（combine_videos）
- 文件: 从代码推断位于 `app/services/video.py`
- 函数名: `combine_videos`
- 输入参数:
  - `combined_video_path`: 最终输出视频路径
  - `video_paths`: 素材视频文件路径列表
  - `audio_file`: 旁白音频文件路径
  - `video_aspect`: 画面比例（枚举，如 `VideoAspect.portrait`）
  - `video_concat_mode`: 拼接模式（顺序/随机，枚举 `VideoConcatMode`）
  - `video_transition_mode`: 转场模式（枚举 `VideoTransitionMode`，可为 `None`）
  - `max_clip_duration`: 每个素材片段最大时长，默认 5 秒
  - `threads`: ffmpeg 线程数，默认 2
  - `clip_speed`: 播放速度，默认 1.0
  - `video_fit_mode`: 适配模式（cover/contain，枚举 `VideoFitMode`）
- 内部处理流程:
  1. 读取音频时长，计算所需视频总时长（音频时长 + 安全余量）
  2. 根据 `video_aspect` 确定目标分辨率
  3. 遍历所有素材视频路径，将每个视频按 `source_clip_duration = max_clip_duration * clip_speed` 切分为多个子片段（如果顺序模式则每个视频只取第一段）
  4. 通过 `_prioritize_unique_source_clips` 优先去重，避免重复使用同一来源
  5. 循环处理每个子片段：
     - 使用 MoviePy 打开并裁剪（subclip）
     - 应用播放速度调整
     - 适配到目标画布（cover/contain）
     - 应用转场效果（fade/slide/zoom/shuffle 等）
     - 确保片段时长不超过 `max_clip_duration`
     - 将处理后的片段写入临时文件（使用编码器回退逻辑）
     - 记录片段时长，关闭资源
     - 累计视频时长，直到达到所需时长
  6. 如果累计时长仍不足，则循环已有片段补足
  7. 调用 `concat_video_clips_with_ffmpeg` 将临时片段合并为最终视频
  8. 删除临时文件，返回输出路径
- 输出:
  - 生成最终的视频文件到 `combined_video_path`
  - 返回该路径
- 关键辅助函数:
  - `_get_required_video_duration`: 根据音频时长加安全边距计算所需时长
  - `_open_video_clip_quietly`: 静默打开视频素材
  - `_fit_clip_to_canvas`: 将画面适配到目标分辨率
  - `_write_videofile_with_codec_fallback`: 写入视频文件，支持编码器回退
  - `concat_video_clips_with_ffmpeg`: 使用 ffmpeg 合并片段
- 编码器:
  - 通过 `_get_configured_video_codec()` 获取配置的编码器（如 libx264 或 h264_nvenc），并支持自动回退




  用户输入
   ├── 主题（自动生成模式）
   │      ↓
   │    generate_script(video_subject, ...)  →  script (str) + terms (list)
   │      ↓
   └── 手工文案（零 Key 模式）
          ↓
        （跳过 LLM，直接使用 script 文本，terms 可为空或手动指定）

script
   ↓
generate_voice / tts(script, voice_name, ...)
   │
   ├── 若 voice_name = "no-voice" → 生成静音音频 + 模拟 SubMaker
   │
   └── 正常 TTS 路径：
        ├── Edge TTS (azure_tts_v1) → audio.mp3 + SubMaker (含 cues)
        ├── 其他 provider (如 azure_tts_v2, siliconflow_tts 等) → audio.mp3 + 兼容 SubMaker
        └── 失败则可能返回 None
   │
   ↓
audio.mp3  + SubMaker
   │
   ↓
create_subtitle(SubMaker, script, subtitle_file)  或  Whisper 路径（可选）
   │
   ├── Edge 路径：基于 SubMaker 聚合生成 SRT
   └── 回退路径：若 SubMaker 不可用或配置 Whisper，则调用 subtitle.create(audio.mp3, subtitle_file) 并 correct
   │
   ↓
subtitle.srt
   │
   ↓
素材获取与预处理
   │
   ├── 本地素材 (video_source = "local")
   │      ↓
   │    preprocess_video(materials) → 校验/转换，得到 valid_materials (视频路径列表)
   │
   └── 在线素材 (video_source = "pexels" / "pixabay")
          ↓
        get_videos(search_terms, video_aspect) → 下载/选择视频，返回视频路径列表
   │
   ↓
video_paths (list)
   │
   ↓
combine_videos(video_paths, audio.mp3, subtitle.srt, aspect, concat_mode, transition, ...)
   │
   ├── 切分素材、适配分辨率、应用转场、变速
   ├── 生成临时片段 temp-clip-*.mp4
   ├── 使用 ffmpeg 合并片段为无声视频
   ├── 添加音频（可能还包括 BGM）
   └── 合成字幕（如果未在合并时硬编码，则后期嵌入）
   │
   ↓
final-1.mp4  (最终视频)





函数: generate_script (app/services/llm.py)

输入参数:
- video_subject: str
- language: str = ""
- paragraph_number: int = 1
- video_script_prompt: str = ""
- custom_system_prompt: str = ""
- app_config: 配置对象

内部关键变量:
- prompt: 构造的 LLM 提示词
- final_script: str，最终脚本文案

输出:
- final_script (返回的字符串)





函数: tts (app/services/voice.py) 或上层封装 generate_voice

输入参数:
- text: str
- voice_name: str
- voice_rate: float
- voice_file: str
- voice_volume: float = 1.0

内部关键变量:
- sub_maker: SubMaker 对象（字幕时间轴）
- audio_file: 实际就是 voice_file 路径

输出:
- 音频文件写入 voice_file
- 返回 sub_maker 或 None




函数: create_subtitle (app/services/voice.py 内部) 或 subtitle.create (Whisper 路径)

输入参数:
- sub_maker (来自 TTS) 或 audio_file (Whisper 路径)
- text (脚本原文)
- subtitle_file: str

内部关键变量:
- script_lines: 按标点分句后的脚本行列表
- sub_items: 聚合后的字幕片段列表

输出:
- 生成 subtitle.srt 文件
- 返回 None 或字幕文件路径（Whisper 路径返回字符串）





函数: preprocess_video (app/services/material.py 或 video.py)

输入参数:
- materials: List[MaterialInfo]
- clip_duration: int = 4

内部关键变量:
- valid_materials: 通过校验的素材列表
- material.url: 素材路径（可能被更新为绝对路径或生成的视频路径）
- local_videos_dir: 本地视频目录

输出:
- valid_materials (处理后的素材列表)





函数: combine_videos (app/services/video.py)

输入参数:
- combined_video_path: str
- video_paths: List[str]
- audio_file: str
- video_aspect: VideoAspect
- video_concat_mode: VideoConcatMode
- video_transition_mode: VideoTransitionMode
- max_clip_duration: int
- threads: int
- clip_speed: float
- video_fit_mode: VideoFitMode

内部关键变量:
- audio_duration: 音频时长
- required_video_duration: 所需视频总时长
- processed_clips: 处理后的片段列表
- clip_files: 临时片段文件路径列表
- output_dir: 输出目录

输出:
- 最终视频文件 combined_video_path
- 返回 combined_video_path


常用中间文件变量名（任务目录内）
变量名	含义	示例路径
script_file	文案文件	storage/tasks/<task_id>/script.json 或 script.txt
audio_file	旁白音频	storage/tasks/<task_id>/audio.mp3
subtitle_file	字幕文件	storage/tasks/<task_id>/subtitle.srt
video_paths	素材视频路径列表	["storage/local_videos/1.mp4", ...]
final_video_path	最终视频	storage/tasks/<task_id>/final-1.mp4



CLI 参数清单表（来自 cli.py）
脚本与内容组（script and content）
参数名	类型/默认值	说明
--video-subject	str，默认 ""	视频主题；与 --video-script 二选一
--video-script	str，默认 ""	完整脚本文本；提供时跳过 LLM 生成
--video-terms	str，默认 None	逗号分隔的素材搜索关键词；省略时自动生成
--video-language	str，默认 None	脚本语言代码，如 zh-CN、en-US（默认自动检测）
--paragraph-number	int，1~10，默认 None	生成脚本段落数（默认 1）
--video-script-prompt	str，默认 None	LLM 生成脚本时的附加要求
--custom-system-prompt	str，默认 None	替换默认 LLM 系统提示词
素材与流水线组（materials and pipeline）
参数名	类型/默认值	说明
--video-source	str，默认 "pexels"，可选 pexels/pixabay/coverr/volcengine_seedance/ofox/openai_image/local	视频素材来源；在线源需在 config.toml 配置对应 API Key
--video-materials	str，默认 ""	逗号分隔的本地图片/视频路径，仅当 --video-source local 时有效
--stop-at	str，默认 "video"，可选 script/terms/audio/subtitle/materials/video	在指定流水线阶段后停止
--confirm-seedance-charge	flag，默认 False	确认火山引擎 Seedance 付费任务（使用该源时必需）
--confirm-ofox-charge	flag，默认 False	确认 OFox 付费任务（使用该源时必需）
视频输出组（video output）
参数名	类型/默认值	说明
--video-count	int，≥1，默认 1	输出视频数量
--video-aspect	str，可选 9:16/16:9/1:1，默认 9:16	画面比例
--video-fit-mode	str，可选 cover/contain，默认 None（最终 cover）	素材适配方式
--video-concat-mode	str，可选 random/sequential，默认 None（最终 random）	素材拼接顺序
--video-transition-mode	str，可选 none/shuffle/fade-in/fade-out/slide-in/slide-out，默认 None（最终 none）	转场效果
--video-clip-duration	int，≥1，默认 None（最终 5）	每个素材片段最大时长（秒）
--match-materials-to-script	bool，默认 None（最终 disabled）	是否按脚本关键词顺序选择素材
--n-threads	int，≥1，默认 None（最终 2）	FFmpeg 线程数
配音与背景音乐组（voiceover and background music）
参数名	类型/默认值	说明
--voice-name	str，默认 None（最终从 config.ui 读取或内置默认）	TTS 音色标识；no-voice 表示静音
--voice-volume	float，≥0，默认 None	旁白音量倍数
--voice-rate	float，>0，默认 None	语速倍数
--custom-audio-file	str，默认 None	自备音频文件路径（跳过 TTS）
--bgm-type	str，可选 none/random/custom/sonilo，默认 None	背景音乐模式
--sonilo-bgm-prompt	str，默认 None	Sonilo 音乐风格提示词
--bgm-file	str，默认 None	自定义 BGM 文件（须在 storage/bgm 或 resource/songs 内）
--bgm-volume	float，≥0，默认 None	背景音乐音量倍数
字幕组（subtitles）
参数名	类型/默认值	说明
--subtitle-enabled	bool，默认 None（最终从 config.ui 读取，未设置则开启）	是否启用字幕
--font-name	str，默认 None	字幕字体文件名（位于 resource/fonts）
--subtitle-position	str，可选 top/center/bottom/custom，默认 None	字幕垂直位置
--custom-position	float，0~100，默认 None	自定义位置（距顶部百分比）
--text-fore-color	str，#RRGGBB，默认 None	字幕文字颜色
--font-size	int，≥1，默认 None	字幕字号
--stroke-color	str，#RRGGBB，默认 None	字幕描边颜色
--stroke-width	float，≥0，默认 None	字幕描边宽度
--subtitle-background-enabled	bool，默认 None	是否启用字幕背景
--subtitle-background-color	str，#RRGGBB，默认 None	字幕背景颜色
--rounded-subtitle-background	bool，默认 None	是否使用圆角背景
执行组（execution）
参数名	类型/默认值	说明
--task-id	UUID，默认 None	自定义任务 ID，否则自动生成
--batch-file	str，默认 None	批量任务清单文件（JSON 数组或 JSONL），与 --task-id 互斥
4. 参数到流水线的调用链
cli.py 的 run_cli() 是入口，执行流程如下：

解析参数：parse_args(argv) 返回 args 命名空间。

构建 VideoParams：调用 build_video_params(args)，将 CLI 参数（以及 config.ui 保存的 WebUI 设置）合并为 VideoParams 对象。

例如：

args.video_script → params.video_script

args.video_source → params.video_source

args.video_materials 被解析为 List[MaterialInfo]，每个元素的 provider="local"，url 为路径，duration=0。

args.voice_name → params.voice_name（经 _resolve_voice_name 处理，优先级：命令行 > config.ui > 默认）

args.subtitle_enabled → params.subtitle_enabled（经 _resolve_subtitle_enabled）

其他参数若为 None 则读取 config.ui 中的保存值或使用默认值。

本地文件预处理：调用 prepare_cli_files(params, stop_at)，对本地素材、自定义音频、BGM、字体等进行路径解析和安全检查，必要时将素材复制到 storage/local_videos。

启动任务流水线：调用 app.services.task.start(task_id, params, stop_at, allow_server_file_input=True)，进入统一的任务处理流程（该函数内部会依次执行脚本生成、语音合成、字幕生成、素材预处理/下载、视频合成等阶段）。

输出结果：成功打印 JSON 并返回 0，失败返回 1；参数错误返回 2。

关键映射表：

CLI 参数	对应 VideoParams 字段	处理方式
--video-script	video_script	直接传入，有值时跳过 LLM 脚本生成
--video-subject	video_subject	当 video_script 为空时用于生成脚本
--video-source local	video_source="local"	使用本地素材
--video-materials "a.mp4,b.mp4"	video_materials=[MaterialInfo(provider="local", url="a.mp4"), ...]	解析为列表
--voice-name no-voice	voice_name="no-voice"	无配音模式，生成静音音频
--video-aspect 9:16	video_aspect="9:16"	输出竖屏
--stop-at video	控制流水线执行深度	默认执行到视频合成完成
--bgm-type none	bgm_type=""	关闭背景音乐
5. 零 Key 成片命令示例（基于 cli.py）
场景：手工文案 + 本地素材 + Edge TTS + Edge 字幕 + CPU 合成
假设你已经准备好：

手工文案文件：storage/scripts/demo_script.txt（注意：CLI 的 --video-script 接收的是文本内容，而不是文件路径。所以你需要将文案内容直接作为参数传递，或者使用批处理文件间接传入。但为方便，也可以把文案内容放在一个变量中传入。）

本地素材：两个竖屏 MP4 文件位于 storage/materials/demo/1.mp4 和 2.mp4

推荐命令（如果你希望直接传递脚本文本）：

powershell
python cli.py --video-script "在今天的视频里，我们会介绍三个提高效率的小工具。第一个工具可以帮你自动整理日程。第二个工具擅长生成会议摘要。第三个工具能跨设备同步剪贴板。现在让我们逐一来看。" --video-source local --video-materials "storage/materials/demo/1.mp4,storage/materials/demo/2.mp4" --voice-name "zh-CN-XiaoxiaoNeural-Female" --video-aspect 9:16 --bgm-type none --video-transition-mode none
如果脚本较长或包含特殊字符，建议使用环境变量或临时文件。
更简单的零 Key 方式：使用 --video-subject 而不提供 --video-script，但那样会走 LLM 生成，需要 API Key，不符合零 Key 要求。因此必须使用 --video-script 提供手工文案。

注意：--voice-name 可以省略，默认会使用 zh-CN-XiaoxiaoNeural-Female（Edge TTS 免费）。
字幕默认开启，且使用 Edge 字幕（基于 TTS 边界信息），无需额外参数。
视频编码器默认使用 libx264（CPU），无需指定。

如果脚本内容很多，建议写入文件并用 PowerShell 读取：

powershell
$script = Get-Content -Raw storage/scripts/demo_script.txt
python cli.py --video-script $script --video-source local --video-materials "storage/materials/demo/1.mp4,storage/materials/demo/2.mp4" --video-aspect 9:16 --bgm-type none
预期结果：成功后在 storage/tasks/<task_id>/ 下生成 final-1.mp4，可播放，有声音和字幕。

补充：更新 B1 文档
现在你应该把这些内容补充到 B1_pipeline_notes.md 中，特别是：

将“CLI 参数清单表”加入文档。

更新“零 Key 成片命令”，替换之前猜测的命令。

记录 cli.py 作为真正的命令行入口，main.py 仅用于启动 API 服务。