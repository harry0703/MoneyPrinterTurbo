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

    # MoviePy's built-in SlideIn is unstable for full-screen material in this processing chain,
    # where "the transition is logically applied but the picture barely changes".
    # It's replaced here with an explicit black background + position animation, so the transition is visible and behaves predictably.
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
    # bg_color keeps the composite opaque, so MoviePy does not build and encode
    # a full-frame transparency mask for every frame.
    return CompositeVideoClip(
        [background, moving_clip], size=(width, height), bg_color=(0, 0, 0)
    ).with_duration(clip.duration)


# SlideOut
def slideout_transition(clip: Clip, t: float, side: str) -> Clip:
    width, height = clip.size
    transition_duration = min(t, clip.duration)
    transition_start = max(clip.duration - transition_duration, 0)

    # SlideOut is likewise changed to explicit movement, so the clip reliably slides out of frame at the end.
    def position(current_time: float):
        if current_time <= transition_start:
            return (0, 0)

        progress = min(
            max((current_time - transition_start) / max(transition_duration, 0.001), 0), 1
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
    return CompositeVideoClip(
        [background, moving_clip], size=(width, height), bg_color=(0, 0, 0)
    ).with_duration(clip.duration)


# Keep the original design's 20% zoom amplitude, so even short clips of about three seconds have a clearly visible Ken Burns motion.
# Zoom stability comes from the sub-pixel center sampling below, rather than masking source video encoding flicker by weakening the effect.
_ZOOM_MAX_SCALE = 1.2


def _zoom_frame(frame: np.ndarray, scale_factor: float) -> np.ndarray:
    """Implement a stable zoom effect without black borders using sub-pixel center cropping.

    The crop width and height can't be converted to integers first: as the zoom ratio changes continuously, integer boundaries jump in uneven steps,
    and switching between odd and even sizes changes the half-pixel sampling phase, ultimately showing up as jitter. Pillow's EXTENT
    transform accepts float boundaries directly and does sub-pixel sampling on a fixed output canvas; the left/right and top/bottom boundaries
    always stay symmetric around the same float center, so it suits slow continuous zooming over an entire video.
    """
    if scale_factor <= 0:
        raise ValueError("scale_factor must be greater than zero")

    # At 1x zoom return the original frame directly, avoiding pointless resampling that slightly blurs the first frame.
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
        # Continuous video zooming cares more about consistency between adjacent frames. BICUBIC/LANCZOS are sharper per frame,
        # but high-frequency textures crossing the sampling grid tend to ring and flicker in brightness; BILINEAR is softer
        # and trades a little sharpness for more stable motion.
        resample=Image.Resampling.BILINEAR,
    )
    return np.asarray(transformed)


def zoomin_transition(clip: Clip, t: float) -> Clip:
    """Smoothly zoom in from the original frame to 1.2x over the whole clip."""
    # t is kept for now to match the call signature of other transition functions; the zoom must cover the whole clip,
    # otherwise the picture would freeze abruptly after a brief zoom, which doesn't suit static or low-motion material.
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = 1 + (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect, apply_to=["mask"])


def zoomout_transition(clip: Clip, t: float) -> Clip:
    """Smoothly zoom out from 1.2x to the original frame over the whole clip."""
    # As with zoomin_transition, t is only for compatibility with the unified transition call interface.
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = _ZOOM_MAX_SCALE - (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect, apply_to=["mask"])
