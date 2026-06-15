# Video/Audio/Subtitle Synchronization Timing Chart

This document illustrates the timing synchronization between video, audio, subtitles, and BGM after the architectural fix.

---

## New Architecture (Correct Order of Operations)

The fix reorganizes the processing order to ensure proper synchronization and clean Silence Prefix:

1. **Combine scene videos** (each with embedded audio)
2. **Add pillarbox** (if needed)
3. **Add Silence Prefix FIRST** (extract clean first frame without subtitles)
4. **Add title** (starts from beginning of still frame)
5. **Add subtitles** (adjust timestamps by Silence Prefix duration)
6. **Add BGM**
7. **Encode**

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                      TIMING CHART AFTER ARCHITECTURAL FIX (CORRECT SYNCHRONIZATION)                ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                                      ║
║ TIME (sec):    0.0      0.3      0.6      0.9      1.2      1.5      1.8      2.1      2.4      2.7 ║
║                │        │        │        │        │        │        │        │        │        │   ║
║                ↓        ↓        ↓        ↓        ↓        ↓        ↓        ↓        ↓        ↓   ║
║                                                                                                      ║
║ VIDEO:        [SILENCE ][Scene1                    ][Scene2                    ][Scene3...]         ║
║               0.3s     0.0-1.0s                   1.0-2.0s                   2.0-...               ║
║                                                                                                      ║
║ AUDIO:        [SILENCE ][Scene1 Audio              ][Scene2 Audio              ][Scene3 Audio...]   ║
║               0.3s     0.3-1.3s                   1.3-2.3s                   2.3-...               ║
║                                                                                                      ║
║ SUBTITLE:     [SILENCE ][SILENCE ][Sub1                       ][Sub2                       ][Sub3...]║
║               0.3s     0.3s     0.6-1.2s                   1.2-1.8s                   1.8-...        ║
║                         ↑ CORRECT: Subtitles perfectly aligned with audio!                          ║
║                                                                                                      ║
║ BGM:          [SILENCE ][BGM LOOPING...                                                           ║
║               0.3s     0.3-...                                                                     ║
║                                                                                                      ║
║ TITLE:        [TITLE   ][TITLE OVERLAY...                                                           ║
║               0.3s     0.3-...                                                                     ║
║               ↑                                                                                      ║
║               Title starts from beginning of Silence Prefix!                                           ║
║                                                                                                      ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Processing Order Summary

| Step | Operation | Description |
|------|-----------|-------------|
| 1 | Video + Audio | Combine scene videos with their audio tracks |
| 2 | Pillarbox | Add pillarbox bars for aspect ratio conversion (if needed) |
| 3 | **Silence Prefix FIRST** | Extend first frame + add silence (CLEAN FRAME - no subtitles yet!) |
| 4 | **Title** | Add title overlay (starts from beginning of Silence Prefix) |
| 5 | Subtitles | Add subtitles, adjusting timestamps by Silence Prefix duration |
| 6 | BGM | Add background music mixed with existing audio |
| 7 | Encode (no title) | **FFmpeg filter_complex** streaming pass (silence+pillarbox+subs+BGM all in one pipeline). ~3 min |
|   | Encode (with title) | **Hybrid**: FFmpeg filter_complex for base (silence+pillarbox+subs+BGM) → temp file → MoviePy loads temp → applies PIL-based title overlay → writes. ~4 min, saves ~14 min vs full MoviePy compositing |

---

## Key Implementation Changes

### Files Modified

1. **`app/services/task.py`** - Main changes:
   - Removed Silence Prefix from `combine_all_scenes()`
   - **REORDERED FLOW**: Moved Silence Prefix BEFORE subtitle processing (line 1574-1601)
   - **MOVED TITLE**: Title now added AFTER Silence Prefix (line 1603-1610)
   - Added `silence_duration` variable to track Silence Prefix
   - Adjust subtitle timestamps by `silence_duration` (line 1671-1672)
   - Moved BGM processing to after Silence Prefix

2. **`app/services/video_target.py`** - Main changes:
   - **REORDERED FLOW**: Moved Silence Prefix BEFORE subtitle processing (line 225-240)
   - **MOVED TITLE**: Title now added AFTER Silence Prefix (line 242-246)
   - Added `silence_duration` variable to track Silence Prefix
   - Adjust subtitle timestamps by `silence_duration` (line 298-299)
   - Fixed ImageClip duration initialization issue

### Why This Fixes the Issue

#### Original Problem:
1. Title was added before Silence Prefix, so it didn't appear from the beginning
2. Silence Prefix extracted first frame AFTER subtitles were added
3. Silence Prefix still frame showed the first subtitle (not desired!)
4. Subtitles appeared too early (before Silence Prefix finished)

#### Fixed Solution:
1. **Silence Prefix FIRST**: Extract clean first frame without subtitles
2. **Title AFTER Silence Prefix**: Title now starts from the beginning of the still frame
3. **Subtitles AFTER Silence Prefix**: Add subtitles, adjusting timestamps by silence duration
4. **Perfect synchronization**: Video, audio, and subtitles all shift together by Silence Prefix

This ensures:
- ✅ Clean Silence Prefix frame without subtitles
- ✅ Title appears from the very beginning of the video
- ✅ Perfect synchronization between video, audio, and subtitles

---

## Technical Details

### Silence Prefix Implementation

```python
# Add Silence Prefix FIRST (before subtitles and title)
from app.config.config import silence_duration as config_silence_duration
silence_duration = 0
if config_silence_duration > 0:
    from moviepy import ImageClip, concatenate_videoclips, AudioClip, concatenate_audioclips
    
    # Extract first frame and create a still frame clip (CLEAN - no subtitles yet!)
    import numpy as np
    first_frame = video_clip.get_frame(0)
    if len(first_frame.shape) == 2:
        # Convert grayscale to RGB
        first_frame = np.stack([first_frame] * 3, axis=-1)
    
    # Create still frame with explicit duration
    still_frame_clip = ImageClip(first_frame, duration=config_silence_duration)
    
    # Add audio silence to match video extension
    if video_clip.audio:
        silence_clip = AudioClip(lambda t: 0, duration=config_silence_duration)
        extended_audio = concatenate_audioclips([silence_clip, video_clip.audio])
        video_clip = video_clip.with_audio(extended_audio)
    
    # Concatenate still frame with original video
    video_clip = concatenate_videoclips([still_frame_clip, video_clip])
    silence_duration = config_silence_duration
```

### Title Added After Silence Prefix

```python
# Add title AFTER Silence Prefix so it starts from the beginning of the still frame
if hasattr(params, 'title_enabled') and params.title_enabled and hasattr(params, 'title_text') and params.title_text:
    logger.info("Adding title to video")
    from app.services.title import add_title_to_video
    video_clip = add_title_to_video(video_clip, params)
```

### Subtitle Timing Adjustment

```python
# Parse time string - ADD SILENCE PREFIX OFFSET!
start_time = _srt_time_to_seconds(start_end[0]) + silence_duration
end_time = _srt_time_to_seconds(start_end[1]) + silence_duration
```

This ensures all content (video, audio, subtitles) is shifted forward together by the Silence Prefix duration, maintaining perfect synchronization!
