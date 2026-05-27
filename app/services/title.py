import os
from typing import Optional
from loguru import logger
from moviepy import TextClip, CompositeVideoClip, ColorClip, vfx

from app.utils import utils
from app.services.video_utils import parse_color, wrap_text
from app.models.schema import VideoParams


def _get_valid_font_path(font_name: str, text: str = "") -> str:
    """
    Get a valid font path, with fallback to a system font if the specified font is not found.
    
    Args:
        font_name: Name of the font file to load
        text: Optional text to check character support
        
    Returns:
        Valid font path
    """
    # First, check if font_name is already a full path
    if os.path.isabs(font_name) and os.path.exists(font_name):
        # Check if font supports the text characters
        if text and not _font_supports_text(font_name, text):
            logger.warning(f"Font '{font_name}' does not support all characters in text")
        else:
            logger.info(f"Using absolute font path: {font_name}")
            return font_name
    
    # Check relative path from font_dir
    font_path = os.path.join(utils.font_dir(), font_name)
    if os.name == "nt":
        font_path = font_path.replace("\\", "/")
    
    # Check if font file exists
    if os.path.exists(font_path):
        # Check if font supports the text characters
        if text and not _font_supports_text(font_path, text):
            logger.warning(f"Font '{font_name}' does not support all characters in text")
        else:
            logger.info(f"Found font: {font_name} at {font_path}")
            return font_path
    
    # Fallback fonts in order of preference - only include fonts that exist
    fallback_fonts = [
        "STHeitiMedium.ttc",
        "MicrosoftYaHeiBold.ttc", 
        "MicrosoftYaHeiNormal.ttc",
        "STHeitiLight.ttc",
        "Charm-Bold.ttf",
        "Charm-Regular.ttf",
        "UTM Kabel KT.ttf",
    ]
    
    # Try fallback fonts
    for fallback_font in fallback_fonts:
        if fallback_font == font_name:
            continue  # Skip the font we already tried
        fallback_path = os.path.join(utils.font_dir(), fallback_font)
        if os.name == "nt":
            fallback_path = fallback_path.replace("\\", "/")
        if os.path.exists(fallback_path):
            # Check if fallback font supports the text
            if text and not _font_supports_text(fallback_path, text):
                continue  # Try next fallback
            logger.warning(f"Font '{font_name}' not found or doesn't support text, falling back to '{fallback_font}'")
            return fallback_path
    
    logger.error(f"Neither '{font_name}' nor any fallback fonts found in {utils.font_dir()}")
    logger.error(f"Available fonts: {os.listdir(utils.font_dir())}")
    return font_path


def _font_supports_text(font_path: str, text: str) -> bool:
    """
    Check if a font file supports all characters in the given text.
    
    Args:
        font_path: Path to the font file
        text: Text to check
        
    Returns:
        True if all characters are supported, False otherwise
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Create a temporary image to test rendering
        img = Image.new('RGB', (100, 100), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype(font_path, 40)
        except Exception:
            # Font cannot be loaded with PIL
            return False
        
        # Get bounding box for each character
        for char in text:
            # Skip whitespace
            if char.isspace():
                continue
            
            # Get bounding box - if font doesn't support char, bbox may be None or zero-sized
            bbox = draw.textbbox((0, 0), char, font=font)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            
            # If bbox is zero-sized, font doesn't support this character
            if width == 0 or height == 0:
                logger.debug(f"Font doesn't support character: '{char}' (Unicode: U+{ord(char):04X})")
                return False
        
        return True
    except Exception as e:
        logger.debug(f"Error checking font support: {str(e)}")
        return True  # Assume support if check fails


def create_title_clip(
    video_width: int,
    video_height: int,
    params: VideoParams
) -> Optional[TextClip]:
    if not params.title_enabled or not params.title_text:
        return None
    
    logger.info(f"Creating title clip: '{params.title_text}' ({video_width}x{video_height})")
    
    font_path = _get_valid_font_path(params.title_font_name, params.title_text)
    logger.info(f"Using font path: {font_path}")
    
    # Verify font file exists
    if not os.path.exists(font_path):
        logger.error(f"Font file does not exist: {font_path}")
        # Fallback to a known working font
        fallback_path = os.path.join(utils.font_dir(), "STHeitiMedium.ttc")
        if os.path.exists(fallback_path):
            logger.warning(f"Falling back to STHeitiMedium.ttc")
            font_path = fallback_path
        else:
            logger.error("No fallback font available!")
            return None
    
    margin_left_px = video_width * params.title_margin_left
    margin_right_px = video_width * params.title_margin_right
    max_width = video_width - margin_left_px - margin_right_px
    
    try:
        wrapped_text, text_height, _ = wrap_text(
            params.title_text,
            max_width=max_width,
            font=font_path,
            fontsize=int(params.title_font_size)
        )
        logger.info(f"Wrapped text: '{wrapped_text}'")
    except Exception as e:
        logger.error(f"Failed to wrap text: {str(e)}")
        # Fallback: use original text without wrapping
        wrapped_text = params.title_text
        text_height = params.title_font_size
        logger.warning(f"Using unwrapped text as fallback: '{wrapped_text}'")
    
    text_color = params.title_text_color
    stroke_color = params.title_stroke_color
    bg_color = params.title_background_color
    
    if bg_color == 'transparent' or bg_color is True:
        bg_color = None
    
    try:
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
        logger.info("TextClip created successfully using label method")
    except Exception as e:
        logger.error(f"Failed to create TextClip with label method: {str(e)}")
        try:
            txt_clip = TextClip(
                text=wrapped_text,
                font=font_path,
                font_size=int(params.title_font_size),
                color=text_color,
                bg_color=bg_color,
                stroke_color=stroke_color if stroke_color != "transparent" else None,
                stroke_width=int(params.title_stroke_width) if stroke_color != "transparent" else 0,
                method='pil'
            )
            logger.info("TextClip created successfully using PIL method")
        except Exception as e2:
            logger.error(f"Failed to create TextClip with PIL method: {str(e2)}")
            return None
    
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
    logger.warning(f"Title style '{style_name}' not supported, using defaults")
    return params


def get_available_title_styles():
    return {}