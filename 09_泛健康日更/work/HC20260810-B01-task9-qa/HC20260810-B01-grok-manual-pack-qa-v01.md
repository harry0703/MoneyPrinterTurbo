# HC20260810-B01 Grok 手工包批次 QA v01

日期：2026-08-17
范围：HC20260810-001—HC20260810-010 的离线、确定性 Grok 手工输入包。
边界：本记录不是 Grok 生成记录、外部审批、最终 QA 签名或发布许可。

## 验收结果

- production 状态：10/10。
- 提示词文档：10/10；每份恰好 S01—S10。
- 镜头行：100/100。
- 逐镜提示词文件：100/100。
- 复制首帧：100/100，全部 1080×1920。
- 源图/复制图字节一致：100/100。
- 空行格式：10/10；UTF-8 + LF，相邻提示词恰好一个空行。
- 动态时长门：100/100 适用行；逐行按 `generation_mode` 分流，其中 63/63 个 `grok_manual` 镜头为 `0 < minimum_grok_source_seconds <= 5.8`，37/37 个 `deterministic_post` 镜头为 `0.00`。
- deterministic-board 不上传 Grok；仅按锁定分镜在后期做确定性处理。
- 10 个手工包均通过当前 builder 的独立 `verify`；没有调用 Grok、浏览器自动化、API 或视频生成服务。

## 用户手动生成与命名

1. 用户手动生成：只对每期 `MANIFEST.csv` 中 `generation_mode=grok_manual` 的行，在 Grok 浏览器扩展中上传同号无字首帧并粘贴同号提示词。
2. `generation_mode=deterministic_post` 的行不上传 Grok。
3. 动态输出由用户手动保存到对应 `05_grok_videos/01_raw/`；文件名必须逐行使用 `MANIFEST.csv` 的 `output_template`，不得自拟名称或覆盖其他镜头。
4. 保存后仍须逐镜检查首、中、尾帧；原始视频应保留，后续入选素材另行复制。

## 状态声明

- 尚未生成视频；本批次只交付首帧复制、逐镜提示词、合并提示词、manifest、指南和本地 QA 证据。
- 尚未通过最终 QA；必须等待真实视频生成、技术/内容检查与外部 `final_qa_reviewer` 签名。
- 本记录不得解释为已上传 Grok、已生成成片、已通过最终 QA 或已获发布许可。
