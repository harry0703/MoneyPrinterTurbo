# Idempotent video submission (client-assigned task IDs)

Video submission (`POST /api/v1/videos`) accepts an **optional**
`idempotency_key` in the request body. When supplied, its exact UUID value is
used as the MPT task id, so a client can safely retry a lost submission response
without creating a duplicate job.

## Request

```json
{
  "video_subject": "…",
  "idempotency_key": "11111111-1111-1111-1111-111111111111"
}
```

- `idempotency_key` is a `UUID` string. Omit it (or send `null`) to keep the
  legacy server-generated task id behavior.
- A non-UUID `idempotency_key` is rejected with **HTTP 400**.

## Ordering and outcomes

The handler reserves the key **atomically** (under a lock for the in-memory
state adapter, via an atomic `SET … NX GET` for the Redis adapter) before any
work is enqueued:

1. **First valid request** -> key is claimed, the task is created and enqueued,
   and the response returns the client-assigned task id (`HTTP 200`).
2. **Repeat with the same canonical parameters** -> the existing task id is
   returned (`HTTP 200`) and **no** duplicate work is enqueued. This is the
   lost-response recovery path: after a retry the client can
   `GET /api/v1/tasks/{task_id}` to read current status.
3. **Same key, different canonical parameters** -> rejected with **HTTP 409**
   and a stable `idempotency_conflict` message.
4. **Concurrent identical submissions** -> exactly one task is enqueued; the
   rest return the same existing task id.
5. **Queue full** -> the request is rejected with **HTTP 429** and the
   provisional idempotency state is cleared so a later legitimate retry can
   proceed.

"Canonical parameters" are the full request payload hashed deterministically
(`json.dumps(..., sort_keys=True)` -> SHA-256), so field ordering and cosmetic
differences do not affect equality.

## Restart / persistence limitations

- The idempotency reservation is held in the same state adapter as task state:
  in-process memory for the default `MemoryState`, or Redis for `RedisState`.
- The in-memory adapter does **not** survive a process restart: after a restart
  a previously reserved key is unknown and a retry creates a new task. Use
  `RedisState` (set `enable_redis = true`) for cross-restart idempotency.
- Redis reservations carry a 24h TTL so abandoned keys are eventually reclaimed.
- Deleting a task (`DELETE /api/v1/tasks/{task_id}`) does **not** expire its
  idempotency reservation; a follow-up retry with the same key still returns the
  existing task id (the task record may no longer exist). This keeps retry
  semantics predictable and is only cleared on queue-full rejection.
