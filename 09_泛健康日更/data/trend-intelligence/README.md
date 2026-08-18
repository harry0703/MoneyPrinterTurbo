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
