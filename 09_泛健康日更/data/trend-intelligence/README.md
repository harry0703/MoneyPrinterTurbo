# 趋势情报导入目录

这里只保存已经人工批准、且经外部 `bundle-manifest.json` SHA-256 锚验证的交换包。导入目录固定为 `<batch-id>/v01/`，已存在的版本不会被覆盖。

SHA-256 必须由操作者从独立审批/交接渠道提供，不得从待导入目录现场计算后冒充外部锚。Task 8 只把完全合成的 Approved 包导入临时假仓库做契约验证；该 10 条候选不是现实趋势榜、医学结论、医学审核或真实人工选题结果。

运行校验：

```powershell
.venv\Scripts\python.exe 09_泛健康日更\scripts\import_trend_intelligence.py verify --source <approved-dir> --expected-manifest-sha256 <64位小写十六进制>
```

运行导入：

```powershell
.venv\Scripts\python.exe 09_泛健康日更\scripts\import_trend_intelligence.py import --source <approved-dir> --repo-root <MoneyPrinterTurbo根目录> --expected-manifest-sha256 <64位小写十六进制>
```

该入口不读取 Raw/Curated，不启动 MediaCrawler，不下载媒体，不自动生成或发布内容。交换包只是选题情报，不是医学事实来源或可直接发布的脚本。

Approved 合同在 producer 和本导入器两端等价执行：每条候选必须恰好有一个 `medical_claim_unverified`，任何结构化 flag 或自然语言中的肯定医学/临床核验状态都会拒绝；明确“未核验、待核验、核验未完成”仍允许。两端同时要求 batch-wide dy+xhs 覆盖、严格字段/类型、1–10 唯一 rank、规范化唯一 topic、非空证据 list、missing sentinel 规则和精确免责声明。

Task 8 的独立边界脚本只在完全合成的仓库外根上演练，并强制显式 profile。`current-worktree-audit` 固定核验当前本机 240 删除集、受审 config identity 和披露的历史 cache 例外，只证明当前 dirty baseline；`clean-checkout-validation` 要求 clean committed checkout 与 0 个 manual-pack 工作树删除，不读取/哈希 ignored 本机 `config.toml`，也不沿用 current 的 legacy cache 例外。成功 JSON 明示 `audit_profile`，两个 PASS 不可混用。两种模式都内置受审 BASE、最终修复提交范围和 MediaCrawler commit，不接受 caller 自报 counts/hash，并核对全仓 Git/磁盘 Raw、配置/依赖、路径链、敏感 JSON 键和媒体文件头。任一项缺失或不可验都非零失败；该合成验证不声称现实热度、医学有效性或真实人工审批。

## 导入事务与恢复边界

导入器会先在 batch 目录下创建唯一的 `.v01-import-*` 临时目录，按“两个 payload 在先、manifest 在后”写入并完整复核，然后在同一父目录中以不覆盖重命名发布为 `v01`。因此写入或复核失败不会占用正式 `v01`，同一交换包可以直接重试。

导入器只自动清理当前调用自己创建、目录身份未变，且内容只是预期三文件子集的临时目录。如果临时目录的初始身份无法取得，导入器会保守地保留该唯一名目录，新的重试会使用另一个唯一名，不会被它阻塞；如果身份已取得，但后续初始化失败，则仅在身份、路径和文件集都仍能保守确认时自动清理。

任何既有 `v01`、未知 `.v01-import-*` 目录、身份已变的目录或含额外文件的目录都不会被自动删除或覆盖，需要操作者先隔离并人工调查。不得仅因目录名类似 staging 就删除它。
