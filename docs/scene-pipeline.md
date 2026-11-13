# Scene-based video pipeline

MoneyPrinterTurbo keeps its existing video workflow as the default. Set
`video_pipeline = "scene"` in a task request or select **Intelligent Scenes** in
the WebUI to opt into scene planning. Existing task records and generated files
remain readable; the new plan, media manifest, timeline, quality reports, and
render metrics are stored as separate versioned task artifacts.

## Current scope

The scene pipeline is an incremental orchestration path, not a replacement for
all existing media providers:

- The configured LLM writes the script through the existing script service.
- `scene_planner` divides that script into ordered scenes and validates exact
  narration coverage.
- Scene-level stock search currently queries configured Pexels, Pixabay, and
  Coverr adapters. Existing AI video, image, and local-material sources remain
  available through the legacy workflow and as the configured fallback.
- Visual candidate acceptance uses TwelveLabs Pegasus when
  `scene_media_visual_validation` is enabled and TwelveLabs keys are present.
  It requires evidence from the beginning, middle, and end of the clip plus
  subject, action, context, and confidence checks. Marengo similarity is an
  optional ranking signal; it is not a visual correctness verdict.
- A candidate that does not pass visual validation is left pending. It is not
  accepted merely because its search terms are related to the topic.
- The scene timeline aligns plan narration with subtitle or TTS timestamps,
  then renders the selected local assets. If a scene plan, media assignment, or
  timeline cannot be used, `scene_plan_fallback` chooses the legacy path or
  stops the task.
- Final scene renders receive the existing technical quality scan. Separate
  render metrics include elapsed time, process CPU, Python-process RSS, output
  size, selected codec, and export parameters.

Per-scene AI generation, local-file assignment into scene search, a user-facing
scene retry endpoint, and a resolution above the existing aspect presets are
not currently implemented. AI video/image providers and local materials remain
available in the legacy workflow. The current quality scan checks technical
properties; it does not independently prove that every final-frame subject is
correct.

## Enable the pipeline

Configure an LLM provider, at least one stock provider, a voice provider, and
FFmpeg as usual. For automatic visual acceptance, also configure TwelveLabs:

```toml
# config.toml, under [app]
video_pipeline = "legacy" # legacy | scene; per-task requests can override this
scene_plan_fallback = "legacy" # legacy | fail
scene_media_visual_validation = false
twelvelabs_api_keys = ["<your-key>"]
pixabay_api_keys = ["<your-key>"]
```

Pexels and Coverr keys can be configured instead of, or alongside, Pixabay.
Scene search uses every configured stock provider. TwelveLabs is optional for
the traditional flow; without it, scene assignments remain pending and the
configured fallback applies. The WebUI disables visual validation when no
TwelveLabs key is configured and shows this limitation before task submission.

Example request body for `POST /api/v1/videos`:

```json
{
  "video_subject": "A short explanation of Saturn's rings",
  "video_script": "Saturn's rings are made mostly of countless pieces of ice and rock.",
  "video_pipeline": "scene",
  "scene_plan_fallback": "fail",
  "scene_media_visual_validation": true,
  "video_source": "pixabay",
  "video_aspect": "9:16",
  "video_clip_duration": 5,
  "subtitle_enabled": true,
  "video_export_profile": "shorts"
}
```

`video_script` may be omitted to use the configured script generator. The
request can also set existing voice, music, subtitle, transition, and provider
fields. Use `scene_plan_fallback: "fail"` when a legacy result would be
unacceptable; the default `legacy` policy prioritizes backwards-compatible task
completion and may therefore produce material without scene-level matching.

## Export and audio options

`video_export_profile` accepts `legacy`, `shorts`, `high_quality`, and `fast`.
Profile bitrates, FPS, CPU preset, and Fast Start can be overridden in the
`video_export_profiles` table in `config.toml`. Resolution and aspect ratio
continue to come from the existing `video_aspect` setting. `high_quality` raises
bitrate and uses a slower CPU preset; it does not upscale the current source
pipeline.

Optional audio fields are `audio_ducking_enabled`,
`audio_normalization_enabled`, `audio_peak_guard_enabled`, and
`sound_effects`. Ducking uses SRT cue times and requires a usable subtitle file.
Normalization applies bounded gain to narration. Peak protection applies a
global reduction to the final mix, rather than a time-varying loudness limiter.
Effects are local files in `storage/sound_effects`; each cue can name a scene,
offset, duration, volume, and fades. No sound effect is generated automatically.

## Task artifacts

The task directory can contain:

- `video_plan.v1.json` — scene plan and script identity.
- `scene_media.v1.json` — search candidates, assignment decisions, validation
  evidence, warnings, and retries performed by the service.
- `scene_timeline.v1.json` — scene IDs, local asset paths, timing, and
  synchronization source.
- `video_quality.v1.json` — final technical quality results for scene renders.
- `video_render_metrics.v1.json` — export metrics, one entry per output video.
- Existing `script.json`, subtitle, audio, material, and final MP4 artifacts
  remain in their established locations and formats.

These files are diagnostic artifacts. Do not edit them while the task is
running. A future retry endpoint should validate plan IDs, script hashes, and
asset paths before reusing their contents.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Scene plan falls back | Check the task log for provider errors and verify the configured LLM model/key. |
| Scene assignments stay pending | Confirm stock-provider keys and, for visual acceptance, TwelveLabs keys. Check `scene_media.v1.json` discard reasons. |
| The old material flow is used | Check `scene_plan_fallback` and task warnings. The legacy policy intentionally permits fallback. |
| Timeline falls back | Compare scene narration with timed SRT/TTS cues and verify every selected local asset still exists. |
| Hardware encoding falls back to CPU | Check FFmpeg's available encoders and GPU driver; actual encode errors also trigger CPU fallback. |
| Render metrics show no child-process memory | RSS currently reports the Python process, not aggregate FFmpeg child memory. |

## Verification

Run the focused suite from the repository root with the bundled interpreter on
Windows:

```powershell
..\lib\python\python.exe -m unittest test.services.test_scene_planner test.services.test_scene_media test.services.test_scene_timeline test.services.test_scene_quality test.services.test_video test.services.test_audio_mix test.services.test_export_profiles -v
```

These tests validate contracts and local FFmpeg rendering. A service-backed
visual acceptance run additionally requires working stock-provider and
TwelveLabs credentials. Mocked provider tests do not establish real semantic
accuracy or external service availability.
