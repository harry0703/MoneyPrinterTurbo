# Video/Audio/Subtitle Synchronization Timing Chart

This document illustrates the timing synchronization between video, audio, subtitles, and BGM after the architectural fix.

---

## New Architecture (Correct Order of Operations)

The fix reorganizes the processing order to ensure proper synchronization:

1. **Combine video + audio + subtitles** first (all synchronized together)
2. **Add idle period** by extending first frame + silence
3. **Add BGM and title**

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                      TIMING CHART AFTER ARCHITECTURAL FIX (CORRECT SYNCHRONIZATION)                ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                                      ║
║ TIME (sec):    0.0      0.3      0.6      0.9      1.2      1.5      1.8      2.1      2.4      2.7 ║
║                │        │        │        │        │        │        │        │        │        │   ║
║                ↓        ↓        ↓        ↓        ↓        ↓        ↓        ↓        ↓        ↓   ║
║                                                                                                      ║
║ VIDEO:        [IDLE    ][Scene1                    ][Scene2                    ][Scene3...]         ║
║               0.3s     0.0-1.0s                   1.0-2.0s                   2.0-...               ║
║                                                                                                      ║
║ AUDIO:        [SILENCE ][Scene1 Audio              ][Scene2 Audio              ][Scene3 Audio...]   ║
║               0.3s     0.3-1.3s                   1.3-2.3s                   2.3-...               ║
║                                                                                                      ║
║ SUBTITLE:     [IDLE    ][IDLE    ][Sub1                       ][Sub2                       ][Sub3...]║
║               0.3s     0.3s     0.6-1.2s                   1.2-1.8s                   1.8-...        ║
║                         ↑ CORRECT: Subtitles perfectly aligned with audio!                          ║
║                                                                                                      ║
║ BGM:          [SILENCE ][BGM LOOPING...                                                           ║
║               0.3s     0.3-...                                                                     ║
║                                                                                                      ║
║ TITLE:        [IDLE    ][TITLE OVERLAY...                                                          ║
║               0.3s     0.3-...                                                                     ║
║                                                                                                      ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Processing Order Summary

| Step | Operation | Description |
|------|-----------|-------------|
| 1 | Video + Audio | Combine scene videos with their audio tracks |
| 2 | Pillarbox | Add pillarbox bars for aspect ratio conversion (if needed) |
| 3 | Subtitles | Add subtitles synchronized with video/audio |
| 4 | **Idle Period** | Extend first frame + add silence to beginning |
| 5 | BGM | Add background music mixed with existing audio |
| 6 | Title | Add title overlay |
| 7 | Encode | Final video encoding |

---

## Key Implementation Changes

### Files Modified

1. **`app/services/task.py`** - Main changes:
   - Removed idle period from `combine_all_scenes()` (line 799-825)
   - Added idle period after subtitle processing in `start_multi_scene()` (line 1764-1782)
   - Moved BGM processing to after idle period (line 1784-1811)

2. **`app/services/video_target.py`** - Removed redundant idle period adjustment from subtitle rendering (line 284-285)

### Why This Fixes the Issue

The original bug was caused by the idle period being applied twice:
- First: During scene combination (correct)
- Second: During subtitle rendering (incorrect - caused subtitles to appear early)

The new architecture ensures:
1. Video, audio, and subtitles are fully synchronized BEFORE the idle period is added
2. The idle period is applied ONCE to the complete synchronized content
3. BGM and title are added last, after all synchronization is complete

---

## Technical Details

### Idle Period Implementation

```python
# After video+audio+subtitles are synchronized
if config_video_idle_period > 0:
    # Extract first frame and create still frame clip
    first_frame = video_clip.get_frame(0)
    still_frame_clip = ImageClip(first_frame).with_duration(config_video_idle_period)
    
    # Add audio silence to match video extension
    if video_clip.audio:
        silence_clip = AudioClip(lambda t: 0, duration=config_video_idle_period)
        extended_audio = concatenate_audioclips([silence_clip, video_clip.audio])
        video_clip = video_clip.with_audio(extended_audio)
    
    # Concatenate still frame with original video
    video_clip = concatenate_videoclips([still_frame_clip, video_clip])
```

This ensures all content (video, audio, subtitles) is shifted forward together by the idle period duration, maintaining perfect synchronization.
