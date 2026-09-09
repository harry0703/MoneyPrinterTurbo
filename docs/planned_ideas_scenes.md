# Future Ideas — Scene-Based Video Generation

Ideas collected during scene-pipeline development. Not scheduled for the current PR.

---

## 1. Per-Scene Transitions

**Status:** Idea  
**Complexity:** Medium  

Allow each scene to have its own unique transition (fade_in, slide_in, zoom_in, etc.)
independent of other scenes. Currently a single global `scene_transition` applies to all
scene boundaries.

**UI:** Each scene block gets its own transition dropdown.  
**Schema:** `SceneConfig.transition` already supports this — the field exists but the UI
doesn't expose it per-scene yet.  
**Backend:** `task.py:1690` already reads `scene.transition or params.scene_transition`,
so the backend is ready.

---

## 2. Parallel Scene Processing (Multi-threaded)

**Status:** Idea  
**Complexity:** High  

Process independent scenes concurrently using `ThreadPoolExecutor`. Scene N+1's audio
generation doesn't depend on scene N's video composition.

**Current state:** `task.py:1666` has a commented-out `executor.submit` stub.  
**Risks:** TTS services may have rate limits; material downloads may share bandwidth;
progress reporting becomes harder.  
**Approach:** Generate all audio first (parallel), then all materials (parallel), then
compose each scene (parallel), then concatenate (sequential). Each stage waits for the
previous to complete across all scenes.

---

## 3. Per-Scene Progress in WebUI

**Status:** Idea  
**Complexity:** Medium  

Show "Processing scene 2/5..." in the WebUI progress bar and log console. Currently the
pipeline logs individual scene progress to stdout, but the WebUI progress bar only shows
overall percentage.

---

## 4. Per-Scene Add/Remove & Reordering in UI

**Status:** Idea  
**Complexity:** Medium  

Currently scene count is controlled only by the slider, and scenes can only be added/removed
from the end. Future: per-scene `+` button between scenes (insert at position) and `×` on
each scene block (remove specific scene), plus drag-and-drop or arrow buttons for reordering.

---

## 5. Scene-Specific TTS Voice

**Status:** Idea  
**Complexity:** Low-Medium  

Allow different voices for different scenes (e.g., narrator in scene 1, character in scene
2). `SceneConfig` could have an optional `voice_name` field that overrides
`params.voice_name`.

---

## 6. Scene Duration Override (Trim/Extend)

**Status:** Idea  
**Complexity:** High  

`SceneConfig.duration` is currently accepted but unused — actual duration is determined by
TTS audio length. Future enhancement: use `duration` to trim or extend the final scene
video (slow down / speed up audio, or use silence padding).

---

## 7. Scene Templates / Presets

**Status:** Idea  
**Complexity:** Low  

Pre-built scene templates: "3 scenes: Intro → Main → Conclusion", "5 scenes: Hook →
Problem → Solution → Demo → CTA". User picks a template and gets pre-filled scene blocks.

---

## 8. i18n: Translate New Scene UI Elements

**Status:** TODO (before PR submission)  
**Complexity:** Low  

The scene-mode UI currently has translations only in `en.json` and `ru.json`. All other
supported languages need the same keys added:

**Languages to update:** `zh.json`, `de.json`, `es.json`, `fr.json`, `id.json`, `it.json`,
`ko.json`, `pt.json`, `tr.json`, `vi.json`, `ja.json`

**Keys to translate:**
```
Generation Mode, Generation Mode whole, Generation Mode scenes, Generation Mode Help,
Scenes, Scene, Add Scene, Remove Scene, Number of Scenes,
Generate Scene Scripts, Generate Scene Keywords,
Generating Scene Scripts, Generating Scene Keywords,
Generate Scene Scripts and Keywords,
Failed to generate scene scripts, Failed to generate scene keywords,
Please Generate Scene Scripts First,
Scene count adjusted, Scene keyword count adjusted
```

---

## 9. Scene-Mode Transition Dropdowns in Video Settings

**Status:** Idea  
**Complexity:** Low  

Currently `scene_transition` and `clip_transition` are not exposed as separate controls in
scene mode. The existing `video_transition_mode` dropdown is used as a fallback. Need two
dedicated dropdowns visible only in scene mode:
- "Transition between scenes" → `params.scene_transition`
- "Transition between clips within a scene" → `params.clip_transition`

**Backend:** Fully ready — `task.py` reads both fields and passes them to the pipeline.

---

## 10. LoomLoom Scene Script Generation

**Status:** Idea  
**Complexity:** Medium  

Scene mode currently only supports local LLM for script/keyword generation. LoomLoom
integration (`_render_loomloom_script_generation`) is not connected to scene mode. Need to
allow LoomLoom to generate per-scene scripts and distribute them into scene blocks.

---

## 11. Task Restore with Scene Data

**Status:** Idea  
**Complexity:** Low-Medium  

When a historical task is loaded from the task manager, `params.scenes` may not round-trip
correctly if scenes weren't persisted to `script_data.json`. Need to verify that
`save_script_data` includes scenes and that `_load_task_restore_payload` reconstructs them.

---

## 12. Settings Presets for Scene Blocks

**Status:** Idea  
**Complexity:** Low  

The WebUI settings export/import (`_parse_settings_preset`) doesn't include scene blocks.
Need to persist `scene_scripts`, `scene_keywords`, and `scene_count` in preset files.

---

## 13. Scene Duration Override (Trim/Extend)

**Status:** Idea  
**Complexity:** High  

`SceneConfig.duration` is accepted but unused — actual duration is determined by TTS audio.
Future: use `duration` to trim or extend the scene video (speed up/slow down audio, or
use silence padding). This was separated from idea #6 because it also affects subtitle
timing and transition calculations.
