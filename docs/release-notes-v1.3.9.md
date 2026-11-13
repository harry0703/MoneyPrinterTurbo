[English](#en-v1.3.9) | [中文](#cn-v1.3.9)

<h2 id="en-v1.3.9">Highlights</h2>

- Added official **`mpt` pip packaging**. Start the WebUI with `mpt webui` or generate videos with `mpt cli`.
- Added **static and slow zoom image effects** for local and AI-generated images. Slow zoom remains the default.
- Added Kimi Code subscription access with browser authorization, alongside improvements to the sign-in dialog, status updates, and cancellation.
- Added an optional **local SDXL image server** for the OpenAI-compatible image material workflow, with idle GPU offloading.
- Added Opper, onomeo, Muse Spark, and EmpirioLabs AI LLM providers, and completed Brazilian Portuguese WebUI translations.
- Added **diagnostic logging controls** in the WebUI, including runtime log-level changes and opt-in API request tracing with redaction and size limits.

## Fixes and Improvements

- Fixed grayscale image brightness, transparent image backgrounds, zoom mask alignment, and subtitle background colors. Improved transitions on short clips, background music fade-out, and special-character handling in concatenation paths.
- Isolated intermediate image files across concurrent jobs, improved image cache identity, and validated cached downloads. Completed videos are retained when another video in the same batch fails.
- Fixed speech speed, volume, and audio container handling across several providers. Improved remote audio validation and preserved existing audio until replacement output is ready.
- Improved subtitle timestamp rounding, long-word wrapping, Unicode handling, and pause-tag recognition. Symbol-only lines and separators no longer distort estimated subtitle alignment.
- Fixed Chinese and Japanese fallback social titles using the entire script. Improved JSON extraction, reasoning removal, Markdown cleanup, and generated search-term validation.
- Expanded supported local upload formats, including multi-picture camera JPEGs. Improved task history checks, deletion state, subtitle previews, and model connection error messages in the WebUI.
- Added HEAD support for generated artifacts and improved byte-range downloads, validation errors, and Redis task updates and deletion safeguards.
- Reduced unsafe speech resubmissions after lost responses or redirects, preserved Upload-Post tracking handles, and improved WaveSpeed submission error detection.
- Updated Edge TTS to address 403 failures, constrained PyAV for Whisper compatibility, and fixed Windows cache cleanup and UTF-8 BOM handling in locale files.
- Improved the agent helper's configuration handling and preflight checks, including workflows with prepared narration and visuals that do not need an LLM.

## Usage and Upgrade Notes

- The official PyPI package is **`mpt`**, maintained by this project, and requires **Python 3.11 or later**. Install or upgrade with `python -m pip install --upgrade mpt`; a virtual environment is recommended. The separately named `MoneyPrinterTurbo` package is a third-party distribution.
- The pip installation stores configuration and generated files in your user directory by default; set `MPT_HOME` to choose another location. Source installations continue to use the project directory. When switching installation methods, migrate your configuration and required resources to the chosen runtime directory.
- Image motion defaults to **slow zoom** for existing users. For a still image without transition effects, select **Static** for image motion and **None** for transitions. The setting is available in the WebUI, CLI, and API.
- Kimi Code requires browser sign-in and uses your plan's usage limits. The other new LLM providers require their corresponding API credentials and configuration.
- The local SDXL server requires separate dependencies, model downloads, and a running GPU service; it is not started automatically with MPT. Its default setup unloads Ollama models before image generation, so avoid concurrent LLM and image work on the same GPU. See the [setup instructions](https://github.com/harry0703/MoneyPrinterTurbo/blob/v1.3.9/docs/local-image-server/README.md).
- API request tracing is **off by default**. Prompts and business parameters may appear in logs when enabled; turn tracing off after troubleshooting and check for private content before sharing logs. See the [diagnostic logging guide](https://github.com/harry0703/MoneyPrinterTurbo/blob/v1.3.9/docs/diagnostic-logging.md).

## What's Changed

- Official pip package with WebUI and CLI launchers — [c3634de](https://github.com/harry0703/MoneyPrinterTurbo/commit/c3634de097ea4951935d22e94580ff0ad2665503).
- Static and slow zoom image options — [90f7701](https://github.com/harry0703/MoneyPrinterTurbo/commit/90f77011d7e3b46d382e6d0180dabfb6725ffee4).
- Kimi Code subscription provider — @ysntony in [#1599](https://github.com/harry0703/MoneyPrinterTurbo/pull/1599), followed by [sign-in flow improvements](https://github.com/harry0703/MoneyPrinterTurbo/commit/4204d0f).
- Local SDXL image server — @imkashif in [#1668](https://github.com/harry0703/MoneyPrinterTurbo/pull/1668).
- Opper LLM provider — @Felixkw12 in [#1589](https://github.com/harry0703/MoneyPrinterTurbo/pull/1589).
- onomeo LLM provider — @Owaid0723666 in [#1600](https://github.com/harry0703/MoneyPrinterTurbo/pull/1600).
- Muse Spark provider and Brazilian Portuguese translations — @humbertocortezia in [#1657](https://github.com/harry0703/MoneyPrinterTurbo/pull/1657).
- EmpirioLabs AI provider — @Adam-Dalloul in [#1694](https://github.com/harry0703/MoneyPrinterTurbo/pull/1694).
- Runtime diagnostic logging and request tracing — [6940611](https://github.com/harry0703/MoneyPrinterTurbo/commit/6940611cc2791d1ca13b3af7ee893ccd9544b874).
- Chinese and Japanese fallback social titles — [e25326e](https://github.com/harry0703/MoneyPrinterTurbo/commit/e25326e).
- Retained completed videos after batch failures — @hdu-r3drum in [#1597](https://github.com/harry0703/MoneyPrinterTurbo/pull/1597).
- Edge TTS 403 fix — @HEOJUNFO in [#1652](https://github.com/harry0703/MoneyPrinterTurbo/pull/1652).
- Whisper/PyAV compatibility — @cristianchiriac in [#1582](https://github.com/harry0703/MoneyPrinterTurbo/pull/1582).
- Windows cache cleanup — @shan3520 in [#1654](https://github.com/harry0703/MoneyPrinterTurbo/pull/1654).
- UTF-8 BOM locale support — @ketpatil77 in [#1658](https://github.com/harry0703/MoneyPrinterTurbo/pull/1658).
- Task protection for unparseable states — @RerankerGuo in [#1663](https://github.com/harry0703/MoneyPrinterTurbo/pull/1663).
- Clearer model connection errors — @fengqiaoqu in [#1645](https://github.com/harry0703/MoneyPrinterTurbo/pull/1645).
- Local material preflight checks — @drakeo338 in [#1585](https://github.com/harry0703/MoneyPrinterTurbo/pull/1585); preserved Redis task IDs — @ac1982 in [#1588](https://github.com/harry0703/MoneyPrinterTurbo/pull/1588).
- Grayscale rendering, artifact HEAD requests, and prepared-media agent workflows — @rudycelekli in [#1620](https://github.com/harry0703/MoneyPrinterTurbo/pull/1620), [#1636](https://github.com/harry0703/MoneyPrinterTurbo/pull/1636), and [#1608](https://github.com/harry0703/MoneyPrinterTurbo/pull/1608), alongside many subtitle, speech, material, API, and task reliability fixes.

Thanks to all contributors and everyone who reported issues and helped test these changes!

**Full Changelog**: [v1.3.8...v1.3.9](https://github.com/harry0703/MoneyPrinterTurbo/compare/v1.3.8...v1.3.9)

---

<h2 id="cn-v1.3.9">重点更新</h2>

- 支持通过 pip 安装官方 **`mpt` 包**，使用 `mpt webui` 启动界面，或通过 `mpt cli` 生成视频。
- 新增**图片动态效果选项**，本地图片和 AI 生成图片均可选择“静止”或“缓慢放大”，默认保留缓慢放大。
- 新增 Kimi Code 订阅接入，支持浏览器授权登录，并优化登录窗口布局、状态更新和取消操作。
- 新增可选的**本地 SDXL 生图服务**，通过 OpenAI 兼容接口接入图片素材生成，支持空闲时释放 GPU 显存。
- 新增 Opper、onomeo、Muse Spark 和 EmpirioLabs AI 大模型服务，完善巴西葡萄牙语界面翻译。
- 新增**诊断日志设置**，支持在 WebUI 中即时调整日志等级，按需记录经过脱敏和长度限制的 API 请求参数。

## 修复与改进

- 修复灰度图片亮度、透明图片背景、缩放蒙版对齐和字幕背景颜色问题；改善短片段转场、背景音乐淡出和拼接路径中的特殊字符处理。
- 隔离并发任务的图片中间文件，改善图片缓存标识并校验下载缓存；批量生成部分失败时，保留已经完成的视频。
- 修复部分配音服务的语速、音量和音频格式处理，完善远程音频校验；替换音频准备完成前保留已有文件。
- 改善字幕时间戳舍入、长词换行、Unicode 字符和停顿标签识别，避免纯符号行和分隔线干扰字幕时间轴估算。
- 修复中文、日文备用社交标题使用整篇脚本的问题；改善 JSON 提取、推理内容过滤、Markdown 文案清理和素材搜索词校验。
- 补齐支持的本地上传格式，包括多图相机 JPEG；改善 WebUI 历史视频检查、任务删除状态、字幕预览和模型连接错误提示。
- 支持生成文件的 HEAD 请求，完善范围下载、参数错误提示，以及 Redis 任务状态更新和删除保护。
- 减少语音请求在响应丢失或重定向后被重复提交的风险，保留 Upload-Post 请求追踪信息，并改善 WaveSpeed 提交失败的识别。
- 更新 Edge TTS，修复相关 403 问题；限制 PyAV 版本以兼容 Whisper，修复 Windows 缓存清理和带 UTF-8 BOM 的翻译文件读取。
- 改善 Agent 辅助脚本的配置处理和启动检查，已准备好配音与画面的任务不再额外要求大模型服务。

## 使用与升级说明

- 本项目维护的官方 PyPI 包名为 **`mpt`**，需要 **Python 3.11 或更高版本**。使用 `python -m pip install --upgrade mpt` 安装或升级，建议使用虚拟环境。PyPI 上另一个名为 `MoneyPrinterTurbo` 的包属于第三方发行版。
- pip 安装版默认将配置和生成文件保存在用户目录，可通过 `MPT_HOME` 指定位置。源码版继续使用原有项目目录；切换安装方式时，请将配置和所需资源迁移到选定的运行目录。
- 图片动态效果默认仍为**缓慢放大**，兼容已有使用方式。希望画面保持静止时，请同时选择**静止**和**无转场**；WebUI、CLI 和 API 均支持该设置。
- Kimi Code 需要浏览器登录，并使用对应订阅额度；其他新增大模型服务需要配置各自的 API 凭据和服务参数。
- 本地 SDXL 服务需要单独安装依赖、下载模型并启动 GPU 服务，不会随主程序自动运行。默认配置会在生图前卸载 Ollama 模型，请避免在同一 GPU 上同时运行大模型和生图任务。部署方法见[本地生图服务文档](https://github.com/harry0703/MoneyPrinterTurbo/blob/v1.3.9/docs/local-image-server/README.md)。
- API 请求追踪**默认关闭**。开启后，提示词和业务参数可能出现在日志中；排查结束后请关闭，分享日志前检查私人内容。详见[诊断日志文档](https://github.com/harry0703/MoneyPrinterTurbo/blob/v1.3.9/docs/diagnostic-logging.md)。

## 主要变更

- [c3634de](https://github.com/harry0703/MoneyPrinterTurbo/commit/c3634de097ea4951935d22e94580ff0ad2665503)：官方 pip 安装包与 WebUI、CLI 启动命令。
- [90f7701](https://github.com/harry0703/MoneyPrinterTurbo/commit/90f77011d7e3b46d382e6d0180dabfb6725ffee4)：图片静止与缓慢放大选项。
- [#1599](https://github.com/harry0703/MoneyPrinterTurbo/pull/1599)：Kimi Code 订阅接入，感谢 @ysntony；后续补充了[登录流程优化](https://github.com/harry0703/MoneyPrinterTurbo/commit/4204d0f)。
- [#1668](https://github.com/harry0703/MoneyPrinterTurbo/pull/1668)：本地 SDXL 生图服务，感谢 @imkashif。
- [#1589](https://github.com/harry0703/MoneyPrinterTurbo/pull/1589)：Opper 大模型服务，感谢 @Felixkw12。
- [#1600](https://github.com/harry0703/MoneyPrinterTurbo/pull/1600)：onomeo 大模型服务，感谢 @Owaid0723666。
- [#1657](https://github.com/harry0703/MoneyPrinterTurbo/pull/1657)：Muse Spark 大模型服务与巴西葡萄牙语翻译，感谢 @humbertocortezia。
- [#1694](https://github.com/harry0703/MoneyPrinterTurbo/pull/1694)：EmpirioLabs AI 大模型服务，感谢 @Adam-Dalloul。
- [6940611](https://github.com/harry0703/MoneyPrinterTurbo/commit/6940611cc2791d1ca13b3af7ee893ccd9544b874)：运行时诊断日志设置与请求追踪。
- [e25326e](https://github.com/harry0703/MoneyPrinterTurbo/commit/e25326e)：中文、日文备用社交标题修复。
- [#1597](https://github.com/harry0703/MoneyPrinterTurbo/pull/1597)：批量生成失败后保留已完成的视频，感谢 @hdu-r3drum。
- [#1652](https://github.com/harry0703/MoneyPrinterTurbo/pull/1652)：Edge TTS 403 修复，感谢 @HEOJUNFO。
- [#1582](https://github.com/harry0703/MoneyPrinterTurbo/pull/1582)：Whisper 与 PyAV 兼容性修复，感谢 @cristianchiriac。
- [#1654](https://github.com/harry0703/MoneyPrinterTurbo/pull/1654)：Windows 缓存清理修复，感谢 @shan3520。
- [#1658](https://github.com/harry0703/MoneyPrinterTurbo/pull/1658)：带 UTF-8 BOM 的翻译文件支持，感谢 @ketpatil77。
- [#1663](https://github.com/harry0703/MoneyPrinterTurbo/pull/1663)：状态无法解析时的任务保护，感谢 @RerankerGuo。
- [#1645](https://github.com/harry0703/MoneyPrinterTurbo/pull/1645)：更清晰的模型连接错误提示，感谢 @fengqiaoqu。
- [#1585](https://github.com/harry0703/MoneyPrinterTurbo/pull/1585)：本地素材启动检查，感谢 @drakeo338；[#1588](https://github.com/harry0703/MoneyPrinterTurbo/pull/1588)：保留 Redis 任务 ID 原始字符串，感谢 @ac1982。
- [#1620](https://github.com/harry0703/MoneyPrinterTurbo/pull/1620)、[#1636](https://github.com/harry0703/MoneyPrinterTurbo/pull/1636)、[#1608](https://github.com/harry0703/MoneyPrinterTurbo/pull/1608)：灰度图片渲染、生成文件 HEAD 请求和已备素材的 Agent 工作流，以及多项字幕、配音、素材、API 与任务稳定性修复，感谢 @rudycelekli。

感谢所有贡献代码、反馈问题和参与测试的朋友！

**完整变更记录**：[v1.3.8...v1.3.9](https://github.com/harry0703/MoneyPrinterTurbo/compare/v1.3.8...v1.3.9)
