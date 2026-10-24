"""阿拉伯字母字幕整形的回归测试。

这些测试检查真实渲染出的字形，而不仅仅是字符串：元音符号必须落在所属字母上、
字母必须连写、文字必须从右到左排列，并且无论 Pillow 是否带 Raqm 都不会经过
Pillow 的文字排版（因此不会二次整形）。
"""

from pathlib import Path

import numpy as np
import pytest
from khatt.fonts import font_path as khatt_font_path
from khatt.video import TextClip as ShapedTextClip
from moviepy import TextClip
from PIL import ImageDraw

from app.services.utils import subtitle_shaping
from app.services.video import wrap_text

FONT_DIR = Path(__file__).resolve().parents[2] / "resource/fonts"
# 项目默认字幕字体，不含阿拉伯字形，用来覆盖字体回退路径。
DEFAULT_FONT = str(FONT_DIR / "STHeitiMedium.ttc")
ARABIC_FONT = str(khatt_font_path("amiri"))


def shaped_clip(text, font=DEFAULT_FONT, **kwargs):
    return subtitle_shaping.text_clip(
        TextClip, text=text, font=font, font_size=100, color="white", **kwargs
    )


def ink_box(clip):
    """字幕 clip 中实际有墨迹的区域 (left, top, right, bottom)。"""
    ink = clip.mask.get_frame(0) > 0.5
    ys, xs = np.nonzero(ink)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def ink_width(clip):
    left, _, right, _ = ink_box(clip)
    return right - left


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("مرحبا بالعالم", True),
        ("سلام دنیا", True),  # 波斯文
        ("ٹھیک ہے", True),  # 乌尔都文
        ("Breaking news: عاجل", True),
        ("Hello world", False),
        ("你好，世界", False),
        ("नमस्ते", False),
        ("", False),
        (None, False),
    ],
)
def test_only_arabic_script_text_is_shaped(text, expected):
    assert subtitle_shaping.needs_shaping(text) is expected


def test_font_without_arabic_glyphs_falls_back():
    font, fell_back = subtitle_shaping.resolve_font(DEFAULT_FONT, "مرحبا")
    assert fell_back
    assert Path(font).name == "NotoNaskhArabic-Regular.ttf"


def test_font_with_arabic_glyphs_is_kept():
    assert subtitle_shaping.resolve_font(ARABIC_FONT, "مرحبا") == (ARABIC_FONT, False)


def test_missing_emoji_alone_does_not_switch_font():
    # 只缺表情符号时保留用户选择的字体，不应改用后备字体。
    assert subtitle_shaping.resolve_font(ARABIC_FONT, "مرحبا 😀") == (ARABIC_FONT, False)


def test_non_arabic_text_goes_to_moviepy_unchanged():
    calls = []

    def native(**kwargs):
        calls.append(kwargs)
        return "native clip"

    kwargs = dict(text="Hello", font=DEFAULT_FONT, font_size=60, color="white", stroke_width=2)
    assert subtitle_shaping.text_clip(native, **kwargs) == "native clip"
    assert calls == [kwargs]


def test_arabic_text_is_drawn_by_khatt():
    clip = shaped_clip("مرحبا بالعالم", stroke_color="black", stroke_width=3)
    assert isinstance(clip, ShapedTextClip)
    assert ink_width(clip) > 0


def test_never_uses_pillow_text_layout(monkeypatch):
    # 无论 Pillow 是否带 Raqm，阿拉伯字母字幕都不经过 Pillow 的文字排版，
    # 因此不存在二次整形，也不会因为环境不同而结果不同。
    def forbidden(*args, **kwargs):
        raise AssertionError("Pillow text layout must not be used for Arabic subtitles")

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", forbidden)
    monkeypatch.setattr(ImageDraw.ImageDraw, "multiline_text", forbidden)
    assert ink_width(shaped_clip("بِتَ مرحبا")) > 0


@pytest.mark.parametrize("font", [DEFAULT_FONT, ARABIC_FONT])
def test_vowel_marks_stay_on_their_letters(font):
    # 维护者复现用例：未整形时 Kasra 会伸出最右侧字形之外（100px 时宽 107 → 145）。
    plain = ink_box(shaped_clip("بت", font=font))
    marked = ink_box(shaped_clip("بِتَ", font=font))
    assert abs((marked[2] - marked[0]) - (plain[2] - plain[0])) <= 2
    # 元音符号在字母上下方，因此墨迹只会在垂直方向变高。
    assert marked[1] < plain[1]
    assert marked[3] > plain[3]


def ink_runs(clip):
    """从左到右数有墨迹的连续列段：连写的单词是一整段。"""
    columns = (clip.mask.get_frame(0) > 0.5).any(axis=0)
    starts = columns & ~np.concatenate(([False], columns[:-1]))
    return int(starts.sum())


@pytest.mark.parametrize("word", ["سسس", "ببب"])
def test_letters_join(word):
    # 未整形时（Pillow 无 Raqm）这些字母是三个分开的独立字形；整形后连成一整段。
    assert ink_runs(shaped_clip(word)) == 1
    assert ink_runs(shaped_clip(" ".join(word))) == 3


def test_right_to_left_order():
    # Alef 是高竖笔，Beh 是低矮字形：从右到左排列时 Alef 必须在右侧。
    ink = shaped_clip("ا ب").mask.get_frame(0) > 0.5
    ys, xs = np.nonzero(ink)
    middle = (xs.min() + xs.max()) / 2
    right_height = np.ptp(ys[xs > middle])
    left_height = np.ptp(ys[xs <= middle])
    assert right_height > left_height


def test_font_fallback_warning_once_per_job(monkeypatch):
    warnings = []
    monkeypatch.setattr(subtitle_shaping.logger, "warning", warnings.append)
    notices = set()
    for _ in range(3):
        shaped_clip("مرحبا", notices=notices)
    assert len(warnings) == 1
    # 新的生成任务使用新的 notices，因此会再提示一次。
    shaped_clip("مرحبا", notices=set())
    assert len(warnings) == 2


def test_wrap_text_measures_shaped_arabic():
    text = "تمنح هذه الشهادة إلى الطالب المتميز تقديرا لجهوده الكبيرة في العام الدراسي"
    wrapped, height = wrap_text(text, 600, font=DEFAULT_FONT, fontsize=60)
    lines = wrapped.split("\n")
    assert len(lines) > 1
    # 只在空格处换行，单词不会被拆开。
    assert " ".join(lines).split() == text.split()
    font, _ = subtitle_shaping.resolve_font(DEFAULT_FONT, text)
    assert all(subtitle_shaping.text_width(line, font, 60) <= 600 for line in lines)
    assert height > 0


def test_wrap_text_leaves_other_languages_alone(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("non-Arabic subtitles must be measured as before")

    monkeypatch.setattr(subtitle_shaping, "text_width", forbidden)
    wrapped, _ = wrap_text("Hello world " * 20, 600, font=DEFAULT_FONT, fontsize=60)
    assert len(wrapped.split("\n")) > 1
