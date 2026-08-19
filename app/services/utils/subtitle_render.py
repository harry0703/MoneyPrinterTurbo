"""
逐词高亮字幕的图像渲染。

MoviePy 的 ``TextClip`` 只能给整段文字设置统一样式，无法把其中一个词
单独描色或加底色。竖屏短视频常见的"当前朗读词高亮"因此只能自己绘制：
用 PIL 逐词测量、排版并落图，再交给 ``ImageClip`` 参与合成。

这里只负责画一帧静态字幕，时间轴与分组由调用方决定，便于单独测试。
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 高亮块在文字外扩的比例，相对字号。太小会贴字，太大会显得松散。
_HIGHLIGHT_PAD_X_RATIO = 0.22
_HIGHLIGHT_PAD_Y_RATIO = 0.12
_LINE_SPACING_RATIO = 0.18
_WORD_SPACING_RATIO = 0.30


def _load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path, font_size)
    except OSError:
        return ImageFont.load_default(font_size)


def _measure(draw: ImageDraw.ImageDraw, text: str, font, stroke_width: int) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox(
        (0, 0), text, font=font, stroke_width=stroke_width
    )
    return right - left, bottom - top


def layout_words(
    words: list[str],
    font,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    stroke_width: int,
    word_spacing: int,
) -> list[list[tuple[str, int]]]:
    """
    把词贪心地排进若干行，返回每行的 ``(word, width)``。

    即使只显示两三个词，大字号加长单词仍可能超出画面宽度，因此换行不是
    可选项：一行放不下就必须折行，否则文字会被裁掉。
    """
    lines: list[list[tuple[str, int]]] = [[]]
    current_width = 0

    for word in words:
        width, _ = _measure(draw, word, font, stroke_width)
        extra = width if not lines[-1] else word_spacing + width
        if lines[-1] and current_width + extra > max_width:
            lines.append([(word, width)])
            current_width = width
        else:
            lines[-1].append((word, width))
            current_width += extra

    return [line for line in lines if line]


def render_caption(
    words: list[str],
    active_index: int,
    font_path: str,
    font_size: int,
    max_width: int,
    text_color: str = "#FFFFFF",
    stroke_color: str = "#000000",
    stroke_width: int = 6,
    highlight_color: str = "#FF2E88",
    uppercase: bool = True,
) -> np.ndarray:
    """
    渲染一帧字幕，并在 ``active_index`` 指向的词后面画高亮块。

    ``active_index`` 为负数时不画高亮，用于需要同样排版但不强调任何词的场合。
    返回 RGBA 数组，未被文字覆盖的区域完全透明。
    """
    if not words:
        return np.zeros((1, 1, 4), dtype=np.uint8)

    display_words = [word.upper() for word in words] if uppercase else list(words)
    font = _load_font(font_path, font_size)

    # 先在一张临时图上测量，PIL 需要 draw 对象才能读取字体度量。
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    word_spacing = int(font_size * _WORD_SPACING_RATIO)
    lines = layout_words(
        display_words, font, probe, max_width, stroke_width, word_spacing
    )

    pad_x = int(font_size * _HIGHLIGHT_PAD_X_RATIO)
    pad_y = int(font_size * _HIGHLIGHT_PAD_Y_RATIO)
    _, line_height = _measure(probe, "Ag", font, stroke_width)
    line_spacing = int(font_size * _LINE_SPACING_RATIO)

    canvas_width = max_width + 2 * pad_x
    canvas_height = (
        len(lines) * (line_height + 2 * pad_y)
        + max(0, len(lines) - 1) * line_spacing
    )

    image = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    word_cursor = 0
    y = 0
    for line in lines:
        line_width = sum(width for _, width in line) + word_spacing * (len(line) - 1)
        x = (canvas_width - line_width) // 2

        for word, width in line:
            if word_cursor == active_index:
                draw.rounded_rectangle(
                    [
                        x - pad_x,
                        y,
                        x + width + pad_x,
                        y + line_height + 2 * pad_y,
                    ],
                    radius=max(6, int(font_size * 0.18)),
                    fill=highlight_color,
                )

            draw.text(
                (x, y + pad_y),
                word,
                font=font,
                fill=text_color,
                stroke_width=stroke_width,
                stroke_fill=stroke_color,
            )
            x += width + word_spacing
            word_cursor += 1

        y += line_height + 2 * pad_y + line_spacing

    return np.array(image)


def split_word_intervals(
    words: list[str], start: float, end: float
) -> list[tuple[float, float]]:
    """
    在一条字幕的时间范围内，按词长比例分配每个词的高亮时段。

    Edge 返回的逐词时间轴在写入 SRT 时已经合并成分组，成片阶段拿不到
    单词边界。按字符数分摊在两三个词的短分组里误差只有几十毫秒，
    肉眼无法分辨，却省去了在整条链路上再传一份词级时间轴。
    """
    if not words:
        return []

    weights = [max(1, len(word)) for word in words]
    total = sum(weights)
    span = max(0.0, end - start)

    intervals = []
    cursor = start
    for index, weight in enumerate(weights):
        is_last = index == len(weights) - 1
        stop = end if is_last else cursor + span * (weight / total)
        intervals.append((cursor, stop))
        cursor = stop
    return intervals
