# Quality-Only General Wellness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove external reviewer/signature gates from `general_wellness_uncredentialed`, preserve automated safety and quality boundaries, move the current ten episodes safely to `production`, archive the superseded Task 8 review machinery, and deliver ten browser-extension-ready Grok manual-generation packs.

**Architecture:** Keep the existing manifest and immutable batch snapshot. Branch workflow behavior only on the existing `content_profile`. The domain service owns profile-specific validation and state transitions; the CLI remains the only writer for active-batch state and current-reference hashes. Task 9 uses a deterministic pack builder that consumes locked storyboards, no-text formal first frames, and Task 6 QA evidence. Current episodes stop at `production`; they must not be marked `automated_qa_passed` until Grok videos, final audio, subtitles, edit, and packaging actually exist.

**Tech Stack:** Python 3, pytest, JSON/CSV/Markdown, Pillow/ImageMagick metadata checks where already available, PowerShell only for read-only verification and exact-path file moves, Git.

## Global Constraints

- Worktree: `E:/MoneyPrinterTurbo-3期/MoneyPrinterTurbo/.worktrees/health-content-system`.
- Approved design: `docs/superpowers/specs/2026-08-17-quality-only-general-wellness-design.md` at commit `56bff50`.
- Apply the simplified flow only to `content_profile == "general_wellness_uncredentialed"`; legacy or future medical profiles keep every existing human review gate.
- Never interpret `not_required` as `approved`, never write reviewer names/timestamps/signatures, and never expose internal review fields in public packages.
- Preserve the quality threshold of 92 and every existing general-wellness score floor.
- Preserve public forbidden-term, credential, identity/profile, batch ID, content ID, no-output-on-error, lock/journal, and active/reference atomicity checks.
- Current batch state target is `production`, not `automated_qa_passed`, because Grok video, final voice, subtitles, and edit evidence do not yet exist.
- Do not modify immutable snapshots, Task 6/7 formal image bytes, `CURRENT`, old `HC20260809-*` work, `tmp/`, `videos/`, `.gitignore`, or `app/utils/logging_utils.py`.
- Do not upload or publish to any platform. Grok generation remains a user-operated browser-extension step.
- Before each commit, stage only the files listed in that task and run `git diff --cached --check` plus an exact staged-path review.

---

## Task 1: Specify the quality-only manifest contract with failing tests

**Files:**
- Modify: `test/services/test_health_content.py`
- Test: `test/services/test_health_content.py`

- [ ] **Step 1: Update only the general-wellness test fixture to the approved compatibility contract**

In `_general_wellness_manifest()`, override the inherited legacy review records:

```python
"medical_review": {
    "status": "not_required",
    "reviewer": "",
    "reviewed_at": "",
    "notes": "一般生活方式内容不要求外部医学审核。",
},
"automated_qa": {
    "status": "passed",
    "checked_at": "2026-08-17T15:30:00+08:00",
},
"final_qa": {
    "status": "not_required",
    "reviewer": "",
    "reviewed_at": "",
},
```

Do not change `_approved_manifest()`: it is the legacy regression fixture.

- [ ] **Step 2: Add RED tests for exact status semantics**

Add tests with these assertions:

```python
def test_general_wellness_requires_not_required_human_review_records():
    manifest = _general_wellness_manifest()
    assert health_content.validate_manifest(manifest)["medical_review"]["status"] == "not_required"
    assert health_content.validate_manifest(manifest)["final_qa"]["status"] == "not_required"


@pytest.mark.parametrize("field", ("medical_review", "final_qa"))
def test_general_wellness_rejects_fake_human_approval(field):
    manifest = _general_wellness_manifest()
    manifest[field]["status"] = "approved" if field == "medical_review" else "passed"
    manifest[field]["reviewer"] = "某审核人"
    manifest[field]["reviewed_at"] = "2026-08-17T15:30:00+08:00"
    with pytest.raises(health_content.HealthContentError, match="not_required"):
        health_content.validate_manifest(manifest)


def test_legacy_manifest_still_rejects_not_required_review_records():
    manifest = _approved_manifest()
    manifest["medical_review"].update(status="not_required", reviewer="", reviewed_at="")
    with pytest.raises(health_content.MedicalReviewRequired):
        health_content.build_publish_pack(manifest)
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run:

```powershell
python -m pytest test/services/test_health_content.py -k "not_required or fake_human_approval" -q
```

Expected: new general-wellness tests fail because current validation accepts the old approved records and current packaging always requires human review.

- [ ] **Step 4: Keep the RED tests uncommitted and continue directly to Task 2**

Do not leave a tests-only red commit in history. Task 2 must make these tests green and commit the test and implementation together.

---

## Task 2: Implement profile-specific validation and state transitions

**Files:**
- Modify: `app/services/health_content.py`
- Modify: `test/services/test_health_content.py`

- [ ] **Step 1: Add RED state-flow tests**

Add one test for the simplified flow and one legacy regression:

```python
def test_general_wellness_uses_three_step_quality_only_flow():
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    manifest = _general_wellness_manifest()
    content_id = manifest["content_id"]

    batch = health_content.advance_topic_state(batch, content_id, "production", manifest)
    batch = health_content.advance_topic_state(batch, content_id, "automated_qa_passed", manifest)
    batch = health_content.advance_topic_state(batch, content_id, "ready_to_publish", manifest)
    assert batch["topics"][0]["state_history"][-3:] == [
        "production", "automated_qa_passed", "ready_to_publish"
    ]


@pytest.mark.parametrize("illegal", ("medical_review_pending", "approved", "final_qa_passed"))
def test_general_wellness_rejects_removed_human_states(illegal):
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    with pytest.raises(health_content.HealthContentError, match="非法状态跃迁"):
        health_content.advance_topic_state(
            batch, "HC20260810-001", illegal, _general_wellness_manifest()
        )
```

Keep `test_state_transition_enforces_medical_and_final_gates()` unchanged for legacy.

- [ ] **Step 2: Confirm the new flow tests fail**

Run:

```powershell
python -m pytest test/services/test_health_content.py -k "three_step_quality_only or removed_human_states or state_transition_enforces" -q
```

Expected: the general flow fails at `research_pending -> production`; the legacy test remains green.

- [ ] **Step 3: Implement exact profile branches**

Replace the single transition table with:

```python
_LEGACY_STATE_TRANSITIONS = {
    "research_pending": "medical_review_pending",
    "medical_review_pending": "approved",
    "approved": "production",
    "production": "automated_qa_passed",
    "automated_qa_passed": "final_qa_passed",
    "final_qa_passed": "ready_to_publish",
}

_GENERAL_WELLNESS_STATE_TRANSITIONS = {
    "research_pending": "production",
    "production": "automated_qa_passed",
    "automated_qa_passed": "ready_to_publish",
}
```

Add private helpers with explicit behavior:

```python
def _is_quality_only_general_wellness(manifest: Mapping) -> bool:
    return manifest.get("content_profile") == GENERAL_WELLNESS_PROFILE


def _state_transitions_for(manifest: Mapping) -> Mapping[str, str]:
    if _is_quality_only_general_wellness(manifest):
        return _GENERAL_WELLNESS_STATE_TRANSITIONS
    return _LEGACY_STATE_TRANSITIONS


def _require_general_wellness_review_policy(manifest: Mapping) -> None:
    # medical_review and final_qa must exist, have status=not_required,
    # and contain blank reviewer/time fields.
```

Call `_require_general_wellness_review_policy()` from `_validate_general_wellness_manifest()`.

Add `run_preproduction_qa(manifest)` that recomputes manifest validity, public-term safety, score/floors, four-platform count, and seven-card count, but does not claim video/audio QA. Use it only for `research_pending -> production` in the simplified profile.

Update `run_automated_qa()`:

- general wellness: do not call `_require_medical_review`; return checks named `profile_boundary`, `quality_score`, `platform_count`, and `article_card_count`;
- legacy: retain `_require_medical_review` and the existing `medical_review=True` check.

Update `advance_topic_state()`:

- verify manifest/batch identity before choosing transitions;
- choose the table from the validated manifest;
- call `run_preproduction_qa()` for general-wellness `production`;
- retain every existing legacy review/final-review branch;
- retain automated-QA record and publish-pack gates;
- retain the hard rejection of `published`.

- [ ] **Step 4: Run focused and full service tests**

```powershell
python -m pytest test/services/test_health_content.py -q
```

Expected: all service tests pass; legacy human-review tests remain unchanged and green.

- [ ] **Step 5: Commit the service change**

```powershell
git add app/services/health_content.py test/services/test_health_content.py
git diff --cached --check
git commit -m "feat: add quality-only wellness state flow"
```

---

## Task 3: Keep publish packaging strict without external review

**Files:**
- Modify: `app/services/health_content.py`
- Modify: `test/services/test_health_content.py`

- [ ] **Step 1: Add RED packaging tests**

Cover four cases:

```python
def test_general_wellness_pack_needs_automated_qa_but_not_human_review():
    manifest = _general_wellness_manifest()
    pack = health_content.build_publish_pack(manifest)
    assert pack["status"] == "human_pending"
    assert "medical_review" not in str(pack)
    assert "final_qa" not in str(pack)
    assert "reviewer" not in str(pack)


def test_general_wellness_pack_rejects_pending_automated_qa():
    manifest = _general_wellness_manifest()
    manifest["automated_qa"] = {"status": "pending", "checked_at": ""}
    with pytest.raises(health_content.FinalQARequired, match="自动QA"):
        health_content.build_publish_pack(manifest)


def test_general_wellness_pack_still_enforces_92_and_all_floors():
    manifest = _general_wellness_manifest()
    manifest["quality"]["visual_explanation"] = 13
    with pytest.raises(health_content.QualityGateFailed):
        health_content.build_publish_pack(manifest)
```

Retain the existing legacy tests that require medical approval and independent final review.

- [ ] **Step 2: Confirm the first new test fails under the current pack builder**

```powershell
python -m pytest test/services/test_health_content.py -k "pack_needs_automated or pack_rejects_pending or pack_still_enforces" -q
```

- [ ] **Step 3: Branch `build_publish_pack()` by profile**

Implement:

```python
validated = validate_manifest(manifest)
if _is_quality_only_general_wellness(validated):
    run_automated_qa(validated)
    _require_automated_qa_record(validated)
else:
    review = _require_medical_review(validated)
    run_automated_qa(validated)
    _require_automated_qa_record(validated)
    _require_final_qa(validated, review)
```

Do not add review-policy fields to the returned pack. Keep `status="human_pending"`, four separate platform packages, public forbidden-term scan, and score floors.

- [ ] **Step 4: Run the whole service test file**

```powershell
python -m pytest test/services/test_health_content.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add app/services/health_content.py test/services/test_health_content.py
git diff --cached --check
git commit -m "feat: package quality-only wellness without review claims"
```

---

## Task 4: Add atomic CLI preparation and verify direct production transition

**Files:**
- Modify: `09_泛健康日更/scripts/health_batch.py`
- Modify: `test/services/test_health_batch_cli.py`

- [ ] **Step 1: Add RED CLI tests**

Add a `prepare-quality-only` command contract:

```python
def test_prepare_quality_only_updates_only_review_policy_atomically(tmp_path):
    manifest = _general_wellness_manifest()
    manifest["medical_review"]["status"] = "pending"
    manifest["final_qa"]["status"] = "pending"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = _run("prepare-quality-only", "--manifest", str(manifest_path))
    assert result.returncode == 0, result.stdout
    stored = json.loads(manifest_path.read_text("utf-8"))
    assert stored["medical_review"] == {
        "status": "not_required", "reviewer": "", "reviewed_at": "",
        "notes": "一般生活方式内容不要求外部医学审核。",
    }
    assert stored["final_qa"] == {
        "status": "not_required", "reviewer": "", "reviewed_at": ""
    }
    assert stored["automated_qa"] == {"status": "pending", "checked_at": ""}
    assert not list(tmp_path.glob(".*.tmp"))


def test_prepare_quality_only_rejects_legacy_without_rewriting(tmp_path):
    # Save bytes, run command on _approved_manifest(), expect code 3 and identical bytes.
```

Add a direct CLI advance test for a general batch:

```python
result = _run(
    "advance", "--batch", str(batch_path),
    "--content-id", "HC20260810-001", "--to", "production",
    "--manifest", str(manifest_path),
)
assert result.returncode == 0
assert active["topics"][0]["state"] == "production"
assert current_ref["active_sha256"] == sha256(active_bytes).hexdigest()
```

Also assert `research_pending -> automated_qa_passed` is still rejected.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest test/services/test_health_batch_cli.py -k "prepare_quality_only or general_direct_production" -q
```

- [ ] **Step 3: Implement `prepare-quality-only`**

Add a command handler that:

1. resolves and reads one manifest;
2. requires explicit `general_wellness_uncredentialed`;
3. changes only the three review/QA records shown in the test;
4. validates the proposed manifest before writing;
5. writes with `_atomic_replace_json()`;
6. is idempotent for identical bytes;
7. emits no files on validation failure.

Register:

```python
prepare_parser = commands.add_parser(
    "prepare-quality-only", help="将一般生活方式manifest切换为免外部审核策略"
)
prepare_parser.add_argument("--manifest", required=True)
prepare_parser.set_defaults(handler=prepare_quality_only)
```

Do not weaken the existing `advance` journal/lock/reference transaction.

- [ ] **Step 4: Run CLI and service regressions**

```powershell
python -m pytest test/services/test_health_batch_cli.py test/services/test_health_content.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add 09_泛健康日更/scripts/health_batch.py test/services/test_health_batch_cli.py
git diff --cached --check
git commit -m "feat: prepare quality-only manifests atomically"
```

---

## Task 5: Migrate the current ten episodes to `production` without claiming final QA

**Files:**
- Modify: `09_泛健康日更/work/HC20260810-001/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-002/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-003/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-004/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-005/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-006/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-007/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-008/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-009/manifest.json`
- Modify: `09_泛健康日更/work/HC20260810-010/manifest.json`
- Modify: `09_泛健康日更/data/01_一般生活方式50集/batch-01/active-batch.json`
- Modify: `09_泛健康日更/data/01_一般生活方式50集/batch-01/current-batch-ref.json`

- [ ] **Step 1: Record a read-only preflight**

Verify all ten manifests have batch `HB20260810`, the explicit profile, unique IDs `001..010`, quality >=92/floors, and current active state `research_pending`. Verify no `.batch-mutation.lock` or `.batch-mutation-*.journal.json` exists. Save hashes in the execution report, not in a new production schema.

- [ ] **Step 2: Prepare each manifest through the new CLI**

For `001..010`, run:

```powershell
python 09_泛健康日更/scripts/health_batch.py prepare-quality-only `
  --manifest 09_泛健康日更/work/HC20260810-001/manifest.json
```

After each call, validate JSON and confirm:

- `medical_review.status == not_required`;
- `final_qa.status == not_required`;
- reviewer/time fields are empty;
- `automated_qa.status == pending` and `checked_at == ""`;
- no user names, review timestamp, signature, public key, or private key was added.

- [ ] **Step 3: Advance each episode exactly one state**

For `001..010`, run the existing atomic CLI:

```powershell
python 09_泛健康日更/scripts/health_batch.py advance `
  --batch 09_泛健康日更/data/01_一般生活方式50集/batch-01/active-batch.json `
  --content-id HC20260810-001 `
  --to production `
  --manifest 09_泛健康日更/work/HC20260810-001/manifest.json
```

Do not advance to `automated_qa_passed`.

- [ ] **Step 4: Verify the transaction result**

Check:

- 10/10 topics are `production`;
- each `state_history` gained exactly one `production` entry;
- active batch hash equals `current-batch-ref.json.active_sha256`;
- immutable `batches/20260810/active-batch.json`, first-wave inputs, dry-run report, and snapshot hashes are unchanged;
- no locks, journals, temp, rollback, or recovery files remain.

- [ ] **Step 5: Run regression tests and commit only the 12 migration files**

```powershell
python -m pytest test/services/test_health_content.py test/services/test_health_batch_cli.py -q
git add 09_泛健康日更/work/HC20260810-*/manifest.json
git add 09_泛健康日更/data/01_一般生活方式50集/batch-01/active-batch.json
git add 09_泛健康日更/data/01_一般生活方式50集/batch-01/current-batch-ref.json
git diff --cached --check
git commit -m "data: move batch 01 into quality-only production"
```

Before committing, verify the staged set is exactly ten manifests plus active batch and current ref.

---

## Task 6: Archive Task 8 without deleting evidence or inventing approvals

**Files:**
- Create: `09_泛健康日更/work/HC20260810-B01-task8-qa/archive_v00/external-review-superseded/SUPERSEDED.md`
- Create: `09_泛健康日更/work/HC20260810-B01-task8-qa/archive_v00/external-review-superseded/ARCHIVE-MANIFEST.csv`
- Move: `09_泛健康日更/work/HC20260810-B01-review-index.md`
- Move: `09_泛健康日更/work/HC20260810-B01-task8-qa/build-review-handoffs.py`
- Move: `09_泛健康日更/work/HC20260810-B01-task8-qa/probe-review-transaction.py`
- Move: ten `09_泛健康日更/work/HC20260810-XXX/production/v01/01_evidence/review-handoff-v01.md`
- Create: `test/services/test_quality_only_task8_archive.py`

- [ ] **Step 1: Write a RED archive-integrity test**

The test must require:

- exactly 13 archived source artifacts: 10 handoffs, one index, builder, probe;
- archive CSV records original path, archive path, bytes, and SHA-256;
- every archived file hash matches its recorded pre-move hash;
- active production paths contain no `review-handoff-v01.md` and no live review index;
- `SUPERSEDED.md` references the approved design and says Task 8 is historical, not approved;
- strings `胡秋生`, `陈晓亮`, `2026-08-17T15:30:00+08:00`, `signature`, and `private_key` are absent from approval/result fields. The builder source may contain schema words such as `signature`; therefore scan archive metadata and handoff result sections semantically, not by a blind whole-tree substring test.

- [ ] **Step 2: Confirm RED before moving anything**

```powershell
python -m pytest test/services/test_quality_only_task8_archive.py -q
```

- [ ] **Step 3: Create the archive with exact-path, hash-preserving moves**

Resolve every source path first. Refuse the move if any source is missing, is a reparse point, or has an unexpected hash. Use native PowerShell `Move-Item -LiteralPath` for each explicit file; do not recursively move broad directories. Store handoffs as:

```text
archive_v00/external-review-superseded/handoffs/HC20260810-001-review-handoff-v01.md
...
```

Store the other three artifacts under `batch/` and `tools/`.

`SUPERSEDED.md` must state:

- superseded by `docs/superpowers/specs/2026-08-17-quality-only-general-wellness-design.md`;
- no external review response was consumed;
- no reviewer identity, timestamp, public key, or signature is asserted;
- general wellness continues via automated safety checks and manual publishing;
- legacy/medical profiles are unaffected.

- [ ] **Step 4: Run archive test and inspect staged scope**

```powershell
python -m pytest test/services/test_quality_only_task8_archive.py -q
git diff --check
```

- [ ] **Step 5: Commit archive evidence only**

```powershell
git add 09_泛健康日更/work/HC20260810-B01-task8-qa/archive_v00/external-review-superseded
git add -u -- 09_泛健康日更/work/HC20260810-B01-review-index.md
git add -u -- 09_泛健康日更/work/HC20260810-*/production/v01/01_evidence/review-handoff-v01.md
git add test/services/test_quality_only_task8_archive.py
git diff --cached --check
git commit -m "chore: archive superseded external review flow"
```

---

## Task 7: Build and verify one Task 9 Grok manual-pack sample

**Files:**
- Create: `09_泛健康日更/scripts/build_grok_manual_packs.py`
- Create: `test/services/test_grok_manual_pack.py`
- Create: `09_泛健康日更/work/HC20260810-001/production/v01/04_grok_batch/manual_pack/`

- [ ] **Step 1: Use the required production skills before implementation**

Read and follow `health-visible-grok-video` completely. Use `health-viral-batch` for protected paths and batch identity. Do not call Grok or any video API; this task creates a user-operated package only.

- [ ] **Step 2: Add RED builder/verifier tests**

Test the `001` sample for:

- active topic state is `production`;
- source storyboard is `production/v01/02_script_storyboard/storyboard-v01.md` and has exactly S01–S10;
- formal source images are only root-level `03_first_frames/*-firstframe.png`, never `storyboard_with_copy/` or UI previews;
- ten copied images are byte-identical to their sources, 1080×1920, and uniquely hashed;
- consolidated prompt document has exactly ten nonblank prompt lines and exactly nine single blank-line separators; no internal blank lines or triple-newline separator;
- each prompt line starts `S01｜` through `S10｜`, contains Chinese and English instructions, one low-amplitude action, identity/scene preservation, and no-added-text/Logo/watermark/paper/pen/notebook rules;
- deterministic-board shots are marked `generation_mode=deterministic_post` and clearly say “无需上传 Grok”; dynamic shots are `generation_mode=grok_manual`;
- every dynamic `minimum_grok_source_seconds <= 5.8`;
- `MANIFEST.csv` binds shot, source/copy path, bytes, SHA-256, prompt SHA-256, timeline, mode, minimum source seconds, and output template;
- `MANUAL-GENERATION-GUIDE.md` says use the Grok browser extension manually and save outputs without slow motion, looping, interpolation, or model-generated UI;
- output directories are created only after all inputs validate; rerun with identical bytes is idempotent; different existing bytes fail closed.

- [ ] **Step 3: Confirm RED**

```powershell
python -m pytest test/services/test_grok_manual_pack.py -q
```

- [ ] **Step 4: Implement the deterministic builder**

Expose:

```powershell
python 09_泛健康日更/scripts/build_grok_manual_packs.py `
  build --content-id HC20260810-001

python 09_泛健康日更/scripts/build_grok_manual_packs.py `
  verify --content-id HC20260810-001
```

The builder must parse storyboard table columns by header name, not fixed column number. It must copy images byte-for-byte, write UTF-8 with LF, use CSV quoting, hash every input/output, and generate these exact entries:

```text
manual_pack/
  01_first_frames/HC20260810-001-v01-S01-firstframe.png ... S10
  02_prompts/HC20260810-001-v01-S01-prompt-zh-en.txt ... S10
  HC20260810-001-v01-Grok-Automation-10条提示词.txt
  MANUAL-GENERATION-GUIDE.md
  MANIFEST.csv
  MANUAL-PACK-QA.md
```

Prompt authoring is content-specific, not a generic ten-line template. For `deterministic-board`, the per-shot file and consolidated line describe the post-production motion but explicitly prohibit Grok upload.

Before writing outputs, the builder must also bind and verify the current episode `production/v01/05_qa/first-frame-qa-v01.md` and the batch `HC20260810-B01-task6-qa/HC20260810-B01-first-frame-qa-v01.md`; neither file is an external approval, but both are required source-quality evidence.

- [ ] **Step 5: Build `001`, inspect all inputs, and verify**

Open the ten formal first frames and the existing with-copy contact sheet to confirm action/identity context, but copy only formal frames. Review all ten bilingual lines manually. Run:

```powershell
python 09_泛健康日更/scripts/build_grok_manual_packs.py verify --content-id HC20260810-001
python -m pytest test/services/test_grok_manual_pack.py -q
```

- [ ] **Step 6: Commit the sample and builder**

```powershell
git add 09_泛健康日更/scripts/build_grok_manual_packs.py
git add test/services/test_grok_manual_pack.py
git add 09_泛健康日更/work/HC20260810-001/production/v01/04_grok_batch/manual_pack
git diff --cached --check
git commit -m "feat: build verified Grok manual generation packs"
```

---

## Task 8: Author and verify Task 9 packs for episodes 002–010

**Files:**
- Create: nine `09_泛健康日更/work/HC20260810-00X/production/v01/04_grok_batch/manual_pack/` directories for `002..010`
- Modify: `test/services/test_grok_manual_pack.py`
- Create: `09_泛健康日更/work/HC20260810-B01-task9-qa/HC20260810-B01-grok-manual-pack-inventory-v01.csv`
- Create: `09_泛健康日更/work/HC20260810-B01-task9-qa/HC20260810-B01-grok-manual-pack-qa-v01.md`

- [ ] **Step 1: Expand tests from one content ID to all ten**

Parametrize IDs `001..010`. Add batch assertions:

- 10 packs;
- 100 manifest rows and 100 first-frame copies;
- 100 per-shot prompt files and 10 consolidated prompt documents;
- every pack has S01–S10 exactly once;
- every dynamic shot obeys the 5.8-second limit;
- source/copy SHA pairs all match;
- formal copies never match a with-copy/UI source path;
- no generated prompt adds paper, pen, notebook, medical identity, readable UI, text, Logo, watermark, extra person, extra hand, or extra object;
- phone shots preserve the accepted Task 6 phone constraints; `010/S02` remains static back-shell-only and is not described as trackable UI;
- the source public copy remains free of medical/device forbidden terms. Prompt safety clauses may name a forbidden object only in an explicit negative instruction such as “不得新增医疗器械”; those internal instructions are never copied into public platform text.

- [ ] **Step 2: Confirm the expanded test is RED for missing packs**

```powershell
python -m pytest test/services/test_grok_manual_pack.py -q
```

- [ ] **Step 3: Author packs episode by episode**

For each episode:

1. read narration and the full storyboard;
2. inspect the ten formal frames at full size and the with-copy contact sheet;
3. write one shot-specific Chinese/English prompt per row;
4. keep one action per dynamic shot and deterministic handling for boards;
5. run `build` and `verify` before moving to the next episode;
6. record any nonblocking visual limitation in that episode's `MANUAL-PACK-QA.md`.

Do not generate all 90 remaining prompts from one fixed sentence skeleton. Repeated safety clauses may be standardized, but action, camera, continuity, object count, and rejection criteria must match the individual storyboard row.

- [ ] **Step 4: Generate the batch inventory and QA summary**

Inventory columns:

```text
content_id,shot_id,generation_mode,source_first_frame,copy_first_frame,
source_sha256,copy_sha256,prompt_file,prompt_sha256,timeline,
minimum_grok_source_seconds,raw_output_template,pack_status
```

Batch QA must explicitly report:

- `production` state 10/10;
- prompt documents 10/10;
- shot rows 100/100;
- copied frames 100/100 at 1080×1920;
- byte-identical source/copy 100/100;
- blank-line format 10/10;
- dynamic duration gate 100/100 applicable rows;
- deterministic-board rows not intended for Grok upload;
- user manual-generation and output naming instructions;
- no claim that any video has already been generated or passed final QA.

- [ ] **Step 5: Run all pack tests and commit**

```powershell
python -m pytest test/services/test_grok_manual_pack.py -q
git add 09_泛健康日更/work/HC20260810-00*/production/v01/04_grok_batch/manual_pack
git add 09_泛健康日更/work/HC20260810-B01-task9-qa
git add test/services/test_grok_manual_pack.py
git diff --cached --check
git commit -m "content: deliver batch 01 Grok manual packs"
```

Before commit, assert no raw `.mp4`, cookies, browser profile, API key, token, or platform credential entered the staged set.

---

## Task 9: Final integration verification and handoff

**Files:**
- Create: `.superpowers/sdd/2026-08-10-batch-01-premium-general-wellness/task-9-report.md` (ignored audit report; do not force-add unless project policy changes)
- Verify only: all files changed in Tasks 1–8

- [ ] **Step 1: Run focused suites**

```powershell
python -m pytest test/services/test_health_content.py -q
python -m pytest test/services/test_health_batch_cli.py -q
python -m pytest test/services/test_quality_only_task8_archive.py -q
python -m pytest test/services/test_grok_manual_pack.py -q
```

- [ ] **Step 2: Run the complete repository test suite**

```powershell
python -m pytest -q
```

If a known unrelated flaky test fails, rerun it in isolation and then rerun the full suite in a fresh process. Record both results; do not silently omit the first failure.

- [ ] **Step 3: Perform fresh data and scope checks**

Verify:

- design commit is an ancestor;
- legacy tests prove medical/final review gates still exist;
- current ten manifests use `not_required` with blank reviewer/time and automated QA pending;
- active/current-ref hashes match and snapshots are unchanged;
- current ten active states are exactly `production`;
- Task 8 archive is complete and not live;
- no reviewer names/timestamps/signatures were manufactured;
- Task 6/7 formal asset hashes remain unchanged;
- 10 Task 9 packs and 100 shot rows verify;
- no videos are claimed as generated;
- pack status is manual/user-operated, not published;
- unrelated dirty files are still unstaged and unchanged by this work.

- [ ] **Step 4: Write the execution report**

Record commits, exact file counts, test totals, current state, archive hashes, pack inventory hash, and residual risks. Residual risks must include: Grok outputs still need per-shot QA; phone/UI compositing remains deterministic post-production; four-platform upload previews remain manual; no external reviewer or signature exists by design.

- [ ] **Step 5: Final clean-scope check**

```powershell
git diff --check
git status --short
git log --oneline 56bff50..HEAD
```

Do not commit the ignored report or unrelated dirty files. Hand the user the ten manual-pack paths and the exact raw-video naming convention `SNN_takeNN.mp4`.

## Completion Criteria

- General wellness uses `research_pending -> production -> automated_qa_passed -> ready_to_publish`; removed human states are rejected only for that profile.
- Legacy/medical content still requires real medical review and an independent final reviewer.
- `not_required` is never represented as approval, and public packages contain no review claims.
- The current ten episodes are at `production`, not falsely at final QA.
- Superseded Task 8 evidence is preserved, hash-inventoried, and removed from the live workflow.
- Ten verified Task 9 manual packs bind 100 locked no-text first frames and 100 shot-specific bilingual prompt records.
- No automatic Grok generation, platform login, upload, or publication occurs.
- Focused and full tests pass, protected assets remain byte-stable, and unrelated workspace changes remain untouched.
