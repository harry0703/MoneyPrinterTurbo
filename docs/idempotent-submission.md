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
  legacy server-generated task id behavior. An empty string is treated as
  omitted (server-generated id).
- A non-UUID, non-empty `idempotency_key` is rejected with **HTTP 400**.

## Ordering and outcomes

The handler first creates a short-lived, owner-fenced `pending` claim. It then
publishes the task record, puts the work on the queue, and changes the claim to
`accepted` as one operation (under the state/manager locks for memory, or one
Redis transaction for Redis):

1. **First valid request** -> key is claimed, the task is created and durably
   accepted into the queue, and the response returns the client-assigned task
   id (`HTTP 200`). A task may remain `QUEUED` while workers are busy; this is
   accepted work, not a provisional record.
2. **Repeat with the same canonical parameters** -> the existing task id is
   returned (`HTTP 200`) and **no** duplicate work is enqueued. This is the
   lost-response recovery path: after a retry the client can
   `GET /api/v1/tasks/{task_id}` to read current status.
3. **Same key, different canonical parameters** -> rejected with **HTTP 409**
   and a stable `idempotency_conflict` message.
4. **Concurrent identical submissions** -> exactly one task is accepted; the
   rest wait for that atomic acceptance and return the same existing task id.
5. **Queue full** -> the request is rejected with **HTTP 429** and the
   pending claim is cleared by its owner so a later legitimate retry can
   proceed. Cleanup from an older owner cannot delete a newer retry.

If a submitter fails before atomic acceptance, its pending claim expires after
five seconds. An identical retry can then claim the key and submit safely. A
request that times out while another live owner is pending receives retryable
**HTTP 409** with `idempotency_pending`. Once accepted, duplicates return
**HTTP 200** immediately; they do not wait for a worker to start.

"Canonical parameters" are the full request payload hashed deterministically
(`json.dumps(..., sort_keys=True)` -> SHA-256), so field ordering and cosmetic
differences do not affect equality.

## Restart / persistence limitations

- The idempotency reservation is held in the same state adapter as task state:
  in-process memory for the default `MemoryState`, or Redis for `RedisState`.
- The in-memory adapter does **not** survive a process restart: after a restart
  a previously reserved key is unknown and a retry creates a new task. Use
  `RedisState` (set `enable_redis = true`) for cross-restart idempotency.
- Redis accepted records carry a 24h TTL. Pending claims use the five-second
  recovery lease described above.
- Queue dispatch is a plain FIFO (`lpop`): accepted work is dispatched when a
  concurrent slot frees (`task_done` -> `check_queue`) or on a later submission.
  If a worker thread cannot start, the item is returned to the queue and picked
  up by the next dispatch pass. There is **no autonomous dispatcher** and **no
  owner-token claim / lease renewal** around dequeued Redis work.
- Application startup does **not** drain queued Redis work; it only recovers
  interrupted cross-posts. After a restart, Redis-queued tasks sit until a new
  submission or a completing worker triggers `check_queue()`. A worker that dies
  mid-task is not automatically retried. This is an inherited upstream gap
  (upstream v1.3.x behaves the same); see `MERGE.md` for the rationale.
- Deleting a task (`DELETE /api/v1/tasks/{task_id}`) does **not** expire its
  idempotency reservation; a follow-up retry with the same key still returns the
  existing task id (the task record may no longer exist). This keeps retry
  semantics predictable and is only cleared on queue-full rejection.
