# 健康趋势情报数据基础 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个与 MediaCrawler 和 MoneyPrinterTurbo 运行环境隔离、可复核、可断点恢复的健康趋势数据基础层，把抖音/小红书离线 JSONL 快照转换为脱敏去重的 Curated 数据，并只允许人工批准的版本化交换包进入 MoneyPrinterTurbo。

**Architecture:** 版本化代码位于 MoneyPrinterTurbo 仓库的 `integrations/health_trend_intelligence/`，但使用独立的 Python 3.11/uv 环境；运行数据根目录固定为仓库外的 `E:\MoneyPrinterTurbo-3期\health-trend-intelligence`。系统只离线读取 MediaCrawler 生成的 JSONL，不导入或修改 MediaCrawler，不登录、不采集、不下载媒体；Raw、Curated、Approved 通过严格 schema、哈希清单、最终完成标记和人工状态单向流动。MoneyPrinterTurbo 只用标准库验证并复制 Approved 交换包，不读取 Raw/Curated。

**Tech Stack:** Python 3.11、uv 0.11.x、Pydantic 2.x、Typer、pytest、Ruff、JSONL、SHA-256/HMAC-SHA-256；MoneyPrinterTurbo 消费端仅使用 Python 标准库。

**Spec:** `docs/superpowers/specs/2026-08-18-media-intelligence-premium-video-design.md`

## Global Constraints

- 本计划只覆盖设计第 11 节第 2 项“情报数据基础子项目”；不登录平台、不启动采集、不评分、不生成 Top 10、不制作视频、不发布。
- MediaCrawler 固定为 `E:\MoneyPrinterTurbo-3期\MediaCrawler`、官方源码 commit `d6f7c5bb906b6dac40ddf343ef9e26438a3de092`；不得修改其源码、配置、依赖、浏览器 profile 或 `NON-COMMERCIAL LEARNING LICENSE 1.1`。
- 当前用途是用户声明的非商业学习研究；所有文档和第三方声明必须保留该许可边界。
- 独立运行数据根目录固定为 `E:\MoneyPrinterTurbo-3期\health-trend-intelligence`，包含 `raw/`、`curated/`、`approved/`；三者全部位于 MoneyPrinterTurbo Git 仓库外。
- `raw/` 永不进入 Git，默认保留 30 天；本计划只生成到期报告，不自动删除原始数据。
- 首轮平台只允许 `dy`（抖音）和 `xhs`（小红书）；未知平台或未知字段语义失败关闭。
- Cookie、手机号、验证码、代理密钥、API 密钥、浏览器 profile、`xsec_token`、原始用户 ID、昵称、头像和媒体 URL 不得进入 Curated、Approved、Git、日志、截图或报告。
- `ENABLE_GET_MEIDAS` 的语义必须保持为 `False`；本计划所有入口拒绝视频、音频、图片及其下载路径。
- 公开帖子和评论仅作统计研究，`media_reuse_allowed` 固定为 `false`，`license_status` 默认固定为 `unknown`。
- 只有 schema 版本、batch ID、生成时间、输入哈希、人工批准状态和文件清单全部有效的 Approved 包可进入 `09_泛健康日更/data/trend-intelligence/<batch-id>/v01/`。
- MoneyPrinterTurbo 不得读取 Raw/Curated；Approved 包不得含受限原链接、账号身份、媒体或凭据。
- 任何批次或合同改动都生成新 batch/version；禁止覆盖已存在的 Raw、Curated、Approved 或 MoneyPrinterTurbo 导入目录。
- 240 个 Grok 手动包删除记录仍由用户裁决；本计划及其测试不得恢复、暂存、提交、删除或改写这些路径。
- 所有测试使用合成数据；不得把真实平台内容、真实账号、Cookie、手机号或个人信息写入 fixture。

---

## File and Interface Map

| Path | Responsibility |
| --- | --- |
| `integrations/health_trend_intelligence/pyproject.toml` | 独立依赖、CLI 入口、pytest/Ruff 配置 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/models.py` | Raw 注册、Curated、Approved、manifest 的严格 Pydantic 模型 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/canonical.py` | NFC、确定性 JSON/JSONL、SHA-256 与唯一键 JSON 解析 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/storage.py` | 外部数据根、reparse/path traversal 防护、独占写入与完成标记 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/batch.py` | batch 注册、源文件绑定、查询清单、30 天到期报告 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/privacy.py` | HMAC 标识、文本脱敏、隐私/凭据字段递归扫描 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/adapters/mediacrawler.py` | 抖音/小红书 JSONL 到统一记录的离线字段映射 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/dedup.py` | 同源合并、标准化文本指纹、SimHash 近重复聚类 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/curation.py` | 分源 chunk、checkpoint、断点续跑、Curated finalize |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/exchange.py` | 人工批准输入验证、Approved 包构建与验证 |
| `integrations/health_trend_intelligence/src/health_trend_intelligence/cli.py` | `init/register/curate/verify/retention-report/build-approved` 命令 |
| `app/services/health_trend_exchange.py` | MoneyPrinterTurbo 标准库 Approved 包验证与导入 |
| `09_泛健康日更/scripts/import_trend_intelligence.py` | 人工调用的 `verify/import` CLI，不自动触发生产 |
| `test/services/test_health_trend_exchange.py` | MoneyPrinterTurbo 消费边界测试 |

### Task 1: 独立项目骨架与许可边界

**Files:**
- Create: `integrations/health_trend_intelligence/pyproject.toml`
- Create: `integrations/health_trend_intelligence/.python-version`
- Create: `integrations/health_trend_intelligence/.gitignore`
- Create: `integrations/health_trend_intelligence/README.md`
- Create: `integrations/health_trend_intelligence/THIRD_PARTY_NOTICES.md`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/__init__.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/__main__.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/cli.py`
- Create: `integrations/health_trend_intelligence/tests/test_project_contract.py`
- Create: `integrations/health_trend_intelligence/uv.lock`

**Interfaces:**
- Consumes: design spec and fixed MediaCrawler path/commit only; no Python import from MediaCrawler.
- Produces: console command `hti`, package version `0.1.0`, and `cli.app: typer.Typer` for later tasks.

- [ ] **Step 1: Write the failing project-contract tests**

```python
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]

def test_runtime_is_independent_and_pinned_to_python_311() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["requires-python"] == ">=3.11,<3.12"
    assert project["project"]["scripts"] == {"hti": "health_trend_intelligence.cli:app"}
    assert "mediacrawler" not in {d.lower() for d in project["project"]["dependencies"]}
    assert (ROOT / ".python-version").read_text("utf-8") == "3.11\n"

def test_notice_binds_fixed_upstream_and_noncommercial_license() -> None:
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    assert "d6f7c5bb906b6dac40ddf343ef9e26438a3de092" in notice
    assert "NON-COMMERCIAL LEARNING LICENSE 1.1" in notice
    assert r"E:\MoneyPrinterTurbo-3期\MediaCrawler" in notice

def test_runtime_data_and_credentials_are_git_ignored() -> None:
    rules = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert {".venv/", ".env", "raw/", "curated/", "approved/", "*_user_data_dir/"} <= set(rules)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_project_contract.py -q`

Expected: FAIL because the independent project files do not exist.

- [ ] **Step 3: Create the independent project and minimal CLI**

Use this dependency contract in `pyproject.toml`:

```toml
[project]
name = "health-trend-intelligence"
version = "0.1.0"
requires-python = ">=3.11,<3.12"
dependencies = ["pydantic>=2.13.4,<3", "typer>=0.12.3,<1"]

[project.scripts]
hti = "health_trend_intelligence.cli:app"

[dependency-groups]
dev = ["pytest>=8.4,<9", "ruff>=0.12,<1"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

Minimal `cli.py`:

```python
import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

@app.command()
def version() -> None:
    typer.echo("health-trend-intelligence 0.1.0")
```

`README.md` must state that this phase only processes synthetic/offline JSONL and never launches MediaCrawler. `THIRD_PARTY_NOTICES.md` must record the exact commit and license without copying upstream code.

- [ ] **Step 4: Lock dependencies and run GREEN checks**

Run:

```powershell
uv lock --project integrations/health_trend_intelligence
uv sync --project integrations/health_trend_intelligence --group dev
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
uv run --project integrations/health_trend_intelligence hti version
```

Expected: tests and Ruff PASS; CLI prints exactly `health-trend-intelligence 0.1.0`.

- [ ] **Step 5: Commit the isolated foundation skeleton**

```powershell
git add integrations/health_trend_intelligence
git commit -m "feat: scaffold isolated health trend intelligence"
```

### Task 2: 严格 schema、唯一键 JSON 与确定性序列化

**Files:**
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/models.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/canonical.py`
- Create: `integrations/health_trend_intelligence/tests/test_models.py`
- Create: `integrations/health_trend_intelligence/tests/test_canonical.py`

**Interfaces:**
- Consumes: Python 3.11 and Pydantic 2.x from Task 1.
- Produces: `BatchManifest`, `QuerySpec`, `SourceFileBinding`, `CuratedPost`, `CuratedComment`, `canonical_json_bytes()`, `canonical_jsonl_bytes()`, `sha256_bytes()`, and `load_unique_json()`.
- Ownership boundary: Task 6 adds `ApprovedCandidate`, `ApprovedSelection`, and the `ApprovedExchangeResult` dataclass after Curated verification exists; Task 2 must not invent an earlier `ApprovedExchange` schema.

- [ ] **Step 1: Write failing strict-schema tests**

Tests must prove:

```python
def test_curated_post_rejects_extra_fields_and_negative_counts() -> None:
    with pytest.raises(ValidationError):
        CuratedPost.model_validate({**VALID_POST, "nickname": "不得保留"})
    with pytest.raises(ValidationError):
        CuratedPost.model_validate({**VALID_POST, "like_count": -1})

def test_manifest_rejects_naive_datetime_and_bad_batch_id() -> None:
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({**VALID_MANIFEST, "batch_id": "batch1"})
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({**VALID_MANIFEST, "snapshot_at": "2026-08-18T12:00:00"})

def test_unique_json_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_unique_json(b'{"schema":"a","schema":"b"}')
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_models.py integrations/health_trend_intelligence/tests/test_canonical.py -q`

Expected: FAIL because the models and serialization functions are missing.

- [ ] **Step 3: Implement exact models and canonical bytes**

Use `ConfigDict(extra="forbid", strict=True, frozen=True)` for every public model. Required model fields:

```python
class QuerySpec(StrictModel):
    query_id: str
    platform: Literal["dy", "xhs"]
    keyword: str
    window_start: AwareDatetime
    window_end: AwareDatetime

class SourceFileBinding(StrictModel):
    relative_path: str
    record_kind: Literal["posts", "comments"]
    platform: Literal["dy", "xhs"]
    sha256: str
    bytes: int
    records: int

class BatchManifest(StrictModel):
    schema: Literal["health_trend_batch.v1"]
    batch_id: str
    created_at: AwareDatetime
    snapshot_at: AwareDatetime
    media_crawler_commit: Literal["d6f7c5bb906b6dac40ddf343ef9e26438a3de092"]
    query_manifest_sha256: str
    sources: tuple[SourceFileBinding, ...]
    state: Literal["raw_registered", "curating", "curated_ready", "approved_ready"]

class CuratedPost(StrictModel):
    schema: Literal["health_trend_post.v1"]
    platform: Literal["dy", "xhs"]
    source_post_key: str
    source_url_restricted: str
    published_at: AwareDatetime
    snapshot_at: AwareDatetime
    age_hours: float
    author_key_hash: str
    follower_band: str | None
    title_redacted: str
    topic_terms: tuple[str, ...]
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    collect_count: int | None
    share_count: int | None
    query_ids: tuple[str, ...]
    best_rank_in_query: int
    duplicate_cluster_id: str
    ad_signal: bool
    suspicious_engagement_signal: bool
    medical_risk_signal: bool
    media_reuse_allowed: Literal[False]
    license_status: Literal["unknown"]

class CuratedComment(StrictModel):
    schema: Literal["health_trend_comment.v1"]
    comment_key_hash: str
    source_post_key: str
    created_at: AwareDatetime
    text_redacted: str
    like_count: int
    need_cluster: str | None
    objection_cluster: str | None
    question_cluster: str | None
    contains_personal_data: bool
    excluded_reason: str | None
```

Add `field_validator` rules for `HTI-YYYYMMDD-NN`, lowercase 64-character SHA-256, non-empty normalized text, timezone-aware dates, nonnegative counts, and `window_start <= window_end <= snapshot_at`. `canonical_json_bytes()` must recursively NFC-normalize strings, sort object keys, use UTF-8/LF, compact separators, reject NaN/Infinity, and end with one newline. `canonical_jsonl_bytes()` must sort records by caller-supplied stable key and serialize one object per line.

- [ ] **Step 4: Run model, serialization, and full project tests**

Run:

```powershell
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_models.py integrations/health_trend_intelligence/tests/test_canonical.py -q
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
```

Expected: PASS with deterministic byte assertions on Windows.

- [ ] **Step 5: Commit schemas and canonical format**

```powershell
git add integrations/health_trend_intelligence/src/health_trend_intelligence integrations/health_trend_intelligence/tests
git commit -m "feat: define health trend data contracts"
```

### Task 3: 外部数据根、路径防护与 Raw 批次注册

**Files:**
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/storage.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/batch.py`
- Create: `integrations/health_trend_intelligence/tests/test_storage.py`
- Create: `integrations/health_trend_intelligence/tests/test_batch.py`
- Modify: `integrations/health_trend_intelligence/src/health_trend_intelligence/cli.py`

**Interfaces:**
- Consumes: Task 2 canonical serializers and `BatchManifest`.
- Produces: `DataLayout.from_root(Path)`, `register_batch(layout, batch_id, query_manifest, sources, snapshot_at) -> BatchManifest`, `verify_raw_batch(layout, batch_id) -> BatchManifest`, and `build_retention_report(layout, as_of) -> tuple[RetentionEntry, ...]`.

Define the immutable retention result in `batch.py` so later code does not infer deletion policy:

```python
@dataclass(frozen=True, slots=True)
class RetentionEntry:
    batch_id: str
    snapshot_at: datetime
    age_days: int
    eligible_for_manual_deletion: bool
```

- [ ] **Step 1: Write failing storage and registration tests**

Cover all of these cases with temporary directories:

```python
def test_layout_creates_only_three_data_layers(tmp_path: Path) -> None:
    layout = DataLayout.from_root(tmp_path / "health-trend-intelligence")
    layout.initialize()
    assert sorted(p.name for p in layout.root.iterdir()) == ["approved", "curated", "raw"]

def test_register_is_no_overwrite_and_binds_exact_source_bytes(tmp_path: Path) -> None:
    manifest = register_fixture_batch(tmp_path)
    assert manifest.state == "raw_registered"
    assert all(binding.sha256 == hash_registered_file(binding) for binding in manifest.sources)
    with pytest.raises(FileExistsError):
        register_fixture_batch(tmp_path)

def test_registration_rejects_media_credentials_and_reparse(tmp_path: Path) -> None:
    for forbidden in ("clip.mp4", "cookies.json", "xhs_user_data_dir/profile.json"):
        with pytest.raises(BatchInputError):
            register_source_named(tmp_path, forbidden)
```

On Windows add a junction/symlink test that expects rejection before any destination is created. Skip only when the current account cannot create the link.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_storage.py integrations/health_trend_intelligence/tests/test_batch.py -q`

Expected: FAIL because `DataLayout` and registration do not exist.

- [ ] **Step 3: Implement guarded storage and immutable registration**

`DataLayout.from_root()` must resolve and require the exact configured root, reject `..`, symlinks, junctions and other reparse components, and expose only `raw`, `curated`, and `approved`. `register_batch()` must:

1. Validate batch ID and a canonical query manifest containing 1–50 `QuerySpec` items.
2. Accept only UTF-8 JSONL files declared as `dy/xhs` and `posts/comments`.
3. Reject file names/keys matching `cookie|token|secret|phone|mobile|profile|proxy|media|video|image|audio` case-insensitively.
4. Copy each source with exclusive create into `raw/<batch-id>/inputs/`, fsync it, then bind relative path/bytes/SHA-256/line count.
5. Write `query-manifest.json`, then `batch-manifest.json` last; never rewrite an existing batch.
6. Re-open and verify every byte before returning.

`build_retention_report()` returns entries older than 30 days but never deletes them. Add CLI commands:

```text
hti init --root <absolute-root>
hti register --root <root> --batch-id HTI-20260818-01 --queries queries.json --source source-spec.json --snapshot-at 2026-08-18T15:30:00+08:00
hti verify-raw --root <root> --batch-id HTI-20260818-01
hti retention-report --root <root> --as-of 2026-09-18T00:00:00+08:00
```

Commands return exit 0 on verified success, exit 3 on invalid input/state, never echo record contents, secrets, or absolute source paths.

- [ ] **Step 4: Run focused tests and CLI smoke checks**

Run:

```powershell
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_storage.py integrations/health_trend_intelligence/tests/test_batch.py -q
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
```

Expected: all PASS; failed registration leaves no consumable `batch-manifest.json`.

- [ ] **Step 5: Commit immutable Raw registration**

```powershell
git add integrations/health_trend_intelligence
git commit -m "feat: register immutable trend data batches"
```

### Task 4: MediaCrawler 离线适配与二次脱敏

**Files:**
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/privacy.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/adapters/__init__.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/adapters/mediacrawler.py`
- Create: `integrations/health_trend_intelligence/tests/fixtures/dy_posts.jsonl`
- Create: `integrations/health_trend_intelligence/tests/fixtures/dy_comments.jsonl`
- Create: `integrations/health_trend_intelligence/tests/fixtures/xhs_posts.jsonl`
- Create: `integrations/health_trend_intelligence/tests/fixtures/xhs_comments.jsonl`
- Create: `integrations/health_trend_intelligence/tests/test_privacy.py`
- Create: `integrations/health_trend_intelligence/tests/test_mediacrawler_adapter.py`

**Interfaces:**
- Consumes: registered JSONL, platform, `query_id`, rank, snapshot time, and `HTI_HASH_KEY` from environment.
- Produces: `PrivacyHasher`, `redact_text()`, `assert_no_sensitive_data()`, `MediaCrawlerContext`, `map_post(row, context, hasher) -> CuratedPostDraft`, and `map_comment(row, context, hasher) -> CuratedComment`.

Define these exact adapter-only immutable types in `adapters/mediacrawler.py`:

```python
@dataclass(frozen=True, slots=True)
class MediaCrawlerContext:
    platform: Literal["dy", "xhs"]
    query_id: str
    rank_in_query: int
    snapshot_at: datetime

@dataclass(frozen=True, slots=True)
class CuratedPostDraft:
    platform: Literal["dy", "xhs"]
    source_post_key: str
    source_url_restricted: str
    published_at: datetime
    snapshot_at: datetime
    author_key_hash: str
    follower_band: str | None
    title_redacted: str
    topic_terms: tuple[str, ...]
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    collect_count: int | None
    share_count: int | None
    query_id: str
    rank_in_query: int
    ad_signal: bool
    suspicious_engagement_signal: bool
    medical_risk_signal: bool
    media_reuse_allowed: Literal[False]
    license_status: Literal["unknown"]
```

- [ ] **Step 1: Write failing field-map and privacy tests**

Synthetic fixtures must include phone, WeChat wording, `@handle`, URL query token, nickname and raw user ID so tests prove they are removed:

```python
def test_xhs_mapping_never_propagates_tokens_identity_or_media() -> None:
    draft = map_post(XHS_ROW, XHS_CONTEXT, PrivacyHasher(b"test-key"))
    encoded = canonical_json_bytes(draft.model_dump(mode="json")).decode("utf-8")
    for forbidden in ("xsec_token", "nickname", "user_id", "image_list", "video_url", "13800138000"):
        assert forbidden not in encoded
    assert draft.source_url_restricted == "https://www.xiaohongshu.com/explore/note-synthetic-001"
    assert draft.media_reuse_allowed is False
    assert draft.license_status == "unknown"

def test_hashes_are_stable_with_key_and_change_with_key() -> None:
    assert PrivacyHasher(b"a").identifier("same") == PrivacyHasher(b"a").identifier("same")
    assert PrivacyHasher(b"a").identifier("same") != PrivacyHasher(b"b").identifier("same")

def test_missing_hash_key_fails_without_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTI_HASH_KEY", raising=False)
    with pytest.raises(PrivacyConfigurationError):
        PrivacyHasher.from_environment()
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_privacy.py integrations/health_trend_intelligence/tests/test_mediacrawler_adapter.py -q`

Expected: FAIL because the privacy and adapter modules are absent.

- [ ] **Step 3: Implement conservative redaction and exact platform mappings**

`PrivacyHasher.identifier()` uses HMAC-SHA-256 with domain separation (`b"author\0"`, `b"comment\0"`, `b"post\0"`). The key is read only from `HTI_HASH_KEY`, must decode to at least 32 bytes, and is never stored or logged.

Map fields exactly:

| Unified | Douyin JSONL | Xiaohongshu JSONL |
| --- | --- | --- |
| post id input | `aweme_id` | `note_id` |
| title input | `title` then `desc` | `title` + `desc` |
| published | `create_time` Unix seconds | `time` Unix milliseconds |
| author input | `user_id` or `sec_uid` or `creator_hash` | `creator_hash` or `user_id` |
| likes | `liked_count` | `liked_count` |
| collects | `collected_count` | `collected_count` |
| comments | `comment_count` | `comment_count` |
| shares | `share_count` | `share_count` |
| query | `source_keyword` mapped through the registered query table | same |

Do not invent view counts or follower counts; map unavailable values to `None`. Numeric strings such as `"1.2万"` must be parsed deterministically, while unknown forms fail the record into quarantine instead of becoming zero. Epoch values convert to an explicit `+08:00` aware datetime and any `published_at > snapshot_at` record is quarantined. `topic_terms` come only from the registered query keyword plus normalized platform tags. `ad_signal` and `medical_risk_signal` use versioned, tested phrase lists; `suspicious_engagement_signal` remains `false` at adapter time and is recomputed from batch distributions during curation. `redact_text()` removes phone/email/URL query strings/WeChat IDs/`@handle`, collapses whitespace, records `contains_personal_data`, and never logs original text. `assert_no_sensitive_data()` recursively rejects forbidden keys and credential-shaped values.

- [ ] **Step 4: Run privacy, adapter, and full tests**

Run:

```powershell
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_privacy.py integrations/health_trend_intelligence/tests/test_mediacrawler_adapter.py -q
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
```

Expected: PASS; a captured log assertion proves no fixture text or identifier appears in logs.

- [ ] **Step 5: Commit offline adapters and privacy guard**

```powershell
git add integrations/health_trend_intelligence
git commit -m "feat: normalize and redact MediaCrawler snapshots"
```

### Task 5: 确定性去重、chunk checkpoint 与 Curated finalize

**Files:**
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/dedup.py`
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/curation.py`
- Create: `integrations/health_trend_intelligence/tests/test_dedup.py`
- Create: `integrations/health_trend_intelligence/tests/test_curation.py`
- Modify: `integrations/health_trend_intelligence/src/health_trend_intelligence/models.py`
- Modify: `integrations/health_trend_intelligence/src/health_trend_intelligence/cli.py`

**Interfaces:**
- Consumes: Task 3 immutable Raw manifest and Task 4 draft mappings.
- Produces: `simhash64()`, `cluster_duplicates()`, `curate_batch(layout, batch_id, hasher, event_hook=None) -> CuratedBatchResult`, `verify_curated_batch(layout, batch_id) -> CuratedBatchResult`, and resumable `CurationCheckpoint`.

Define the public result and checkpoint contracts in `curation.py`:

```python
@dataclass(frozen=True, slots=True)
class CurationCheckpoint:
    schema: Literal["health_trend_checkpoint.v1"]
    raw_manifest_sha256: str
    completed_source_sha256: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CuratedBatchResult:
    path: Path
    manifest_sha256: str
    raw_records: int
    curated_posts: int
    curated_comments: int
    duplicate_records: int
    quarantined_records: int
    pii_redacted_records: int

@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    schema: Literal["health_trend_quarantine.v1"]
    source_sha256: str
    line_number: int
    reason_code: str
    platform: Literal["dy", "xhs"]
```

- [ ] **Step 1: Write failing duplicate and interruption tests**

Required tests:

```python
def test_same_post_seen_by_two_queries_merges_without_double_counting() -> None:
    result = curate_synthetic_rows([POST_QUERY_A, POST_QUERY_B])
    assert len(result.posts) == 1
    assert result.posts[0].query_ids == ("dy-sleep-01", "dy-sleep-02")
    assert result.posts[0].best_rank_in_query == 2

def test_near_duplicate_titles_share_deterministic_cluster() -> None:
    a = "午后总犯困，先看昨晚睡眠和午餐节奏"
    b = "午后总犯困 先看昨晚睡眠、午餐节奏"
    assert hamming_distance(simhash64(a), simhash64(b)) <= 3

def test_resume_after_chunk_interrupt_is_byte_identical(tmp_path: Path) -> None:
    with pytest.raises(InjectedInterruption):
        curate_fixture_batch(tmp_path / "interrupted", event_hook=raise_after_first_chunk)
    resumed = curate_fixture_batch(tmp_path / "interrupted")
    clean = curate_fixture_batch(tmp_path / "clean")
    assert tree_sha256(resumed.path) == tree_sha256(clean.path)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_dedup.py integrations/health_trend_intelligence/tests/test_curation.py -q`

Expected: FAIL because deduplication and curation do not exist.

- [ ] **Step 3: Implement deterministic deduplication and resumable curation**

Algorithm contract:

1. Normalize titles to NFC lowercase CJK/alphanumeric tokens and character trigrams.
2. Build 64-bit SimHash from SHA-256-derived trigram weights; use four 16-bit buckets and union-find; only merge candidates with Hamming distance `<= 3`.
3. Same `(platform, source_post_key)` always merges; keep latest snapshot metrics, union/sort query IDs, and minimum positive query rank.
4. `duplicate_cluster_id` is `sha256("hti-duplicate-v1\0" + sorted member keys)`.
5. Comments deduplicate by `comment_key_hash`; conflicting text for the same key fails the batch.
6. `suspicious_engagement_signal` is recomputed only when the platform/count fields are comparable; impossible comparisons remain `false` and add the aggregate warning `suspicious_signal_unavailable` to `curated-manifest.json`.

Resume contract:

- Process each bound source into `curated/<batch-id>.work/chunks/<source-sha256>/`.
- A chunk is consumable only when its `chunk-manifest.json` is written last and binds exact bytes/counts.
- `checkpoint.json` stores the raw manifest SHA and sorted completed source SHAs; write via temp file + `os.replace` + fsync.
- On restart, reverify every completed chunk. Unknown files, changed source bytes or changed query manifest fail closed.
- Finalization deterministically merges all chunks, writes `posts.jsonl`, `comments.jsonl`, `quarantine.jsonl`, `curated-manifest.json`, and writes `READY.json` last.
- Move `.work` to `curated/<batch-id>/` only when the destination does not exist; never overwrite.

`CuratedBatchResult` exposes path, input/output counts, duplicate count, quarantined count, PII-redacted count and manifest SHA. Add commands `hti curate` and `hti verify-curated`; errors print only batch/file identifiers and reason codes.

- [ ] **Step 4: Run interruption, reproducibility, and project suites**

Run:

```powershell
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_dedup.py integrations/health_trend_intelligence/tests/test_curation.py -q
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
```

Expected: PASS; two independent builds from identical synthetic Raw trees are byte-identical.

- [ ] **Step 5: Commit the Curated pipeline**

```powershell
git add integrations/health_trend_intelligence
git commit -m "feat: curate resumable deduplicated trend data"
```

### Task 6: 人工批准的 Approved 交换包

**Files:**
- Create: `integrations/health_trend_intelligence/src/health_trend_intelligence/exchange.py`
- Create: `integrations/health_trend_intelligence/tests/fixtures/approved-selection.json`
- Create: `integrations/health_trend_intelligence/tests/test_exchange.py`
- Modify: `integrations/health_trend_intelligence/src/health_trend_intelligence/models.py`
- Modify: `integrations/health_trend_intelligence/src/health_trend_intelligence/cli.py`

**Interfaces:**
- Consumes: verified Curated manifest and a separate human-authored selection file.
- Produces: `build_approved_exchange(layout, batch_id, selection_path) -> ApprovedExchangeResult` and `verify_approved_exchange(path, expected_manifest_sha256=None) -> ApprovedExchangeResult`.

Define the exchange result in `exchange.py`:

```python
@dataclass(frozen=True, slots=True)
class ApprovedExchangeResult:
    path: Path
    batch_id: str
    manifest_sha256: str
    candidate_count: int
    input_curated_manifest_sha256: str
```

- [ ] **Step 1: Write failing approval and leakage tests**

```python
def test_pending_selection_cannot_create_approved_directory(tmp_path: Path) -> None:
    selection = valid_selection(status="pending")
    with pytest.raises(ApprovalRequired):
        build_approved_exchange(layout(tmp_path), BATCH_ID, selection)
    assert not (tmp_path / "approved" / BATCH_ID).exists()

def test_approved_bundle_has_exact_files_and_no_restricted_data(tmp_path: Path) -> None:
    result = build_valid_exchange(tmp_path)
    assert sorted(p.name for p in result.path.iterdir()) == [
        "bundle-manifest.json", "evidence-summary.json", "top10.json"
    ]
    tree = b"".join(p.read_bytes() for p in result.path.iterdir() if p.is_file())
    for forbidden in (b"source_url_restricted", b"xsec_token", b"nickname", b"avatar", b"cookie"):
        assert forbidden not in tree.lower()
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_exchange.py -q`

Expected: FAIL because the Approved exchange builder is absent.

- [ ] **Step 3: Implement strict human-approved package creation**

The selection input is strict JSON with:

```python
class ApprovedSelection(StrictModel):
    schema: Literal["health_trend_selection.v1"]
    batch_id: str
    curated_manifest_sha256: str
    human_selection_status: Literal["approved"]
    approved_at: AwareDatetime
    candidates: tuple[ApprovedCandidate, ...]  # exactly 10, ranks 1..10 unique

class ApprovedCandidate(StrictModel):
    rank: int
    topic: str
    platform_rank_evidence: dict[Literal["dy", "xhs"], str]
    growth_evidence: tuple[str, ...]
    user_questions: tuple[str, ...]
    user_needs: tuple[str, ...]
    misunderstandings: tuple[str, ...]
    objections: tuple[str, ...]
    homogeneity_pattern: str
    narrative_gap: str
    original_visual_direction: str
    risk_flags: tuple[str, ...]
    confidence: Literal["low", "medium", "high"]
    missing_data: tuple[str, ...]
    disclaimer: Literal["该包只是选题情报，不是医学事实来源或可直接发布的脚本。"]
```

`ApprovedCandidate` contains only: `rank`, `topic`, `platform_rank_evidence`, `growth_evidence`, `user_questions`, `user_needs`, `misunderstandings`, `objections`, `homogeneity_pattern`, `narrative_gap`, `original_visual_direction`, `risk_flags`, `confidence`, `missing_data`, and the exact disclaimer `该包只是选题情报，不是医学事实来源或可直接发布的脚本。` It must not contain raw excerpts or source URLs.

Build rules:

1. Reverify Curated before reading selection.
2. Require exactly 10 unique ranks and topics; status must literally be `approved`.
3. Recursively run `assert_no_sensitive_data()` and an Approved-specific forbidden-key allowlist.
4. Write `top10.json` and aggregate-only `evidence-summary.json` with exclusive creation and fsync.
5. Write `bundle-manifest.json` last, binding schema `health_trend_exchange.v1`, batch ID, generated time, Curated input hash, selection hash, file bytes/SHA-256 and `human_selection_status=approved`.
6. Reverify final bytes before success. Existing destination or any extra file fails closed.

Add `hti build-approved` and `hti verify-approved`; `verify-approved` accepts optional `--expected-manifest-sha256` for provenance anchoring.

- [ ] **Step 4: Run exchange and complete independent-project tests**

Run:

```powershell
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_exchange.py -q
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
```

Expected: PASS; tampered payload, manifest, approval status, extra file and leaked URL each fail verification.

- [ ] **Step 5: Commit Approved package boundary**

```powershell
git add integrations/health_trend_intelligence
git commit -m "feat: build approved trend intelligence exchanges"
```

### Task 7: MoneyPrinterTurbo 的只读验证与版本化导入

**Files:**
- Create: `app/services/health_trend_exchange.py`
- Create: `09_泛健康日更/scripts/import_trend_intelligence.py`
- Create: `09_泛健康日更/data/trend-intelligence/README.md`
- Create: `test/services/test_health_trend_exchange.py`
- Modify: `.gitattributes`

**Interfaces:**
- Consumes: Task 6 Approved directory and trusted expected manifest SHA-256 supplied by operator.
- Produces: `verify_trend_exchange(source: Path, expected_manifest_sha256: str) -> VerifiedTrendExchange` and `import_trend_exchange(source: Path, repo_root: Path, expected_manifest_sha256: str) -> Path`.

Define the consumer result in `app/services/health_trend_exchange.py`:

```python
@dataclass(frozen=True, slots=True)
class VerifiedTrendExchange:
    source: Path
    batch_id: str
    version: Literal["v01"]
    manifest_sha256: str
    candidate_count: int
```

- [ ] **Step 1: Write failing MoneyPrinterTurbo boundary tests**

Tests build small synthetic Approved bundles without importing the independent package, then assert:

```python
def test_import_requires_external_manifest_anchor(tmp_path: Path) -> None:
    with pytest.raises(TrendExchangeError, match="expected manifest"):
        verify_trend_exchange(bundle(tmp_path), expected_manifest_sha256="")

def test_import_rejects_raw_curated_media_and_credentials(tmp_path: Path) -> None:
    for injected in ("source_url_restricted", "cookie", "video_url", "raw_record"):
        path, sha = bundle_with_injected_key(tmp_path, injected)
        with pytest.raises(TrendExchangeError):
            import_trend_exchange(path, tmp_path / "repo", sha)

def test_import_is_exact_versioned_and_no_overwrite(tmp_path: Path) -> None:
    source, sha = valid_bundle(tmp_path)
    target = import_trend_exchange(source, fake_repo(tmp_path), sha)
    assert target.as_posix().endswith(
        "09_泛健康日更/data/trend-intelligence/HTI-20260818-01/v01"
    )
    with pytest.raises(FileExistsError):
        import_trend_exchange(source, fake_repo(tmp_path), sha)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest test/services/test_health_trend_exchange.py -q`

Expected: FAIL because the consumer and CLI do not exist.

- [ ] **Step 3: Implement a standard-library-only importer**

Do not add MoneyPrinterTurbo dependencies. Use strict unique-key `json.loads(..., object_pairs_hook=...)`, NFC, SHA-256, `Path`, `csv` only if needed, and existing project logging without payload contents.

Verification requires:

- ordinary non-reparse directory and ordinary regular files;
- exact file set `top10.json`, `evidence-summary.json`, `bundle-manifest.json`;
- external expected hash equals the manifest bytes;
- schema `health_trend_exchange.v1`, `human_selection_status=approved`, exact batch/version;
- every file byte count and SHA matches;
- recursive forbidden keys and values absent;
- exactly 10 candidates/ranks 1–10 and exact disclaimer;
- no media extension, raw/curated path or executable file.

Import creates `.../<batch-id>/v01` once, writes the two payloads exclusively with fsync, writes `bundle-manifest.json` last, and calls `verify_trend_exchange()` on the copied bytes before returning. The CLI surface is:

```text
python 09_泛健康日更/scripts/import_trend_intelligence.py verify --source <approved-dir> --expected-manifest-sha256 <64hex>
python 09_泛健康日更/scripts/import_trend_intelligence.py import --source <approved-dir> --repo-root <repo> --expected-manifest-sha256 <64hex>
```

Exit 0 means verified/imported; exit 3 means rejected. No command reads `raw/` or `curated/`.

- [ ] **Step 4: Add exact LF rules and run focused/full tests**

Add narrow `.gitattributes` entries for the new JSON/JSONL/Markdown outputs and tests so Windows `core.autocrlf=true` does not change bound bytes; do not wildcard all future health content.

Run:

```powershell
.venv\Scripts\python.exe -m pytest test/services/test_health_trend_exchange.py -q
.venv\Scripts\python.exe -m pytest test/services/test_health_content.py test/services/test_health_batch_cli.py -q
.venv\Scripts\python.exe -m ruff check app/services/health_trend_exchange.py "09_泛健康日更/scripts/import_trend_intelligence.py" test/services/test_health_trend_exchange.py
.venv\Scripts\python.exe -m py_compile app/services/health_trend_exchange.py "09_泛健康日更/scripts/import_trend_intelligence.py"
```

Expected: all PASS; Git diff for the 240 manual-pack paths is unchanged from the task baseline.

- [ ] **Step 5: Commit the one-way MoneyPrinterTurbo exchange boundary**

```powershell
git add .gitattributes app/services/health_trend_exchange.py "09_泛健康日更/scripts/import_trend_intelligence.py" "09_泛健康日更/data/trend-intelligence/README.md" test/services/test_health_trend_exchange.py
git commit -m "feat: import approved health trend intelligence"
```

### Task 8: 端到端合成批次、可复现性与运行手册

**Files:**
- Create: `integrations/health_trend_intelligence/tests/test_foundation_e2e.py`
- Create: `integrations/health_trend_intelligence/RUNBOOK.md`
- Create: `integrations/health_trend_intelligence/scripts/verify_boundaries.py`
- Modify: `integrations/health_trend_intelligence/README.md`
- Modify: `09_泛健康日更/data/trend-intelligence/README.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: one synthetic 500-record validation workflow, machine-readable boundary report, operator runbook, and final verification evidence.

- [ ] **Step 1: Write the failing end-to-end and boundary tests**

The test generates 300 synthetic posts + 200 synthetic comments across `dy/xhs`, including exact duplicates, near duplicates, invalid counters and PII-shaped test strings. Assertions:

```python
def test_foundation_pipeline_is_reproducible_private_and_one_way(tmp_path: Path) -> None:
    first = run_synthetic_pipeline(tmp_path / "first")
    second = run_synthetic_pipeline(tmp_path / "second")
    assert first.curated_tree_sha256 == second.curated_tree_sha256
    assert first.approved_tree_sha256 == second.approved_tree_sha256
    assert first.raw_records == 500
    assert first.curated_records + first.quarantined_records <= 500
    assert first.approved_candidates == 10
    assert scan_for_sensitive_or_media(first.approved_path) == []
```

Add a repository boundary test that snapshots Git status for:

- `E:\MoneyPrinterTurbo-3期\MediaCrawler` (must remain unchanged),
- the 240 manual-pack deletion pathspec (must remain byte-for-byte identical status),
- MoneyPrinterTurbo dependency/config files (no unexpected diff).

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_foundation_e2e.py -q`

Expected: FAIL because the end-to-end harness and verifier are absent.

- [ ] **Step 3: Implement the boundary verifier and Chinese runbook**

`scripts/verify_boundaries.py` emits canonical JSON with:

```json
{
  "schema": "health_trend_foundation_qa.v1",
  "media_crawler_commit": "d6f7c5bb906b6dac40ddf343ef9e26438a3de092",
  "media_crawler_modified": false,
  "raw_in_git": false,
  "credentials_detected": false,
  "media_detected": false,
  "curated_verified": true,
  "approved_verified": true,
  "moneyprinter_import_verified": true,
  "manual_pack_deletion_status_unchanged": true
}
```

`RUNBOOK.md` must be Chinese and include exact commands for environment setup, synthetic validation, offline Raw registration, curation, manual selection-file preparation, Approved build/verify, MoneyPrinterTurbo verify/import, retention report, interruption recovery and failure cleanup. It must visibly state:

- 本计划不启动 MediaCrawler；
- 下一阶段人工扫码采集另行计划；
- 不下载媒体；
- 不把热度当医学证据；
- 不自动发布；
- Raw 30 天到期只报告、不自动删除。

- [ ] **Step 4: Run complete verification matrix**

Run:

```powershell
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests -q
uv run --project integrations/health_trend_intelligence ruff check integrations/health_trend_intelligence
.venv\Scripts\python.exe -m pytest test/services/test_health_trend_exchange.py test/services/test_health_content.py test/services/test_health_batch_cli.py -q
.venv\Scripts\python.exe -m ruff check app/services/health_trend_exchange.py "09_泛健康日更/scripts/import_trend_intelligence.py" test/services/test_health_trend_exchange.py
git diff --check
```

Then run the synthetic pipeline twice in two empty external roots and compare every Curated/Approved file SHA-256. Expected: all tests PASS, all bound bytes identical, no MediaCrawler source/config diff, no credential/media finding, and exactly the pre-existing 240 manual-pack deletion records remain.

- [ ] **Step 5: Commit end-to-end evidence and runbook**

```powershell
git add integrations/health_trend_intelligence "09_泛健康日更/data/trend-intelligence/README.md"
git commit -m "test: verify health trend intelligence boundaries"
```

## Final Acceptance Checklist

- [ ] Independent environment uses Python 3.11 and its own uv lock; MoneyPrinterTurbo dependency files are unchanged.
- [ ] MediaCrawler remains at the fixed commit and has no source/config/profile mutation.
- [ ] Offline `dy/xhs` fixtures map deterministically; unknown schema fails closed.
- [ ] Raw/Curated/Approved live outside the repository; no credential or media enters Git.
- [ ] HMAC key is required, never persisted or logged, and all human text is conservatively redacted.
- [ ] Deduplication, quarantine, checkpoint resume and two-clean-root reproducibility tests pass.
- [ ] Approved package requires explicit human status, exact 10 candidates, manifest-last binding and no restricted source data.
- [ ] MoneyPrinterTurbo only imports externally anchored Approved packages into a new versioned directory.
- [ ] No crawler launch, login, collection, scoring, video generation or publishing was added.
- [ ] The 240 manual-pack deletion records and all unrelated user changes are unchanged.
