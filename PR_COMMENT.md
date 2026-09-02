# Scene-Based Video Generation

## The Idea

Add a scene-based generation mode: instead of a single global script, the user splits the video into N independent scenes, each with its own script, keywords, and materials. Scenes are processed independently and assembled into a final video with transitions and background music.

## Architecture

```
Scene 1: script → TTS(audio) → subtitles → materials → scene video (audio+subs burned in)
Scene 2: script → TTS(audio) → subtitles → materials → scene video (audio+subs burned in)
...
Final:   concatenate(scene videos) + BGM → final.mp4
```

**Key design decisions:**
- Each scene is a fully independent mini-pipeline (`_generate_single_scene`) producing a self-contained video file with audio
- Concatenation uses MoviePy `concatenate_videoclips(method="compose")` — reliably handles videos with different codecs/resolutions
- BGM is overlaid **once** on the final video via MoviePy `CompositeAudioClip` (same approach as `generate_video`)
- UI: mode toggle, scene editor (slider + N blocks), AI buttons for script/keyword generation

## What Was Done

### Backend
- `task.py`: `_generate_single_scene()` — full mini-pipeline per scene. BGM disabled at scene level (`bgm_file_override=""`)
- `video.py`: `concat_scene_videos_with_transitions()` — MoviePy-based concatenation + transitions + BGM overlay
- `video.py`: `_overlay_bgm_on_video()` rewritten to use MoviePy (CompositeAudioClip + AudioLoop + AudioFadeOut)
- `llm.py`: `generate_scene_scripts()` and `generate_scene_keywords()` — structured JSON from LLM with retry and regex recovery
- `schema.py`: `SceneConfig.duration` documented as reserved field
- Eliminated unnecessary LLM call for global script generation in scene mode

### WebUI
- Mode toggle "Whole Video / Scene-Based" with text migration on switch
- Scene editor: count slider, N blocks × [script + keywords]
- AI buttons: "Generate Scene Scripts" / "Generate Scene Keywords"
- `scene_scripts_pending` flag for correct one-time AI result injection into widgets
- New i18n keys in `en.json` and `ru.json`

### Bug Fixes
- `concat_video_clips_with_ffmpeg`: added `-c:a aac` (audio was dropped when concatenating clips 2+)
- `_apply_scene_transition`: `audio=True` when opening video (audio was lost during transitions)
- BGM resolution: `params.bgm_file` now passed to `get_bgm_file` (custom BGM wasn't resolving)
- Double BGM layering (applied per-scene AND on final video)

### Tests
- **85 tests** in `test/services/test_scene_pipeline.py`, all passing
- Coverage: transitions (10), concat (9), BGM (5), LLM JSON parsing (11), schema (8), CLI (7), failure modes (4), pipeline logic (31)

## What Can Be Done in Future PRs

Full roadmap: [`docs/planned_ideas_scenes.md`](docs/planned_ideas_scenes.md)

| # | Idea | Complexity |
|---|------|------------|
| 1 | Per-scene transitions (unique transition per scene) | Medium |
| 2 | Parallel scene processing (ThreadPoolExecutor) | High |
| 3 | Per-scene progress in WebUI | Medium |
| 4 | Per-scene add/remove & reordering in UI | Medium |
| 5 | Scene-specific TTS voice | Low-Medium |
| 6 | Scene duration override (trim/extend) | High |
| 7 | Scene templates (Intro → Main → CTA) | Low |
| 8 | i18n: translate new elements to 11 languages | Low |
| 9 | Scene-mode transition dropdowns in Video Settings | Low |
| 10 | LoomLoom scene script generation | Medium |
| 11 | Task restore with scene data | Low-Medium |
| 12 | Settings presets for scene blocks | Low |

---

> 💡 **Suggestion:** Open issues for #8 (i18n), #11 (task restore), and #9 (transition dropdowns) as low-hanging fruit for the next PR.
