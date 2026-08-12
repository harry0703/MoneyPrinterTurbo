# Migration Note — for services depending on the MPT API

Applies to the merged result on `sync-upstream-v1.3.4` (fork + upstream v1.3.4).
Everything below was verified against the actual request/response schemas and
state constants on both sides; see [MERGE.md](./MERGE.md) for the merge decisions.

## TL;DR

For well-formed consumers, the API is **backward-compatible**: every endpoint
path, verb, request shape, response envelope, and status code you already use is
unchanged, and `idempotency_key` still works exactly as before. Four narrow
behaviors changed. Everything else is additive.

## What did NOT change (verified)

- **Endpoints**: all of `/api/v1/videos`, `/subtitle`, `/audio`, `/tasks`,
  `/tasks/{id}` (GET/DELETE), `/musics`, `/video_materials`, `/stream/*`,
  `/download/*` — same paths, same methods, same `/api/v1` prefix.
- **`task_id` format**: UUID on both sides (server-generated, or your
  `idempotency_key` verbatim).
- **Status codes**: 429 queue-full, 404 not-found, 400 validation, and the
  idempotency 409s (duplicate/pending/conflict) — all preserved.
- **State values**: COMPLETE=1, FAILED=-1, PROCESSING=4 unchanged.
- **State `==0` (queued)**: preserved — the fork's submission path is kept, so
  queued tasks still report `state: 0`.
- **`idempotency_key` contract**: client-assigned UUID used as the task id,
  retry returns the existing id (200), parameter mismatch returns 409
  `idempotency_conflict`, queue-full returns 429 and lets a later retry proceed.
- **qwen LLM behavior**: unchanged (the fork's `MultiModalConversation` fix is
  carried over; upstream's old `dashscope.Generation` path is replaced by it).

## What DID change — check these four

### 1. g4f LLM provider is removed
Upstream dropped the `g4f` provider (`enable_g4f`, `g4f_model_name`, and the
`llm_provider="g4f"` path are gone).
→ **Action**: migrate any g4f config/consumers to another provider.

### 2. Stricter request validation (new 422s)
`VideoParams` tightened two fields to `ge=1`:
- `video_count: 0` → now **422** (was accepted)
- `video_clip_duration: 0` → now **422** (was accepted)
→ **Action**: audit orchestration code for `0` in these two fields and send `≥1`.

### 3. `text_background_color` default flipped `true` → `false`
Omitting the field now renders subtitles differently (transparent background).
The field is still accepted if you send it explicitly.
→ **Action**: if you relied on the old default, set `text_background_color: true`
explicitly.

### 4. Redis task dispatch is no longer crash-safe mid-video
The fork's owner-safe Redis claims / dispatcher were dropped (see MERGE.md).
A worker that dies *after dequeuing a video task* leaves that task stuck in
upstream's model — this was already true of upstream v1.3.x; the fork no longer
patches it. In-memory (non-Redis) deployments are unaffected (only matters for
`enable_redis = true`).

## Additive changes you may adopt (optional)

- **New request fields** (all optional, defaults provided):
  `video_clip_speed` (global clip-speed multiplier), `video_music_prompt`,
  `sonilo_bgm_prompt`.
- **New providers/features**: cloudflare LLM, ElevenLabs + Sonilo BGM,
  cross-post status fields on tasks.
- **New task fields** in responses: `failed_stage`, `error`, `stage` on failures
  (additive; existing readers unaffected).
- **New config keys** (all optional): `cloudflare_*`, `sonilo_*`, `listen_host`,
  `listen_port`, `log_level`, `match_materials_to_script`, `music_model_id`,
  `music_timeout`, `open_task_folder_on_completion`,
  `upload_post_max_pending_tasks`.

## Deployment notes

- **Python**: `requires-python` widened `>=3.11,<3.13` → `>=3.11`; existing
  3.11/3.12 deployments are unaffected, 3.13 is now allowed.
- **Dependencies**: `google.generativeai` replaced by `google-genai`; `openai`
  stays `2.24.0`; `dashscope` stays `1.20.14`. Regenerate environments from the
  committed `uv.lock` (`uv sync`).
- **Config file**: remove g4f keys; nothing else is required.

## Suggested post-deploy acceptance checks

1. `POST /api/v1/videos` without `idempotency_key` → 200, task lifecycle reaches
   `state: 1` or `state: -1`.
2. Same request twice with an `idempotency_key` → both 200, same `task_id`,
   exactly one job.
3. Same key, different params → 409 `idempotency_conflict`.
4. `video_count: 0` → 422.
5. If you consumed `state: 0`: confirm queued tasks report it (they should).