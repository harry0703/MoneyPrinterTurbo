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

import re

import khatt
from khatt.fonts import font_path as khatt_font_path
from khatt.video import TextClip as ShapedTextClip
from loguru import logger

# 阿拉伯字母相关的 Unicode 区块：基本区、补充区、扩展 A/B/C 以及表现形式 A/B。
_ARABIC_SCRIPT = re.compile(
    "[؀-ۿݐ-ݿࡰ-࢟ࢠ-ࣿﭐ-﷿ﹰ-﻿]"
)

# 项目自带字体都不含阿拉伯字形。所选字体缺字时改用 khatt 自带的
# Noto Naskh Arabic（SIL OFL 1.1），它同时覆盖阿拉伯文、波斯文和乌尔都文。
FALLBACK_FONT = "noto-naskh"

FONT_FALLBACK_NOTICE = "subtitle_font_fallback"


def needs_shaping(text: str | None) -> bool:
    """文本是否包含需要整形的阿拉伯字母。"""
    return bool(text) and _ARABIC_SCRIPT.search(text) is not None


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
    if any(_ARABIC_SCRIPT.match(char) for char in missing):
        return str(khatt_font_path(FALLBACK_FONT)), True
    return font_path, False


def text_width(text: str, font_path: str, font_size: int) -> int:
    """按整形后的实际字形测量单行文本宽度（像素）。"""
    left, _, right, _ = khatt.text_bbox(text, font=font_path, size_px=int(font_size))
    return right - left


def text_clip(native, *, notices: set[str] | None = None, **kwargs):
    """创建字幕 TextClip：阿拉伯字母文本由 khatt 绘制，其余交给 ``native``。

    ``native`` 是调用方使用的 MoviePy ``TextClip``，非阿拉伯字母文本原样
    交给它，与改动前完全相同。其余参数与 MoviePy 2.2 的 ``TextClip`` 一致。
    ``notices`` 用于在一次视频生成任务内去重提示，使字体回退的警告每个
    任务只出现一次。
    """
    text = kwargs.get("text")
    if not needs_shaping(text):
        return native(**kwargs)

    font, fell_back = resolve_font(kwargs.get("font") or "", text)
    if fell_back and (notices is None or FONT_FALLBACK_NOTICE not in notices):
        if notices is not None:
            notices.add(FONT_FALLBACK_NOTICE)
        logger.warning(
            f"subtitle font has no Arabic-script glyphs, using {FALLBACK_FONT} "
            f"for Arabic-script subtitles: {kwargs.get('font')}"
        )
    return ShapedTextClip(**{**kwargs, "font": font})
