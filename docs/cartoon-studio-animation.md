# 2D cartoon animation engine

`app/services/cartoon_animation` is an offline, CPU-only animation engine for
Cartoon Studio. It replaces camera motion over a still with an articulated
character: separate parts, joints, keyframes and a per-frame renderer. The
classic stills + zoom workflow is unchanged and remains the default.

Everything in the engine is local: Pillow draws the frames, FFmpeg encodes
them, and nothing downloads models or calls a commercial service. Narration
(Edge TTS or another configured voice) stays in Cartoon Studio and is only
used to time scenes and drive lip sync.

## Layout

```text
app/services/cartoon_animation/
  models.py        channels, Pose, Shape, Part, Character, Keyframe, Animation
  interpolation.py linear, step, ease-in/out/in-out, smoothstep
  keyframes.py     track sampling and clip mixing
  rig.py           joint hierarchy resolution
  characters.py    Tiko and the character preset registry
  expressions.py   facial expression offsets and mouth states
  presets.py       idle, blink, talk, wave, walk, jump, point...
  timeline.py      clips, priorities and blending
  lip_sync.py      amplitude envelope -> mouth openness
  assets.py        procedural backgrounds and props
  compositor.py    scene plans, actors, props, per-frame composition
  renderer.py      Pillow drawing and the FFmpeg frame pipe
  validation.py    manifest validation for the animation section
```

`cartoon_studio.py` owns episodes, scenes, narration and the video-project
export. The engine only answers "what does frame N look like?".

## Character model

A character is a palette plus a component tree. Each `Part` has a shape, a
layer, a parent, an anchor in the parent's local space and an optional
rotation/translation channel. Tiko's tree:

```text
Tiko
├── left/right leg -> foot
├── body -> chest
│   ├── left/right arm -> hand
│   └── head -> visor, eyes -> pupils, brows, blush, mouth, antenna -> ball
```

Poses are flat numeric channels with hard limits (`CHANNELS` in
`models.py`), so a rotation can never leave its joint range no matter how
keyframes are combined. Coordinates are pixels in the internal canvas with
`+y` down; rotations are degrees, clockwise.

New characters are added to `CHARACTER_PRESETS`; the renderer, presets,
expressions and lip sync are character-independent.

## Animations and interpolation

```json
{
  "character": "tiko",
  "animation": "wave",
  "duration": 2.0,
  "keyframes": [
    {"time": 0.0, "right_arm_rotation": 0},
    {"time": 0.5, "right_arm_rotation": -35},
    {"time": 1.0, "right_arm_rotation": 15}
  ]
}
```

This is the conceptual schema. In code an `Animation` holds one track per
channel (`{channel: (Keyframe, ...)}`), keyframes are sorted and may not
exceed the duration, and each keyframe chooses the easing used to reach it:
`linear`, `step`, `ease-in`, `ease-out`, `ease-in-out` or `smoothstep`.

Built-in presets: `idle`, `blink`, `look_left`, `look_right`, `talk`, `wave`,
`walk`, `jump`, `happy`, `surprised`, `head_tilt`, `pick_up`, `point`,
`water_plant`, `celebrate`.

Combining animations works at the timeline level. Clips have a start, speed,
weight and priority; higher priorities win on shared channels, weights blend
towards the clip value, and additive animations offset the current value
instead of replacing it. `sample_clips` is deterministic for a given set of
clips and time, which keeps renders reproducible.

## Scene manifest

Animation is opt-in and additive. Existing `cartoon.json` files keep working
untouched. Declare the character once, then add an `animation` object per
scene:

```json
{
  "project_id": "primer-episodio",
  "aspect": "9:16",
  "characters": [{"name": "Tiko", "description": "a small blue robot"}],
  "animation": {
    "characters": [{"id": "tiko", "preset": "tiko"}]
  },
  "scenes": [
    {
      "id": "escena-01",
      "visual": "Tiko finds a seed",
      "narration": "Un día, Tiko encontró una semilla.",
      "duration": 5,
      "animation": {
        "background": "garden",
        "character": "tiko",
        "x": 0.42,
        "y": 0.66,
        "scale": 0.95,
        "expression": "curious",
        "lip_sync": true,
        "props": [
          {"name": "seed", "x": 0.72, "y": 0.82, "scale": 0.9, "appear": 0.2}
        ],
        "actions": [
          {"animation": "blink", "at": 0.35},
          {"animation": "look_right", "at": 0.95},
          {"animation": "head_tilt", "at": 1.7}
        ],
        "travel": {"to_x": 0.62, "start": 0.3, "duration": 1.8}
      }
    }
  ]
}
```

- `x`/`y`/`scale` place the actor; `y` is the feet position and coordinates
  are fractions of the internal canvas.
- `travel` moves the actor smoothly during the scene (no end-of-clip snap).
- `props`: `seed`, `pot`, `watering_can`, `flower`. All are drawn
  procedurally. `flower` supports `appear`, `growth_from`, `growth_to`,
  `grow_duration` and `base_y` to animate a stem, leaves and petals.
- `actions`: built-in animations with `at` (seconds), optional `weight` and
  `speed`.
- `expression`: `neutral`, `happy`, `surprised`, `curious`, `sad`,
  `determined`.
- `lip_sync`: `true` by default. When narration exists, mouth openness is
  derived from the audio envelope. Set it to `false` for a fixed mouth.
- `background`: `garden`, `meadow`, `night`, `studio`.

Unknown fields, characters, props, backgrounds, annotations or out-of-range
coordinates are rejected when the manifest is loaded. A project in animation
mode must animate every scene; otherwise the build stops with the missing
scene IDs.

## Lip sync

`lip_sync.analyze_audio` decodes the narration MP3 with FFmpeg to 8 kHz mono
16-bit PCM, computes one RMS value per video frame, normalises with a robust
peak, smooths with a fast attack and slower release, then quantises to four
mouth states: closed, slightly open, half open, open. Runs shorter than
`min_hold` frames are merged so the mouth does not flicker.

This is an amplitude envelope, **not** phoneme recognition. The interface is
intentionally narrow: a future phoneme-timed backend can replace
`analyze_audio` and return the same per-frame openness values without touching
the renderer or compositor.

## Rendering

- Draw with Pillow at 720 x 1280 (or 1280 x 720 / 960 x 960 for other
  aspects), 24 fps by default.
- Parts are drawn at 2x and downsampled for smooth edges. Rotations below
  0.75 degrees are skipped because they are invisible and expensive.
- Frames are generated one at a time and written as raw RGB to a single
  FFmpeg pipe; no PNG sequence is stored.
- FFmpeg scales to 1080 x 1920 with Lanczos and encodes H.264 (`yuv420p`,
  configurable CRF). Temporary output is renamed atomically on success.
- Backgrounds are cached per size; scene memory stays around one frame.
- Scenes render sequentially with one FFmpeg process at a time, which bounds
  CPU and memory use on integrated graphics laptops.
- No CUDA, no GPU, no model downloads.

Settings are data (`RenderSettings`), not code: width, height, fps, output
size, CRF and x264 preset can all be changed from the CLI or from Python.

## CLI

The existing commands are unchanged; animation adds subcommands and a mode
flag:

```sh
# Validate a character and list its parts/animations
python -m app.services.cartoon_studio --project storage/cartoon/primer-episodio \
  validate-character --preset tiko

# Render one still of an animated scene
python -m app.services.cartoon_studio --project storage/cartoon/primer-episodio \
  preview --scene escena-01 --time 1.2 --out previews/escena-01.png

# Render one animated scene clip (no narration, uses the scene duration)
python -m app.services.cartoon_studio --project storage/cartoon/primer-episodio \
  scene --scene escena-01 --fps 24

# Classic mode stays the default; animate explicitly or via the manifest
python -m app.services.cartoon_studio --project storage/cartoon/primer-episodio \
  build --mode animation --voice es-CO-SalomeNeural --subtitles

# Inspect the latest revision
python -m app.services.cartoon_studio --project storage/cartoon/primer-episodio status
```

`build` also accepts `--fps`, `--crf`, `--animation-width`,
`--animation-height`, `--output-width` and `--output-height`. `--mode auto`
(default) animates only when the manifest contains an `animation` section.

## Caching and invalidation

Animated clips live in `<project>/clips/<scene>-<digest>.mp4`. The digest
covers the renderer version, the validated scene animation, the effective
duration, the encoding settings and the narration file name. Changing an
action, prop, background, fps or CRF re-renders only the affected scenes;
unchanged scenes are reused. Classic image identities and the existing
`video_project` revision cache are untouched, so old projects keep their
artifacts.

## Python API for a future web panel

The stable surface for a service layer:

```python
from app.services.cartoon_animation import (
    RenderSettings, build_plan, parse_animation,
    render_scene_video, render_still, get_character, get_animation,
)

project, scenes = parse_animation(manifest["animation"], manifest["scenes"])
plan = build_plan(scenes["escena-01"], project.characters, 5.0, RenderSettings())
render_still(plan, 1.2, "preview.png")
render_scene_video(plan, "scene.mp4", progress=lambda seconds: print(seconds))
```

A panel can validate characters, preview stills, start a render and poll
progress without importing Cartoon Studio internals. Episode approval and
export stay with `video_project`.

## Tests

```sh
python -m pytest test/services/test_cartoon_animation_models.py \
  test/services/test_cartoon_animation_rig.py \
  test/services/test_cartoon_animation_timeline.py \
  test/services/test_cartoon_animation_renderer.py \
  test/services/test_cartoon_animation_lip_sync.py \
  test/services/test_cartoon_animation_integration.py -v
```

They cover pose validation and limits, part hierarchy and inheritance,
interpolation and priority blending, layer order, expressions, mouth states,
sprite determinism, props and fades, H.264 encoding, manifest compatibility,
cache reuse and selective invalidation.
