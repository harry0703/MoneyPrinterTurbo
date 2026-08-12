# Merge Note — sync with upstream v1.3.4

Date: 2026-08-12
Branch: `sync-upstream-v1.3.4`
Merge: `origin/main` (fork, 15 commits) ← `upstream/main` (harry0703/MoneyPrinterTurbo, v1.3.4, 49 commits)

## What this merge is

A full sync of this fork onto upstream **v1.3.4** while preserving the fork's
distinctive feature: **idempotent video submission with client-assigned task IDs**
(`idempotency_key`). The two sides both rewrote the same core modules
(`TaskManager`, `RedisTaskManager`, `state.py`) in divergent ways; this merge
reconciles them by keeping each side's *complementary* value and consciously
dropping the parts upstream superseded.

## Key upstream features pulled in

- **v1.3.3 / v1.3.4**: ElevenLabs video-matched music, Sonilo video-matched BGM,
  preserve API keys on restart, output-folder preference.
- **WebUI modernization**: subject-named downloads, non-blocking update checks,
  full voiceover preview, custom BGM upload, global clip-speed multiplier.
- **Video pipeline**: ZoomIn/ZoomOut transitions, duration safety buffer, stock
  video orientation matching, material provenance + provider caching, Whisper
  `initial_prompt` config, cross-post state tracking.
- **Task execution hardening** (`6b4dd6f`): stage/error persistence
  (`failed_stage`, `error`), interrupted cross-post recovery, concurrency-count
  pre-reservation, stale-queued-task dropping.
- **Deps/tooling**: `google.generativeai` → `google-genai`, widened Python
  range (`>=3.11`), `.gitattributes` line-ending normalization.

## Resolution decisions (per file)

| File | Decision |
|---|---|
| `app/controllers/manager/base_manager.py` | **Upstream wholesale** + thin `submit_idempotent` (accept → enqueue → `check_queue`) + `enqueue_transaction` compat method. **Dropped**: dispatcher thread, owner-safe dispatch claims, renewal, deferred acknowledgements. |
| `app/controllers/manager/redis_manager.py` | **Upstream wholesale** (plain `lpop` queue, stale-task validation) + `_serialize_task` helper + `enqueue_transaction` for atomic idempotent acceptance. **Dropped**: claim keys, processing-deadline zset, terminal markers. |
| `app/services/state.py` | **Upstream base** (`patch_task`, cross-post) + fork's idempotency layer (`IdempotentAcceptance`, `reserve/get/abort/accept_idempotent_task`) as additive methods. Redis `accept_idempotent_task` re-expressed without terminal markers. |
| `app/models/const.py` | Both idempotency **and** cross-post constants; **re-added `TASK_STATE_QUEUED=0`** (upstream removed it; fork's controller emits it). Dropped `TASK_TERMINAL_MARKER_PREFIX`. |
| `app/controllers/v1/video.py` | Fork's submission path kept (preserves `state==0` queued semantics + idempotency 409s). Removed obsolete `wake_dispatcher()` nudge. |
| `app/asgi.py` | **Upstream lifespan** (cross-post recovery). Dropped fork's startup/shutdown dispatcher hooks. |
| `app/services/llm.py` | **Upstream refactor** + fork's qwen fix re-applied (`MultiModalConversation` + `enable_thinking=False`). Note: upstream's llm.py still used the old `dashscope.Generation` qwen path; the fork's fix remains genuinely needed. |
| `requirements.txt` / `pyproject.toml` / `uv.lock` | **Upstream deps** (`google-genai`, `dashscope==1.20.14`, `openai==2.24.0`). The fork's `requirements.txt` bumps (openai 2.36.0, dashscope 1.25.18) were never in `uv.lock`/`pyproject` and are not carried over. Dev deps consolidated: `fakeredis` + `httpx` folded into `[dependency-groups].dev` so the fork's idempotency tests run under the default `uv sync`. Lockfile regenerated with `uv lock`. |
| `config.example.toml` | Upstream base + fork's provider docs. Fork's duplicate `qwen_*` block dropped (upstream already has the keys; duplicates would be invalid TOML). |
| `.github/workflows/ci.yml` | **pytest runner** running **both** suites: upstream core-service tests + fork's `test_idempotency.py` / `test_idempotent_submission.py`. |

## What was consciously dropped (and why)

The fork's **dispatch-claims machinery** — the dispatcher thread, owner-safe
Redis leases (`_dispatch_claim_id`, renewal), `recover_expired_dispatches`,
terminal markers, and startup drain — was built against the *old* task manager.
Upstream **deliberately removed** the dispatcher and claims in their refactor and
did not adopt this pattern. Re-adding it would re-divergence from upstream, which
is the opposite of a sync. Dropped items:

- Dispatcher thread + `start/stop/wake_dispatcher` lifecycle.
- Redis owner claims, visibility leases, renewal, expired-claim recovery.
- `TASK_TERMINAL_MARKER` skip-replay logic.
- `asgi.py` startup drain of queued work.

**Consequence:** the fork no longer provides crash-safe recovery of *in-flight
Redis video tasks* (a worker dies mid-video → task is stuck). Upstream does not
cover this either (their startup recovery is cross-posts only), so this is
inheriting an upstream gap, not introducing a regression. If Redis crash-safety
matters, it should be built later as a visibility-lease consumer *on top of*
upstream's model.

## Test suite adaptation

The fork's `test_idempotency.py` (~927 lines) heavily tested the removed
dispatch-claims machinery. It was rewritten to cover only the surviving contract:

- Idempotency claim/lease contract (memory + Redis) — kept.
- Submission acceptance contract (accept → enqueue → dispatch; queue-full;
  thread-start failure retains queued work) — kept, one test adapted to the
  no-dispatcher model.
- Redis atomic-acceptance transaction tests (watch conflicts, wrong-type keys,
  serialization failure, lease expiry, concurrent owners, TTL) — kept verbatim.
- Dispatcher/recovery/terminal-marker tests — removed.

`test_state.py`: removed terminal-marker tests; kept idem-key listing test.
`test_idempotent_submission.py`: removed `stop_dispatcher` teardown and the
startup-drain test; rewrote the wake test as `test_queued_work_dispatches_when_capacity_returns`.

## Verification

- `uv lock` regenerated cleanly (126 packages; added `fakeredis`, `sortedcontainers`).
- `compileall` passes for `app cli.py main.py webui test`.
- `test/services/test_idempotency.py` + `test_idempotent_submission.py`: **37 passed**.
- Full suite: see CI / local `pytest -q test`.

## Follow-ups (not in this merge)

1. **Redis video-task crash recovery** (visibility-lease consumer on top of
   upstream's model) — if the fork's original restart-safety is still required.
2. Consumer-impact details are in [MIGRATION.md](./MIGRATION.md).

## Post-review hardening (code-review loop)

After the first code-review pass, addressed:

- `state.py`: extracted shared `_reserve_outcome` / `_task_record_fields`
  helpers (dedup across Memory/Redis adapters); `RedisState.get_idempotency`
  now reuses `_decode_idempotency`.
- `video.py`: a `STALE` acceptance now returns a distinct retryable
  `idempotency_stale` 409 (accurate message for one's own expired claim);
  covered by a new unit test.
- `llm.py`: removed dead `_extract_qwen_generation_text` / `_get_response_field`
  helpers left over from the qwen fix.
- `docs/idempotent-submission.md`: rewritten the restart/persistence section to
  match the merged (dispatcher-less) reality; documented empty-string
  `idempotency_key` as omitted.
- `base_manager.py`: documented the accept-then-dispatch queue-capacity
  policy (`max_queued_tasks + available_slots`).

Judgement-call items deliberately not changed (documented rationale in the
review): `IdempotentAcceptance` covers the `(task_id, params_hash, owner_token)`
clump where it matters; `accept_idempotent_task` reaching into the manager is
required for one atomic Redis transaction; `dequeue`'s `sm.state` use is
inherited upstream coupling; plain-string outcome constants match the existing
codebase pattern (incl. upstream's `CROSS_POST_STATE_*`).