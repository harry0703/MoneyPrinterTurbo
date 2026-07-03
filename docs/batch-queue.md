# Batch queue — generate many videos at once

`batch.py` lets you queue many video jobs in one command and drop every finished
video into an output folder you choose. Jobs run through a worker pool, so you can
control how many render at the same time. It reuses the exact same pipeline as the
WebUI/CLI (`app.services.task.start`).

## Where finished videos go

Videos are copied to the `--output-dir` (default: `$MPT_BATCH_OUTPUT`, or
`storage/output`). In Docker the image maps `/output` to the host folder set by
`MPT_OUTPUT_DIR` in `.env` (see `.env.example`), and the `api` service defaults
`MPT_BATCH_OUTPUT=/output`, so `docker compose run --rm api python batch.py …`
writes straight to your chosen host folder.

Each job produces `NNN-<slug>.mp4` (e.g. `001-benefits-of-walking.mp4`) plus a
`batch-manifest.json` summarising every job (status, task id, output files, errors).

## Providing the jobs

Three ways, combinable:

**1. Subjects on the command line** (`--subject`, repeatable):
```bash
docker compose run --rm api python batch.py \
  --subject "Benefits of walking" \
  --subject "How to save money" \
  --video-language en-US
```

**2. A text file** (`jobs.txt`, one subject per line, `#` for comments):
```
Benefits of walking
How to save money
# this line is ignored
```
```bash
docker compose run --rm api python batch.py --jobs-file jobs.txt
```

**3. A JSON file** for full per-job control (each object accepts any `VideoParams`
field):
```json
[
  { "video_subject": "Benefits of walking", "video_language": "en-US", "video_aspect": "9:16" },
  { "video_subject": "How to save money", "video_language": "en-US", "voice_name": "en-US-GuyNeural-Male" }
]
```
```bash
docker compose run --rm api python batch.py --jobs-file jobs.json --concurrency 2
```

## Options

| Flag | Meaning |
|------|---------|
| `--subject` | A subject; repeat for multiple videos. |
| `--jobs-file` | `.txt` (one subject per line) or `.json` (list of job objects). |
| `--output-dir` | Where finished videos are copied (default `$MPT_BATCH_OUTPUT` or `storage/output`). |
| `--concurrency` | How many videos to render at once (default `1`; rendering is CPU-heavy). |
| `--stop-at` | Stop each job early: `script`, `terms`, `audio`, `subtitle`, `materials`, `video` (default). |
| `--video-language`, `--video-source`, `--video-aspect`, `--video-count`, `--voice-name` | Defaults applied to every job unless a JSON job overrides them. |

If no voice is given, a free Edge TTS voice is chosen from the job's language
(e.g. `es-ES-ElviraNeural`, `ca-ES-JoanaNeural`, `en-US-JennyNeural`).

## Native (no Docker)

```bash
python batch.py --jobs-file jobs.txt --output-dir ./storage/output
```

The exit code is `0` only when every job succeeds, so it is safe to use in scripts.
