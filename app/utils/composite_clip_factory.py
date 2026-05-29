from moviepy import CompositeVideoClip
from loguru import logger


def create_composite_video_clip(clips, **kwargs):
    """
    Create a CompositeVideoClip with guaranteed duration set.
    
    This factory function solves MoviePy v2's issue where CompositeVideoClip
    doesn't automatically set the duration attribute.
    
    Args:
        clips: List of clips to composite
        **kwargs: Additional arguments for CompositeVideoClip
        
    Returns:
        CompositeVideoClip object with duration properly set
    """
    # Calculate maximum end time from all clips
    valid_clips = [c for c in clips if (getattr(c, 'end', None) is not None or getattr(c, 'duration', None) is not None)]
    
    if valid_clips:
        max_end = max(
            (getattr(c, 'end', None) if getattr(c, 'end', None) is not None else getattr(c, 'duration', 0))
            for c in valid_clips
        )
    else:
        # Fallback: no valid clips, use default
        max_end = 60
        logger.warning(f"create_composite_video_clip: No clips with valid duration, using default {max_end}s")
    
    # Create composite clip
    composite_clip = CompositeVideoClip(clips, **kwargs)
    
    # Explicitly set duration and end attributes
    composite_clip.duration = max_end
    composite_clip.end = max_end
    
    logger.info(f"create_composite_video_clip: Created CompositeVideoClip with duration={max_end}s from {len(clips)} clips")
    
    # Double-check: verify duration is actually set
    if not hasattr(composite_clip, 'duration') or composite_clip.duration is None:
        logger.error(f"create_composite_video_clip: FAILED to set duration! Setting fallback duration")
        composite_clip.duration = max_end
        composite_clip.end = max_end
    
    return composite_clip


def safe_concatenate_videoclips(clips, **kwargs):
    """
    Safely concatenate video clips and ensure duration is set.
    
    Args:
        clips: List of video clips to concatenate
        **kwargs: Additional arguments for concatenate_videoclips
        
    Returns:
        Concatenated video clip with guaranteed duration set
    """
    from moviepy import concatenate_videoclips
    
    # Calculate expected total duration
    expected_duration = 0
    for clip in clips:
        clip_duration = getattr(clip, 'duration', 0)
        if clip_duration:
            expected_duration += clip_duration
        elif getattr(clip, 'end', None):
            expected_duration += (clip.end - getattr(clip, 'start', 0))
    
    # Create concatenated clip
    result_clip = concatenate_videoclips(clips, **kwargs)
    
    # Ensure duration is set
    if not hasattr(result_clip, 'duration') or result_clip.duration is None:
        if expected_duration > 0:
            result_clip.duration = expected_duration
            result_clip.end = expected_duration
            logger.debug(f"safe_concatenate_videoclips: Set duration to {expected_duration}s manually")
        else:
            logger.warning(f"safe_concatenate_videoclips: Could not determine duration, setting to 60s default")
            result_clip.duration = 60
            result_clip.end = 60
    
    return result_clip


def ensure_clip_duration(clip, fallback_duration=60):
    """
    Ensure a video clip has a valid duration attribute.
    
    Args:
        clip: Any MoviePy video clip
        fallback_duration: Duration to use if cannot be determined
        
    Returns:
        The original clip with duration guaranteed to be set
    """
    current_duration = getattr(clip, 'duration', 'NOT SET')
    logger.info(f"ensure_clip_duration: Input clip duration={current_duration}")
    
    if hasattr(clip, 'duration') and clip.duration is not None:
        logger.info(f"ensure_clip_duration: Duration already set to {clip.duration}")
        return clip
    
    # Try to compute from end and start
    if hasattr(clip, 'end'):
        clip_start = getattr(clip, 'start', 0)
        clip.duration = clip.end - clip_start
        clip.end = clip.duration + clip_start
        logger.info(f"ensure_clip_duration: Computed duration {clip.duration}s from end attribute")
        return clip
    
    # Use fallback
    clip.duration = fallback_duration
    clip.end = fallback_duration
    logger.warning(f"ensure_clip_duration: Set fallback duration {fallback_duration}s")
    
    return clip