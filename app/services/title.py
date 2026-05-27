import os
from typing import Optional
from loguru import logger
from moviepy import TextClip, CompositeVideoClip, ColorClip, vfx

from app.utils import utils
from app.services.video_utils import parse_color, wrap_text
from app.models.schema import VideoParams


def _get_valid_font_path(font_name: str) -> str:
    """
    Get a valid font path, with fallback to a system font if the specified font is not found.
    
    Args:
        font_name: Name of the font file to load
        
    Returns:
        Valid font path
    """
    font_path = os.path.join(utils.font_dir(), font_name)
    if os.name == "nt":
        font_path = font_path.replace("\\", "/")
    
    # Check if font file exists
    if os.path.exists(font_path):
        return font_path
    
    # Fallback fonts in order of preference
    # Only include fonts that actually exist in the resource/fonts directory
    fallback_fonts = [
        "STHeitiMedium.ttc",
        "MicrosoftYaHeiBold.ttc", 
        "MicrosoftYaHeiNormal.ttc",
        "STHeitiLight.ttc",
        "Charm-Bold.ttf",
        "Charm-Regular.ttf",
        "UTM Kabel KT.ttf",
        "站酷仓耳渔阳体-W03.ttf",  # Medium weight 黄油体
        "站酷意大利体-01.ttf",
        "站酷意大利体-02.ttf",
    ]
    
    # Try fallback fonts
    for fallback_font in fallback_fonts:
        if fallback_font == font_name:
            continue  # Skip the font we already tried
        fallback_path = os.path.join(utils.font_dir(), fallback_font)
        if os.name == "nt":
            fallback_path = fallback_path.replace("\\", "/")
        if os.path.exists(fallback_path):
            logger.warning(f"Font '{font_name}' not found, falling back to '{fallback_font}'")
            return fallback_path
    
    logger.error(f"Neither '{font_name}' nor any fallback fonts found in {utils.font_dir()}")
    return font_path


def create_title_clip(
    video_width: int,
    video_height: int,
    params: VideoParams
) -> Optional[TextClip]:
    if not params.title_enabled or not params.title_text:
        return None
    
    logger.info(f"Creating title clip: '{params.title_text}' ({video_width}x{video_height})")
    
    font_path = _get_valid_font_path(params.title_font_name)
    
    margin_left_px = video_width * params.title_margin_left
    margin_right_px = video_width * params.title_margin_right
    max_width = video_width - margin_left_px - margin_right_px
    
    wrapped_text, text_height, _ = wrap_text(
        params.title_text,
        max_width=max_width,
        font=font_path,
        fontsize=int(params.title_font_size)
    )
    
    text_color = params.title_text_color
    stroke_color = params.title_stroke_color
    bg_color = params.title_background_color
    
    if bg_color == 'transparent' or bg_color is True:
        bg_color = None
    
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
    
    margin_px_h = video_height * params.title_margin
    
    if params.title_position == "top":
        position = ("center", margin_px_h)
    elif params.title_position == "bottom":
        position = ("center", video_height - margin_px_h - txt_clip.h)
    else:
        position = ("center", "center")
    
    txt_clip = txt_clip.with_position(position)
    
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
    if not params.title_enabled or not params.title_text:
        return video_clip
    
    video_width, video_height = video_clip.size
    title_duration = params.title_duration
    
    title_clip = create_title_clip(video_width, video_height, params)
    if title_clip is None:
        return video_clip
    
    title_clip = title_clip.with_duration(title_duration)
    
    layers = []
    if params.title_background_overlay:
        overlay_color = parse_color(params.title_overlay_color)
        overlay = ColorClip(
            size=(video_width, video_height),
            color=overlay_color,
            duration=title_duration
        )
        layers.append(overlay)
    
    layers.append(video_clip.subclipped(0, title_duration))
    layers.append(title_clip)
    
    title_section = CompositeVideoClip(layers, size=(video_width, video_height))
    
    remaining_video = video_clip.subclipped(title_duration) if video_clip.duration > title_duration else None
    
    if remaining_video:
        from moviepy import concatenate_videoclips
        final_video = concatenate_videoclips([title_section, remaining_video])
    else:
        final_video = title_section
    
    logger.success(f"Title added to video successfully")
    return final_video


def apply_title_style(params: VideoParams, style_name: str) -> VideoParams:
    from app.services.title_styles import TITLE_STYLES
    
    if style_name not in TITLE_STYLES:
        logger.warning(f"Title style '{style_name}' not found, using defaults")
        return params
    
    style_params = TITLE_STYLES[style_name]["params"]
    
    for key, value in style_params.items():
        if hasattr(params, key):
            setattr(params, key, value)
    
    params.title_enabled = True
    logger.info(f"Applied title style: {style_name}")
    return params


def get_available_title_styles():
    from app.services.title_styles import TITLE_STYLES
    
    return {
        style_id: {
            "name": style["name"],
            "description": style["description"]
        }
        for style_id, style in TITLE_STYLES.items()
    }