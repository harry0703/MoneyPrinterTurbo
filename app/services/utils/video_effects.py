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
