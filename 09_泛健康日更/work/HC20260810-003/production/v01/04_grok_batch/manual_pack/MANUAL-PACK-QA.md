# HC20260810-003 v01 Grok 手动包 QA

## 结果

- 活动主题状态：`production`；批次：`HB20260810`。
- 分镜：`09_泛健康日更/work/HC20260810-003/production/v01/02_script_storyboard/storyboard-v01.md`，SHA-256 `6a9790399ad4353b5dd6aecd36b447cb895742258b0f7858e9523ae04f75d2b8`，按表头名解析并确认恰好 S01–S10。
- 正式首帧：仅消费 `03_first_frames/` 根目录中 10 张无字 PNG；全部 1080×1920、哈希唯一，拷贝后字节与源文件相同。
- 排除：未消费 `storyboard_with_copy/`、带字联系表、UI 预览或候选图。
- 提示词：10 条中英双语单行，S03、S07、S10 为 `deterministic_post` 且无需上传 Grok；其余动态镜头为 `grok_manual`，最小 Grok 源时长均不超过 5.8 秒。
- 合并 TXT：恰好 10 条非空提示词，相邻恰好一个空行，UTF-8 + LF。
- 必需动态源输出：7 个；每个必需源至少保留 2 个候选，并发为 1，每次生成后至少等待 30 秒。
- 双源镜头：无；每个动态镜头 required_output_count=1。

## 必需源质量证据

- 单期 Task 6：`09_泛健康日更/work/HC20260810-003/production/v01/05_qa/first-frame-qa-v01.md`，SHA-256 `3603709318e32a6ac07e8c864c607fbd879396350315b031e8c9fb9988a86694`。
- 批次 Task 6：`09_泛健康日更/work/HC20260810-B01-task6-qa/HC20260810-B01-first-frame-qa-v01.md`，SHA-256 `599af3788947838820f0c1b3f9ea834d7308d7114a7a9330439fe181952934c9`。
- 两份 QA 只是必需的当前源质量证据，**不是外部审批**、Task 8 事实批准、最终 QA 授权或发布许可。

## 视觉核对边界

- 审阅方式：`view_image`。
- 审阅日期：`2026-08-17`。
- 审阅者：`Codex Task 8 manual-pack review`。
- 带字联系表：`09_泛健康日更/work/HC20260810-003/production/v01/05_qa/storyboard-with-copy-contactsheet-v01.png`，SHA-256 `b469fb7c08d628092ac6ceadd5358c1f9da5ff08d5ad62baceb48a6b452151bc`；只用于理解文案/动作上下文，不会被复制。

| 镜号 | 正式首帧 SHA-256 | `view_image` 逐镜结论 |
|---|---|---|
| S01 | `32fad8b746573df906464e3acbc66adcf5a7e4d04c5a56cd10d828bcc4b6a358` | 人物坐在餐桌前低头看小餐盘，前景公用菜盘和盛菜勺清楚 |
| S02 | `05309d5c341f121a8c0a400f17f748bf1457bbecc3f36168632e841103c1d080` | 手持盛菜勺贴近桌面，公用盘和个人小盘位置稳定 |
| S03 | `301d09376129abe9858ac34f48e9f35683347f214d80de4dee8ada08f87e34db` | 左右静物分别为空碗和添加后餐盘，白色中线分隔 |
| S04 | `06a0cca336f9c9ac43b082c507c23b0088adabd85a5cc4cbc7cfda418f2fff45` | 叉子举在个人餐盘上方，适合向前少量后停手 |
| S05 | `802b42cc210425d087f335882ea36a37f8a26e2281304e26ccd208dc4105e960` | 人物双手扶一只米白靠垫站在沙发旁，物件单一 |
| S06 | `62d9fee71a209ce1cea3e39061749507a0c296454589c7f4a294f18b3e859ee2` | 盛菜勺中已有一小份豆腐豆角，空小盘位于落点 |
| S07 | `4b00b7752cae6bd2d3e9b8b921148a8e74e17642b7691894bea50460b5b80515` | 暖米白底为开放餐盘及餐具轮廓，无数字或刻度 |
| S08 | `aaaca833b87a55a4c4f8086ded09f959fa0e2730f07c8ccad4912d81eb976217` | 人物沿明确方向走向餐椅，桌上现有两只餐盘 |
| S09 | `bff8a986fb10938fe4f58d16c29ddc13e1d8ff6e92e3883da0cad3f99f4ec611` | 唯一叉子已平放，人物仍处于半起身相位，只允许轻微抬起后停住 |
| S10 | `c2a5f88d4c681ebf5a373561823705b7109c68faaf63374686c1bbcd91ee1f47` | 深青绿结束板含一个浅桃椭圆和一个青绿圆点，无文字 |

- 上述记录不是 Grok 动态或最终 QA 批准，也不是外部审批或发布许可。
