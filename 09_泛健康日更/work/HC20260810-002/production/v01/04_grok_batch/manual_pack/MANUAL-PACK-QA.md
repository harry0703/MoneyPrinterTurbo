# HC20260810-002 v01 Grok 手动包 QA

## 结果

- 活动主题状态：`production`；批次：`HB20260810`。
- 分镜：`09_泛健康日更/work/HC20260810-002/production/v01/02_script_storyboard/storyboard-v01.md`，SHA-256 `88e152039b49bc4e2f3a345df5aaacabb309112f36eb1544756cbf9bc701ff1f`，按表头名解析并确认恰好 S01–S10。
- 正式首帧：仅消费 `03_first_frames/` 根目录中 10 张无字 PNG；全部 1080×1920、哈希唯一，拷贝后字节与源文件相同。
- 排除：未消费 `storyboard_with_copy/`、带字联系表、UI 预览或候选图。
- 提示词：10 条中英双语单行，S02、S09、S10 为 `deterministic_post` 且无需上传 Grok；其余动态镜头为 `grok_manual`，最小 Grok 源时长均不超过 5.8 秒。
- 合并 TXT：恰好 10 条非空提示词，相邻恰好一个空行，UTF-8 + LF。
- 必需动态源输出：7 个；每个必需源至少保留 2 个候选，并发为 1，每次生成后至少等待 30 秒。
- 双源镜头：无；每个动态镜头 required_output_count=1。

## 必需源质量证据

- 单期 Task 6：`09_泛健康日更/work/HC20260810-002/production/v01/05_qa/first-frame-qa-v01.md`，SHA-256 `7a8402bc54f652d0ab70185390637839571ea70a399460dc6d3c61a1e38b2fbe`。
- 批次 Task 6：`09_泛健康日更/work/HC20260810-B01-task6-qa/HC20260810-B01-first-frame-qa-v01.md`，SHA-256 `599af3788947838820f0c1b3f9ea834d7308d7114a7a9330439fe181952934c9`。
- 两份 QA 只是必需的当前源质量证据，**不是外部审批**、Task 8 事实批准、最终 QA 授权或发布许可。

## 视觉核对边界

- 审阅方式：`view_image`。
- 审阅日期：`2026-08-17`。
- 审阅者：`Codex Task 8 manual-pack review`。
- 带字联系表：`09_泛健康日更/work/HC20260810-002/production/v01/05_qa/storyboard-with-copy-contactsheet-v01.png`，SHA-256 `88e88601e50f1170b31d515c2469f34bac59fffa74d5c287d362ba4ef5b95133`；只用于理解文案/动作上下文，不会被复制。

| 镜号 | 正式首帧 SHA-256 | `view_image` 逐镜结论 |
|---|---|---|
| S01 | `c849d17c006db022a3b15a89897af3e5a301e54b21d30ce3d9e461b63d4b1c6e` | 左右分屏为同一人物和同类餐盒，左侧食物已到唇边、右侧筷子位于餐盒上方 |
| S02 | `e6059ff3ef10e7cd9c0e7c062ef7ed792f7575c37552ab42ea0013863b9e8dd4` | 左右餐盒静物板份量与构图对齐，中央青绿分隔明确 |
| S03 | `333ddb73f1db1e5874491469ea43911994fe92919c83e69a33440eab7f44d4b5` | 侧面坐姿人物用勺进餐，食物已到唇边，另一手扶餐盒 |
| S04 | `262f918aa070df29b4ace913fb544b26baa7ce389d03dac8b18ee1055e082e5f` | 勺子已平放桌面，手靠近勺柄，适合只做最终落稳与撤手 |
| S05 | `5b0959d59261470776f1fc05c7a232627f380d946e6e17bdce95c442568136f7` | 人物已坐在办公椅上，双手在腿上，黑色显示器无界面 |
| S06 | `f21bf18c41201bcaf38a2e54fcf2fe397aa8b5a4f3e983fb6d4ca1d190a26464` | 人物低头看餐盒，双手交叠在腿上，适合一次抬眼 |
| S07 | `aa06cd2a24c4e2c580eb1c1e4c9808b5bf68a8f2bcf057148e959dd4db1fe8ff` | 俯拍中叉子已平放餐盒旁，手指靠近叉柄 |
| S08 | `5458290eec7c0119317a116aba0ca67554220a8846ae6bbe2c3fee45d804af37` | 人物从走廊迈向办公椅，方向和落座目标清楚 |
| S09 | `a38c6d60bc0257428feb14fff2addc0943f59f04042c8dcde74370e682814023` | 剩余餐盘与空青绿椅构成静态边界板，无人物 |
| S10 | `c5e69bf794b63cd36ac941c0d08f35871ce9e8135e0b6540a7b44d4da7f28d23` | 暖米白结束板中央只有两条青绿暂停符号，无文字 |

- 上述记录不是 Grok 动态或最终 QA 批准，也不是外部审批或发布许可。
