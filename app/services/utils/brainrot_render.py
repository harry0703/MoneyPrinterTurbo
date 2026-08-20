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

# 入侵阶段每隔这么久叠加一个新的播放实例。参考样片约每 0.2 秒来一次。
PANEL_INTERVAL_SECONDS = 0.2
# 实例数量上限，防止把入侵时长调得过长时无限堆叠。
MAX_PANELS = 24


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


def panel_schedule(
    elapsed: float,
    width: int,
    height: int,
    seed: int,
    interval: float = PANEL_INTERVAL_SECONDS,
    max_panels: int = MAX_PANELS,
) -> list[tuple[int, int, int, int, float]]:
    """
    返回入侵开始 ``elapsed`` 秒后已经出现的全部实例，每项为 ``(x, y, w, h, start)``。

    实例是累加的而不是每次重新抽取：参考样片里剪辑一次次叠上去，画面越来越满，
    直到几乎盖住整幅——之前每个刷新槽重抽一批矩形，看起来是同一段画面在乱跳，
    而不是很多段各自在放。

    ``start`` 是该实例相对入侵开始的时刻，调用方据此决定它该播到第几帧：每个
    实例都从剪辑的开头放起，这正是那种一拍接一拍的错位感的来源。
    """
    if elapsed < 0:
        return []

    count = min(max_panels, int(elapsed / max(1e-6, interval)) + 1)

    panels = []
    for index in range(count):
        # 每个实例的位置只由它自己的序号决定，出现之后就不再变动。
        rng = random.Random(seed + index * 7919)
        growth = index / max(1, max_panels - 1)
        scale = (0.30 + 0.45 * growth) * rng.uniform(0.8, 1.25)
        panel_width = max(24, min(width, int(width * scale)))
        panel_height = max(24, min(height, int(panel_width * rng.uniform(0.7, 1.5))))
        x = rng.randint(0, max(0, width - panel_width))
        y = rng.randint(0, max(0, height - panel_height))
        panels.append((x, y, panel_width, panel_height, index * interval))
    return panels


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


def letterbox(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """
    等比缩放后居中放进目标画幅，多出来的部分留黑边。

    剪辑本身是 16:9 的横屏素材。裁成竖屏会把构图砍掉两侧——而这类剪辑的主体
    经常并不在正中，裁切会直接切掉重点。竖屏平台上的黑边完全可以接受，观众
    对搬运来的横屏素材早就习惯了。
    """
    source = Image.fromarray(frame)
    ratio = min(width / source.width, height / source.height)
    new_size = (max(1, int(source.width * ratio)), max(1, int(source.height * ratio)))

    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    resized = source.resize(new_size, Image.LANCZOS)
    canvas.paste(resized, ((width - new_size[0]) // 2, (height - new_size[1]) // 2))
    return np.array(canvas)


# 客串镜头按 16:9 呈现：它要让人一眼认出"这就是那段剪辑，只是变小了"，
# 用随机长宽比反而会削弱这种辨识。
CAMEO_ASPECT = 16 / 9


def cameo_rect(
    width: int,
    height: int,
    scale: float,
    progress: float,
    kind: str = "flash",
    direction: int = 1,
    seed: int = 0,
) -> tuple[int, int, int, int]:
    """
    返回客串镜头在 ``progress``（0~1）时刻的位置与尺寸。

    ``flash`` 停在随机一处，``sweep`` 横向掠过整幅画面——起止都留在画外，
    这样它是"经过"而不是"出现又消失"。
    """
    progress = min(1.0, max(0.0, progress))
    rng = random.Random(seed)

    panel_width = max(24, int(width * scale))
    panel_height = max(16, int(panel_width / CAMEO_ASPECT))

    if kind == "sweep":
        # 纵向落在中段，避开顶部的文字卡。
        y = rng.randint(int(height * 0.30), int(height * 0.62))
        travel = width + panel_width
        offset = progress if direction >= 0 else 1.0 - progress
        x = int(-panel_width + travel * offset)
        return x, y, panel_width, panel_height

    x = rng.randint(0, max(0, width - panel_width))
    y = rng.randint(int(height * 0.25), max(int(height * 0.25), height - panel_height))
    return x, y, panel_width, panel_height
