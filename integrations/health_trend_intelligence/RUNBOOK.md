# 健康趋势情报基础验证运行手册

## 不可越过的七项边界

> 1. **本计划不启动、不导入 MediaCrawler；下一阶段人工扫码采集另行计划。**
> 2. **不下载图片、视频或音频媒体。**
> 3. **不把热度或排名当作医学证据。**
> 4. **不自动发布，不生成可直接发布的结论。**
> 5. **Raw 满 30 天只生成到期报告，不自动删除。**
> 6. **合成的 10 条候选不是现实趋势榜，也不是医学结论或医学审核结果。**
> 7. **Task 7 校验/导入必须由操作者提供通过外部交接渠道获得的 `bundle-manifest.json` SHA-256；不得用待导入目录自我背书。**

以下全是离线、完全合成演练。命令从 MoneyPrinterTurbo 工作树根目录执行，且只写入系统临时目录；不得将 `$RunRoot` 或 `$DataRoot` 设为真实 `E:\MoneyPrinterTurbo-3期\health-trend-intelligence` 数据根。

## 1. 建立独立环境

```powershell
$RepoRoot = (Resolve-Path .).Path
$Integration = Join-Path $RepoRoot 'integrations\health_trend_intelligence'
$RunRoot = Join-Path $env:TEMP 'hti-foundation-synthetic-20260818'
$DataRoot = Join-Path $RunRoot 'data-root'
$InputRoot = Join-Path $RunRoot 'offline-inputs'
$FakeRepo = Join-Path $RunRoot 'fake-moneyprinter-repo'
$BatchId = 'HTI-20260818-01'

if (Test-Path -LiteralPath $RunRoot) { throw 'synthetic run root already exists; inspect it before choosing a new name' }
New-Item -ItemType Directory -Path $InputRoot, $FakeRepo | Out-Null
uv sync --project $Integration --locked
$env:HTI_HASH_KEY = 'hex:0000000000000000000000000000000000000000000000000000000000000000'
uv run --project $Integration hti init --root $DataRoot
```

`HTI_HASH_KEY` 上值只是可复现合成演练键，不能用于真实数据。

## 2. 运行 500 条合成端到端验证

该测试自行建立两个空根，生成 300 post + 200 comment，覆盖 dy/xhs、精确重复、近重复、非法计数和虚构 PII 形状值，并通过 Task 1–7 公开 API。

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'hti-task8-uv-cache'
$BaseTemp = Join-Path $env:TEMP 'hti-task8-pytest'
uv run --project $Integration pytest integrations/health_trend_intelligence/tests/test_foundation_e2e.py -q --basetemp $BaseTemp -p no:cacheprovider
```

通过只证明合成契约、可复现字节与边界成立，不证明现实热度或医学真实性。

## 3. 准备最小离线 Raw 演练输入

```powershell
$Utf8NoBom = [Text.UTF8Encoding]::new($false)

$DyPost = @{aweme_id='dy-synthetic-001'; title='完全合成睡眠记录'; desc=''; create_time=1776398400; user_id='dy-author-synthetic'; source_keyword='睡眠'; liked_count=10; comment_count=1; collected_count=2; share_count=1; hashtags=@('睡眠')}
$DyComment = @{comment_id='dy-comment-synthetic-001'; aweme_id='dy-synthetic-001'; create_time=1776402000; content='完全合成问题'; like_count=1}
$XhsPost = @{note_id='xhs-synthetic-001'; title='完全合成睡眠记录'; desc=''; time=1776398400000; creator_hash='xhs-author-synthetic'; source_keyword='睡眠'; liked_count=10; comment_count=1; collected_count=2; share_count=1; tag_list=@(@{name='睡眠'})}
$XhsComment = @{comment_id='xhs-comment-synthetic-001'; note_id='xhs-synthetic-001'; create_time=1776402000000; content='完全合成问题'; like_count=1}

[IO.File]::WriteAllText((Join-Path $InputRoot 'dy-posts.jsonl'), (($DyPost | ConvertTo-Json -Compress -Depth 5) + "`n"), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $InputRoot 'dy-comments.jsonl'), (($DyComment | ConvertTo-Json -Compress -Depth 5) + "`n"), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $InputRoot 'xhs-posts.jsonl'), (($XhsPost | ConvertTo-Json -Compress -Depth 5) + "`n"), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $InputRoot 'xhs-comments.jsonl'), (($XhsComment | ConvertTo-Json -Compress -Depth 5) + "`n"), $Utf8NoBom)

$Queries = @(
  @{query_id='dy-sleep-v1'; platform='dy'; keyword='睡眠'; window_start='2026-04-01T00:00:00+08:00'; window_end='2026-04-30T23:59:59+08:00'},
  @{query_id='xhs-sleep-v1'; platform='xhs'; keyword='睡眠'; window_start='2026-04-01T00:00:00+08:00'; window_end='2026-04-30T23:59:59+08:00'}
)
$Sources = @(
  @{path=(Join-Path $InputRoot 'dy-posts.jsonl'); platform='dy'; record_kind='posts'},
  @{path=(Join-Path $InputRoot 'dy-comments.jsonl'); platform='dy'; record_kind='comments'},
  @{path=(Join-Path $InputRoot 'xhs-posts.jsonl'); platform='xhs'; record_kind='posts'},
  @{path=(Join-Path $InputRoot 'xhs-comments.jsonl'); platform='xhs'; record_kind='comments'}
)
$QueriesPath = Join-Path $RunRoot 'queries.json'
$SourcesPath = Join-Path $RunRoot 'sources.json'
[IO.File]::WriteAllText($QueriesPath, ($Queries | ConvertTo-Json -Compress -Depth 5), $Utf8NoBom)
[IO.File]::WriteAllText($SourcesPath, ($Sources | ConvertTo-Json -Compress -Depth 5), $Utf8NoBom)
```

## 4. 离线 Raw 注册与 Curated

```powershell
uv run --project $Integration hti register --root $DataRoot --batch-id $BatchId --queries $QueriesPath --source $SourcesPath --snapshot-at '2026-04-20T12:00:00+08:00'
uv run --project $Integration hti verify-raw --root $DataRoot --batch-id $BatchId
uv run --project $Integration hti curate --root $DataRoot --batch-id $BatchId
uv run --project $Integration hti verify-curated --root $DataRoot --batch-id $BatchId
```

## 5. 准备合成 selection，构建并校验 Approved

本步复用仓库的 10 条合成测试模板，只模拟操作者 selection 文件；它不等于真实人工选题或医学审核。

```powershell
$CuratedManifest = Join-Path $DataRoot "curated\$BatchId\curated-manifest.json"
$SelectionTemplate = Join-Path $Integration 'tests\fixtures\approved-selection.json'
$SelectionPath = Join-Path $RunRoot 'synthetic-operator-selection.json'

uv run --project $Integration python -c 'import hashlib,sys; from pathlib import Path; from health_trend_intelligence.canonical import canonical_json_bytes,load_unique_json; value=load_unique_json(Path(sys.argv[1]).read_bytes()); value["batch_id"]=sys.argv[4]; value["curated_manifest_sha256"]=hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(); [candidate.__setitem__("risk_flags", ["medical_claim_unverified"]) for candidate in value["candidates"]]; Path(sys.argv[3]).write_bytes(canonical_json_bytes(value))' $SelectionTemplate $CuratedManifest $SelectionPath $BatchId

uv run --project $Integration hti build-approved --root $DataRoot --batch-id $BatchId --selection $SelectionPath
$ApprovedPath = Join-Path $DataRoot "approved\$BatchId"
```

从独立审批/交接渠道粘贴外部锚，不要从 `$ApprovedPath` 现场自行计算后冒充外部锚：

```powershell
$ExternalManifestSha256 = (Read-Host '粘贴外部交接的 bundle-manifest.json SHA-256').Trim().ToLowerInvariant()
if ($ExternalManifestSha256 -notmatch '^[0-9a-f]{64}$') { throw 'external manifest SHA-256 is invalid' }
uv run --project $Integration hti verify-approved --path $ApprovedPath --expected-manifest-sha256 $ExternalManifestSha256
```

## 6. Task 7 验证与单向导入临时假仓库

```powershell
$Importer = Join-Path $RepoRoot '09_泛健康日更\scripts\import_trend_intelligence.py'
.venv\Scripts\python.exe $Importer verify --source $ApprovedPath --expected-manifest-sha256 $ExternalManifestSha256
.venv\Scripts\python.exe $Importer import --source $ApprovedPath --repo-root $FakeRepo --expected-manifest-sha256 $ExternalManifestSha256
$ImportedPath = Join-Path $FakeRepo "09_泛健康日更\data\trend-intelligence\$BatchId\v01"
```

## 7. 生成只读边界报告

Task 8 基线与 240 个删除路径哈希是本计划的已审核锚。路径哈希算法是：Git `-z` 原始路径字节排序后，以 LF 连接并保留末尾 LF，再计算 SHA-256。

```powershell
$BoundaryVerifier = Join-Path $Integration 'scripts\verify_boundaries.py'
uv run --project $Integration python $BoundaryVerifier `
  --repo-root $RepoRoot `
  --media-crawler-root 'E:\MoneyPrinterTurbo-3期\MediaCrawler' `
  --raw-path (Join-Path $DataRoot 'raw') `
  --curated-path (Join-Path $DataRoot "curated\$BatchId") `
  --approved-path $ApprovedPath `
  --imported-path $ImportedPath `
  --external-manifest-sha256 $ExternalManifestSha256 `
  --task8-base 'f5f6d900b78cc583272d3f29bb1c6e3976b1109e' `
  --expected-media-crawler-commit 'd6f7c5bb906b6dac40ddf343ef9e26438a3de092' `
  --expected-manual-deletion-count 240 `
  --expected-manual-deletion-sha256 '391aa69f5238ab573788c248ced49824a51a5fa08b4c3c9477d9bbf2eda26db6'
```

只有所有必检项都能核验时，命令才输出一行 canonical UTF-8/LF JSON 并以 0 退出。缺路径、越界、无法检查、MediaCrawler 改动、锚不匹配或删除集改变都会非零失败，不会把 skip 记为 true。

## 8. Raw 30 天到期报告

```powershell
uv run --project $Integration hti retention-report --root $DataRoot --as-of '2026-05-21T12:00:00+08:00'
```

输出中的 `eligible_for_manual_deletion=true` 只是提示人工处置，不会删除 Raw。

## 9. 中断恢复与失败清理

- `curate` 在已证实的 checkpoint/chunk 上恢复；输入未变时可原命令重跑：

```powershell
uv run --project $Integration hti curate --root $DataRoot --batch-id $BatchId
uv run --project $Integration hti verify-curated --root $DataRoot --batch-id $BatchId
```

- `build-approved` 或 Task 7 import 失败后，先保留现场、记录安全错误码并检查 `*.work` / `.v01-import-*`；不要根据目录名盲删，不要覆盖已有 `v01`。
- 只有确认本次是临时合成演练、`$RunRoot` 位于 `$env:TEMP` 且路径精确相等时，才能删除整个演练根：

```powershell
$ExpectedSyntheticRoot = [IO.Path]::GetFullPath((Join-Path $env:TEMP 'hti-foundation-synthetic-20260818'))
if ([IO.Path]::GetFullPath($RunRoot) -ne $ExpectedSyntheticRoot) { throw 'refusing cleanup outside the exact synthetic root' }
Remove-Item -LiteralPath $ExpectedSyntheticRoot -Recurse -Force
Remove-Item Env:HTI_HASH_KEY -ErrorAction SilentlyContinue
```

真实数据根、不明 staging、Raw 或已发布 `v01` 不在此清理授权内。
