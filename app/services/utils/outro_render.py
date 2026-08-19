"""
片尾"关注"角标的逐帧绘制。

短视频的完播率决定分发量，因此这里刻意不做"另起一段片尾"：动画直接叠加在
正片最后一秒多的画面上，成片时长不变，观众也不会收到"结束了"的信号而提前
划走。模块只负责画出某一时刻的角标，出现时机与叠加交给合成层。

与 ``subtitle_render`` 同理，MoviePy 无法表达"logo 弹入 + 按钮呼吸"这类
动画，只能自行逐帧落图后交给 ``ImageSequenceClip``。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

# 时间轴按整体进度归一化，这样改片尾时长不需要重算每一段。
_LOGO_IN_END = 0.30
_PILL_IN_START = 0.22
_PILL_IN_END = 0.52
_PULSE_START = 0.55
_PULSE_PERIOD = 0.42

_RING_RATIO = 0.045
_HANDLE_FONT_RATIO = 0.155
_PILL_FONT_RATIO = 0.150
_PILL_HEIGHT_RATIO = 0.310
_PILL_PAD_X_RATIO = 0.230


@dataclass(frozen=True)
class OutroPose:
    """某一帧里各元素的形变与透明度，0~1 的 alpha。"""

    logo_scale: float
    logo_alpha: float
    pill_scale: float
    pill_alpha: float
    pill_rise: float  # 相对 pill 高度的上移比例，1 表示还在下方


def _ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """带回弹的缓出。logo 略微超出目标再收回，比线性放大更"活"。"""
    t -= 1.0
    return t * t * ((overshoot + 1) * t + overshoot) + 1.0


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _segment(progress: float, start: float, end: float) -> float:
    if progress <= start:
        return 0.0
    if progress >= end:
        return 1.0
    return (progress - start) / (end - start)


def outro_pose(progress: float) -> OutroPose:
    """
    把整体进度映射成各元素的姿态。

    这是片尾动画唯一的时间逻辑，独立于绘制，便于直接断言"logo 先出现、
    按钮后出现、结尾不淡出"这些容易被改坏的性质。
    """
    progress = min(1.0, max(0.0, progress))

    logo_t = _segment(progress, 0.0, _LOGO_IN_END)
    pill_t = _segment(progress, _PILL_IN_START, _PILL_IN_END)

    if progress >= _PULSE_START:
        phase = (progress - _PULSE_START) / _PULSE_PERIOD
        pulse = 1.0 + 0.05 * math.sin(phase * 2 * math.pi)
    else:
        pulse = 1.0

    return OutroPose(
        logo_scale=0.45 + 0.55 * _ease_out_back(logo_t) if logo_t else 0.0,
        logo_alpha=_ease_out_cubic(logo_t),
        pill_scale=pulse if pill_t >= 1.0 else 0.85 + 0.15 * _ease_out_cubic(pill_t),
        pill_alpha=_ease_out_cubic(pill_t),
        pill_rise=1.0 - _ease_out_cubic(pill_t),
    )


def circular_logo(image: Image.Image, size: int, ring_width: int) -> Image.Image:
    """
    把方形头像裁成带白环的圆形。

    圆形头像是 Instagram/TikTok 的既有视觉语言，观众不需要任何说明就知道
    这是一个账号，比直接贴方形 logo 更快被识别。
    """
    inner = max(1, size - 2 * ring_width)
    source = image.convert("RGBA").resize((inner, inner), Image.LANCZOS)

    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, inner - 1, inner - 1], fill=255)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if ring_width > 0:
        draw.ellipse([0, 0, size - 1, size - 1], fill=(255, 255, 255, 255))
    canvas.paste(source, (ring_width, ring_width), mask)
    return canvas


def _load_font(font_path: str, size: int):
    try:
        return ImageFont.truetype(font_path, size)
    except OSError:
        return ImageFont.load_default(size)


def _scaled(layer: Image.Image, scale: float, alpha: float) -> Image.Image | None:
    """按比例缩放并整体调透明度，返回可直接 alpha_composite 的图层。"""
    if alpha <= 0.0 or scale <= 0.0:
        return None
    width = max(1, int(round(layer.width * scale)))
    height = max(1, int(round(layer.height * scale)))
    resized = layer.resize((width, height), Image.LANCZOS)
    if alpha < 1.0:
        channels = list(resized.split())
        channels[3] = channels[3].point(lambda value: int(value * alpha))
        resized = Image.merge("RGBA", channels)
    return resized


def _paste_centered(canvas: Image.Image, layer: Image.Image | None, center) -> None:
    if layer is None:
        return
    x = int(center[0] - layer.width / 2)
    y = int(center[1] - layer.height / 2)
    canvas.alpha_composite(layer, (x, y))


def readable_text_color(background: str) -> str:
    """
    按背景亮度选黑或白字。

    每个账号的强调色沿用它字幕的高亮色，其中既有深粉也有亮黄；写死白字会让
    黄色按钮上的文字彻底看不清，所以由亮度决定而不是由配置决定。
    """
    try:
        rgb = ImageColor.getrgb(background)[:3]
    except ValueError:
        return "#FFFFFF"
    luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
    return "#111111" if luminance > 0.55 else "#FFFFFF"


def _build_pill(
    label: str, font, accent_color: str, height: int, pad_x: int
) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), label, font=font)
    width = (right - left) + 2 * pad_x

    pill = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pill)
    draw.rounded_rectangle(
        [0, 0, width - 1, height - 1], radius=height // 2, fill=accent_color
    )
    draw.text(
        ((width - (right - left)) // 2 - left, (height - (bottom - top)) // 2 - top),
        label,
        font=font,
        fill=readable_text_color(accent_color),
    )
    return pill


def _build_handle(handle: str, font) -> Image.Image | None:
    if not handle:
        return None
    stroke = max(2, int(font.size * 0.14))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox(
        (0, 0), handle, font=font, stroke_width=stroke
    )
    layer = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (-left, -top),
        handle,
        font=font,
        fill="#FFFFFF",
        stroke_width=stroke,
        stroke_fill="#000000",
    )
    return layer


def render_outro_frames(
    logo_path: str,
    handle: str,
    font_path: str,
    accent_color: str = "#FF2E88",
    logo_size: int = 300,
    label: str = "FOLLOW",
    duration: float = 1.2,
    fps: int = 25,
) -> list[np.ndarray]:
    """
    渲染整段片尾角标，返回 RGBA 帧序列。

    只绘制角标本身而不是整幅画面：1080x1920 的全屏帧列表会占用几百 MB 内存，
    而角标画布不到十分之一，定位交给合成层即可。
    """
    frame_count = max(1, int(round(duration * fps)))

    ring = max(2, int(logo_size * _RING_RATIO))
    logo_layer = None
    if logo_path and os.path.isfile(logo_path):
        with Image.open(logo_path) as source:
            logo_layer = circular_logo(source, logo_size, ring)

    handle_font = _load_font(font_path, max(10, int(logo_size * _HANDLE_FONT_RATIO)))
    pill_font = _load_font(font_path, max(10, int(logo_size * _PILL_FONT_RATIO)))

    handle_layer = _build_handle(handle, handle_font)
    pill_layer = _build_pill(
        label,
        pill_font,
        accent_color,
        height=max(8, int(logo_size * _PILL_HEIGHT_RATIO)),
        pad_x=max(4, int(logo_size * _PILL_PAD_X_RATIO)),
    )

    gap = int(logo_size * 0.10)
    handle_height = handle_layer.height if handle_layer else 0
    handle_gap = gap if handle_layer else 0
    content_height = logo_size + handle_gap + handle_height + gap + pill_layer.height
    content_width = max(logo_size, pill_layer.width, handle_layer.width if handle_layer else 0)

    # 留出回弹与呼吸的余量，否则放大的瞬间会被画布边缘裁掉。
    canvas_width = int(content_width * 1.22)
    canvas_height = int(content_height * 1.16)

    center_x = canvas_width / 2
    top = (canvas_height - content_height) / 2
    logo_center_y = top + logo_size / 2
    handle_center_y = top + logo_size + handle_gap + handle_height / 2
    pill_center_y = top + content_height - pill_layer.height / 2

    frames = []
    for index in range(frame_count):
        progress = index / (frame_count - 1) if frame_count > 1 else 1.0
        pose = outro_pose(progress)

        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        if logo_layer is not None:
            _paste_centered(
                canvas,
                _scaled(logo_layer, pose.logo_scale, pose.logo_alpha),
                (center_x, logo_center_y),
            )
        if handle_layer is not None:
            _paste_centered(
                canvas,
                _scaled(handle_layer, 1.0, pose.pill_alpha),
                (center_x, handle_center_y),
            )
        _paste_centered(
            canvas,
            _scaled(pill_layer, pose.pill_scale, pose.pill_alpha),
            (center_x, pill_center_y + pose.pill_rise * pill_layer.height),
        )
        frames.append(np.array(canvas))

    return frames
