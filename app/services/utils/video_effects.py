import numpy as np
from moviepy import Clip, ColorClip, CompositeVideoClip, vfx
from PIL import Image


# FadeIn
def fadein_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeIn(t)])


# FadeOut
def fadeout_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeOut(t)])


# SlideIn
def slidein_transition(clip: Clip, t: float, side: str) -> Clip:
    width, height = clip.size

    # MoviePy's built-in SlideIn is unstable for full-screen footage on this processing chain:
    # the transition is "logically applied" but the picture barely changes.
    # Replace it with an explicit black background plus a translate animation so the effect is visible and predictable.
    def position(current_time: float):
        progress = min(max(current_time / max(t, 0.001), 0), 1)

        if side == "left":
            return (-width + width * progress, 0)
        if side == "right":
            return (width - width * progress, 0)
        if side == "top":
            return (0, -height + height * progress)
        if side == "bottom":
            return (0, height - height * progress)
        return (0, 0)

    background = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(
        clip.duration
    )
    moving_clip = clip.with_position(position)
    return CompositeVideoClip([background, moving_clip], size=(width, height)).with_duration(
        clip.duration
    )


# SlideOut
def slideout_transition(clip: Clip, t: float, side: str) -> Clip:
    width, height = clip.size
    transition_start = max(clip.duration - t, 0)

    # SlideOut likewise uses an explicit translate so the segment reliably slides out at its end.
    def position(current_time: float):
        if current_time <= transition_start:
            return (0, 0)

        progress = min(
            max((current_time - transition_start) / max(t, 0.001), 0), 1
        )

        if side == "left":
            return (-width * progress, 0)
        if side == "right":
            return (width * progress, 0)
        if side == "top":
            return (0, -height * progress)
        if side == "bottom":
            return (0, height * progress)
        return (0, 0)

    background = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(
        clip.duration
    )
    moving_clip = clip.with_position(position)
    return CompositeVideoClip([background, moving_clip], size=(width, height)).with_duration(
        clip.duration
    )


# Keep the original 20% zoom amplitude so even ~3-second clips show a clearly visible Ken Burns motion.
# Zoom stability comes from the sub-pixel center sampling below, not from weakening the effect to hide source-video encode flicker.
_ZOOM_MAX_SCALE = 1.2


def _zoom_frame(frame: np.ndarray, scale_factor: float) -> np.ndarray:
    """Implement stable, border-free zooming via sub-pixel center cropping.

    The crop width and height must not be rounded to integers first: as the zoom ratio changes
    continuously, integer boundaries jump in uneven steps and flip the half-pixel sampling phase
    between odd and even sizes, showing up as jitter. Pillow's EXTENT transform accepts float
    bounds directly and completes sub-pixel sampling onto a fixed output canvas; the left/right
    and top/bottom bounds stay symmetric around the same float center, which suits continuous
    slow zooming across a whole clip.
    """
    if scale_factor <= 0:
        raise ValueError("scale_factor must be greater than zero")

    # A 1x zoom returns the original frame, avoiding a pointless resample that would slightly blur the first frame.
    if abs(scale_factor - 1.0) < 1e-9:
        return frame

    height, width = frame.shape[:2]
    crop_width = width / scale_factor
    crop_height = height / scale_factor
    left = (width - crop_width) / 2
    top = (height - crop_height) / 2
    right = left + crop_width
    bottom = top + crop_height

    image = Image.fromarray(frame)
    transformed = image.transform(
        (width, height),
        Image.Transform.EXTENT,
        (left, top, right, bottom),
        # Continuous video zooming cares most about frame-to-frame consistency. BICUBIC/LANCZOS are sharper
        # per frame but tend to ring and flicker in brightness as high-frequency texture crosses the sampling
        # grid; BILINEAR is softer and trades a little sharpness for steadier motion.
        resample=Image.Resampling.BILINEAR,
    )
    return np.asarray(transformed)


def zoomin_transition(clip: Clip, t: float) -> Clip:
    """Smoothly zoom in from the original picture to 1.2x across the whole segment."""
    # t is kept for a uniform call signature with the other transition functions; the zoom must cover
    # the full segment, otherwise the picture would freeze abruptly after a brief zoom — unsuitable for static or low-motion footage.
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = 1 + (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect)


def zoomout_transition(clip: Clip, t: float) -> Clip:
    """Smoothly zoom out from 1.2x to the original picture across the whole segment."""
    # Same as zoomin_transition: t exists only for the unified transition call interface.
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = _ZOOM_MAX_SCALE - (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect)
