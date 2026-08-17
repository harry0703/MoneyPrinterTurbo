# HC20260810-010 v01 Grok 手动生成指南

## 边界

- 本包是用户操作的浏览器扩展输入包，不包含已生成视频，也不代表外部审批或最终 QA。
- 动态镜头 S02、S04、S05、S08：使用 **Grok 浏览器扩展**手动上传 `09_泛健康日更/work/HC20260810-010/production/v01/04_grok_batch/manual_pack/01_first_frames/` 中的对应图片，并粘贴 `02_prompts/` 中的同号提示词。
- S01、S03、S06、S07、S09、S10 无需上传 Grok；它们标记为 `generation_mode=deterministic_post`，只按提示词在后期制作确定性动效。

## 本期操作参数

- 合并提示词：`09_泛健康日更/work/HC20260810-010/production/v01/04_grok_batch/manual_pack/HC20260810-010-v01-Grok-Automation-10条提示词.txt`。
- 首帧图片目录：`09_泛健康日更/work/HC20260810-010/production/v01/04_grok_batch/manual_pack/01_first_frames/`。
- Grok 保存文件夹名称：`HC20260810-010-S01-S10`。
- 动态源保存目录：`09_泛健康日更/work/HC20260810-010/production/v01/05_grok_videos/01_raw/`。
- 镜头总数：10。
- 必需动态源输出总数：5（已计入双源镜头的 A/B 增量）。
- 并发：1；任何时刻只运行一个生成任务。
- 每次生成后等待：至少 30 秒，再开始下一次生成。
- 每个必需动态源候选：至少 2 个；本期至少保存 10 个候选文件。
- 动态输出使用带 `takeNN` 的候选文件名；`NN` 从 `01` 起按候选递增。
- `deterministic_post` 不上传 Grok，使用表内固定后期输出名，不使用 `takeNN`。

## 目标时长 / 最低源时长

| 镜号 | generation_mode | 目标时长 / 最低源时长 | required_output_count | 输出命名 |
|---|---|---:|---:|---|
| S01 | `deterministic_post` | 4.00s / 0.00s | 0 | `HC20260810-010-v01-S01-deterministic-post.mp4` |
| S02 | `grok_manual` | 5.30s / 5.30s | 1 | `HC20260810-010-v01-S02-takeNN.mp4` |
| S03 | `deterministic_post` | 5.70s / 0.00s | 0 | `HC20260810-010-v01-S03-deterministic-post.mp4` |
| S04 | `grok_manual` | 5.70s / 5.70s | 1 | `HC20260810-010-v01-S04-takeNN.mp4` |
| S05 | `grok_manual` | 5.70s / 5.70s | 2 | `HC20260810-010-v01-S05A-takeNN.mp4`；`HC20260810-010-v01-S05B-takeNN.mp4` |
| S06 | `deterministic_post` | 5.70s / 0.00s | 0 | `HC20260810-010-v01-S06-deterministic-post.mp4` |
| S07 | `deterministic_post` | 5.70s / 0.00s | 0 | `HC20260810-010-v01-S07-deterministic-post.mp4` |
| S08 | `grok_manual` | 5.70s / 5.70s | 1 | `HC20260810-010-v01-S08-takeNN.mp4` |
| S09 | `deterministic_post` | 6.70s / 0.00s | 0 | `HC20260810-010-v01-S09-deterministic-post.mp4` |
| S10 | `deterministic_post` | 6.80s / 0.00s | 0 | `HC20260810-010-v01-S10-deterministic-post.mp4` |

## 双源镜头

- S05：required_output_count=2；Source A 保存为 `HC20260810-010-v01-S05A-takeNN.mp4`；Source B 保存为 `HC20260810-010-v01-S05B-takeNN.mp4`；两条独立源只在后期硬切；不得在单条 clip 内制作硬切或分屏。

## 手动操作

1. 按 S01 到 S10 顺序处理；动态镜头的无字首帧是唯一构图参考。
2. 每个动态镜头只执行提示词中的一个低幅动作，不生成文字、Logo、水印、纸张、纸笔、本册或 UI。
3. 手动保存动态输出到上述 `05_grok_videos/01_raw/` 仓库完整路径，使用 `MANIFEST.csv` 的 `output_template` 文件名；双源镜头分别生成并分别保存 A/B。
4. 保持 1.0 倍速；禁止慢动作、循环、插帧或模型生成 UI。任何补时只按锁定分镜的 `extension_strategy` 使用末帧短停或确定性叠加。
5. 生成完成不等于通过质检；后续必须保留原文件并逐镜检查首、中、尾帧。
