from moviepy import Clip, vfx


# FadeIn
def fadein_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeIn(t)])


# FadeOut
def fadeout_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeOut(t)])


# SlideIn
def slidein_transition(clip: Clip, t: float, side: str) -> Clip:
    return clip.with_effects([vfx.SlideIn(t, side)])


# SlideOut
def slideout_transition(clip: Clip, t: float, side: str) -> Clip:
    return clip.with_effects([vfx.SlideOut(t, side)])


# Brightness enhancement
def brightness_enhance(clip: Clip, factor: float = 1.1) -> Clip:
    """
    Enhance video brightness.
    
    Args:
        clip: Video clip to enhance
        factor: Brightness factor (1.0 = no change, >1.0 = brighter, <1.0 = darker)
    
    Returns:
        Enhanced video clip
    """
    return clip.with_effects([vfx.MultiplyColor(factor)])


# Contrast enhancement
def contrast_enhance(clip: Clip, factor: float = 1.1) -> Clip:
    """
    Enhance video contrast using gamma correction.
    
    Args:
        clip: Video clip to enhance
        factor: Contrast factor (1.0 = no change, >1.0 = more contrast)
    
    Returns:
        Enhanced video clip
    """
    return clip.with_effects([vfx.GammaCorrection(factor)])


# Brightness detection
def detect_brightness(clip: Clip, num_samples: int = 10) -> float:
    """
    Detect average brightness of a video clip.
    
    Args:
        clip: Video clip to analyze
        num_samples: Number of frames to sample
    
    Returns:
        Average brightness value (0.0 = black, 1.0 = white)
    """
    import numpy as np
    from moviepy.video.io.ffmpeg_reader import FFMPEG_VideoReader
    
    # Get clip duration
    duration = clip.duration
    
    # Calculate sample times
    sample_times = np.linspace(0, duration, num_samples, endpoint=False)
    
    # Get the underlying video reader
    if hasattr(clip, 'reader') and isinstance(clip.reader, FFMPEG_VideoReader):
        reader = clip.reader
    else:
        # For subclips, we need to create a new reader
        from moviepy.video.io.VideoFileClip import VideoFileClip
        if hasattr(clip, 'filename'):
            reader = VideoFileClip(clip.filename).reader
        else:
            # Fallback: return medium brightness
            return 0.5
    
    total_brightness = 0
    valid_samples = 0
    
    try:
        for t in sample_times:
            try:
                # Read frame at time t
                frame = reader.get_frame(t)
                
                # Convert to grayscale and calculate average brightness
                if len(frame.shape) == 3:
                    # RGB frame
                    gray_frame = np.mean(frame, axis=2)
                else:
                    # Grayscale frame
                    gray_frame = frame
                
                # Normalize to 0-1 range
                brightness = np.mean(gray_frame) / 255.0
                total_brightness += brightness
                valid_samples += 1
            except Exception:
                continue
    finally:
        if 'reader' in locals() and reader != clip.reader:
            reader.close()
    
    if valid_samples > 0:
        return total_brightness / valid_samples
    else:
        # Fallback: return medium brightness
        return 0.5
