import os
import numpy as np
from typing import Optional, Union
from moviepy import VideoClip, ImageClip
from loguru import logger
from moviepy import CompositeVideoClip, ColorClip, vfx
from PIL import Image, ImageDraw, ImageFont

from app.utils import utils
from app.utils.composite_clip_factory import create_composite_video_clip, safe_concatenate_videoclips
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
) -> Optional[Union[VideoClip, CompositeVideoClip]]:
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
    
    font_size = int(params.title_font_size)
    
    # Load font first for accurate text measurement
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception as e:
        logger.error(f"Failed to load font: {str(e)}")
        return None
    
    # Parse colors
    text_color = parse_color(params.title_text_color)
    stroke_color = parse_color(params.title_stroke_color) if params.title_stroke_color != "transparent" else None
    stroke_width = int(params.title_stroke_width) if params.title_stroke_color != "transparent" else 0
    
    bg_color = None
    if params.title_background_color != 'transparent' and params.title_background_color is not True:
        bg_color = parse_color(params.title_background_color)
    
    # Create temporary draw object to measure text
    temp_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    
    # Wrap text manually using PIL's actual text measurement
    # First split by existing newlines to preserve original line breaks!
    original_lines = params.title_text.split('\n')
    lines = []
    
    def get_text_width(txt):
        bbox = temp_draw.textbbox((0, 0), txt, font=font, stroke_width=stroke_width)
        return bbox[2] - bbox[0]
    
    # Process each original line
    for orig_line in original_lines:
        if not orig_line:
            lines.append('')
            continue
            
        # Check if this original line fits on one line
        if get_text_width(orig_line) <= max_width:
            lines.append(orig_line)
            continue
        
        # Need to wrap this individual original line
        punctuation_chars = '，,。.！!？?；;：:、'
        
        current_line = orig_line
        while current_line:
            line_width = get_text_width(current_line)
            
            if line_width <= max_width:
                lines.append(current_line)
                break
            
            # Find best split position
            best_split = 1
            best_width = get_text_width(current_line[:1])
            
            for i in range(2, len(current_line)):
                w = get_text_width(current_line[:i])
                if w <= max_width and w > best_width:
                    best_width = w
                    best_split = i
                    # Prefer splitting at punctuation
                    if current_line[i-1] in punctuation_chars:
                        break
            
            lines.append(current_line[:best_split])
            current_line = current_line[best_split:].lstrip()
    
    logger.info(f"Wrapped text: '{chr(10).join(lines)}'")
    
    # Calculate total dimensions and line heights
    line_heights = []
    max_line_width = 0
    
    for line in lines:
        if not line.strip():
            line_heights.append(font_size * 1.2)
            continue
        bbox = temp_draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        line_width = bbox[2] - bbox[0]
        line_height = bbox[3] - bbox[1]
        
        max_line_width = max(max_line_width, line_width)
        line_heights.append(line_height + 4)  # Add small padding
    
    # Calculate total height
    total_height = int(sum(line_heights))
    
    # To match preview: use max_width (the available width) as img_width
    # This ensures we have a block that fills the available width, just like the preview
    img_width = int(max_width)
    img_height = total_height
    
    logger.info(f"Setting image width to max_width={img_width} to match preview's text block size")
    
    # Create RGBA image for transparency support
    img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw background color if needed
    if bg_color:
        # Convert RGB to RGBA if necessary
        if len(bg_color) == 3:
            bg_color = (bg_color[0], bg_color[1], bg_color[2], 255)
        draw.rectangle([(0, 0), (img_width, img_height)], fill=bg_color)
    
    # Draw each line with correct alignment
    logger.info(f"Drawing {len(lines)} lines with title_align={params.title_align}:")
    current_y = 0
    for i, line in enumerate(lines):
        # Calculate y position increment even if it's empty
        line_height = line_heights[i]
        
        if line.strip():
            # Get line dimensions
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
            line_width = bbox[2] - bbox[0]
            
            # Calculate x position for this line based on alignment
            if params.title_align == "left":
                x = 0
            elif params.title_align == "right":
                x = img_width - line_width
            else:  # center
                x = (img_width - line_width) // 2
            
            logger.info(f"  Line {i}: '{line}', line_width={line_width}, x={x}, current_y={current_y}")
            
            # Draw text with stroke
            if stroke_color and stroke_width > 0:
                # Draw stroke
                draw.text((x, current_y), line, font=font, fill=stroke_color, 
                          stroke_width=stroke_width, stroke_fill=stroke_color)
            
            # Draw text on top
            draw.text((x, current_y), line, font=font, fill=text_color)
        
        # Always advance y, even for empty lines!
        current_y += line_height
    
    logger.info(f"PIL image dimensions: width={img_width}, height={img_height}")
    
    # Convert PIL image to numpy array, then to MoviePy ImageClip
    try:
        img_array = np.array(img)
        img_clip = ImageClip(img_array)
    except Exception as e:
        logger.error(f"Failed to create ImageClip: {str(e)}")
        return None
    
    # Calculate position of entire text block on video
    margin_px_h = video_height * params.title_margin
    
    # Log debug info for position calculation
    logger.info(f"Position calculation params:")
    logger.info(f"  video_width: {video_width}, video_height: {video_height}")
    logger.info(f"  title_align: {params.title_align}")
    logger.info(f"  margin_left_px: {margin_left_px}, margin_right_px: {margin_right_px}")
    logger.info(f"  max_width: {max_width}, img_width: {img_width}, img_height: {img_height}")
    
    # Calculate horizontal (X) position of entire block
    # Since image width is max_width, entire block is always positioned at margin_left_px!
    block_x = margin_left_px
    logger.info(f"  Image width matches max_width, so block_x = {block_x} (margin_left_px)")
    
    # Calculate vertical (Y) position
    if params.title_position == "top":
        block_y = margin_px_h
        logger.info(f"  Using top position: block_y = {block_y}")
    elif params.title_position == "bottom":
        block_y = video_height - margin_px_h - img_height
        logger.info(f"  Using bottom position: block_y = {block_y}")
    else:  # center
        block_y = "center"
        logger.info(f"  Using center position: block_y = center")
        
    position = (block_x, block_y)
    logger.info(f"Final position for title clip: {position}")
    img_clip = img_clip.with_position(position)
    
    # Ensure duration is set
    if not hasattr(img_clip, 'duration') or img_clip.duration is None:
        img_clip.duration = 5.0
        img_clip.end = 5.0
    
    # Apply animations
    animation_duration = params.title_animation_duration
    if params.title_animation == "fade_in":
        img_clip = img_clip.with_effects([vfx.FadeIn(animation_duration)])
    elif params.title_animation == "fade_out":
        img_clip = img_clip.with_effects([vfx.FadeOut(animation_duration)])
    elif params.title_animation == "slide_up":
        img_clip = img_clip.with_position((block_x, video_height + img_height))
        img_clip = img_clip.with_effects([vfx.MoveToTargetPosition(
            (block_x, block_y) if block_y != "center" else (block_x, (video_height - img_height)/2),
            duration=animation_duration
        )])
    elif params.title_animation == "slide_down":
        start_y = -img_height
        end_y = block_y if block_y != "center" else (video_height - img_height)/2
        img_clip = img_clip.with_position((block_x, start_y))
        img_clip = img_clip.with_effects([vfx.MoveToTargetPosition(
            (block_x, end_y),
            duration=animation_duration
        )])
    
    return img_clip


def add_title_to_video(
    video_clip,
    params: VideoParams
) -> CompositeVideoClip:
    if not params.title_enabled or not params.title_text:
        return video_clip
    
    logger.debug(f"add_title_to_video - Input video_clip duration: {getattr(video_clip, 'duration', 'NOT SET')}")
    
    # Ensure input video_clip has duration before proceeding
    if not hasattr(video_clip, 'duration') or video_clip.duration is None:
        # Try to compute duration from end and start
        if hasattr(video_clip, 'end'):
            video_start = getattr(video_clip, 'start', 0)
            video_clip.duration = video_clip.end - video_start
            logger.debug(f"add_title_to_video - Computed duration from end: {video_clip.duration}")
        else:
            logger.error(f"DEBUG add_title_to_video - Cannot determine video_clip duration, cannot add title")
            return video_clip
    
    video_width, video_height = video_clip.size
    title_duration = params.title_duration
    logger.debug(f"add_title_to_video - title_duration: {title_duration}")
    
    title_clip = create_title_clip(video_width, video_height, params)
    if title_clip is None:
        logger.error(f"Failed to create title clip for text '{params.title_text}' — title will NOT appear in final video. "
                     f"Check font availability and rendering configuration.")
        return video_clip
    
    # Check if title_clip has duration before calling with_duration
    title_clip_has_duration = hasattr(title_clip, 'duration') and title_clip.duration is not None
    logger.debug(f"add_title_to_video - title_clip has duration: {title_clip_has_duration}, value: {getattr(title_clip, 'duration', 'NOT SET')}")
    
    # Ensure title_clip has duration before calling with_duration
    if not title_clip_has_duration:
        title_clip.duration = title_duration
        title_clip.end = title_duration
        logger.debug(f"add_title_to_video - Set title_clip duration to {title_duration} before with_duration")
    
    title_clip = title_clip.with_duration(title_duration)
    logger.debug(f"add_title_to_video - title_clip duration after with_duration: {getattr(title_clip, 'duration', 'NOT SET')}")
    
    layers = []
    if params.title_background_overlay:
        overlay_color = parse_color(params.title_overlay_color)
        overlay = ColorClip(
            size=(video_width, video_height),
            color=overlay_color,
            duration=title_duration
        )
        layers.append(overlay)
    
    # Get subclip and ensure it has duration
    video_subclip = video_clip.subclipped(0, title_duration)
    video_subclip_duration = getattr(video_subclip, 'duration', None)
    if video_subclip_duration is None:
        video_subclip.duration = title_duration
        video_subclip.end = title_duration
        logger.debug(f"add_title_to_video - Set subclip duration to {title_duration}")
    layers.append(video_subclip)
    layers.append(title_clip)
    
    title_section = create_composite_video_clip(layers, size=(video_width, video_height))
    title_section_duration = getattr(title_section, 'duration', 'NOT SET')
    logger.debug(f"add_title_to_video - title_section duration: {title_section_duration}")
    # Ensure title_section has duration
    if title_section_duration == 'NOT SET' or title_section_duration is None:
        logger.error(f"DEBUG add_title_to_video - title_section has no duration!")
        title_section.duration = title_duration
        title_section.end = title_duration
        logger.debug(f"add_title_to_video - Set title_section duration to {title_duration}")
    
    # Safe way to get video_clip duration
    video_duration = getattr(video_clip, 'duration', None)
    remaining_video = None
    if video_duration and video_duration > title_duration:
        remaining_video = video_clip.subclipped(title_duration)
        # Ensure remaining_video has duration
        remaining_duration = getattr(remaining_video, 'duration', None)
        if remaining_duration is None:
            remaining_duration = video_duration - title_duration
            remaining_video.duration = remaining_duration
            remaining_video.end = remaining_duration
            logger.debug(f"add_title_to_video - Set remaining_video duration to {remaining_duration}")
    
    logger.debug(f"add_title_to_video - remaining_video exists: {remaining_video is not None}, duration: {getattr(remaining_video, 'duration', 'NOT SET')}")
    
    if remaining_video:
        final_video = safe_concatenate_videoclips([title_section, remaining_video])
        logger.debug(f"add_title_to_video - After safe_concatenate_videoclips, duration: {getattr(final_video, 'duration', 'NOT SET')}")
    else:
        final_video = title_section
    
    logger.debug(f"add_title_to_video - Returning final_video with duration: {getattr(final_video, 'duration', 'NOT SET')}")
    logger.success(f"Title added to video successfully")
    return final_video


def apply_title_style(params: VideoParams, style_name: str) -> VideoParams:
    logger.warning(f"Title style '{style_name}' not supported, using defaults")
    return params


def get_available_title_styles():
    return {}