[English](#en-v1.3.11) | [中文](#cn-v1.3.11)

<h2 id="en-v1.3.11">Highlights</h2>

- Added **[Aigei](https://www.aigei.com/?utm_source=github&utm_medium=sponsorship&utm_campaign=moneyprinterturbo)** as a stock video source.
- Added **useapi.net** as a source for AI video and images.
- Added **APINEBULA, APIXO Responses, AtmoRouter, and MartLLM** (formerly UberLLM) as LLM providers.
- Improved **local rendering performance** by reducing per-frame compositing work for subtitles, letterboxing, and slide transitions.
- Local video projects now return **individual rendered scene clips** in timeline order. This release also fixes cropping for footage with non-square pixels and reduces redundant cache verification during repeat renders.
- Updated **Gemini speech synthesis** to Gemini 3.8 Flash-Lite TTS and improved **Edge TTS** timeout handling so long narration can finish while data is still arriving.

## Fixes and Improvements

- Fixed FFmpeg audio validation that could accept a damaged MP3 or reject a valid short clip. Long files are checked without buffering the entire validation output.
- Improved stock footage selection and playback. Sequential mode uses the rest of a clip before repeating it, faster playback gets enough footage to cover narration, and Pixabay can use a suitable 1080p file instead of downloading 4K.
- Kept polling Seedance jobs when an Ark-compatible gateway reports `pending`.
- Improved subtitle alignment with script lines and kept titles such as “Mr.” and “Dr.” with the names that follow. Accepted full-width brackets in narration pause tags.
- Fixed voice previews that used the interface language instead of the selected voice’s language. Refined Spanish WebUI translations and file-size formatting.
- Removed Markdown code fences from generated narration and preserved the first sentence when falling back to a social title.
- Omitted or null API voice names use the default voice. CLI batch entries with a null voice inherit the batch voice. The API rejects blank scripts on `/audio` and `/subtitle`, and a null aspect ratio on `/videos`, before queuing a task.
- Preserved Unicode separators inside JSONL strings. Cleared stale failure information after a successful local-project retry and made the agent helper honor `MPT_HOME`.

## What's Changed

- Aigei, APINEBULA, and APIXO Responses integrations · [Aigei](https://github.com/harry0703/MoneyPrinterTurbo/commit/d4877bc) · [APINEBULA](https://github.com/harry0703/MoneyPrinterTurbo/commit/075f7ac) · [APIXO](https://github.com/harry0703/MoneyPrinterTurbo/commit/110b14d)
- useapi.net material sources by @useapi. [#1784](https://github.com/harry0703/MoneyPrinterTurbo/pull/1784)
- AtmoRouter and MartLLM by @BeckleyTenriajeng and @al-global-tech. [#1827](https://github.com/harry0703/MoneyPrinterTurbo/pull/1827) · [#1770](https://github.com/harry0703/MoneyPrinterTurbo/pull/1770) · [#1840](https://github.com/harry0703/MoneyPrinterTurbo/pull/1840)
- Local rendering performance and backend interface by @b84330808 and @venkatsammm. [#1779](https://github.com/harry0703/MoneyPrinterTurbo/pull/1779) · [#1820](https://github.com/harry0703/MoneyPrinterTurbo/pull/1820) · [#1841](https://github.com/harry0703/MoneyPrinterTurbo/pull/1841) · [#1825](https://github.com/harry0703/MoneyPrinterTurbo/pull/1825)
- Project scene clips, cropping, retry, and cache handling by @meowtivator and @nemo-crypto. [#1818](https://github.com/harry0703/MoneyPrinterTurbo/pull/1818) · [#1835](https://github.com/harry0703/MoneyPrinterTurbo/pull/1835) · [#1837](https://github.com/harry0703/MoneyPrinterTurbo/pull/1837) · [#1839](https://github.com/harry0703/MoneyPrinterTurbo/pull/1839)
- Gemini TTS, Edge TTS, and FFmpeg audio validation by @JunaidAhamed-7777, @venkatsammm, and @AyhamJo7. [#1821](https://github.com/harry0703/MoneyPrinterTurbo/pull/1821) · [#1826](https://github.com/harry0703/MoneyPrinterTurbo/pull/1826) · [#1823](https://github.com/harry0703/MoneyPrinterTurbo/pull/1823)
- Stock footage coverage and playback, and Seedance polling, by @tanishqbaweja and @k01082915788-rgb. [#1788](https://github.com/harry0703/MoneyPrinterTurbo/pull/1788) · [#1794](https://github.com/harry0703/MoneyPrinterTurbo/pull/1794) · [#1799](https://github.com/harry0703/MoneyPrinterTurbo/pull/1799) · [#1829](https://github.com/harry0703/MoneyPrinterTurbo/pull/1829)
- API and CLI input handling by @tanishqbaweja, @nemo-crypto, and @HEOJUNFO. [#1796](https://github.com/harry0703/MoneyPrinterTurbo/pull/1796) · [#1822](https://github.com/harry0703/MoneyPrinterTurbo/pull/1822) · [#1833](https://github.com/harry0703/MoneyPrinterTurbo/pull/1833) · [#1843](https://github.com/harry0703/MoneyPrinterTurbo/pull/1843) · [#1844](https://github.com/harry0703/MoneyPrinterTurbo/pull/1844)
- Spanish WebUI translations and agent runtime directory handling by @PedroFlores199 and @dajiaohuang. [#1819](https://github.com/harry0703/MoneyPrinterTurbo/pull/1819) · [#1804](https://github.com/harry0703/MoneyPrinterTurbo/pull/1804)

**Full Changelog** · [v1.3.10...v1.3.11](https://github.com/harry0703/MoneyPrinterTurbo/compare/v1.3.10...v1.3.11)

---

<h2 id="cn-v1.3.11">重点更新</h2>

- 新增 **[爱给网](https://www.aigei.com/?utm_source=github&utm_medium=sponsorship&utm_campaign=moneyprinterturbo)** 视频素材来源。
- 新增 **useapi.net** AI 视频和图片素材来源。
- 新增 **APINEBULA、APIXO Responses、AtmoRouter 和 MartLLM**（原 UberLLM）大模型服务。
- 优化**本地视频渲染性能**，减少字幕、留黑边和滑动转场的逐帧合成开销。
- **本地视频项目**现在可按时间线顺序取得各场景的成片。修复非方形像素素材裁剪后变形的问题，并减少重复渲染时的缓存校验。
- 将 **Gemini 配音**迁移到 Gemini 3.8 Flash-Lite TTS，改善 **Edge TTS** 超时处理，让持续接收数据的长文案配音能在总时限内完成。

## 修复与改进

- 修复 FFmpeg 误接受损坏 MP3、误拒有效短音频的问题。校验长音频时按流读取，减少内存占用。
- 改善库存素材的下载与播放。顺序模式先播完当前片段再重复，高倍速下会下载足够覆盖旁白的素材，分辨率足够时优先使用 Pixabay 的 1080p 文件，减少不必要的 4K 下载。
- 兼容 Ark 网关返回的 Seedance `pending` 状态，任务排队期间继续轮询。
- 改善字幕按原稿行对齐的效果，避免把 `Mr.`、`Dr.` 等称谓与后续姓名拆到不同字幕行。配音停顿标签支持全角方括号。
- 试听示例按所选音色的语言播放，修复界面语言不同时的试听问题。完善西班牙语 WebUI 文案和文件大小显示。
- 清理 AI 生成文案中的 Markdown 代码块标记，生成备用社交标题时保留首句。
- API 省略音色或显式传入 `null` 时使用默认音色，CLI 批任务传入 `null` 时继承批次音色。`/audio`、`/subtitle` 的空白脚本以及 `/videos` 的空画幅会在入队前报错。
- 保留 JSONL 字符串里的 Unicode 分隔符。修复本地项目成功重试后仍显示旧失败阶段的问题，并让 Agent 辅助工具正确使用 `MPT_HOME`。

## 主要变更

- 爱给网、APINEBULA 和 APIXO Responses 接入。 [爱给网](https://github.com/harry0703/MoneyPrinterTurbo/commit/d4877bc) · [APINEBULA](https://github.com/harry0703/MoneyPrinterTurbo/commit/075f7ac) · [APIXO](https://github.com/harry0703/MoneyPrinterTurbo/commit/110b14d)
- useapi.net 素材接入，感谢 @useapi。 [#1784](https://github.com/harry0703/MoneyPrinterTurbo/pull/1784)
- AtmoRouter 接入与 MartLLM 接入及更名，感谢 @BeckleyTenriajeng、@al-global-tech。 [#1827](https://github.com/harry0703/MoneyPrinterTurbo/pull/1827) · [#1770](https://github.com/harry0703/MoneyPrinterTurbo/pull/1770) · [#1840](https://github.com/harry0703/MoneyPrinterTurbo/pull/1840)
- 本地渲染性能与后端接口，感谢 @b84330808、@venkatsammm。 [#1779](https://github.com/harry0703/MoneyPrinterTurbo/pull/1779) · [#1820](https://github.com/harry0703/MoneyPrinterTurbo/pull/1820) · [#1841](https://github.com/harry0703/MoneyPrinterTurbo/pull/1841) · [#1825](https://github.com/harry0703/MoneyPrinterTurbo/pull/1825)
- 本地项目的场景成片、裁剪、重试和缓存，感谢 @meowtivator、@nemo-crypto。 [#1818](https://github.com/harry0703/MoneyPrinterTurbo/pull/1818) · [#1835](https://github.com/harry0703/MoneyPrinterTurbo/pull/1835) · [#1837](https://github.com/harry0703/MoneyPrinterTurbo/pull/1837) · [#1839](https://github.com/harry0703/MoneyPrinterTurbo/pull/1839)
- Gemini 配音、Edge TTS 和 FFmpeg 音频校验，感谢 @JunaidAhamed-7777、@venkatsammm、@AyhamJo7。 [#1821](https://github.com/harry0703/MoneyPrinterTurbo/pull/1821) · [#1826](https://github.com/harry0703/MoneyPrinterTurbo/pull/1826) · [#1823](https://github.com/harry0703/MoneyPrinterTurbo/pull/1823)
- 库存素材下载与播放及 Seedance 轮询，感谢 @tanishqbaweja、@k01082915788-rgb。 [#1788](https://github.com/harry0703/MoneyPrinterTurbo/pull/1788) · [#1794](https://github.com/harry0703/MoneyPrinterTurbo/pull/1794) · [#1799](https://github.com/harry0703/MoneyPrinterTurbo/pull/1799) · [#1829](https://github.com/harry0703/MoneyPrinterTurbo/pull/1829)
- API 和 CLI 输入处理，感谢 @tanishqbaweja、@nemo-crypto、@HEOJUNFO。 [#1796](https://github.com/harry0703/MoneyPrinterTurbo/pull/1796) · [#1822](https://github.com/harry0703/MoneyPrinterTurbo/pull/1822) · [#1833](https://github.com/harry0703/MoneyPrinterTurbo/pull/1833) · [#1843](https://github.com/harry0703/MoneyPrinterTurbo/pull/1843) · [#1844](https://github.com/harry0703/MoneyPrinterTurbo/pull/1844)
- 西班牙语 WebUI 翻译和 Agent 运行目录，感谢 @PedroFlores199、@dajiaohuang。 [#1819](https://github.com/harry0703/MoneyPrinterTurbo/pull/1819) · [#1804](https://github.com/harry0703/MoneyPrinterTurbo/pull/1804)

**完整变更记录** · [v1.3.10...v1.3.11](https://github.com/harry0703/MoneyPrinterTurbo/compare/v1.3.10...v1.3.11)
