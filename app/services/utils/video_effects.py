import numpy as np
from moviepy import Clip, CompositeVideoClip, vfx
from moviepy.tools import compute_position
from PIL import Image


def _compose_layer_in_box(layer_clip, frame: np.ndarray, t: float) -> None:
    """
    Draw one layer onto an opaque RGB frame in place, as VideoClip.compose_on does.

    For a layer with transparency, MoviePy converts the whole frame to RGBA,
    pastes the layer onto a transparent canvas of the same size and
    alpha-composites the two. Transparent pixels leave the frame unchanged, so
    blending only the box that the layer covers gives the same pixels. For a
    subtitle line that box is a small part of the frame.
    """
    clip_time = t - layer_clip.start
    color = np.asarray(layer_clip.get_frame(clip_time), dtype=np.uint8)
    height, width = color.shape[:2]
    frame_height, frame_width = frame.shape[:2]
    x, y = compute_position(
        (width, height),
        (frame_width, frame_height),
        layer_clip.pos(clip_time),
        layer_clip.relative_pos,
    )
    left, top = max(x, 0), max(y, 0)
    right, bottom = min(x + width, frame_width), min(y + height, frame_height)
    if left >= right or top >= bottom:
        return
    if layer_clip.mask is None and color.ndim == 3 and color.shape[2] == 3:
        frame[top:bottom, left:right] = color[top - y : bottom - y, left - x : right - x]
        return

    layer = Image.fromarray(color)
    if layer_clip.mask is not None:
        mask = Image.fromarray(
            (layer_clip.mask.get_frame(clip_time) * 255).astype("uint8")
        ).convert("L")
        if mask.size != layer.size:
            # Like MoviePy, align the mask at the top left, then crop it or
            # fill the rest with transparency.
            fitted_mask = Image.new("L", layer.size, 0)
            fitted_mask.paste(mask, (0, 0))
            mask = fitted_mask
        layer = layer.convert("RGBA")
        layer.putalpha(mask)
    layer = layer.crop((left - x, top - y, right - x, bottom - y))
    if layer.mode == "RGBA":
        region = Image.fromarray(frame[top:bottom, left:right]).convert("RGBA")
        layer = Image.alpha_composite(region, layer)
    frame[top:bottom, left:right] = np.asarray(layer.convert("RGB"))


class OpaqueCompositeVideoClip(CompositeVideoClip):
    """
    CompositeVideoClip on an opaque background color that draws each layer in its box.

    The constructor is CompositeVideoClip's, so size, duration, layer order and
    closing stay the same, and the frames are identical. MoviePy builds every
    frame from a ColorClip of the background color, held as an int64 array that
    it converts to uint8 for each frame, and alpha-composites every transparent
    layer over the full frame. Here the frame starts as a uint8 array of the
    background color and each layer touches only the pixels it covers.
    """

    def __init__(self, clips, size=None, bg_color=(0, 0, 0)):
        super().__init__(clips, size=size, bg_color=bg_color)

    def frame_function(self, t):
        frame = np.empty((self.size[1], self.size[0], 3), dtype=np.uint8)
        frame[:] = self.bg_color
        for layer_clip in self.playing_clips(t):
            _compose_layer_in_box(layer_clip, frame, t)
        return frame


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

    moving_clip = clip.with_position(position)
    # The composite's own black background is the canvas the clip slides over.
    # It is opaque, so MoviePy does not build and encode a full-frame
    # transparency mask for every frame.
    return OpaqueCompositeVideoClip(
        [moving_clip], size=(width, height)
    ).with_duration(clip.duration)


# SlideOut
def slideout_transition(clip: Clip, t: float, side: str) -> Clip:
    width, height = clip.size
    transition_duration = min(t, clip.duration)
    transition_start = max(clip.duration - transition_duration, 0)

    # SlideOut 同样改成显式位移，保证片段末尾能稳定滑出画面。
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

    moving_clip = clip.with_position(position)
    return OpaqueCompositeVideoClip(
        [moving_clip], size=(width, height)
    ).with_duration(clip.duration)


# 保留原始设计的 20% 缩放幅度，让三秒左右的短片也有清晰可见的 Ken Burns 运动感。
# 缩放稳定性由下方的亚像素中心采样保证，不通过削弱效果幅度来掩盖源视频编码闪烁。
_ZOOM_MAX_SCALE = 1.2


def _zoom_frame(frame: np.ndarray, scale_factor: float) -> np.ndarray:
    """使用亚像素中心裁剪实现无黑边且稳定的缩放效果。

    不能先把裁剪宽高转换为整数：缩放比例连续变化时，整数边界会按不同步长跳动，
    并在奇偶尺寸切换时改变半像素采样相位，最终表现为画面抖动。Pillow 的 EXTENT
    变换可以直接接收浮点边界，在固定输出画布上完成亚像素采样；左右、上下边界
    始终围绕同一个浮点中心对称，因此适用于整段视频持续缓慢缩放的场景。
    """
    if scale_factor <= 0:
        raise ValueError("scale_factor must be greater than zero")

    # 1 倍缩放直接返回原帧，避免无意义的重采样造成首帧轻微模糊。
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
        # 视频连续缩放更关注相邻帧的一致性。BICUBIC/LANCZOS 虽然单帧更锐利，
        # 但高频纹理跨越采样网格时容易出现振铃和亮度闪烁；BILINEAR 更柔和，
        # 能以少量锐度损失换取更稳定的动态观感。
        resample=Image.Resampling.BILINEAR,
    )
    return np.asarray(transformed)


def zoomin_transition(clip: Clip, t: float) -> Clip:
    """在整个片段内从原始画面平滑放大到 1.2 倍。"""
    # t 暂时保留，用于与其它转场函数保持统一调用签名；缩放需要覆盖完整片段，
    # 否则短暂缩放结束后画面会突然静止，不适合静态或低运动量素材。
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = 1 + (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect, apply_to=["mask"])


def zoomout_transition(clip: Clip, t: float) -> Clip:
    """在整个片段内从 1.2 倍平滑缩小到原始画面。"""
    # 与 zoomin_transition 一致，t 仅用于兼容统一的转场调用接口。
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = _ZOOM_MAX_SCALE - (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect, apply_to=["mask"])
