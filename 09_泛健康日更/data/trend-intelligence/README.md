# 趋势情报导入目录

这里只保存已经人工批准、且经外部 `bundle-manifest.json` SHA-256 锚验证的交换包。导入目录固定为 `<batch-id>/v01/`，已存在的版本不会被覆盖。

运行校验：

```powershell
.venv\Scripts\python.exe 09_泛健康日更\scripts\import_trend_intelligence.py verify --source <approved-dir> --expected-manifest-sha256 <64位小写十六进制>
```

运行导入：

```powershell
.venv\Scripts\python.exe 09_泛健康日更\scripts\import_trend_intelligence.py import --source <approved-dir> --repo-root <MoneyPrinterTurbo根目录> --expected-manifest-sha256 <64位小写十六进制>
```

该入口不读取 Raw/Curated，不启动 MediaCrawler，不下载媒体，不自动生成或发布内容。交换包只是选题情报，不是医学事实来源或可直接发布的脚本。

## 导入事务与恢复边界

导入器会先在 batch 目录下创建唯一的 `.v01-import-*` 临时目录，按“两个 payload 在先、manifest 在后”写入并完整复核，然后在同一父目录中以不覆盖重命名发布为 `v01`。因此写入或复核失败不会占用正式 `v01`，同一交换包可以直接重试。

导入器只自动清理当前调用自己创建、目录身份未变，且内容只是预期三文件子集的临时目录。任何既有 `v01`、未知 `.v01-import-*` 目录、身份已变的目录或含额外文件的目录都不会被自动删除或覆盖，需要操作者先隔离并人工调查。不得仅因目录名类似 staging 就删除它。
