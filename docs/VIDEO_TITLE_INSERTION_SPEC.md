# Video Title Insertion Automation Feature Specification

## 1. Overview

This feature enables automatic insertion of title clips at the beginning of generated videos. The title can be configured with various properties including duration, font, color, style, and animation effects.

## 2. Requirements Analysis

### 2.1 Functional Requirements

| Requirement ID | Description | Priority |
|---------------|-------------|----------|
| REQ-001 | Support configurable title duration | High |
| REQ-002 | Support multiple font options | High |
| REQ-003 | Support customizable text color | High |
| REQ-004 | Support customizable stroke color and width | High |
| REQ-005 | Support text background color/transparency | High |
| REQ-006 | Support title positioning (top, center, bottom) | High |
| REQ-007 | Support static title styles (preset themes) | High |
| REQ-008 | Support title animation effects (fade, slide) | Medium |
| REQ-009 | Support background overlay for title | Medium |

### 2.2 Non-Functional Requirements

| Requirement ID | Description | Priority |
|---------------|-------------|----------|
| NFR-001 | Must integrate seamlessly with existing video generation pipeline | High |
| NFR-002 | Must support all video aspect ratios (9:16, 16:9, 1:1, 3:4) | High |
| NFR-003 | Must use existing font resources from resource/fonts/ | High |
| NFR-004 | Must maintain backward compatibility | High |

## 3. Technical Solution

### 3.1 Architecture Design

#### 3.1.1 System Integration

The title insertion feature will be integrated into the existing video generation pipeline at the `video_target.py` level, after video composition but before final encoding.

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Video Generation Pipeline                         │
├─────────────────────────────────────────────────────────────────────┤
│  Scene Processing → Video Composition → Silence Prefix             │
│                                              ↓                     │
│                                     Pillarbox (if needed)          │
│                                              ↓                     │
│              ┌──────────────────────────────────────────────┐      │
│              │         Final Encoding (Dual Path)           │      │
│              │                                              │      │
│              │  No Title? ──→ FFmpeg filter_complex ──→    │      │
│              │                  (single streaming pass)     │      │
│              │                                              │      │
│              │  Has Title? ──→ Hybrid FFmpeg+MoviePy:      │      │
│              │    1. FFmpeg: silence+pillarbox+subs+BGM    │      │
│              │       +loudnorm → temp file (single pass)   │      │
│              │    2. MoviePy: load temp + title overlay    │      │
│              │       → fast write (only ~5s compositing)   │      │
│              └──────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.2 Component Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  VideoParams    │────→│  TitleService   │────→│ VideoTarget     │
│  (Schema)       │     │  (Business)     │     │  (Generation)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                      │                       │
         ↓                      ↓                       ↓
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  config.toml    │     │  TitleStyleSet  │     │  Final Video    │
│  (Config)       │     │  (Presets)      │     │  Output         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### 3.2 Data Model Design

#### 3.2.1 TitleParams Schema

Add to `app/models/schema.py`:

```python
class TitlePosition(str, Enum):
    top = "top"
    center = "center"
    bottom = "bottom"


class TitleAnimation(str, Enum):
    none = "none"
    fade_in = "fade_in"
    fade_out = "fade_out"
    slide_up = "slide_up"
    slide_down = "slide_down"


class TitleParams(BaseModel):
    title_enabled: Optional[bool] = False
    title_text: Optional[str] = ""
    title_duration: Optional[float] = 3.0  # seconds
    title_font_name: Optional[str] = "MicrosoftYaHeiBold.ttc"
    title_font_size: Optional[int] = 72
    title_text_color: Optional[str] = "#FFFFFF"
    title_stroke_color: Optional[str] = "#000000"
    title_stroke_width: Optional[float] = 2.0
    title_background_color: Union[bool, str] = "transparent"
    title_position: Optional[TitlePosition] = TitlePosition.center
    title_margin: Optional[float] = 0.05  # 5% margin from edge
    title_animation: Optional[TitleAnimation] = TitleAnimation.none
    title_animation_duration: Optional[float] = 0.5  # seconds
    title_background_overlay: Optional[bool] = False
    title_overlay_color: Optional[str] = "rgba(0,0,0,0.5)"
```

#### 3.2.2 VideoParams Extension

Extend `VideoParams` class to include title parameters:

```python
class VideoParams(BaseModel):
    # ... existing fields ...
    
    # Title settings
    title_enabled: Optional[bool] = False
    title_text: Optional[str] = ""
    title_duration: Optional[float] = 3.0
    title_font_name: Optional[str] = "MicrosoftYaHeiBold.ttc"
    title_font_size: Optional[int] = 72
    title_text_color: Optional[str] = "#FFFFFF"
    title_stroke_color: Optional[str] = "#000000"
    title_stroke_width: Optional[float] = 2.0
    title_background_color: Union[bool, str] = "transparent"
    title_position: Optional[str] = "center"
    title_margin: Optional[float] = 0.05
    title_animation: Optional[str] = "none"
    title_animation_duration: Optional[float] = 0.5
    title_background_overlay: Optional[bool] = False
    title_overlay_color: Optional[str] = "rgba(0,0,0,0.5)"
```

### 3.3 Static Style Sets

Define preset title styles in a new module `app/services/title_styles.py`:

```python
TITLE_STYLES = {
    "classic": {
        "name": "Classic",
        "description": "Elegant white text with black stroke",
        "params": {
            "title_font_name": "STHeitiMedium.ttc",
            "title_font_size": 72,
            "title_text_color": "#FFFFFF",
            "title_stroke_color": "#000000",
            "title_stroke_width": 2.0,
            "title_background_color": "transparent",
            "title_position": "center",
            "title_animation": "fade_in",
            "title_animation_duration": 0.5
        }
    },
    "modern": {
        "name": "Modern",
        "description": "Clean sans-serif with subtle shadow",
        "params": {
            "title_font_name": "MicrosoftYaHeiBold.ttc",
            "title_font_size": 64,
            "title_text_color": "#F5F5F5",
            "title_stroke_color": "#333333",
            "title_stroke_width": 1.5,
            "title_background_color": "transparent",
            "title_position": "top",
            "title_animation": "slide_down",
            "title_animation_duration": 0.6
        }
    },
    "bold": {
        "name": "Bold",
        "description": "Strong impact with thick stroke",
        "params": {
            "title_font_name": "MicrosoftYaHeiBold.ttc",
            "title_font_size": 80,
            "title_text_color": "#FFD700",
            "title_stroke_color": "#8B4513",
            "title_stroke_width": 3.0,
            "title_background_color": "transparent",
            "title_position": "center",
            "title_animation": "fade_in",
            "title_animation_duration": 0.4
        }
    },
    "minimal": {
        "name": "Minimal",
        "description": "Clean and simple design",
        "params": {
            "title_font_name": "STHeitiLight.ttc",
            "title_font_size": 60,
            "title_text_color": "#FFFFFF",
            "title_stroke_color": "transparent",
            "title_stroke_width": 0,
            "title_background_color": "transparent",
            "title_position": "bottom",
            "title_animation": "none",
            "title_animation_duration": 0.3
        }
    },
    "dark_overlay": {
        "name": "Dark Overlay",
        "description": "Title with semi-transparent background",
        "params": {
            "title_font_name": "MicrosoftYaHeiBold.ttc",
            "title_font_size": 68,
            "title_text_color": "#FFFFFF",
            "title_stroke_color": "#000000",
            "title_stroke_width": 1.5,
            "title_background_color": "rgba(0,0,0,0.7)",
            "title_position": "bottom",
            "title_animation": "fade_in",
            "title_animation_duration": 0.5,
            "title_background_overlay": False
        }
    },
    "gradient": {
        "name": "Gradient",
        "description": "Colorful gradient style",
        "params": {
            "title_font_name": "UTM Kabel KT.ttf",
            "title_font_size": 76,
            "title_text_color": "#FF6B6B",
            "title_stroke_color": "#4ECDC4",
            "title_stroke_width": 2.0,
            "title_background_color": "transparent",
            "title_position": "center",
            "title_animation": "slide_up",
            "title_animation_duration": 0.7
        }
    }
}
```

### 3.4 Service Implementation

#### 3.4.1 Title Service Module

Create `app/services/title.py`:

```python
import os
from typing import Optional
from loguru import logger
from moviepy import TextClip, CompositeVideoClip, ColorClip, vfx

from app.utils import utils
from app.services.video_utils import parse_color, wrap_text
from app.models.schema import VideoParams


def create_title_clip(
    video_width: int,
    video_height: int,
    params: VideoParams
) -> Optional[TextClip]:
    """
    Create a title clip based on the provided parameters.
    
    Args:
        video_width: Target video width in pixels
        video_height: Target video height in pixels
        params: VideoParams containing title settings
    
    Returns:
        TextClip with title, or None if title is disabled
    """
    if not params.title_enabled or not params.title_text:
        return None
    
    logger.info(f"Creating title clip: '{params.title_text}' ({video_width}x{video_height})")
    
    # Build font path
    font_path = os.path.join(utils.font_dir(), params.title_font_name)
    if os.name == "nt":
        font_path = font_path.replace("\\", "/")
    
    # Calculate max width for text wrapping
    margin_px = video_width * params.title_margin
    max_width = video_width - 2 * margin_px
    
    # Wrap text if needed
    wrapped_text, text_height = wrap_text(
        params.title_text,
        max_width=max_width,
        font=font_path,
        fontsize=int(params.title_font_size)
    )
    
    # Parse colors
    text_color = params.title_text_color
    stroke_color = params.title_stroke_color
    bg_color = params.title_background_color
    
    # Handle transparent background
    if bg_color == 'transparent' or bg_color is True:
        bg_color = None
    
    # Create text clip
    txt_clip = TextClip(
        text=wrapped_text,
        font=font_path,
        font_size=int(params.title_font_size),
        color=text_color,
        bg_color=bg_color,
        stroke_color=stroke_color if stroke_color != "transparent" else None,
        stroke_width=int(params.title_stroke_width) if stroke_color != "transparent" else 0,
        method='label'
    )
    
    # Position the title
    margin_px_h = video_height * params.title_margin
    
    if params.title_position == "top":
        position = ("center", margin_px_h)
    elif params.title_position == "bottom":
        position = ("center", video_height - margin_px_h - txt_clip.h)
    else:  # center
        position = ("center", "center")
    
    txt_clip = txt_clip.with_position(position)
    
    # Apply animation
    animation_duration = params.title_animation_duration
    if params.title_animation == "fade_in":
        txt_clip = txt_clip.with_effects([vfx.FadeIn(animation_duration)])
    elif params.title_animation == "fade_out":
        txt_clip = txt_clip.with_effects([vfx.FadeOut(animation_duration)])
    elif params.title_animation == "slide_up":
        txt_clip = txt_clip.with_position(("center", video_height + txt_clip.h))
        txt_clip = txt_clip.with_effects([vfx.MoveToTargetPosition(
            ("center", position[1]),
            duration=animation_duration
        )])
    elif params.title_animation == "slide_down":
        txt_clip = txt_clip.with_position(("center", -txt_clip.h))
        txt_clip = txt_clip.with_effects([vfx.MoveToTargetPosition(
            ("center", position[1]),
            duration=animation_duration
        )])
    
    return txt_clip


def add_title_to_video(
    video_clip,
    params: VideoParams
) -> CompositeVideoClip:
    """
    Add title clip to video.
    
    Args:
        video_clip: Original video clip
        params: VideoParams containing title settings
    
    Returns:
        Composite video clip with title
    """
    if not params.title_enabled or not params.title_text:
        return video_clip
    
    video_width, video_height = video_clip.size
    title_duration = params.title_duration
    
    # Create title clip
    title_clip = create_title_clip(video_width, video_height, params)
    if title_clip is None:
        return video_clip
    
    # Set title duration
    title_clip = title_clip.with_duration(title_duration)
    
    # Create background overlay if enabled
    layers = []
    if params.title_background_overlay:
        overlay_color = parse_color(params.title_overlay_color)
        overlay = ColorClip(
            size=(video_width, video_height),
            color=overlay_color,
            duration=title_duration
        )
        layers.append(overlay)
    
    # Add original video (trimmed to title duration for overlay)
    layers.append(video_clip.subclipped(0, title_duration))
    
    # Add title clip
    layers.append(title_clip)
    
    # Create composite
    title_section = CompositeVideoClip(layers, size=(video_width, video_height))
    
    # Get remaining video (after title duration)
    remaining_video = video_clip.subclipped(title_duration) if video_clip.duration > title_duration else None
    
    # Concatenate title section with remaining video
    if remaining_video:
        from moviepy import concatenate_videoclips
        final_video = concatenate_videoclips([title_section, remaining_video])
    else:
        final_video = title_section
    
    logger.success(f"Title added to video successfully")
    return final_video


def apply_title_style(params: VideoParams, style_name: str) -> VideoParams:
    """
    Apply a predefined title style to the video parameters.
    
    Args:
        params: VideoParams object to modify
        style_name: Name of the style to apply
    
    Returns:
        Modified VideoParams with style applied
    """
    from app.services.title_styles import TITLE_STYLES
    
    if style_name not in TITLE_STYLES:
        logger.warning(f"Title style '{style_name}' not found, using defaults")
        return params
    
    style_params = TITLE_STYLES[style_name]["params"]
    
    # Apply style parameters
    for key, value in style_params.items():
        if hasattr(params, key):
            setattr(params, key, value)
    
    params.title_enabled = True
    logger.info(f"Applied title style: {style_name}")
    return params


def get_available_title_styles():
    """
    Get list of available title styles.
    
    Returns:
        Dictionary of available styles with metadata
    """
    from app.services.title_styles import TITLE_STYLES
    
    return {
        style_id: {
            "name": style["name"],
            "description": style["description"]
        }
        for style_id, style in TITLE_STYLES.items()
    }
```

### 3.5 Configuration Integration

Add title settings to `config.toml`:

```toml
[ui]
# ... existing settings ...

# Title settings
title_enabled = false
title_text = ""
title_duration = 3.0
title_font_name = "MicrosoftYaHeiBold.ttc"
title_font_size = 72
title_text_color = "#FFFFFF"
title_stroke_color = "#000000"
title_stroke_width = 2.0
title_background_color = "transparent"
title_position = "center"
title_margin = 0.05
title_animation = "none"
title_animation_duration = 0.5
title_background_overlay = false
title_overlay_color = "rgba(0,0,0,0.5)"
title_style = "classic"
```

### 3.6 Video Target Integration

Modify `app/services/video_target.py` to integrate title insertion:

```python
def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params,
    progress_callback=None,
):
    """
    Combine video, audio and subtitles into final video
    """
    # ... existing code ...
    
    try:
        # Load video
        video_clip = VideoFileClip(video_path)
        
        # Add title if enabled
        if hasattr(params, 'title_enabled') and params.title_enabled and hasattr(params, 'title_text') and params.title_text:
            logger.info("Adding title to video")
            from app.services.title import add_title_to_video
            video_clip = add_title_to_video(video_clip, params)
        
        # ... rest of the function ...
```

### 3.7 API Endpoints

Add endpoints to `app/controllers/v1/video.py`:

```python
@router.get("/title-styles", summary="Get available title styles")
def get_title_styles(request: Request):
    """Get list of available title styles"""
    from app.services.title import get_available_title_styles
    
    styles = get_available_title_styles()
    return utils.get_response(200, styles)


@router.post("/title-preview", summary="Preview title style")
def preview_title(request: Request, body: dict):
    """Generate a preview image for title style"""
    from app.services.title import create_title_clip
    from app.models.schema import VideoParams
    from app.models.schema import VideoAspect
    
    # Extract parameters from request
    params = VideoParams()
    params.title_enabled = body.get('title_enabled', True)
    params.title_text = body.get('title_text', 'Preview Title')
    params.title_font_name = body.get('title_font_name', 'MicrosoftYaHeiBold.ttc')
    params.title_font_size = body.get('title_font_size', 72)
    params.title_text_color = body.get('title_text_color', '#FFFFFF')
    params.title_stroke_color = body.get('title_stroke_color', '#000000')
    params.title_stroke_width = body.get('title_stroke_width', 2.0)
    params.title_background_color = body.get('title_background_color', 'transparent')
    params.title_position = body.get('title_position', 'center')
    params.title_margin = body.get('title_margin', 0.05)
    params.title_animation = body.get('title_animation', 'none')
    params.title_animation_duration = body.get('title_animation_duration', 0.5)
    
    # Use default video dimensions
    video_aspect = body.get('video_aspect', '9:16')
    if video_aspect == '9:16':
        width, height = 1080, 1920
    elif video_aspect == '16:9':
        width, height = 1920, 1080
    elif video_aspect == '1:1':
        width, height = 1080, 1080
    else:
        width, height = 1080, 1920
    
    # Create title clip
    title_clip = create_title_clip(width, height, params)
    
    if title_clip is None:
        raise HttpException(task_id="", status_code=400, message="Failed to create title clip")
    
    # Generate preview image path
    preview_dir = utils.storage_dir("title_previews", create=True)
    preview_path = os.path.join(preview_dir, f"title_preview_{utils.get_uuid()[:8]}.png")
    
    # Save first frame as preview
    title_clip.save_frame(preview_path, t=0)
    
    response = {"preview_path": preview_path}
    return utils.get_response(200, response)
```

### 3.8 Frontend Integration

The frontend will need to add a title configuration panel in `vue-frontend/src/views/VideoSettings.vue`:

```vue
<template>
  <div class="title-settings">
    <h3>Video Title Settings</h3>
    
    <div class="form-group">
      <label>Enable Title</label>
      <input type="checkbox" v-model="titleEnabled" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Title Text</label>
      <input type="text" v-model="titleText" placeholder="Enter video title" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Duration (seconds)</label>
      <input type="number" v-model="titleDuration" min="1" max="10" step="0.5" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Style Preset</label>
      <select v-model="titleStyle" @change="applyStyle">
        <option value="">Custom</option>
        <option v-for="(style, key) in titleStyles" :key="key" :value="key">
          {{ style.name }}
        </option>
      </select>
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Font</label>
      <select v-model="titleFontName">
        <option v-for="font in availableFonts" :key="font" :value="font">
          {{ font }}
        </option>
      </select>
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Font Size</label>
      <input type="number" v-model="titleFontSize" min="20" max="120" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Text Color</label>
      <input type="color" v-model="titleTextColor" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Stroke Color</label>
      <input type="color" v-model="titleStrokeColor" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Stroke Width</label>
      <input type="number" v-model="titleStrokeWidth" min="0" max="10" step="0.5" />
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Position</label>
      <select v-model="titlePosition">
        <option value="top">Top</option>
        <option value="center">Center</option>
        <option value="bottom">Bottom</option>
      </select>
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Animation</label>
      <select v-model="titleAnimation">
        <option value="none">None</option>
        <option value="fade_in">Fade In</option>
        <option value="fade_out">Fade Out</option>
        <option value="slide_up">Slide Up</option>
        <option value="slide_down">Slide Down</option>
      </select>
    </div>
    
    <div class="form-group" v-if="titleEnabled">
      <label>Background Overlay</label>
      <input type="checkbox" v-model="titleBackgroundOverlay" />
    </div>
    
    <div class="form-group" v-if="titleEnabled && titleBackgroundOverlay">
      <label>Overlay Color</label>
      <input type="color" v-model="titleOverlayColor" />
    </div>
  </div>
</template>
```

## 4. Static Style Set Details

### 4.1 Available Fonts

The feature will use existing fonts from `resource/fonts/`:

| Font File | Font Name | Language | Style |
|-----------|-----------|----------|-------|
| MicrosoftYaHeiBold.ttc | Microsoft YaHei Bold | Chinese | Bold |
| MicrosoftYaHeiNormal.ttc | Microsoft YaHei Normal | Chinese | Regular |
| STHeitiLight.ttc | ST Heiti Light | Chinese | Light |
| STHeitiMedium.ttc | ST Heiti Medium | Chinese | Medium |
| Charm-Bold.ttf | Charm Bold | Latin | Bold |
| Charm-Regular.ttf | Charm Regular | Latin | Regular |
| UTM Kabel KT.ttf | UTM Kabel KT | Latin/Vietnamese | Regular |

### 4.2 Style Presets

| Style ID | Name | Font | Font Size | Text Color | Stroke Color | Position | Animation |
|----------|------|------|-----------|------------|--------------|----------|-----------|
| classic | Classic | STHeitiMedium | 72 | #FFFFFF | #000000 | Center | Fade In |
| modern | Modern | MicrosoftYaHeiBold | 64 | #F5F5F5 | #333333 | Top | Slide Down |
| bold | Bold | MicrosoftYaHeiBold | 80 | #FFD700 | #8B4513 | Center | Fade In |
| minimal | Minimal | STHeitiLight | 60 | #FFFFFF | transparent | Bottom | None |
| dark_overlay | Dark Overlay | MicrosoftYaHeiBold | 68 | #FFFFFF | #000000 | Bottom | Fade In |
| gradient | Gradient | UTM Kabel KT | 76 | #FF6B6B | #4ECDC4 | Center | Slide Up |

## 5. Implementation Checklist

### 5.1 Backend Tasks

| Task | Status |
|------|--------|
| Add TitleParams schema to models/schema.py | Pending |
| Extend VideoParams with title fields | Pending |
| Create title_styles.py with static style sets | Pending |
| Create title.py service module | Pending |
| Update video_target.py to integrate title insertion | Pending |
| Add API endpoints for title styles and preview | Pending |
| Update config.toml with title settings | Pending |

### 5.2 Frontend Tasks

| Task | Status |
|------|--------|
| Add title settings panel to VideoSettings.vue | Pending |
| Add API calls for title styles | Pending |
| Add preview functionality | Pending |

## 6. Testing Strategy

### 6.1 Unit Tests

- Test title clip creation with various parameters
- Test style application function
- Test title positioning logic
- Test animation effects

### 6.2 Integration Tests

- Test video generation with title enabled
- Test title integration with different aspect ratios
- Test backward compatibility (title disabled)

### 6.3 Acceptance Criteria

| Criteria | Description |
|----------|-------------|
| AC-001 | Title appears at the beginning of video when enabled |
| AC-002 | Title duration matches configured value |
| AC-003 | Font settings are correctly applied |
| AC-004 | Color settings are correctly applied |
| AC-005 | Position settings work correctly |
| AC-006 | Animation effects work correctly |
| AC-007 | Style presets are applied correctly |
| AC-008 | Video generation works without title (backward compatibility) |

## 7. Security Considerations

1. **Input Sanitization**: Title text should be sanitized to prevent injection attacks
2. **Path Validation**: Font paths should be validated to prevent path traversal
3. **Resource Limits**: Title duration and font size should have reasonable limits
4. **Error Handling**: Graceful handling of missing fonts or invalid configurations

## 8. Performance Considerations

1. **Memory Management**: Title clips should be properly closed after use
2. **Caching**: Font loading can be cached for better performance
3. **Preview Optimization**: Preview generation should be lightweight
4. **Hybrid Encoding (Title Enabled)**: When a title is enabled, the encoding splits into two stages:
   - **Stage 1 (FFmpeg)**: Silence prefix, pillarbox, subtitle burn-in, BGM mixing, and EBU R128 loudness normalization (`loudnorm=I=-16:TP=-1.5:LRA=11`) are rendered into a temp file via a single FFmpeg filter_complex pass. This is 4-6× faster than MoviePy compositing for these elements.
   - **Stage 2 (MoviePy)**: The temp file is loaded, the PIL-based title clip is overlaid via `add_title_to_video()`, and MoviePy writes the final output. Since the title is typically only ~5s of a ~180s video, **97% of frames are plain passthrough** with no compositing. Total time: ~4 min (vs ~18 min for full MoviePy compositing).
   - **Quality**: The temp file uses CRF 18 encoding (visually lossless). One extra lossy generation occurs when MoviePy re-encodes, but this is equivalent to what would happen in the full MoviePy path anyway.
   - **Temp File Cleanup**: The temp file is always deleted in a `finally` block. On failure, the full MoviePy fallback path is used instead.

## 9. Backward Compatibility

The feature is designed to be fully backward compatible:
- Title is disabled by default (`title_enabled: false`)
- When disabled, the video generation process remains unchanged
- Existing API calls will continue to work without modification