# Creative Pipeline Orchestration (HTTP contract)

Contract for an external orchestrator (for example an OpenCode agent) that
drives the creative production pipeline through the MoneyPrinterTurbo HTTP
API. Every stage of the pipeline can be inspected and resumed through the
same endpoints; no other access is required.

## 1. Base URL and scope

- API base: `http://<host>:8080/api/v1` (deployment detail, not part of the contract).
- A creative task is a regular video task created with `creative_mode: true`.
- All `/creative/...` routes are only meaningful for creative tasks. The
  vanilla MoneyPrinterTurbo flow never imports or touches creative code.

## 2. Creating a creative task

`POST /videos`

```json
{
  "video_subject": "a short film about a harbor at dawn",
  "title": "Harbor Dawn",
  "video_length": 30,
  "voice_name": "en-US-AriaNeural",
  "creative_mode": true,
  "creative_brief": {
    "topic": "harbor at dawn",
    "audience": "short-form viewers",
    "tone": "contemplative",
    "visual_language": "natural light, slow camera"
  }
}
```

The response carries `task_id` and the initial state. From here on the
orchestrator only uses the task id.

## 3. Task states

| state | name                  | meaning                                             |
| ----- | --------------------- | --------------------------------------------------- |
| -1    | `failed`              | terminal failure; inspect `pipeline` for the stage  |
| 1     | `complete`            | terminal success; final video + handoff available   |
| 4     | `processing`          | running; poll until the state changes               |
| 5     | `waiting_for_director`| paused at the rough-cut checkpoint, awaiting a call |

Poll the raw state with `GET /tasks/{task_id}` (returns `state` and
`progress`). Poll the stage view with the pipeline endpoint below.

## 4. Pipeline view

`GET /creative/tasks/{task_id}/pipeline`

- `404` when the task id is unknown to the in-memory state store.
- Response payload:

```json
{
  "status": 200,
  "data": {
    "task_id": "...",
    "pipeline": {
      "task_id": "...",
      "task_state": 4,
      "state_name": "processing",
      "progress": 40,
      "stages": [{"name": "brief", "status": "done", "detail": "creative_brief.json"}],
      "shots": [{"index": 1, "source": "stock", "duration": 5.0, "asset_exists": true, "asset": "shot_001.mp4"}],
      "available_actions": []
    }
  }
}
```

### 4.1 Stages

Eleven stages, always returned in pipeline order:

`brief → script → shot_plan → audio → subtitle → materials → rough_cut →
director_review → final_video → qc → publish`

Stage statuses:

- `done` — the stage artifact exists on disk.
- `active` — the stage currently in flight. While the task is `processing`,
  exactly the first stage without its artifact is marked `active`
  (detail `current stage`), unless an earlier stage already is `active`
  (e.g. `materials` with partial assets). `director_review` is `active`
  while the task is `waiting_for_director`.
- `pending` — not reached yet.
- `skipped` — the task finished but an optional artifact is absent
  (for example no `subtitle.srt` because subtitles were disabled).
- `failed` — the task failed and this is the first stage whose artifact is
  missing; or the task is `complete` but no final video was found (anomaly).

Artifact mapping:

| stage            | artifact / source                          |
| ---------------- | ------------------------------------------ |
| brief            | `creative_brief.json`                      |
| script           | `script.json`                              |
| shot_plan        | `shot_plan.json`                           |
| audio            | `audio.mp3`                                |
| subtitle         | `subtitle.srt`                             |
| materials        | shot asset files referenced by `rough_cut.json` (`detail` is `N/M shot assets resolved`) |
| rough_cut        | `rough_cut.mp4` (plus the `rough_cut.json` timeline) |
| director_review  | task state `waiting_for_director`          |
| final_video      | `final-*.mp4`                              |
| qc               | `qc_report.json`                           |
| publish          | exportable once a final video exists       |

### 4.2 Shots

`shots[]` mirrors the rough cut timeline (empty until the rough cut exists):
`index` (1-based), `source` (`stock`, `local`, `generated_image`,
`generated_video`, `graphic`, `archive`), `duration` (seconds),
`asset_exists`, `asset` (file name).

### 4.3 available_actions

- state `5` (waiting_for_director): `approve`, `resume`, `get_rough_cut`,
  `regenerate_shot`, `reorder_shots`, `set_shot_duration`,
  `replace_shot_asset`, `delete_shot`, `qc`
- state `1` (complete): `qc`, `premiere`
- any other state: `[]`

## 5. Director actions (state 5)

| action             | endpoint                                        | body |
| ------------------ | ----------------------------------------------- | ---- |
| approve            | `POST /creative/tasks/{id}/approve`             | —    |
| resume             | `POST /creative/tasks/{id}/resume`              | —    |
| get_rough_cut      | `GET /creative/tasks/{id}/rough_cut`            | —    |
| regenerate_shot    | `POST /creative/tasks/{id}/shots/{i}/regenerate`| `{"prompt": "optional", "provider": "optional"}` |
| reorder_shots      | `POST /creative/tasks/{id}/shots/reorder`       | `{"order": [3, 1, 2]}` (1-based indices, full order) |
| set_shot_duration  | `POST /creative/tasks/{id}/shots/{i}/duration`  | `{"duration": 6.5}` (> 0.5, ≤ 600) |
| replace_shot_asset | `PUT /creative/tasks/{id}/shots/{i}`            | `{"asset_path": "/absolute/path.mp4"}` |
| delete_shot        | `DELETE /creative/tasks/{id}/shots/{i}`         | —    |
| qc                 | `GET /creative/tasks/{id}/qc`                   | —    |

`approve` (or `resume`) re-enters the queue: the state goes back to `4` and
the final video is rendered, then the task completes.

`regenerate_shot` provider override: `provider` is the name of a registered
image/video provider (for example `comfyui`, `drawthings`, `kling`). When
omitted, the shot's stored provider is used, then the configured default
image provider, then `comfyui`. A 404 is returned when the named provider is
not available in this deployment.

## 6. Completion actions (state 1)

- `qc` — `GET /creative/tasks/{id}/qc`: advisory QC report (issues list,
  durations, asset checks). It does not block completion.
- `premiere` — `GET /creative/tasks/{id}/premiere`: downloads a zip with the
  Premiere Pro handoff (4.1 XML sequence referencing the final video and
  media). This is the publish handoff; nothing is published automatically.

## 7. Orchestration loop (reference)

```bash
API=http://localhost:8080/api/v1
TASK=<task_id>

while :; do
  STATE=$(curl -s "$API/tasks/$TASK" | jq -r '.data.state')
  curl -s "$API/creative/tasks/$TASK/pipeline" | jq -c '.data.pipeline'

  case "$STATE" in
    4) sleep 15 ;;                       # processing: inspect stages
    5) # decide: approve or edit shots first
       curl -s -X POST "$API/creative/tasks/$TASK/approve" ;;
    1) break ;;                          # done: fetch qc / premiere
    *) echo "task failed"; break ;;
  esac
done
```

## 8. Caveats

- Task state lives in memory. After an API restart, old task ids return
  `404` on `/tasks/{id}` and `/creative/.../pipeline`, while the artifacts
  on disk (`storage/tasks/{id}/`) persist and can still be re-inspected
  directly.
- The `active` marker is a heuristic derived from state + artifacts; treat
  `done`/`skipped`/`failed` as the stable facts and `active`/`pending` as
  guidance for what to wait for.
- No deployment-specific values appear in the contract; the base URL, the
  available providers, and the TTS voices are deployment details.
