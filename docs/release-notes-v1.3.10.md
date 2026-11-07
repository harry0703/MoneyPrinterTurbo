[English](#en-v1.3.10) | [中文](#cn-v1.3.10)

<h2 id="en-v1.3.10">Highlights</h2>

- Added **OpenAI Codex subscription access** with device-code sign-in and dynamic model selection, plus a separate **ChatGPT Native OAuth** provider. Native OAuth availability depends on account eligibility; existing Codex sign-in remains independent.
- Added **Codex image generation** as a material source. Text and image generation can share the application's Codex login, and generated images support the existing static and slow zoom effects.
- Added **Infistar and Jalapeno Cloud** for LLM and video generation, alongside **Runcrate, CloudGPU, and cheapaimodel** LLM providers.
- Improved **long-running video generation feedback** with generation stages, elapsed time, and polling status. Task tracking survives page refreshes and temporary query failures, with protection against duplicate submissions.
- Simplified **provider settings and selection** in the WebUI, making configured services easier to find and switch between.
- Added **Arabic-script subtitle shaping**, including connected letters, right-to-left layout, mixed-script font fallback, and glyph-aware wrapping and backgrounds.
- Made **slow image zoom smoother** with sub-pixel rendering, eliminating visible stepping and wobble.
- Added Indonesian to script-language choices and refined the Indonesian interface translations.

## Fixes and Improvements

- Fixed long Edge TTS narration timing out because of unnecessary delays between streamed chunks. Added support for Edge voices with script subtags and clearer Gemini empty-audio diagnostics.
- Removed emoji from narration and burned-in subtitles, and clarified that Gemini and MiMo TTS do not use the voice-speed setting.
- Improved subtitle splitting around clock times, full-width numbers, dates, abbreviations, names, and Chinese and Japanese punctuation. Added sentence splitting for Thai and Lao scripts.
- Preserved the original timed transcription when subtitle correction cannot align the full script. Fixed empty-string and Unicode length-expansion cases in subtitle similarity scoring.
- Preserved combining marks in multilingual social hashtags, excluded emoji marks, and recognized Chinese and Japanese hashtag separators.
- Kept existing script and keywords when AI generation fails, displayed an actionable error, and avoided requesting keywords after script generation has already failed.
- Preserved the position of repeated topics during script-order stock-material matching, repaired corrupt video caches, and added clearer Pexels and Coverr search-failure logs.
- Stopped console keystrokes from prematurely ending or stalling FFmpeg clip concatenation. Fixed render-output synchronization on Windows and big-endian grayscale TIFF brightness.
- Improved Windows startup from paths containing special characters, from other working directories, and with LAN listening enabled. Fixed redirected console logs and preserved Windows paths and non-breaking spaces when saving configuration.
- Shared Redis task-concurrency limits across workers, with atomic slot reservation, lease renewal, and queued-task recovery.
- Improved subtitle-font error messages, API enum defaults, and ChatGPT/Codex sign-in diagnostics. Clarified Docker configuration setup and recovery from an accidentally mounted `config.toml` directory.
- Updated CPU-container dependencies to address fixable security findings and added container vulnerability scanning. Expanded regression coverage and corrected Windows-specific path assertions.

## What's Changed

- Codex subscription provider — @Hackerprod in [#1715](https://github.com/harry0703/MoneyPrinterTurbo/pull/1715).
- ChatGPT Native OAuth provider — @Quiyyy in [#1716](https://github.com/harry0703/MoneyPrinterTurbo/pull/1716).
- Codex image material source — @Hackerprod in [#1719](https://github.com/harry0703/MoneyPrinterTurbo/pull/1719).
- Infistar LLM and video providers — [ebb0e28](https://github.com/harry0703/MoneyPrinterTurbo/commit/ebb0e283) / [fddd3d6](https://github.com/harry0703/MoneyPrinterTurbo/commit/fddd3d6a).
- Jalapeno Cloud LLM and video support — [66e41b0](https://github.com/harry0703/MoneyPrinterTurbo/commit/66e41b0f).
- Runcrate LLM provider — @heydryft in [#1713](https://github.com/harry0703/MoneyPrinterTurbo/pull/1713).
- CloudGPU LLM provider — @cursoragent in [#1730](https://github.com/harry0703/MoneyPrinterTurbo/pull/1730).
- cheapaimodel LLM provider — @nicho810 in [#1757](https://github.com/harry0703/MoneyPrinterTurbo/pull/1757).
- Video-generation progress and task tracking — [950ba89](https://github.com/harry0703/MoneyPrinterTurbo/commit/950ba898).
- Simplified provider settings — @Hackerprod in [#1723](https://github.com/harry0703/MoneyPrinterTurbo/pull/1723).
- Arabic subtitle shaping — @DrEssam97 in [#1698](https://github.com/harry0703/MoneyPrinterTurbo/pull/1698).
- Smooth image zoom — @kindsr in [#1767](https://github.com/harry0703/MoneyPrinterTurbo/pull/1767).
- Indonesian language improvements — @mteguhfh in [5c1268b](https://github.com/harry0703/MoneyPrinterTurbo/commit/5c1268b5) / [89c7e41](https://github.com/harry0703/MoneyPrinterTurbo/commit/89c7e418).
- Windows render-output synchronization — @rodriguetg in [#1701](https://github.com/harry0703/MoneyPrinterTurbo/pull/1701).
- FFmpeg path expansion and clearer font-path errors — @RerankerGuo in [#1662](https://github.com/harry0703/MoneyPrinterTurbo/pull/1662) / [#1664](https://github.com/harry0703/MoneyPrinterTurbo/pull/1664).
- Gemini empty-audio diagnostics and preserved transcription timing — @Shubham-Padkonde in [#1721](https://github.com/harry0703/MoneyPrinterTurbo/pull/1721) / [#1763](https://github.com/harry0703/MoneyPrinterTurbo/pull/1763).
- Redis concurrency, cache repair, and enum defaults — @guishiw in [#1742](https://github.com/harry0703/MoneyPrinterTurbo/pull/1742) / [#1744](https://github.com/harry0703/MoneyPrinterTurbo/pull/1744) / [bbb9c13](https://github.com/harry0703/MoneyPrinterTurbo/commit/bbb9c13c).
- CPU-container security updates — @TheInfamousToTo in [13fabd5](https://github.com/harry0703/MoneyPrinterTurbo/commit/13fabd52).
- Docker configuration guidance — @ketpatil77 in [#1653](https://github.com/harry0703/MoneyPrinterTurbo/pull/1653).
- Docker configuration recovery — @ChandraChaan in [#1753](https://github.com/harry0703/MoneyPrinterTurbo/pull/1753).
- Subtitle, speech, Windows startup, and generation-error fixes — @tanishqbaweja in [#1728](https://github.com/harry0703/MoneyPrinterTurbo/pull/1728) / [#1755](https://github.com/harry0703/MoneyPrinterTurbo/pull/1755) / [#1756](https://github.com/harry0703/MoneyPrinterTurbo/pull/1756) / [#1760](https://github.com/harry0703/MoneyPrinterTurbo/pull/1760) / [#1766](https://github.com/harry0703/MoneyPrinterTurbo/pull/1766).
- Hashtag handling, subtitle punctuation, repeated material topics, and Edge voice compatibility — @L4XB in [#1772](https://github.com/harry0703/MoneyPrinterTurbo/pull/1772) / [#1773](https://github.com/harry0703/MoneyPrinterTurbo/pull/1773).
- Subtitle similarity boundaries — @liangliang205 in [#1776](https://github.com/harry0703/MoneyPrinterTurbo/pull/1776).
- Safer download filenames and TIFF image handling — @rudycelekli in [33dde16](https://github.com/harry0703/MoneyPrinterTurbo/commit/33dde166) / [9c13dd6](https://github.com/harry0703/MoneyPrinterTurbo/commit/9c13dd6d).
- Service-test cleanup — @SammyFerreiraa and @Natan-Lucena in [#1724](https://github.com/harry0703/MoneyPrinterTurbo/pull/1724).
- Windows path-test fixes — @kumain-in in [#1778](https://github.com/harry0703/MoneyPrinterTurbo/pull/1778).

**Full Changelog**: [v1.3.9...v1.3.10](https://github.com/harry0703/MoneyPrinterTurbo/compare/v1.3.9...v1.3.10)

---

<h2 id="cn-v1.3.10">重点更新</h2>

- 新增 **OpenAI Codex 订阅接入**，支持设备码登录和动态模型选择；另提供独立的 **ChatGPT 原生 OAuth 接入**。原生授权取决于账号资格，与已有 Codex 登录相互独立。
- 新增 **Codex 图片素材来源**，文案与生图可复用本应用的 Codex 登录，生成的图片支持现有的静止和缓慢放大效果。
- 新增 **Infistar 和 Jalapeno Cloud 大模型及视频生成服务**，以及 **Runcrate、CloudGPU、cheapaimodel** 大模型服务。
- 完善**长时间视频生成的进度反馈**，显示生成阶段、已用时间和轮询状态；刷新页面或查询短暂失败后可继续跟踪任务，并增加重复提交保护。
- 简化 WebUI 的**服务商设置与选择**，便于查找和切换已经配置的服务。
- 新增**阿拉伯语文字字幕整形**，支持字母连写、从右到左排版、混合文字字体回退，以及按实际字形计算换行和背景。
- 改善**图片缓慢放大的流畅度**，通过亚像素渲染消除明显的步进和抖动。
- 新增印尼语脚本语言选项，并完善印尼语界面翻译。

## 修复与改进

- 修复 Edge TTS 因流式数据处理延迟导致长文案配音超时的问题；支持带脚本子标签的 Edge 音色，并补充 Gemini 返回空音频时的原因提示。
- 从配音和烧录字幕中清理 emoji，明确提示 Gemini、MiMo TTS 不使用配音语速设置。
- 改善时间、全角数字、日期、缩写、人名及中日文标点附近的字幕断句；补充泰语、老挝语按句间空格拆分的处理。
- 字幕校正无法对齐完整文案时保留原始转写时间轴；修复相似度计算遇到空字符串或特殊 Unicode 字符时除零、返回负值的问题。
- 保留多语言社交标签中的组合字符，排除 emoji 标记，并识别中文、日文标签分隔符。
- AI 文案或关键词生成失败时保留已有内容并显示错误；文案生成失败后不再继续请求关键词。
- 修复按脚本顺序匹配库存素材时重复主题丢失位置的问题；修复损坏的视频缓存，并补充 Pexels、Coverr 搜索失败的具体原因。
- 避免控制台按键提前结束或阻塞 FFmpeg 片段拼接；修复 Windows 渲染文件同步，以及大端灰度 TIFF 图片亮度问题。
- 改善 Windows 下特殊字符路径、其他工作目录和局域网监听场景中的启动兼容性；修复日志重定向，并在保存配置时保留 Windows 路径和不换行空格。
- 统一多个工作进程的 Redis 任务并发限制，支持原子占用执行名额、续期和排队任务恢复。
- 改善字幕字体错误提示、API 枚举默认值和 ChatGPT/Codex 登录诊断；补充 Docker 配置说明，以及误将 `config.toml` 挂载为目录时的恢复提示。
- 更新 CPU 容器依赖，修复可解决的安全扫描问题，并增加容器漏洞扫描；完善回归测试，修正 Windows 路径断言误报。

## 主要变更

- [#1715](https://github.com/harry0703/MoneyPrinterTurbo/pull/1715)：Codex 订阅接入，感谢 @Hackerprod。
- [#1716](https://github.com/harry0703/MoneyPrinterTurbo/pull/1716)：ChatGPT 原生 OAuth 接入，感谢 @Quiyyy。
- [#1719](https://github.com/harry0703/MoneyPrinterTurbo/pull/1719)：Codex 图片素材来源，感谢 @Hackerprod。
- [ebb0e28](https://github.com/harry0703/MoneyPrinterTurbo/commit/ebb0e283) / [fddd3d6](https://github.com/harry0703/MoneyPrinterTurbo/commit/fddd3d6a)：Infistar 大模型与视频生成服务。
- [66e41b0](https://github.com/harry0703/MoneyPrinterTurbo/commit/66e41b0f)：Jalapeno Cloud 大模型与视频生成服务。
- [#1713](https://github.com/harry0703/MoneyPrinterTurbo/pull/1713)：Runcrate 大模型服务，感谢 @heydryft。
- [#1730](https://github.com/harry0703/MoneyPrinterTurbo/pull/1730)：CloudGPU 大模型服务，感谢 @cursoragent。
- [#1757](https://github.com/harry0703/MoneyPrinterTurbo/pull/1757)：cheapaimodel 大模型服务，感谢 @nicho810。
- [950ba89](https://github.com/harry0703/MoneyPrinterTurbo/commit/950ba898)：视频生成进度与任务跟踪。
- [#1723](https://github.com/harry0703/MoneyPrinterTurbo/pull/1723)：简化服务商设置，感谢 @Hackerprod。
- [#1698](https://github.com/harry0703/MoneyPrinterTurbo/pull/1698)：阿拉伯语字幕整形，感谢 @DrEssam97。
- [#1767](https://github.com/harry0703/MoneyPrinterTurbo/pull/1767)：改善图片放大的流畅度，感谢 @kindsr。
- [5c1268b](https://github.com/harry0703/MoneyPrinterTurbo/commit/5c1268b5) / [89c7e41](https://github.com/harry0703/MoneyPrinterTurbo/commit/89c7e418)：印尼语选项与翻译改进，感谢 @mteguhfh。
- [#1701](https://github.com/harry0703/MoneyPrinterTurbo/pull/1701)：Windows 渲染文件同步修复，感谢 @rodriguetg。
- [#1662](https://github.com/harry0703/MoneyPrinterTurbo/pull/1662) / [#1664](https://github.com/harry0703/MoneyPrinterTurbo/pull/1664)：FFmpeg 路径展开和字体路径错误提示，感谢 @RerankerGuo。
- [#1721](https://github.com/harry0703/MoneyPrinterTurbo/pull/1721) / [#1763](https://github.com/harry0703/MoneyPrinterTurbo/pull/1763)：Gemini 空音频诊断和字幕时间轴保留，感谢 @Shubham-Padkonde。
- [#1742](https://github.com/harry0703/MoneyPrinterTurbo/pull/1742) / [#1744](https://github.com/harry0703/MoneyPrinterTurbo/pull/1744) / [bbb9c13](https://github.com/harry0703/MoneyPrinterTurbo/commit/bbb9c13c)：Redis 并发限制、缓存修复和枚举默认值处理，感谢 @guishiw。
- [13fabd5](https://github.com/harry0703/MoneyPrinterTurbo/commit/13fabd52)：CPU 容器安全更新，感谢 @TheInfamousToTo。
- [#1653](https://github.com/harry0703/MoneyPrinterTurbo/pull/1653)：Docker 配置说明，感谢 @ketpatil77。
- [#1753](https://github.com/harry0703/MoneyPrinterTurbo/pull/1753)：Docker 配置恢复提示，感谢 @ChandraChaan。
- [#1728](https://github.com/harry0703/MoneyPrinterTurbo/pull/1728) / [#1755](https://github.com/harry0703/MoneyPrinterTurbo/pull/1755) / [#1756](https://github.com/harry0703/MoneyPrinterTurbo/pull/1756) / [#1760](https://github.com/harry0703/MoneyPrinterTurbo/pull/1760) / [#1766](https://github.com/harry0703/MoneyPrinterTurbo/pull/1766)：多项字幕、配音、Windows 启动和生成错误处理修复，感谢 @tanishqbaweja。
- [#1772](https://github.com/harry0703/MoneyPrinterTurbo/pull/1772) / [#1773](https://github.com/harry0703/MoneyPrinterTurbo/pull/1773)：多项标签和字幕标点修复、重复主题素材匹配及 Edge 音色兼容，感谢 @L4XB。
- [#1776](https://github.com/harry0703/MoneyPrinterTurbo/pull/1776)：字幕相似度边界修复，感谢 @liangliang205。
- [33dde16](https://github.com/harry0703/MoneyPrinterTurbo/commit/33dde166) / [9c13dd6](https://github.com/harry0703/MoneyPrinterTurbo/commit/9c13dd6d)：下载文件名安全处理和 TIFF 图片修复，感谢 @rudycelekli。
- [#1724](https://github.com/harry0703/MoneyPrinterTurbo/pull/1724)：服务测试整理，感谢 @SammyFerreiraa、@Natan-Lucena。
- [#1778](https://github.com/harry0703/MoneyPrinterTurbo/pull/1778)：Windows 路径测试修复，感谢 @kumain-in。

**完整变更记录**：[v1.3.9...v1.3.10](https://github.com/harry0703/MoneyPrinterTurbo/compare/v1.3.9...v1.3.10)
