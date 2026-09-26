# AI Video Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement each project plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend MoneyPrinterTurbo into a scene-driven video production system that improves factual and visual quality first, then supports reviewed scheduling, publishing, and feedback.

**Architecture:** Keep the current FastAPI, Streamlit, MoviePy/FFmpeg, and provider integrations. Add a versioned `ProductionPlan` artifact per task. Scene IDs connect narration spans, claims, visual candidates, selected assets, edit decisions, subtitles, costs, and review findings. The existing pipeline remains the legacy path behind an opt-in `director_mode` switch until the new path passes evaluation.

**Tech Stack:** Python 3.11+, Pydantic, FastAPI, Streamlit, MoviePy 2, FFmpeg, pytest; existing Redis task state and provider adapters. Add durable storage and a worker only when scheduling and analytics require it.

**Spec:** User-provided `C:/Users/awwh9/.codex/attachments/6872f4a9-3643-473b-a6e7-02c3387c3a64/Pasted text.txt` (AI Video Autopilot proposal). This document is a program roadmap; each phase gets a small task-level plan before coding.

## Global constraints

- Preserve existing API, CLI, and WebUI behavior when `director_mode=false`.
- Use existing stock, image/video, TTS, music, TwelveLabs, and Upload-Post adapters where possible. Provider availability and current contract must be checked before committing to an integration.
- No publish action before the task is approved in the first production release. Disable the existing `upload_post_auto_upload` path for director-mode tasks until the approval gate is implemented.
- Store source attribution, prompt/model version, scores, reasons, timings, and cost with each task. Never persist API keys or signed media URLs in public artifacts.
- Treat AI review scores as ranking signals. Deterministic checks and human review control publication until scores are calibrated on real videos.
- Use a task-local immutable artifact/version for each stage so retries do not repeat paid work or silently change a previously approved video.

## Baseline in this repo

| Existing capability | Current location | Change needed |
| --- | --- | --- |
| Script, search terms, TTS, subtitles, materials, render, cross-post sequence | `app/services/task.py` | Insert typed scene and review stages without breaking partial endpoints |
| Global clip duration/speed and sequential stock matching | `app/models/schema.py`, `app/services/video.py` | Add per-scene timing and speed; retain global legacy settings |
| Stock search and generated visual sources | `app/services/material.py` | Search multiple queries per scene and return ranked candidates |
| 24-hour search-result cache and material source manifest | `app/services/material_cache.py`, `app/services/task_artifacts.py` | Extend to validated downloaded-asset catalog, usage history, and provenance |
| Optional TwelveLabs term rerank and clip analysis | `app/services/twelvelabs.py` | Adapt analysis to candidate evaluation; add provider-neutral interface |
| Social title/caption/hashtags and Upload-Post | `app/services/llm.py`, `app/services/upload_post.py` | Add approval-aware publish and cover creation |
| Memory/Redis task state and Streamlit task history | `app/services/state.py`, `webui/Main.py` | Add production lifecycle, review details, and durable scheduler state |

## Project sequence

### Phase 0 — Baseline and contracts

**Deliverable:** Reproducible evaluation set and a versioned scene contract. No production behavior change.

- [ ] Collect 10–20 representative scripts and outputs across technical explanation, footage-rich subjects, missing-stock topics, portrait crop, custom audio, and provider failure. Record baseline relevance, repetition, timing, subtitle legibility, render defects, elapsed time, and cost. Human reviewers rate footage against narration; keep sample media local or licensed for this use. Scoring rubric: `docs/ai-video-autopilot-evaluation.md`. Await real output videos; do not substitute synthetic scores.
- [x] Define `ProductionPlan` and `ScenePlan` in `app/models/production_plan.py`: stable `scene_id`, verbatim narration span, start/end after TTS alignment, intent, factual claims, visual strategy, query list, selected asset, source trim, clip speed, subtitle instructions, and review status. Define `CandidateAsset`, `ReviewFinding`, and stage/version metadata. Avoid scene text that diverges from spoken script.
- [x] Add atomic JSON read/write to `app/services/task_artifacts.py`; define backward-compatible API representation in `app/models/schema.py`. Invalid or older artifact versions fail with a named stage error, never silently render as an empty plan.
- [x] Add unit tests in `test/services/test_production_plan.py` for schema bounds, contiguous narration coverage, stable IDs, serialization/versioning, and corruption. Run `uv run python -X utf8 -m pytest -q test/services/test_production_plan.py`.

**Exit:** Every new-mode task can produce and reload a valid plan; legacy API behavior remains unchanged.

### Phase 1 — Scene-driven MVP (first shipping target)

**Deliverable:** A human-reviewed video whose scenes use relevant varied footage and narration-driven pacing. This is the four-improvement slice recommended in the proposal.

- [ ] **Scene planner and alignment.** Add `app/services/scene_planner.py`. Build scenes from the final script, then align to actual TTS/subtitle word timings; rebalance boundaries where speech pauses allow it. Insert into `task._run_pipeline` after audio/subtitles and before material retrieval. For custom audio, use transcription timing or fall back to sentence spans with a review warning. Persist `scene-plan.json`.
- [ ] **Multi-query search and candidate pool.** Add `app/services/visual_candidates.py`. Generate 2–4 concrete queries per scene; search configured stock sources through `material.py`; deduplicate by source asset ID/content hash; keep source/license metadata. Bound calls and downloads per scene. The existing 24-hour search cache remains intact. Persist candidate manifests before paid analysis.
- [ ] **Visual reviewer and diversity.** Add `app/services/visual_review.py` with a provider-neutral `review_candidate(scene, candidate)` adapter. Use cheap metadata/orientation and sampled frames first; send only finalists to a vision provider (including optional TwelveLabs). Score narration relevance, crop safety, visual style, and duplication against adjacent scenes. Reject candidates below a calibrated threshold; if review is unavailable, mark the scene for human review and use a conservative stock fallback. No fabricated “review passed” result.
- [ ] **Adaptive timing and render.** Add `app/services/scene_timing.py` and a scene-list rendering path in `app/services/video.py`. Compute scene duration from aligned narration with small lead/tail handles; clamp per-scene stock speed to the proposal's 0.85–1.35x range; derive source trim from output duration × speed. Keep TTS speed independent. Preserve the old `combine_videos` route for legacy tasks.
- [ ] **Final reviewer.** Add `app/services/final_review.py`. Deterministic gates: file decodes, duration covers speech, black/silent spans, crop/aspect, subtitle bounds, missing scene coverage. A vision pass samples scene boundaries and representative frames for mismatch/continuity; persist findings with timestamps and scene IDs. At first, a failed gate marks `NEEDS_REVIEW` and allows a bounded manual rerender of named scenes; automatic self-healing follows in Phase 2.
- [ ] **WebUI review and publish gate.** Add scene cards and a final verdict to `webui/Main.py`, with selected asset preview, source, timing, reviewer reason, override/retry, and render preview. Add i18n keys. `director_mode` is opt-in and defaults off. In `task._run_pipeline`, suppress the existing auto-upload path for director-mode tasks until Phase 3 approval transitions are in place. Preserve legacy task history.

**Tests:** `test/services/test_scene_planner.py`, `test_visual_candidates.py`, `test_visual_review.py`, `test_scene_timing.py`, `test_final_review.py`, plus pipeline/API and WebUI regression tests. Mock remote providers; use a small local media fixture to check playback speed, source continuity, and subtitle alignment. Run focused tests, then `uv run python -X utf8 -m pytest -q test` and `uv run ruff check app webui test`.

**Exit:** On the Phase 0 set, human reviewers see a measurable relevance improvement without increased repetition; all speech has matching visual coverage; no reviewer-failed video is queued for upload. Record actual baseline/new numbers before deciding a target threshold.

### Phase 2 — Editorial accuracy and finish

**Deliverable:** Factual and stylistically consistent videos with useful non-stock visuals and scene-level repair.

- [ ] **Research and fact checks:** `app/services/research.py`, `fact_check.py`; extract checkable claims and attach evidence URLs, source date, confidence, and correction. Run before TTS; block unsupported high-risk technical claims for human edit. Re-run downstream scene/voice artifacts only when the script changes. Tests cover a wrong technical claim and a source conflict.
- [ ] **Brand profile and hook:** versioned profile with style, voice, subtitle, music, and hook preferences; generate 3–5 hook candidates, record choice and reason. A profile change affects only new tasks or explicit regeneration. Tests cover reproducibility and language handling.
- [ ] **Visual strategy:** decide stock, generated image, diagram, or generated video per scene. Add a deterministic diagram renderer for labeled technical concepts; validate all labels against the fact-checked script. Reuse existing generated-media adapters only on stock failure or when the scene explicitly requires it. Add visual continuity and shot diversity checks across the whole plan.
- [ ] **Audio/text director:** per-segment TTS rate only where the selected voice adapter supports it; otherwise use a single rate and flag limitation. Use aligned subtitle chunks, keyword emphasis, brand font, and portrait safe-area constraints. Add music mood selection, narration-aware ducking, and sparse SFX. Keep narration intelligible under every mix.
- [ ] **Bounded repair:** map final-review findings to scene IDs; regenerate or replace only the affected scene and dependent render; cap attempts and paid spend; preserve previous render and audit trail. Failure after the cap remains `NEEDS_REVIEW`.

**Exit:** Human checks confirm factual claims have traceable evidence; subtitles and diagram labels stay in safe zones; repair changes only the flagged scene and its final composition.

### Phase 3 — Reliable two-videos-per-day operations

**Deliverable:** Scheduled generation with an approval queue, duplicate prevention, and recovery from interruption.

- [ ] **Content planner and memory:** add durable topic/script history, semantic similarity with normalized topic matching, series tags, and an override for legitimate follow-ups. Treat the proposal's `0.85` duplicate cutoff as an initial experiment, calibrated against labeled near-duplicate topics; never use it as a blind universal threshold.
- [ ] **Durable job queue:** introduce a persistent store for schedule, stage state, leases, attempts, and artifact pointers. Use one worker owner per task with idempotent stage keys. Enforce two daily *scheduled slots* in the configured channel timezone; missed slots and restarts recover without duplicate generation. Keep generation concurrency/cost caps explicit.
- [ ] **Recovery:** classify retryable provider/network errors versus content/permanent errors. Retry with capped backoff; move to fallback provider or visual strategy only when attribution and quality remain valid. Publishing failure retains `READY` or `PUBLISH_FAILED` for retry without generating a second video.
- [ ] **Approval UI/API:** distinct `GENERATING → NEEDS_REVIEW/READY_FOR_APPROVAL → APPROVED → PUBLISHING → PUBLISHED/PUBLISH_FAILED` transitions. Reviewer can inspect script, claims, scene sources, final video, score, cost, and metadata before approving. Authorized API actions use compare-and-set transitions to prevent double publication.

**Exit:** Restart the app/worker during each stage in a test environment; each slot yields at most one task and each approved task is published at most once. Run 30–50 reviewed videos before considering automatic approval.

### Phase 4 — Publishing and measurement

**Deliverable:** Auditable posting and performance feedback, still controlled by human approval by default.

- [ ] Generate cover/title/caption/limited relevant hashtags per platform; store exact approved metadata and cover with the render. Reuse existing `llm.py` social metadata and `upload_post.py`; verify current provider capabilities for covers, status, and analytics before implementation.
- [ ] Publish approved tasks only; persist remote request/post IDs, status, retries, and timestamps. Reconcile uncertain upload outcomes by remote ID before retrying. Never post the same approved render twice because of an HTTP timeout.
- [ ] Collect available metrics at 24h, 72h, and 7d; record missing metrics explicitly. Define a versioned performance score using available views, shares, comments, likes, and (when available) retention, normalized by age and account baseline.
- [ ] Add an experiment registry: vary one chosen factor (for example hook type), assign variants before generation, hold other settings steady, and compare only sufficiently sampled groups. Feed measured results to the content planner with an exploration quota (the proposal's 80/20 is a starting policy, not proof of optimality).

**Exit:** A published video can be traced from approved render to remote post and metric snapshots; experiment reports distinguish missing data from zero performance.

### Phase 5 — Cost control and guarded autopilot

**Deliverable:** Production controls that can safely support more volume.

- [ ] Instrument cost per provider call and per task, including retries; show estimated versus actual cost and stop paid stages at a configured budget. Add model routing by task difficulty and reviewer uncertainty.
- [ ] Extend the search cache into an asset catalog with content hash, source/license, quality, embedding, usage count, and last used. Prefer local assets when relevant, but penalize recent/overused clips. Respect source rights and deletion requests.
- [ ] Calibrate quality scores against human decisions. Only then allow a separately enabled autopublish policy with a documented score threshold (proposal example: 90/100), minimum evidence count, budget limit, deterministic gate pass, and an immediate off switch. Audit every automatic decision.

**Exit:** A failure of vision, analytics, model, music, or publisher does not result in an unreviewed post; costs and fallback decisions are visible per video.

## Review focus

The owning phase must add a test for each case below before merging:

1. **Custom audio with inaccurate/no transcript (Phase 1):** scene timings remain bounded by actual audio and the result requires review.
2. **No relevant stock or vision provider timeout (Phase 1):** the fallback is labeled and publication remains gated.
3. **Technical claim with contradictory sources (Phase 2):** the claim is not silently marked verified or spoken as settled fact.
4. **Worker restart or upload timeout (Phases 3–4):** no duplicate video task or duplicate remote post.
5. **Generated diagram labels and portrait subtitles (Phase 2):** text stays readable inside configured safe bounds.

## Release gates and order of work

Complete Phases 0 and 1 first; review the measured improvement before starting Phase 2. Phases 2 and 3 can then advance separately, but automatic posting waits for both editorial checks and a reliable approval state machine. Phases 4 and 5 depend on persistent task/post IDs. Keep one independent, testable plan per phase rather than implementing the entire proposal in one branch.

**Suggested first milestone:** Phase 0 plus Phase 1 with stock footage only, one portrait video at a time, opt-in `director_mode`, manual approval, and no automatic repair. This directly addresses the reported failures: wrong footage, monotonous pacing, fixed speed, and missing final QA.
