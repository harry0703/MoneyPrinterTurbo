"""
"诱饵 + 剪辑入侵"格式的绘制与版式。

这类视频的结构与正片完全不同：没有旁白，没有逐句字幕，只有一张从头挂到尾
的文字卡，以及一段在中途逐渐"侵入"画面的现成剪辑。两段素材的衔接不是硬切，
而是剪辑以大小不一的矩形块反复闪现，块数和面积随时间增长，直到占满整幅画面。

这里只负责纯函数部分：文字卡的位图、入侵矩形的位置、以及把任意画幅裁成竖屏。
时间轴与合成留给调用方，便于单独测试。
"""

from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_CARD_PAD_X_RATIO = 0.42
_CARD_PAD_Y_RATIO = 0.30
_CARD_RADIUS_RATIO = 0.28
_LINE_SPACING_RATIO = 0.22

# 入侵阶段的矩形数量上限。太少不像"故障"，太多会在结束前就盖满画面，
# 让最后的全屏切换失去冲击。
MAX_PANELS = 9
# 每隔这么久重新抽一次矩形。连续移动会显得平滑，而这个格式要的是闪跳。
PANEL_REFRESH_SECONDS = 0.15


def _load_font(font_path: str, font_size: int):
    try:
        return ImageFont.truetype(font_path, font_size)
    except OSError:
        return ImageFont.load_default(font_size)


def _split_oversized(word: str, font, draw, max_width: int) -> list[str]:
    """把单个超宽的词按字符切开。切字很难看，但溢出画面更难看。"""
    pieces = [""]
    for character in word:
        candidate = pieces[-1] + character
        if pieces[-1] and draw.textlength(candidate, font=font) > max_width:
            pieces.append(character)
        else:
            pieces[-1] = candidate
    return [piece for piece in pieces if piece]


def wrap_lines(text: str, font, draw, max_width: int) -> list[str]:
    """
    按可用宽度贪心折行。

    单个词就超过整行宽度时必须切开：卡片宽度由最长的一行决定，放任它独占
    一行会把整张卡片撑到画面之外。
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    for word in words:
        if draw.textlength(word, font=font) > max_width:
            lines.extend(_split_oversized(word, font, draw, max_width))
            continue

        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(candidate, font=font) <= max_width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


def render_text_card(
    text: str,
    font_path: str,
    font_size: int,
    max_width: int,
    background: str = "#FFFFFF",
    text_color: str = "#000000",
) -> np.ndarray:
    """
    渲染白底圆角文字卡，返回 RGBA 数组。

    卡片宽度贴合最长的一行而不是固定值：这个格式里文字长短差别很大，固定宽度
    会让短句显得空荡，看起来不像随手打上去的。
    """
    font = _load_font(font_path, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    pad_x = int(font_size * _CARD_PAD_X_RATIO)
    pad_y = int(font_size * _CARD_PAD_Y_RATIO)
    line_spacing = int(font_size * _LINE_SPACING_RATIO)

    lines = wrap_lines(text, font, probe, max_width - 2 * pad_x)
    if not lines:
        return np.zeros((1, 1, 4), dtype=np.uint8)

    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    text_width = int(max(probe.textlength(line, font=font) for line in lines))

    width = text_width + 2 * pad_x
    height = len(lines) * line_height + (len(lines) - 1) * line_spacing + 2 * pad_y

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [0, 0, width - 1, height - 1],
        radius=int(font_size * _CARD_RADIUS_RATIO),
        fill=background,
    )

    y = pad_y
    for line in lines:
        line_width = draw.textlength(line, font=font)
        draw.text(((width - line_width) / 2, y), line, font=font, fill=text_color)
        y += line_height + line_spacing

    return np.array(image)


def panel_rects(
    progress: float, width: int, height: int, seed: int
) -> list[tuple[int, int, int, int]]:
    """
    返回入侵阶段某一时刻的矩形列表，每项为 ``(x, y, w, h)``。

    ``progress`` 从 0 到 1 同时驱动数量和面积，因此剪辑是"越来越多、越来越大"
    地压过来，而不是突然铺满。用显式的 seed 而不是全局随机，保证同一秒重复
    渲染得到同一批矩形——否则相邻两帧会各自抖动，看起来是噪点而不是闪跳。
    """
    progress = min(1.0, max(0.0, progress))
    if progress <= 0.0:
        return []

    rng = random.Random(seed)
    count = 1 + int(progress * (MAX_PANELS - 1))

    rects = []
    for _ in range(count):
        scale = 0.30 + 0.55 * progress * rng.uniform(0.7, 1.3)
        panel_width = max(24, min(width, int(width * scale)))
        panel_height = max(24, min(height, int(panel_width * rng.uniform(0.8, 1.6))))
        x = rng.randint(0, max(0, width - panel_width))
        y = rng.randint(0, max(0, height - panel_height))
        rects.append((x, y, panel_width, panel_height))
    return rects


def panel_seed(elapsed: float, refresh: float = PANEL_REFRESH_SECONDS) -> int:
    """把时间量化成刷新槽位，同一槽位内的帧共用同一批矩形。"""
    return int(elapsed / max(1e-6, refresh))


def crop_to_aspect(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """
    居中裁剪并缩放到目标画幅。

    剪辑模板是 16:9 的横屏素材，直接拉伸会把人物压扁,加黑边则会露出这是
    搬运来的素材。居中裁剪保留主体，是这个格式里通行的做法。
    """
    source = Image.fromarray(frame)
    target_ratio = width / height
    source_ratio = source.width / source.height

    if source_ratio > target_ratio:
        new_width = int(source.height * target_ratio)
        left = (source.width - new_width) // 2
        source = source.crop((left, 0, left + new_width, source.height))
    elif source_ratio < target_ratio:
        new_height = int(source.width / target_ratio)
        top = (source.height - new_height) // 2
        source = source.crop((0, top, source.width, top + new_height))

    return np.array(source.resize((width, height), Image.LANCZOS))
