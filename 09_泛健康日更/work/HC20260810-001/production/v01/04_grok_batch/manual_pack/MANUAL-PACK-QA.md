# HC20260810-001 v01 Grok 手动包 QA

## 结果

- 活动主题状态：`production`；批次：`HB20260810`。
- 分镜：`09_泛健康日更/work/HC20260810-001/production/v01/02_script_storyboard/storyboard-v01.md`，SHA-256 `17dcad272b94c6ce1da6228b6bf12c1d6c8622d99e1ec37dc9630f54a343732e`，按表头名解析并确认恰好 S01–S10。
- 正式首帧：仅消费 `03_first_frames/` 根目录中 10 张无字 PNG；全部 1080×1920、哈希唯一，拷贝后字节与源文件相同。
- 排除：未消费 `storyboard_with_copy/`、带字联系表、UI 预览或候选图。
- 提示词：10 条中英双语单行，S03/S08/S10 为 `deterministic_post` 且无需上传 Grok；其余 7 镜为 `grok_manual`，最小 Grok 源时长均不超过 5.8 秒。
- 合并 TXT：恰好 10 条非空提示词，相邻恰好一个空行，UTF-8 + LF。

## 必需源质量证据

- 单期 Task 6：`09_泛健康日更/work/HC20260810-001/production/v01/05_qa/first-frame-qa-v01.md`，SHA-256 `479d5305e2264f90dd7fef059665a73d5fc8d28bcd074f54a554299880f634cc`。
- 批次 Task 6：`09_泛健康日更/work/HC20260810-B01-task6-qa/HC20260810-B01-first-frame-qa-v01.md`，SHA-256 `599af3788947838820f0c1b3f9ea834d7308d7114a7a9330439fe181952934c9`。
- 两份 QA 只是必需的当前源质量证据，**不是外部审批**、Task 8 事实批准、最终 QA 授权或发布许可。

## 视觉核对边界

- 10 张正式首帧及带字联系表已逐项打开用于理解动作、人物和场景上下文；带字层仅审阅，不会被复制。
- 这份本地 QA 不声称 Grok 动态连续性或最终成片已通过。
