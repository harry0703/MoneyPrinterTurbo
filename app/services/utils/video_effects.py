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

    # MoviePy 内置 SlideIn 在当前这条处理链里对全屏素材不稳定，
    # 会出现“逻辑上应用了转场，但画面几乎看不出变化”的情况。
    # 这里改成显式黑底 + 位移动画，保证转场效果可见且行为可控。
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

    # SlideOut 同样改成显式位移，保证片段末尾能稳定滑出画面。
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


ZOOM_MAX_SCALE = 1.2


def _zoom_frame(frame: np.ndarray, scale_factor: float) -> np.ndarray:
    height, width = frame.shape[:2]
    crop_width = max(int(width / scale_factor), 1)
    crop_height = max(int(height / scale_factor), 1)
    x1 = (width - crop_width) // 2
    y1 = (height - crop_height) // 2
    cropped = frame[y1 : y1 + crop_height, x1 : x1 + crop_width]
    image = Image.fromarray(cropped)
    return np.asarray(image.resize((width, height), Image.LANCZOS))


# ZoomIn - Ken Burns style zoom across the whole clip; `t` is kept for the
# uniform transition signature but the ramp spans clip.duration.
def zoomin_transition(clip: Clip, t: float) -> Clip:
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        scale_factor = 1 + (ZOOM_MAX_SCALE - 1) * (current_time / duration)
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect)


# ZoomOut
def zoomout_transition(clip: Clip, t: float) -> Clip:
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        scale_factor = ZOOM_MAX_SCALE - (ZOOM_MAX_SCALE - 1) * (current_time / duration)
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect)
