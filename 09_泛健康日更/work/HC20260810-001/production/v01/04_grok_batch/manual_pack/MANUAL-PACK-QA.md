# HC20260810-001 v01 Grok 手动包 QA

## 结果

- 活动主题状态：`production`；批次：`HB20260810`。
- 分镜：`09_泛健康日更/work/HC20260810-001/production/v01/02_script_storyboard/storyboard-v01.md`，SHA-256 `17dcad272b94c6ce1da6228b6bf12c1d6c8622d99e1ec37dc9630f54a343732e`，按表头名解析并确认恰好 S01–S10。
- 正式首帧：仅消费 `03_first_frames/` 根目录中 10 张无字 PNG；全部 1080×1920、哈希唯一，拷贝后字节与源文件相同。
- 排除：未消费 `storyboard_with_copy/`、带字联系表、UI 预览或候选图。
- 提示词：10 条中英双语单行，S03、S08、S10 为 `deterministic_post` 且无需上传 Grok；其余动态镜头为 `grok_manual`，最小 Grok 源时长均不超过 5.8 秒。
- 合并 TXT：恰好 10 条非空提示词，相邻恰好一个空行，UTF-8 + LF。
- 必需动态源输出：7 个；每个必需源至少保留 2 个候选，并发为 1，每次生成后至少等待 30 秒。
- 双源镜头：无；每个动态镜头 required_output_count=1。

## 必需源质量证据

- 单期 Task 6：`09_泛健康日更/work/HC20260810-001/production/v01/05_qa/first-frame-qa-v01.md`，SHA-256 `479d5305e2264f90dd7fef059665a73d5fc8d28bcd074f54a554299880f634cc`。
- 批次 Task 6：`09_泛健康日更/work/HC20260810-B01-task6-qa/HC20260810-B01-first-frame-qa-v01.md`，SHA-256 `599af3788947838820f0c1b3f9ea834d7308d7114a7a9330439fe181952934c9`。
- 两份 QA 只是必需的当前源质量证据，**不是外部审批**、Task 8 事实批准、最终 QA 授权或发布许可。

## 视觉核对边界

- 审阅方式：`view_image`。
- 审阅日期：`2026-08-17`。
- 审阅者：`Codex Task 8 manual-pack review`。
- 带字联系表：`09_泛健康日更/work/HC20260810-001/production/v01/05_qa/storyboard-with-copy-contactsheet-v01.png`，SHA-256 `d3e2be9bf647cf12f5a6038b43917af4d70d964bdfae694cb2550ff5f21f3840`；只用于理解文案/动作上下文，不会被复制。

| 镜号 | 正式首帧 SHA-256 | `view_image` 逐镜结论 |
|---|---|---|
| S01 | `b3c852ff963fd4abbfb187b6ba1d59fab1de01d83c2101125aac671a0e681394` | 暖光餐桌旁坐姿人物，闭眼、手与餐盘关系清楚 |
| S02 | `3216d4be1eac7717e2d0eff24b6bc8926027ea58aacb2ec110e58772fe104870` | 同一人物侧后坐姿，手已离盘，视线面向窗光 |
| S03 | `0227b931e1253e161a2b4b67f21e34ff8875a4a0a3b58da3c1289be7b89efe58` | 夜间暗光与早晨窗光双板，中央分隔稳定 |
| S04 | `47a195c23d5317a9c78173621fa11f5f7216ba55e4edafc79d199cd1c45c436b` | 餐具已在桌面，手在勺子附近，支持放勺最后落稳阶段 |
| S05 | `dff77f067c2c0efa0302617c9e39ab3086f96db7819bd1c6327ebbaa7444811d` | 人物已站立行走，从餐区朝客厅的方向清楚 |
| S06 | `fe7abb38c27bd634d9df083217496f8093a3fcb79575724365e58ca7aa7e2c8b` | 越肩黑屏手机，四角完整，拇指点按位置清楚 |
| S07 | `c398e1370f6237b6de9104aa0c42377c45e1e4275a4f544d1f1cf3a80cdd3c91` | 手机已平放桌面，人物闭眼静坐 |
| S08 | `082cc1c38ad7f81ebd982c68c9234daa744d35da476fb74ed521d8aeb75f70f1` | 三块色板与三个一致坐姿剪影，适合确定性亮度提示 |
| S09 | `b51e031d10ddc622459079fa4df77b52fa9e48a813203a645834a8cd93d420ef` | 车钥匙在置物盘中，人物朝沙发方向处于离开姿态 |
| S10 | `a8f85b8463f4443994e585409aeda160aa3ede74725c0bd643bcc96979f2bae4` | 暖米白结束板与三枚青绿圆点，无文字 |

- 上述记录不是 Grok 动态或最终 QA 批准，也不是外部审批或发布许可。
