"""阿拉伯字母字幕的整形（shaping）适配层。

阿拉伯文、波斯文、乌尔都文等阿拉伯字母文字必须先按上下文选择字形、连写，
再从右到左排版，才能正确显示；元音符号也要由 OpenType 规则定位到所属字母上。
Pillow 只有在带 Raqm 构建时才会整形，而 Windows 等常见安装没有 Raqm，
于是字母断开、顺序颠倒、元音符号错位。

这里把含阿拉伯字母的字幕交给 khatt（HarfBuzz 整形 + FreeType 光栅化，
由 wheel 自带，不依赖系统库）测量和绘制；khatt 从不调用 Pillow 的文字排版，
因此无论 Pillow 是否带 Raqm，结果都一致，也不会出现二次整形。
其他语言仍走 MoviePy 原生 TextClip，渲染结果保持不变。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

import khatt
from khatt.fonts import font_path as khatt_font_path
from khatt.video import TextClip as ShapedTextClip
from loguru import logger

# 阿拉伯字母相关的 Unicode 区块：基本区、补充区、扩展 A/B 以及表现形式 A/B
# （不含 U+FEFF 字节顺序标记）。
_ARABIC_SCRIPT_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x0870, 0x089F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFC),
)

# 方向标记：不可见，只决定一行文字作为段落的方向。
RLM = "‏"
LRM = "‎"

# 项目自带字体都不含阿拉伯字形。所选字体缺字时改用 khatt 自带的
# Noto Naskh Arabic（SIL OFL 1.1），它同时覆盖阿拉伯文、波斯文和乌尔都文。
FALLBACK_FONT = "noto-naskh"


def _is_arabic_char(char: str) -> bool:
    # 只看字母、标记和符号（L/M/S 类）：阿拉伯逗号、问号和阿拉伯-印度数字
    # 也被迪维希语（Thaana）、叙利亚文和 N'Ko 共用，不能据此判定为阿拉伯字母。
    return unicodedata.category(char)[0] in "LMS" and any(
        start <= ord(char) <= end for start, end in _ARABIC_SCRIPT_RANGES
    )


def needs_shaping(text: str | None) -> bool:
    """文本是否包含需要整形的阿拉伯字母。"""
    return any(_is_arabic_char(char) for char in text or "")


def is_rtl_paragraph(text: str) -> bool:
    """按第一个强方向字符判断段落方向（Unicode 双向算法 P2/P3 规则）。"""
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in ("R", "AL"):
            return True
        if direction == "L":
            return False
    return False


def direction_mark(text: str) -> str:
    """与 ``text`` 段落方向一致的方向标记。

    khatt 把每一行当作独立段落，按行首第一个强方向字符判断方向。自动折出的
    行必须沿用原段落的方向，否则以英文或数字开头的行词序会颠倒，所以每行
    前面都加上这个标记。
    """
    return RLM if is_rtl_paragraph(text) else LRM


def resolve_font(font_path: str, text: str) -> tuple[str, bool]:
    """返回实际用于绘制 ``text`` 的字体文件，以及是否改用了后备字体。

    只在所选字体缺少阿拉伯字母字形时才回退；缺少的若只是表情符号等
    其他字符，保持用户选择的字体，由 khatt 按原有方式跳过并给出警告。
    """
    try:
        missing = khatt.missing_characters(text, font_path)
    except (KeyError, ValueError) as exc:
        # 字体文件不存在或 khatt 无法读取时，仍然保证字幕可读。
        logger.warning(f"cannot check subtitle font glyphs, using {FALLBACK_FONT}: {exc}")
        return str(khatt_font_path(FALLBACK_FONT)), True
    if any(_is_arabic_char(char) for char in missing):
        return str(khatt_font_path(FALLBACK_FONT)), True
    return font_path, False


def video_font(font_path: str, subtitles: Iterable[str]) -> str:
    """为一条视频的全部阿拉伯字母字幕确定同一个字体。

    逐条字幕各自选择字体时，同一视频中的字幕可能在两种字体之间来回切换，
    因此按全部字幕一次确定；字体回退和无法绘制的字符各提示一次。
    """
    text = "".join(subtitle for subtitle in subtitles if needs_shaping(subtitle))
    if not text:
        return font_path
    font, fell_back = resolve_font(font_path, text)
    if fell_back:
        logger.warning(
            f"subtitle font has no Arabic-script glyphs, using {FALLBACK_FONT} "
            f"for Arabic-script subtitles: {font_path}"
        )
    skipped = khatt.missing_characters(text, font)
    if skipped:
        # 例如阿拉伯字幕中夹杂的中文：后备字体没有这些字形，绘制时会被跳过。
        logger.warning(
            "characters in Arabic-script subtitles that the subtitle font cannot "
            f"draw are skipped: {''.join(skipped[:20])}"
        )
    return font


def supports_text(font_path: str, text: str) -> bool:
    """实际绘制 ``text`` 的字体（必要时为后备字体）能否画出其中全部字符。"""
    font, _ = resolve_font(font_path, text)
    return not khatt.missing_characters(text, font)


def text_width(text: str, font_path: str, font_size: int) -> int:
    """按整形后的实际字形测量单行文本宽度（像素）。"""
    left, _, right, _ = khatt.text_bbox(text, font=font_path, size_px=int(font_size))
    return right - left


def text_clip(native, *, shaped_font: str | None = None, **kwargs):
    """创建字幕 TextClip：阿拉伯字母文本由 khatt 绘制，其余交给 ``native``。

    ``native`` 是调用方使用的 MoviePy ``TextClip``，非阿拉伯字母文本原样
    交给它，与改动前完全相同。其余参数与 MoviePy 2.2 的 ``TextClip`` 一致。
    ``shaped_font`` 是绘制阿拉伯字母文本的字体（见 :func:`video_font`），
    省略时按 ``font`` 和本段文本确定。
    """
    text = kwargs.get("text")
    if not needs_shaping(text):
        return native(**kwargs)
    if shaped_font is None:
        shaped_font, _ = resolve_font(kwargs.get("font") or "", text)
    return ShapedTextClip(**{**kwargs, "font": shaped_font})
