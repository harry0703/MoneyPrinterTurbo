# Batch 01 Premium General Wellness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first ten fully packaged, platform-safe, premium general-wellness episodes for “生活节奏看得见”, creating a ten-day publishing buffer without medical qualification signals.

**Architecture:** Preserve the existing medical batch as immutable evidence and start a separate Batch 01 inventory from an explicit topic file. Extend the existing health-content contract with a `general_wellness_uncredentialed` profile so automated validation, article cards, and four-platform packages remove disease, diagnosis, clinician, device, and medical-brand signals while retaining internal factual review and final QA. Each episode has an isolated production directory and moves through evidence, script, generated imagery, manual Grok generation, deterministic Chinese graphics, voice, edit, QA, and `human_pending` publish packaging.

**Tech Stack:** Python 3 via `uv`, pytest, JSON/CSV/Markdown, built-in image generation, deterministic SVG/HTML rendering, Grok browser extension operated manually by the user, FFmpeg/ffprobe, ImageMagick, Mandarin TTS, existing health batch CLI.

## Global Constraints

- Audience: Chinese mainland users aged 35—60.
- Account name: `生活节奏看得见`.
- Account bio: `记录睡眠、进餐和日常活动中的小习惯`.
- Avatar: simple sunlight, plate, and walking elements; no anatomy, organs, white coat, stethoscope, medical cross, or device.
- Content profile: `general_wellness_uncredentialed`.
- Never show or mention disease names, diagnosis, tests, treatment, prescriptions, clinicians, clinics, hospitals, body-fat scale, 减重云, 健康卫士, blood glucose, blood pressure, blood lipids, uric acid, oxygen saturation, body temperature, or medical curves.
- Never use paper, pens, or notebooks as the recording method.
- General safety reminders are allowed; they must not imply diagnosis or professional identity.
- One 1080×1920, 24 fps, 50—60 second master per episode; H.264 yuv420p video and AAC 48 kHz audio.
- Generated images contain no Chinese, English, numbers, logos, watermarks, or model-generated UI; all visible copy is deterministic post-production.
- Article cards: 7 pages, 1080×1920; title 58—78 px, body 34—42 px; critical content inside x=72—900 and y=160—1500.
- Mobile safe captions: maximum 2 lines, 16—20 Chinese characters per line, no critical text behind right-side or bottom platform controls.
- Voice master: 48 kHz mono, integrated loudness −16.0 LUFS, true peak no higher than −1.5 dBTP.
- General-wellness quality gate: total score at least 92/100; topic value ≥18/20, factual reliability using the existing `medical_credibility` field ≥18/20, retention ≥18/20, visual explanation ≥14/15, save value ≥13/15, follow conversion ≥8/10.
- The old `09_泛健康日更/data/00_十主题滚动库/` remains untouched and blocked; do not overwrite, delete, rename, or advance it.
- Grok generation is a manual external gate. Generate no paid or external video automatically and store no credentials.
- Final platform submission remains manual; publish packs must stay `human_pending`.

---

### Task 1: Add the uncredentialed general-wellness profile to the existing contract

**Files:**
- Modify: `app/services/health_content.py`
- Modify: `09_泛健康日更/scripts/health_batch.py`
- Modify: `09_泛健康日更/templates/health-content-manifest.template.json`
- Test: `test/services/test_health_content.py`
- Test: `test/services/test_health_batch_cli.py`

**Interfaces:**
- Consumes: the existing `health-batch-v1` batch object and existing manifest fields.
- Produces: `GENERAL_WELLNESS_PROFILE`, `create_seed_batch(date, topics=None, content_profile=None)`, CLI `start-batch --topics-file`, profile-aware validation/article cards/platform package, and profile-specific quality floors.

- [ ] **Step 1: Write failing service tests for the new profile**

Add a `_general_wellness_manifest()` fixture with:

```python
{
    "content_profile": "general_wellness_uncredentialed",
    "account_name": "生活节奏看得见",
    "account_bio": "记录睡眠、进餐和日常活动中的小习惯",
    "topic": "午饭后总想打盹，先观察3件事",
    "observations": [
        {"label": "昨晚睡眠", "detail": "回想入睡和起床时间"},
        {"label": "午餐状态", "detail": "留意速度和饱足感"},
        {"label": "饭后安排", "detail": "对比久坐和轻松活动"},
    ],
    "medical_attention": "困倦时不要继续驾驶或操作机器，先停下来休息。",
    "save_reason": "收藏这三个观察方向，连续看一周。",
}
```

Assert that the serialized publish pack contains none of:

```python
(
    "疾病", "诊断", "治疗", "医生", "医务", "医院", "门诊", "检查",
    "血糖", "血压", "血脂", "尿酸", "血氧", "体温", "减重云",
    "健康卫士", "体脂秤", "医疗器械", "健康科普", "不替代诊疗",
)
```

Assert seven article-card roles equal:

```python
["封面", "场景", "观察一", "观察二", "观察三", "小尝试", "总结"]
```

Assert a 91-point general-wellness manifest fails and a 92-point manifest passes.

- [ ] **Step 2: Run the service tests and confirm the profile is absent**

Run:

```powershell
uv run pytest test/services/test_health_content.py -q
```

Expected: FAIL because profile-aware validation and packaging do not exist.

- [ ] **Step 3: Implement profile-aware validation and packaging**

In `app/services/health_content.py`:

```python
GENERAL_WELLNESS_PROFILE = "general_wellness_uncredentialed"
GENERAL_WELLNESS_PUBLIC_FORBIDDEN = (
    "疾病", "诊断", "治疗", "医生", "医务", "医院", "门诊", "检查",
    "血糖", "血压", "血脂", "尿酸", "血氧", "体温", "减重云",
    "健康卫士", "体脂秤", "医疗器械",
)
GENERAL_WELLNESS_SCORE_FLOORS = {
    "topic_value": 18,
    "medical_credibility": 18,
    "retention": 18,
    "visual_explanation": 14,
    "save_value": 13,
    "follow_conversion": 8,
}
```

For the general-wellness profile, require exact account name/bio, exactly three observation objects, non-empty `save_reason`, all existing source/review/final-QA fields, total score ≥92, and every floor above. Scan only public content fields and generated public packages for forbidden terms; internal field names such as `medical_review` remain private contract fields and must not leak into publish copy.

Branch `_article_cards()` and `_platform_package()` by `content_profile`. Use lifestyle tags only:

```python
{
    "wechat_channels": ["生活观察", "日常习惯", "生活节奏"],
    "douyin": ["生活小习惯", "日常记录", "状态管理"],
    "xiaohongshu": ["生活方式", "习惯养成", "日常观察"],
    "kuaishou": ["生活经验", "日常习惯", "过日子"],
}
```

Pinned comments must invite users to share a personal habit and must not mention medical care.

- [ ] **Step 4: Write failing CLI tests for `--topics-file`**

Create a temporary JSON object with schema `health-topic-input-v1`, profile `general_wellness_uncredentialed`, and exactly ten topics containing `slot`, `category`, `topic`, and `audience`. Assert:

```python
started = _run(
    "start-batch", "--date", "20260810", "--output", str(output),
    "--topics-file", str(topics_file),
)
assert started.returncode == 0
assert json.loads((output / "active-batch.json").read_text("utf-8"))["content_profile"] == "general_wellness_uncredentialed"
```

Also assert 9 topics, duplicate slots, a medical forbidden term, or an unrecognized profile exits with code 3 and creates no output directory.

- [ ] **Step 5: Implement `--topics-file` without changing the existing output schema**

Parse and validate the file before creating any directory. Pass the ten normalized topics to `create_seed_batch()`, assign `HC20260810-001` through `HC20260810-010`, and bind the profile into `active-batch.json`, `first-wave-inputs.json`, and `dry-run-report.json`. Keep the no-overwrite behavior.

- [ ] **Step 6: Update the manifest template**

Add exact fields:

```json
"content_profile": "general_wellness_uncredentialed",
"account_name": "生活节奏看得见",
"account_bio": "记录睡眠、进餐和日常活动中的小习惯",
"observations": [],
"save_reason": ""
```

Keep `medical_review` as an internal factual-review gate; do not expose that label in public copy.

- [ ] **Step 7: Run focused and full tests**

Run:

```powershell
uv run pytest test/services/test_health_content.py test/services/test_health_batch_cli.py -q
uv run pytest -q
```

Expected: all tests pass; existing legacy profile tests remain unchanged.

- [ ] **Step 8: Commit Task 1**

```powershell
git add app/services/health_content.py 09_泛健康日更/scripts/health_batch.py 09_泛健康日更/templates/health-content-manifest.template.json test/services/test_health_content.py test/services/test_health_batch_cli.py
git commit -m "feat: add uncredentialed general wellness profile"
```

---

### Task 2: Create the 50-topic inventory and isolated Batch 01

**Files:**
- Create: `09_泛健康日更/data/01_一般生活方式50集/series-inventory-v01.json`
- Create: `09_泛健康日更/data/01_一般生活方式50集/batch-01-inputs.json`
- Generate: `09_泛健康日更/data/01_一般生活方式50集/batch-01/active-batch.json`
- Generate: `09_泛健康日更/data/01_一般生活方式50集/batch-01/current-batch-ref.json`
- Generate: `09_泛健康日更/data/01_一般生活方式50集/batch-01/batches/20260810/*`
- Create: `09_泛健康日更/data/01_一般生活方式50集/README.md`

**Interfaces:**
- Consumes: approved design spec and Task 1 `--topics-file` contract.
- Produces: immutable 50-topic inventory plus a ten-topic active Batch 01 independent of the blocked medical batch.

- [ ] **Step 1: Verify the blocked legacy batch is unchanged and has no mutation guard**

Run:

```powershell
uv run python "09_泛健康日更/scripts/health_batch.py" status --batch "09_泛健康日更/data/00_十主题滚动库/active-batch.json"
Get-ChildItem -Force "09_泛健康日更/data/00_十主题滚动库" | Where-Object Name -Match '^\.batch-mutation|journal|lock'
```

Expected: `HB20260809`, states `production=1`, `medical_review_pending=1`, `research_pending=8`, and no lock/journal. Record its SHA-256 in the new README; do not mutate it.

- [ ] **Step 2: Write the complete 50-topic inventory**

Use the exact 50 titles in the approved design spec. Each item includes `series_slot` 1—50, `batch_number` 1—5, `batch_slot` 1—10, `category`, `topic`, `content_profile`, and `status: planned`. Validate all three number sequences and uniqueness.

- [ ] **Step 3: Write Batch 01 topic input**

Use these exact categories and titles:

```json
[
  ["afternoon_rhythm", "午饭后总想打盹，先观察3件事"],
  ["meal_pace", "吃饭太快，下午状态有什么不同"],
  ["meal_comfort", "午餐吃得太撑，下午怎么安排更舒服"],
  ["after_meal_routine", "饭后一直坐和轻松走动，感受有什么不同"],
  ["afternoon_reset", "下午没精神，试试3分钟状态重启"],
  ["nap_rhythm", "午休后更困？先看入睡和醒来时间"],
  ["coffee_timing", "下午总靠咖啡顶，先记录饮用时间"],
  ["snack_trigger", "午后嘴馋，先分清饿、渴还是习惯"],
  ["work_rhythm", "下午最难的任务，什么时候做更顺"],
  ["weekly_pattern", "连续7天，找到自己的午后规律"]
]
```

- [ ] **Step 4: Start the isolated batch**

Run:

```powershell
uv run python "09_泛健康日更/scripts/health_batch.py" start-batch `
  --date 20260810 `
  --output "09_泛健康日更/data/01_一般生活方式50集/batch-01" `
  --topics-file "09_泛健康日更/data/01_一般生活方式50集/batch-01-inputs.json"
```

Expected: exit 0, ten `research_pending` topics, four-platform human-only policy, no changes under `data/00_十主题滚动库/`.

- [ ] **Step 5: Verify hashes and commit Task 2**

```powershell
uv run python "09_泛健康日更/scripts/health_batch.py" status --batch "09_泛健康日更/data/01_一般生活方式50集/batch-01/active-batch.json"
git diff --check
git add 09_泛健康日更/data/01_一般生活方式50集
git commit -m "content: initialize 50-episode wellness series"
```

---

### Task 3: Build the premium account brand system

**Files:**
- Create: `09_泛健康日更/branding/生活节奏看得见/brand-lock-v01.md`
- Create: `09_泛健康日更/branding/生活节奏看得见/prompts/avatar-prompts-v01.md`
- Create: `09_泛健康日更/branding/生活节奏看得见/avatar/avatar-candidate-01.png`
- Create: `09_泛健康日更/branding/生活节奏看得见/avatar/avatar-candidate-02.png`
- Create: `09_泛健康日更/branding/生活节奏看得见/avatar/avatar-candidate-03.png`
- Create: `09_泛健康日更/branding/生活节奏看得见/avatar/avatar-final.png`
- Create: `09_泛健康日更/branding/生活节奏看得见/cover/cover-template-v01.svg`
- Create: `09_泛健康日更/branding/生活节奏看得见/cover/cover-template-v01.png`
- Create: `09_泛健康日更/branding/生活节奏看得见/qa/brand-contactsheet-v01.png`
- Create: `09_泛健康日更/branding/生活节奏看得见/qa/brand-qa-v01.md`

**Interfaces:**
- Consumes: exact name, bio, and avatar concept from the design spec.
- Produces: one approved avatar, deterministic cover system, color/type/spacing tokens used by all episodes.

- [ ] **Step 1: Lock premium visual tokens**

Specify: deep teal `#087F78`, fresh teal `#10BFAE`, warm cream `#FFF8EC`, pale peach `#F5C79E`, charcoal `#24313D`; one display Chinese font and one body Chinese font available locally; 24 px corner radius; 8 px spacing grid; no clinical blue, red alert, anatomy, glossy medical-tech gradients, or pseudo-professional seals.

- [ ] **Step 2: Generate three avatar candidates with the built-in image generator**

Use three distinct compositions of sunlight, plate, and walking path. Require a flat, memorable silhouette, no text, no person, no organ/anatomy, no health cross, no device, no watermark. Copy every retained candidate into the workspace and record its final prompt.

- [ ] **Step 3: Select and crop the final avatar**

Check at 1024, 256, 96, and 48 px. The symbol must remain recognizable at 48 px and preserve at least 12% empty margin. Save the selected source as `avatar-final.png`; do not overwrite candidates.

- [ ] **Step 4: Build the deterministic cover template**

Create an editable SVG with generated-illustration slot, 8—12 Chinese-character headline slot, small series marker, no logo-like medical badge, and the cross-platform safe area. Render to PNG and inspect both full frame and safe preview.

- [ ] **Step 5: Run brand QA and commit**

Record legibility, small-size recognition, forbidden-symbol scan, exact name/bio, and color contrast. Commit only approved brand files:

```powershell
git add 09_泛健康日更/branding/生活节奏看得见
git commit -m "design: add premium lifestyle brand system"
```

---

### Task 4: Build authoritative evidence and claim boundaries for all ten episodes

**Files:**
- Create: `09_泛健康日更/work/HC20260810-001/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-002/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-003/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-004/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-005/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-006/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-007/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-008/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-009/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-010/research/fact-card.md`
- Create: `09_泛健康日更/work/HC20260810-B01-evidence-index.md`

**Interfaces:**
- Consumes: Batch 01 topics and official primary sources.
- Produces: one bounded, source-backed claim bundle per episode plus a batch evidence index.

- [ ] **Step 1: Define the fact-card contract**

Each card contains: everyday question, one conservative conclusion, three observable variables, one minimum action, applicable audience, excluded situations, safety boundary, official source title/publisher/date/URL, verbatim-quote count, and forbidden extrapolations.

- [ ] **Step 2: Research only authoritative primary sources**

Prefer Chinese government health guidance, national standards, official public-health bodies, and primary research when an official public guide is unavailable. Do not use marketing pages, influencer posts, aggregator articles, or copied platform captions. Record publication dates and exact supporting sections.

- [ ] **Step 3: Write ten fact cards**

Keep conclusions observational. Do not claim that a meal, coffee, nap, walk, or habit prevents, diagnoses, treats, or reverses a disease. Do not prescribe a universal duration or quantity unless the primary source explicitly supports it and the wording remains general-wellness safe.

- [ ] **Step 4: Run a forbidden-language scan**

Scan public claim fields for all Global Constraint terms. Any hit fails closed unless it appears only in a private “forbidden extrapolations” section.

- [ ] **Step 5: Commit Task 4**

```powershell
git add 09_泛健康日更/work/HC20260810-*/research 09_泛健康日更/work/HC20260810-B01-evidence-index.md
git commit -m "content: add batch 01 evidence cards"
```

---

### Task 5: Write premium scripts, storyboards, article copy, and four-platform packaging

**Files:**
- Create per episode: `manifest.json`
- Create per episode: `production/v01/00_lock/platform-brand-lock.md`
- Create per episode: `production/v01/02_script_storyboard/narration-v01.md`
- Create per episode: `production/v01/02_script_storyboard/storyboard-v01.md`
- Create per episode: `production/v01/02_script_storyboard/article-cards-v01.md`
- Create per episode: `production/v01/02_script_storyboard/platform-copy-v01.md`
- Create: `09_泛健康日更/work/HC20260810-B01-script-matrix.csv`
- Create: `09_泛健康日更/work/HC20260810-B01-content-qa.md`

**Interfaces:**
- Consumes: Task 3 brand lock and Task 4 fact cards.
- Produces: ten complete content packages ready for internal review and image production.

- [ ] **Step 1: Assign non-repeating hook types**

Use this exact order: scene empathy, behavior contrast, three-item checklist, seven-day observation, execution failure, time contrast, object cue, self-question, work-scene contrast, weekly summary. Adjacent episodes must not share the same primary setting or closing sentence.

- [ ] **Step 2: Write ten 50—60 second narrations**

Target 165—195 Chinese characters each and 3.0—3.7 Chinese characters per spoken second. Each narration must contain one hook, three concrete observations/actions, one minimum experiment, one safety boundary where relevant, and one honest save reason. Do not use “专家、研究表明、一定、必须、最、立刻见效”.

- [ ] **Step 3: Write 8—10-shot storyboards**

Every shot declares start/end time, visual purpose, action, camera, deterministic overlay, forbidden objects, reusable asset status, and Grok duration. Use home/office/table/community/walking environments only. Do not use a generic phone UI unless it is a system reminder or neutral checklist.

- [ ] **Step 4: Write seven-page article copy**

Page roles: cover, relatable scene, observation one, observation two, observation three, smallest experiment, summary/save card. Each page has one idea, title ≤14 Chinese characters, body ≤72 Chinese characters, and no paragraph copied verbatim from narration.

- [ ] **Step 5: Write distinct four-platform packaging**

For each platform provide three titles, two cover texts, one body, 3—5 tags, one pinned comment, and one interaction question. Scan all copy for banned medical signals and exaggerated promises.

- [ ] **Step 6: Score and self-review**

Complete the 100-point matrix. Any episode below 92 or any dimension below its floor returns to rewrite. The batch matrix must also confirm: ten unique hooks, at least five environments, no repeated first sentence, no repeated CTA in adjacent episodes, and no public forbidden term.

- [ ] **Step 7: Commit Task 5**

```powershell
git add 09_泛健康日更/work/HC20260810-*
git commit -m "content: write premium batch 01 packages"
```

---

### Task 6: Create the recurring-character reference and 80—100 approved first frames

**Files:**
- Create: `09_泛健康日更/branding/生活节奏看得见/character/character-lock-v01.md`
- Create: `09_泛健康日更/branding/生活节奏看得见/character/character-reference-v01.png`
- Create per episode: `production/v01/03_first_frames/base/*`
- Create per episode: `production/v01/03_first_frames/HC20260810-NNN-v01-SNN-firstframe.png`
- Create per episode: `production/v01/05_qa/firstframes-contactsheet-v01.png`
- Create per episode: `production/v01/05_qa/first-frame-qa-v01.md`

**Interfaces:**
- Consumes: Task 3 brand system and Task 5 storyboard specifications.
- Produces: one locked recurring character and every approved Grok input frame.

- [ ] **Step 1: Generate and approve the character reference**

Create front, three-quarter, side, seated, standing, and walking views of the same 45-year-old Chinese woman: shoulder-length black hair, beige cardigan, muted blue inner shirt, navy trousers, natural proportions. No professional clothing or role cues. Validate face, hair, clothing, age, and proportions.

- [ ] **Step 2: Build a per-shot asset matrix before generation**

Mark each shot `new`, `safe-reuse`, or `deterministic-board`. Reuse only project-generated assets with matching semantics; no asset from v03 containing devices, medical UI, clinicians, symptom gestures, or medical copy may enter.

- [ ] **Step 3: Generate new raster first frames one shot at a time**

Use the built-in image generator. Save every selected project-bound image in its episode directory. For cover shots and shots with visible hands, food, phone, stairs, or driving props, generate at least two candidates and retain rejected variants under `_rejected/` with a written reason.

- [ ] **Step 4: Apply deterministic text and icon layers only to review previews**

Keep Grok inputs text-free. Store review previews containing Chinese overlays in `storyboard_with_copy/`; never pass those previews to Grok.

- [ ] **Step 5: Run visual QA for every frame**

Check 1080×1920 dimensions, safe space, character identity, hand count, food/object count, phone ratio 1:2.0—1:2.2 when present, no paper/pen/notebook, no medical signal, no text/logo/watermark, and action clarity at thumbnail size.

- [ ] **Step 6: Build batch contact sheets and commit**

Create one contact sheet per episode and one batch contact sheet. Commit only approved frames, documented sources, and QA records.

---

### Task 7: Produce premium article-card illustrations and deterministic layouts

**Files:**
- Create per episode: `production/v01/03_article_images/source/illustrations/*`
- Create per episode: `production/v01/03_article_images/source/A01.svg` through `A07.svg`
- Create per episode: `production/v01/03_article_images/A01.png` through `A07.png`
- Create per episode: `production/v01/03_article_images/cover-v01.png`
- Create per episode: `production/v01/05_qa/article-contactsheet-v01.png`
- Create per episode: `production/v01/05_qa/article-qa-v01.md`

**Interfaces:**
- Consumes: approved copy from Task 5, brand tokens from Task 3, and approved illustrations from Task 6 or new built-in image generation.
- Produces: seventy final 1080×1920 article cards.

- [ ] **Step 1: Define seven visually distinct page archetypes**

Use hero cover, scene crop, three icon-led observation pages, one action page, and one summary card. Rotate illustration placement across episodes while preserving brand hierarchy.

- [ ] **Step 2: Generate missing illustrations**

Use built-in image generation for raster lifestyle scenes; no in-image text. Do not stretch video first frames when a dedicated crop would materially improve the card.

- [ ] **Step 3: Render deterministic Chinese layouts**

Create editable SVG sources and render PNGs. Verify fonts are embedded or available, punctuation is correct, and line breaks are intentional.

- [ ] **Step 4: Render a dedicated platform cover**

Use the approved cover template, one episode-specific illustration, and one 8—12 character headline. Do not simply crop A01 when the platform cover needs a stronger focal point. Inspect full-frame and center-crop previews without adding platform logos.

- [ ] **Step 5: Run article QA**

Check 70/70 dimensions, safe area, title/body size, no clipped text, no repeated typo, no forbidden term, no clinical symbol, and readability at 25% scale. Build per-episode and batch contact sheets.

- [ ] **Step 6: Commit Task 7**

```powershell
git add 09_泛健康日更/work/HC20260810-*/production/v01/03_article_images 09_泛健康日更/work/HC20260810-*/production/v01/05_qa/article-*
git commit -m "design: render batch 01 article cards"
```

---

### Task 8: Prepare and pass the internal factual/originality review gate

**Files:**
- Create per episode: `production/v01/01_evidence/review-handoff-v01.md`
- Create: `09_泛健康日更/work/HC20260810-B01-review-index.md`
- Modify after real review: each episode `manifest.json`

**Interfaces:**
- Consumes: evidence, scripts, storyboards, article copy, images, and hashes.
- Produces: one immutable review package per episode and externally supplied reviewer records; no public medical identity.

- [ ] **Step 1: Build ten hash-bound review handoffs**

Each handoff binds content ID, topic, fact card, narration, storyboard, article copy, platform copy, first-frame contact sheet, article contact sheet, and SHA-256 values.

- [ ] **Step 2: Pause for real review**

Request one real reviewer/time/decision per content ID or one batch approval that explicitly lists all ten IDs and hashes. Do not reuse the 2026-08-09 v03 approval and do not invent a reviewer signature.

- [ ] **Step 3: Record approved results privately**

Write approval into the existing internal `medical_review` field for contract compatibility, but keep reviewer identity and the word “medical” out of all public packaging.

- [ ] **Step 4: Advance each topic through the supported CLI**

Advance `research_pending → medical_review_pending → approved → production` only after valid review. Verify every state transition and current-batch reference hash.

- [ ] **Step 5: Commit Task 8 records**

Commit only public-safe artifacts and permitted review records; never commit private keys, credentials, cookies, sessions, or unsigned placeholder approvals.

---

### Task 9: Build ten Grok browser-extension manual generation packs

**Files:**
- Create per episode: `production/v01/04_grok_batch/manual_pack/01_first_frames/*`
- Create per episode: `production/v01/04_grok_batch/manual_pack/HC20260810-NNN-v01-Grok-prompts.txt`
- Create per episode: `production/v01/04_grok_batch/manual_pack/MANUAL-GENERATION-GUIDE.md`
- Create per episode: `production/v01/04_grok_batch/manual_pack/MANIFEST.csv`
- Create per episode: `production/v01/04_grok_batch/manual_pack/MANUAL-PACK-QA.md`

**Interfaces:**
- Consumes: approved storyboards and text-free first frames.
- Produces: manual-only upload packages for the user.

- [ ] **Step 1: Write one bilingual prompt per shot**

Each prompt locks composition, character, object count, one restrained action, camera motion, and all forbidden additions. Prompts contain no request for generated text or UI.

- [ ] **Step 2: Consolidate prompts exactly**

One physical line per shot, one blank line between adjacent prompts, no extra headings, and shot numbers continuous within each episode.

- [ ] **Step 3: Copy exact first-frame bytes into each pack**

Verify SHA-256 equality between pack copies and approved sources. Do not use review previews with Chinese overlays.

- [ ] **Step 4: Validate the ten packs**

Check expected image count, prompt count, blank-line count, dimensions, source hashes, output naming, and existence of raw-video destination directories.

- [ ] **Step 5: Pause for user-operated Grok generation**

The user uploads each frame and prompt through the Grok browser extension, downloads the clips, and provides the containing folder. No automated Grok call is permitted.

---

### Task 10: Ingest and audit all returned Grok clips

**Files:**
- Create per episode: `production/v01/05_grok_videos/01_raw/download_take01/*`
- Create per episode: `production/v01/05_grok_videos/02_selected/SNN.mp4`
- Create per episode: `production/v01/05_grok_videos/02_selected/selected-manifest-v01.csv`
- Create per episode: `production/v01/05_grok_videos/03_qa/technical-inventory-v01.csv`
- Create per episode: `production/v01/05_grok_videos/03_qa/content-qa-v01.md`

**Interfaces:**
- Consumes: user-downloaded Grok clips and Task 9 manifest.
- Produces: only technically and visually approved selected clips plus exact usable intervals.

- [ ] **Step 1: Non-destructively archive every download**

Copy without renaming the source, record source/archive SHA-256, and retain all rejected candidates.

- [ ] **Step 2: Run full technical decode**

Use ffprobe and FFmpeg to verify codec, resolution, fps, duration, video/audio stream count, and complete decode. Technical PASS does not imply content PASS.

- [ ] **Step 3: Run dense visual and character QA**

Inspect first/middle/last plus at least 4 fps contact sheets. One-ticket rejects: extra limbs/fingers, face drift, object duplication, generated text/logo, medical object, paper/pen/notebook, camera contract break, missing required action, or insufficient clean duration.

- [ ] **Step 4: Create minimal regenerate packs**

Regenerate only failed shots, with one targeted change and versioned Take02/Take03 packages. Never overwrite originals or loosen a quality gate to avoid regeneration.

- [ ] **Step 5: Select exact-byte candidates**

Copy only PASS candidates to `02_selected`, record source hash and usable interval, and leave incomplete episodes outside final edit.

---

### Task 11: Generate and verify ten Mandarin voice packages

**Files:**
- Create per episode: `production/v01/06_edit/audio/voiceover-master.wav`
- Create per episode: `production/v01/06_edit/audio/voiceover-preview.mp3`
- Create per episode: `production/v01/06_edit/audio/audio-qa-v01.md`
- Create per episode: `production/v01/06_edit/subtitles/voiceover.srt`
- Create per episode: `production/v01/06_edit/subtitles/segment-timing.csv`

**Interfaces:**
- Consumes: approved narration and shot timing.
- Produces: normalized voice, exact subtitles, and shot timing contracts.

- [ ] **Step 1: Generate one consistent warm Mandarin female voice**

Use the same approved voice across all ten episodes. Avoid exaggerated broadcaster delivery, medical authority tone, and excessive speed.

- [ ] **Step 2: Normalize audio**

Render 48 kHz mono WAV and preview MP3 at −16.0 LUFS, true peak ≤−1.5 dBTP. Preserve natural pauses; do not compress speech to rescue an overlong script.

- [ ] **Step 3: Build exact SRT and timing CSV**

No subtitle overlap, no more than two lines, exact narration match after punctuation normalization, and final subtitle ends before the master duration.

- [ ] **Step 4: Run audio QA and commit**

Decode WAV/MP3 fully, verify duration, loudness, peak, sample rate, channel count, wording, and pronunciation. Commit only passing audio packages.

---

### Task 12: Compose ten final masters with deterministic Chinese graphics

**Files:**
- Create per episode: `production/v01/06_edit/project/edit-manifest-v01.json`
- Create per episode: `production/v01/06_edit/project/graphics/*`
- Create per episode: `production/v01/07_master/HC20260810-NNN-v01-master.mp4`
- Create per episode: `production/v01/07_master/HC20260810-NNN-v01-master-sha256.txt`

**Interfaces:**
- Consumes: selected Grok clips, approved deterministic graphics, voice, subtitles, and timing CSV.
- Produces: ten platform-ready visual masters, not yet approved for publication.

- [ ] **Step 1: Build the edit manifest**

List every source path, source hash, in/out time, speed exactly 1.0, transition, graphic layer, subtitle interval, and audio source. Grok audio must be muted.

- [ ] **Step 2: Assemble at 1080×1920 and 24 fps**

Use hard cuts or restrained 4—8 frame dissolves. No interpolation, looping, speed stretching, fake depth-of-field, or decorative motion that competes with comprehension.

- [ ] **Step 3: Add deterministic overlays**

Use brand colors and typography; one emphasis per shot. Keep copy within safe area and visible long enough to read. Do not add medical disclaimers because the content itself must remain non-medical.

- [ ] **Step 4: Encode final masters**

Use H.264 yuv420p, 1080×1920, 24 fps, AAC 48 kHz, and a visually transparent bitrate/quality setting. Record SHA-256.

- [ ] **Step 5: Decode and inspect every master**

Run complete decode, duration, black-frame, freeze-frame, silence, audio-peak, subtitle-safe-area, and random-frame checks before content review.

---

### Task 13: Run premium batch final QA and generate four-platform human-pending packages

**Files:**
- Create per episode: `production/v01/05_qa/final-qa-v01.md`
- Create per episode: `production/v01/05_qa/final-safe-zone-contactsheet-v01.png`
- Create per episode: `production/v01/08_publish_pack/publish-pack.json`
- Create: `09_泛健康日更/work/HC20260810-B01-final-qa-index.md`

**Interfaces:**
- Consumes: ten masters, article cards, manifests, evidence, internal review, automated QA, and a real independent final reviewer.
- Produces: ten finalized `human_pending` publish packages.

- [ ] **Step 1: Re-run automated QA from source bytes**

Do not trust prior status flags. Recalculate manifest validation, public forbidden-term scan, quality ≥92 and floors, platform count, seven-card count, media hashes, and full decode.

- [ ] **Step 2: Perform independent human final review**

Reviewer must differ from the internal factual reviewer. Review video, sound, subtitles, card set, cover, titles, captions, brand identity, medical-signal absence, and four-platform safe areas.

- [ ] **Step 3: Fix and re-review any failed episode**

An episode with any P1/P2 issue remains blocked; do not average quality across the batch. Regenerate the smallest defective unit and repeat its dependent QA.

- [ ] **Step 4: Advance and create publish packs**

Advance each topic through `automated_qa_passed → final_qa_passed → ready_to_publish`, then generate four-platform `human_pending` packages. Do not mark published.

- [ ] **Step 5: Verify ten complete release bundles**

Each bundle contains master, cover, seven cards, four platform packages, source list, authorization record, final QA identity/time, and hashes. Confirm `CURRENT` points only to a version that passed every gate.

- [ ] **Step 6: Commit Task 13**

```powershell
git add 09_泛健康日更/work/HC20260810-*
git commit -m "release: finalize premium wellness batch 01"
```

---

### Task 14: Create the ten-day release calendar and honest data feedback loop

**Files:**
- Create: `09_泛健康日更/outputs/生活节奏看得见/batch-01/release-calendar.csv`
- Create: `09_泛健康日更/outputs/生活节奏看得见/batch-01/profile-update-copy.md`
- Create: `09_泛健康日更/outputs/生活节奏看得见/batch-01/manual-publish-checklist.md`
- Create: `09_泛健康日更/data/01_一般生活方式50集/metrics/batch-01-metrics.csv`
- Create: `09_泛健康日更/data/01_一般生活方式50集/metrics/README.md`

**Interfaces:**
- Consumes: ten `human_pending` release packages.
- Produces: manual daily schedule and empty 24h/72h/168h metrics rows for each platform/format.

- [ ] **Step 1: Prepare the manual account-profile update pack**

Provide exact name `生活节奏看得见`, exact bio `记录睡眠、进餐和日常活动中的小习惯`, approved avatar path, and per-platform preview checklist. The user manually changes each account; the project does not log in or store credentials.

- [ ] **Step 2: Schedule one episode per day**

Assign ten consecutive dates only after the account restriction and manual publishing status are checked. Do not invent an end date for the 30-day restriction; the user verifies the platform account state before Day 1.

- [ ] **Step 3: Build per-platform manual checklists**

Require account name/avatar/bio match, correct master, correct cover/cards, AI-generation label where the platform asks, title/body/tags, no medical signal, and a screenshot of final preview before manual submission.

- [ ] **Step 4: Create empty metric snapshots**

For each content/platform/format create unique 24h, 72h, and 168h rows. Leave unavailable fields blank, never zero-fill, and keep review/limitation status explicit.

- [ ] **Step 5: Verify the buffer and stop before publishing**

Confirm ten ready packages and ten calendar rows. Final platform submission remains a user action. After real 72h data for at least three episodes, start the separate Batch 02 implementation plan.

- [ ] **Step 6: Commit Task 14**

```powershell
git add 09_泛健康日更/outputs/生活节奏看得见/batch-01 09_泛健康日更/data/01_一般生活方式50集/metrics
git commit -m "ops: add batch 01 release and metrics workflow"
```

---

## Plan Self-Review Checklist

- Every approved design requirement maps to a task: account packaging (Task 3), 50-topic inventory (Task 2), first ten complete episodes (Tasks 4—13), four-platform packaging (Tasks 5 and 13), data feedback (Task 14), and no-medical boundary (Tasks 1, 4, 5, 6, 13).
- The blocked legacy batch is preserved and never used as the new active Batch 01.
- External gates are explicit: real internal review, user-operated Grok generation, independent final QA, and manual platform publishing.
- Top quality is measurable through score floors, image/video/audio specifications, candidate generation, dense visual QA, and per-episode fail-closed review.
- No task assumes medical qualification, reuses the old v03 approval, or publishes medical devices/apps.
- No task logs or stores credentials.
