# 一般生活方式 50 集库存

本目录是账号“生活节奏看得见”的独立一般生活方式系列库存，内容档案固定为 `general_wellness_uncredentialed`。旧的医疗批次不作为本系列的活动批次，也不得被覆盖、推进或重命名。

## 权威来源

- `series-inventory-v01.json` 的 50 个标题逐字取自 `docs/superpowers/specs/2026-08-10-50-episode-general-wellness-design.md`。其中“3 件事”“3 分钟”“连续 7 天”等空格属于批准规格正文的一部分。
- `batch-01-inputs.json` 的 10 个类别与标题逐字取自 Task 2 实施简报。简报中的“3件事”“3分钟”“连续7天”没有空格，因此 Batch 01 输入有意保留该写法，不据库存标题擅自归一化。
- 第 11—50 集的英文 `category` 是从批准标题派生的内部稳定标识；标题、批次和顺序仍以批准规格为准。

## 旧批次不可变证据

- 路径：`09_泛健康日更/data/00_十主题滚动库/active-batch.json`
- 创建本目录前 SHA-256：`36777a54b574997a1364b67ee624ff8f57f238f3533a879db2ee07ab8b7c847e`
- 创建独立 Batch 01 后 SHA-256：`36777a54b574997a1364b67ee624ff8f57f238f3533a879db2ee07ab8b7c847e`（与创建前一致）
- 批次：`HB20260809`
- 创建前状态：`production=1`、`medical_review_pending=1`、`research_pending=8`
- 创建后状态：`production=1`、`medical_review_pending=1`、`research_pending=8`（未推进）
- mutation/journal/lock 检查：未发现

## Batch 01

Batch 01 由项目 CLI 从显式主题输入创建，日期为 `20260810`。它包含 `HC20260810-001` 至 `HC20260810-010`，全部从 `research_pending` 开始；发布策略固定为四平台人工提交，不包含自动发布。根活动批次与版本化活动批次 SHA-256 均为 `a9b27cf2437e4660f1d182ad57b526338fa1ef24a7b7ea66a8574aeea2b4b780`，且 `current-batch-ref.json` 的两个哈希引用均已核对。
