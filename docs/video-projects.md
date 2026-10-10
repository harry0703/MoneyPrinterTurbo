# Editable local video projects

Change one scene without rendering the whole episode again. This opt-in CLI
snapshots prepared local footage and narration, records immutable revisions, and
reuses artifacts only when both their dependencies and SHA-256 integrity match.
It makes no API calls and does not publish videos. Existing generation jobs and
WebUI behavior are unchanged.

This is a revision/artifact foundation for the existing scene/director proposals,
not another director or paid-provider workflow. First generate/download the
footage and narration using the existing task pipeline or your preferred tools.
Use their local output paths below. Keep a scene's ID when replacing its media;
change the order in the manifest to reorder the video.

## Requirements

Python 3.11 or newer and FFmpeg/FFprobe on PATH, including the `libx264` encoder.
Prepared inputs must be standalone encoded media: MOV/MP4, Matroska/WebM, AVI,
MPEG-TS/video, Ogg, FLV, WAV, MP3, FLAC or AAC. HLS/DASH/concat playlists and
external-reference media are rejected; copying only a playlist would not snapshot
its referenced segments. Concat is permitted only for internally generated
assembly lists. Network protocols are disabled for all render inputs.
There are no new Python dependencies. Projects are local single-host stores;
network filesystems with unreliable locking are unsupported. Reserve enough disk
for source snapshots, retained revisions and exports. There is no automatic
artifact pruning or deletion of older successful exports.

## Create, inspect and render

Save `episode.json` beside your prepared assets:

```json
{
  "project_id": "product-episode",
  "settings": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "narration_volume": 1.0,
    "bgm_volume": 0.15
  },
  "scenes": [
    {
      "id": "opening",
      "footage": "opening.mp4",
      "audio": "opening.wav",
      "narration": "Introduce the product."
    },
    {
      "id": "product-detail",
      "footage": "detail.mp4",
      "duration": 5
    }
  ],
  "bgm": "music.mp3"
}
```

```sh
python -m app.services.video_project --project storage/projects/product-episode revise episode.json
python -m app.services.video_project --project storage/projects/product-episode plan
python -m app.services.video_project --project storage/projects/product-episode render
python -m app.services.video_project --project storage/projects/product-episode status
```

Relative asset paths resolve against the manifest's directory. Sources are copied
into the project; later editing the original file does not silently change a
revision. The revision ID printed by `revise` identifies an immutable input
snapshot. `status` reports completed stages, reused artifacts, failures and the
export path. `project.json` points to the current revision and the last successful
export, which is preserved until a newer current revision succeeds.

Audio determines the duration of narrated scenes. Silent scenes use `duration`
(default five seconds). Short footage loops; long footage is trimmed. Source
video audio is intentionally replaced with the prepared narration or silence.
All scene outputs use the same dimensions, frame rate and stereo 48kHz audio.
The final BGM mix loops music to the timeline duration and does not normalize
narration away. Zero BGM volume produces an unmixed export.

`narration` is provenance text, not a TTS request. When changing narration, provide
its newly prepared audio too; the CLI cannot verify that the recording speaks the
text. Word-aligned subtitles, transitions, overlays and provider generation are
not implemented by this first local renderer. The timing stage records duration,
not generated word alignments.

## Replace, compare and reuse

Edit only the affected scene/BGM fields, then run `revise` again with the same
`project_id` and stable scene IDs. Use the old and new printed IDs to compare:

```sh
python -m app.services.video_project --project storage/projects/product-episode compare OLD_REVISION NEW_REVISION
python -m app.services.video_project --project storage/projects/product-episode plan
python -m app.services.video_project --project storage/projects/product-episode render
```

| Change | Rebuilt stages |
|---|---|
| One scene's footage | That scene's render, assembly and final export |
| One scene's narration/audio | That scene's audio normalization, timing and render; assembly and export |
| BGM file or volume | Final mix/export only |
| Scene order | Assembly and export only |
| Dimensions/frame rate | Scene renders, assembly and export |
| Narration volume | Audio, timing, scenes, assembly and export |
| FFmpeg tool version/renderer contract | A new revision rebuilds under the changed transformation fingerprint |

The plan explains changed dependencies, missing completed artifacts and integrity
failures. Damaged artifacts are rebuilt from verified snapshots. Damaged source
snapshots fail closed: create a new revision from the original prepared media.
Caches stay inside one project; another project cannot implicitly reuse them.
There are no savings percentages or paid-generation idempotency guarantees.

## Cancellation, failures and concurrent revisions

```sh
python -m app.services.video_project --project storage/projects/product-episode cancel
python -m app.services.video_project --project storage/projects/product-episode render --retry
```

A cancellation request stops the active media subprocess and prevents promotion.
An explicit `--retry` is required after a failed, cancelled or interrupted render.
Completed verified stages remain reusable. A process crash may leave status
`running`; retry rechecks artifacts instead of assuming it completed. Temporary
uncommitted `.work` directories from an abrupt process death may be deleted when
no render is active. They are never a source of trusted reusable artifacts.

Only one renderer writes a revision at a time. Different revisions may render
concurrently and share immutable completed artifacts. If a newer revision is
created while an older one renders, the old revision may finish for comparison,
but cannot replace the current project's last successful export. OS locks release
after process death. Each external media command has a bounded deadline (600
seconds by default, adjustable with `render --stage-timeout`).

Manifests and artifact records use atomic file replacement. Artifact bytes are
published before the commit record; incomplete writes are never trusted. A
fingerprint includes the renderer contract, FFmpeg/FFprobe versions, relevant
settings and content hashes. Unknown manifest/settings fields are rejected,
including provider credentials. Store only public narration content here; no
software can infer whether arbitrary user-written text contains a secret.

## Reusable episode/brand render settings

```sh
python -m app.services.video_project --project storage/projects/product-episode save-preset brand-render.json
python -m app.services.video_project --project storage/projects/next-episode revise next-episode.json --preset brand-render.json
```

Presets reuse dimensions, frame rate and narration/BGM volume. They contain no
assets, project IDs, credentials, provider selections or claims of consistent
AI-generated characters. A supplied preset replaces the manifest's settings.
Scene assets and narration remain explicit per episode.

## Integration boundary

`VideoProject.create_revision`, `plan`, `render`, `status` and `compare` provide the
same prepared-media contract as the CLI. A future accepted director can pass its
completed narration/footage paths, retain scene IDs, and consume export/revision
receipts without changing provider ownership. Existing creative-outcome records
can reference a completed revision ID without introducing automated publishing
or treating observational performance as causal evidence.

## Return to a previous revision

```sh
python -m app.services.video_project --project storage/projects/product-episode checkout OLD_REVISION
python -m app.services.video_project --project storage/projects/product-episode plan
python -m app.services.video_project --project storage/projects/product-episode render
```

Checkout changes the current revision pointer under the project lock. It retains
all revision specifications, statuses, source snapshots, artifacts and the last
successful export. Rendering then reuses verified artifacts where available and
promotes the selected revision's successful export. Checking out a revision does
not reset a failed/cancelled render; use `render --retry` when required. Edits
created after checkout use the selected revision as their parent. If another
revision is already rendering, it can finish, but can promote only while it is
still the current revision. This command does not remove or cancel other work.
