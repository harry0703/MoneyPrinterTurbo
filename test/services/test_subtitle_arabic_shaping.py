"""阿拉伯字母字幕整形的回归测试。

这些测试检查真实渲染出的字形，而不仅仅是字符串：元音符号必须落在所属字母上、
字母必须连写、文字必须从右到左排列，并且无论 Pillow 是否带 Raqm 都不会经过
Pillow 的文字排版（因此不会二次整形）。
"""

import functools
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from khatt.fonts import font_path as khatt_font_path
from khatt.video import TextClip as ShapedTextClip
from loguru import logger
from moviepy import ColorClip, TextClip
from PIL import ImageDraw, ImageFont

from app.services import video as vd
from app.services.utils import subtitle_shaping
from app.services.video import wrap_text

FONT_DIR = Path(__file__).resolve().parents[2] / "resource/fonts"
# 项目默认字幕字体，不含阿拉伯字形，用来覆盖字体回退路径。
DEFAULT_FONT = str(FONT_DIR / "STHeitiMedium.ttc")
# 维护者复现阿拉伯文与中文同在一条字幕时所用的字体。
YAHEI_FONT = str(FONT_DIR / "MicrosoftYaHeiBold.ttc")
MIXED_CUE = "مرحبا بالعالم 中文测试"
ARABIC_FONT = str(khatt_font_path("amiri"))
FALLBACK_FONT = str(khatt_font_path(subtitle_shaping.FALLBACK_FONT))
# khatt 自带字体所在目录，用来让 generate_video 直接选用这些字体。
KHATT_FONT_DIR = str(khatt_font_path("amiri").parent)
RLM, LRM = subtitle_shaping.RLM, subtitle_shaping.LRM

# khatt 在文字超出画布、内容被裁掉时发出 TextOverflowWarning：这里一律视为失败。
pytestmark = pytest.mark.filterwarnings("error::khatt.TextOverflowWarning")


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
        ("ﻻ", True),  # 表现形式（lam-alef 连字）
        ("﷽", True),  # 巴斯马拉连字（符号类）
        ("Hello world", False),
        ("你好，世界", False),
        ("नमस्ते", False),
        ("", False),
        (None, False),
        ("\ufeffBOM", False),  # 字节顺序标记不是阿拉伯字母
        ("שלום עולם", False),  # 希伯来文
        ("ދިވެހި، ބަސް", False),  # 迪维希语（Thaana）使用阿拉伯逗号
        ("ܫܠܡܐ؟", False),  # 叙利亚文使用阿拉伯问号
        ("ߒߞߏ؛", False),  # N'Ko 使用阿拉伯分号
        ("١٢٣ ٤٥٦", False),  # 只有阿拉伯-印度数字
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


def strip_marks(line):
    return line.lstrip(RLM + LRM)


ARABIC_PARAGRAPH = "تمنح هذه الشهادة إلى الطالب المتميز تقديرا لجهوده الكبيرة في العام الدراسي"


def test_wrap_text_measures_shaped_arabic():
    wrapped, height = wrap_text(ARABIC_PARAGRAPH, 600, font=DEFAULT_FONT, fontsize=60)
    lines = wrapped.split("\n")
    assert len(lines) > 1
    # 只在空格处换行，单词不会被拆开。
    assert " ".join(strip_marks(line) for line in lines).split() == ARABIC_PARAGRAPH.split()
    font, _ = subtitle_shaping.resolve_font(DEFAULT_FONT, ARABIC_PARAGRAPH)
    assert all(subtitle_shaping.text_width(line, font, 60) <= 600 for line in lines)
    assert height > 0


def test_arabic_wraps_by_shaped_width_even_without_raqm(monkeypatch):
    # Windows 版 Pillow 没有 Raqm：按 Pillow 测量的阿拉伯文宽度是断开、倒序的
    # 字母宽度。换行必须仍然按整形后的宽度进行：每行不超宽，且贪心地尽量填满。
    basic = functools.partial(ImageFont.truetype, layout_engine=ImageFont.Layout.BASIC)
    monkeypatch.setattr(vd.ImageFont, "truetype", basic)
    max_width = 420
    wrapped, height = wrap_text(ARABIC_PARAGRAPH, max_width, font=ARABIC_FONT, fontsize=48)
    lines = wrapped.split("\n")
    assert len(lines) > 1
    assert " ".join(strip_marks(line) for line in lines) == ARABIC_PARAGRAPH
    for line, following in zip(lines, lines[1:] + [None]):
        assert subtitle_shaping.text_width(line, ARABIC_FONT, 48) <= max_width
        if following is not None:
            longer = f"{line} {strip_marks(following).split()[0]}"
            assert subtitle_shaping.text_width(longer, ARABIC_FONT, 48) > max_width
    assert height == len(lines) * sum(ImageFont.truetype(ARABIC_FONT, 48).getmetrics())


def test_wrapped_lines_keep_their_paragraphs_direction():
    # 自动折出的行沿用原段落方向：从右到左段落的每行以 RLM 开头，
    # 夹有阿拉伯文的从左到右段落的每行以 LRM 开头。
    rtl, _ = wrap_text("مرحبا بالعالم Khatt 2026 جديد " * 4, 300, font=ARABIC_FONT, fontsize=48)
    ltr, _ = wrap_text("Hello مرحبا world بالعالم " * 4, 300, font=ARABIC_FONT, fontsize=48)
    assert len(rtl.split("\n")) > 1 and len(ltr.split("\n")) > 1
    for line in rtl.split("\n"):
        assert line.startswith(RLM) and subtitle_shaping.is_rtl_paragraph(line)
    for line in ltr.split("\n"):
        assert line.startswith(LRM) and not subtitle_shaping.is_rtl_paragraph(line)


def test_hand_broken_lines_keep_their_own_direction():
    # 双语字幕：阿拉伯语一行、英文翻译一行，各自保持自己的方向。
    wrapped, _ = wrap_text("مرحبا بالعالم\nHello, world!", 900, font=ARABIC_FONT, fontsize=48)
    arabic_line, english_line = wrapped.split("\n")
    assert arabic_line == RLM + "مرحبا بالعالم"
    assert strip_marks(english_line) == "Hello, world!"
    assert not subtitle_shaping.is_rtl_paragraph(english_line)


def test_translation_lines_are_measured_as_khatt_draws_them(monkeypatch):
    # 含阿拉伯字母的字幕整段由 khatt 绘制，英文翻译行也要按 khatt 测量。
    measured = []
    original = subtitle_shaping.text_width

    def spy(text, *args):
        measured.append(strip_marks(text))
        return original(text, *args)

    monkeypatch.setattr(subtitle_shaping, "text_width", spy)
    wrap_text("مرحبا\nHello, world!", 900, font=ARABIC_FONT, fontsize=48)
    assert "Hello, world!" in measured


def test_lines_are_measured_in_the_direction_they_render():
    # 从右到左段落中折出的第二行以英文开头。混排行的宽度随方向不同而不同，
    # 测量必须用渲染时的方向（从右到左），而不是按行首英文判断的方向。
    word = "الاستـ" + "ـ" * 16 + "ـقبال"  # 用 Kashida 拉长、正好占满第一行的单词
    line = "Khatt 1.5 مرحبا بكم"
    rtl_width = subtitle_shaping.text_width(RLM + line, ARABIC_FONT, 48)
    ltr_width = subtitle_shaping.text_width(LRM + line, ARABIC_FONT, 48)
    assert rtl_width < ltr_width  # 前提：按从左到右测量会更宽
    wrapped, _ = wrap_text(f"{word} {line}", rtl_width, font=ARABIC_FONT, fontsize=48)
    assert wrapped.split("\n") == [RLM + word, RLM + line]  # 第二行恰好放得下


def test_arabic_words_are_never_split_across_lines():
    # 中日文的行首标点调整会把上一行最后一个字移到下一行；阿拉伯单词
    # 不能这样拆开，否则字母连写会断开。
    text = "مرحبا بالعالم الجميل ! نعم , هذا اختبار . للتأكد ؟ من النتيجة"
    words = set(text.split())
    for max_width in range(120, 600, 15):
        wrapped, _ = wrap_text(text, max_width, font=ARABIC_FONT, fontsize=48)
        assert {w for line in wrapped.split("\n") for w in strip_marks(line).split()} <= words


def test_non_arabic_wrapping_gets_no_direction_marks():
    for text in ("Hello world from MoneyPrinterTurbo " * 4, "你好世界，这是一个很长的中文字幕句子。" * 3):
        wrapped, _ = wrap_text(text, 300, font=DEFAULT_FONT, fontsize=48)
        assert RLM not in wrapped and LRM not in wrapped


def test_webui_font_check_judges_the_font_that_draws_arabic():
    # 纯阿拉伯文：后备字体会补上字形，不再误报字体不支持。
    assert vd.subtitle_font_supports_text(DEFAULT_FONT, "مرحبا بالعالم")
    # 阿拉伯文夹中文：后备字体画阿拉伯文，所选字体画中文，两者都能画出。
    assert vd.subtitle_font_supports_text(DEFAULT_FONT, "مرحبا 你好")
    # 其他语言的检测保持不变。
    vietnamese_only = str(FONT_DIR / "BeVietnamPro-Medium.ttf")
    assert not vd.subtitle_font_supports_text(vietnamese_only, "你好世界")
    assert vd.subtitle_font_supports_text(DEFAULT_FONT, "你好世界")


class FakeAudio:
    duration = 3

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        pass

    def with_effects(self, _effects):
        return self


def render_subtitled_video(subtitles, frame_at=None, font_dir=None, **param_overrides):
    """用真实的 ColorClip 走完 generate_video 的字幕流程，返回指定时刻的画面和渲染器调用。"""
    params = vd.VideoParams(
        video_subject="test",
        video_aspect="9:16",
        subtitle_enabled=True,
        font_name=param_overrides.pop("font_name", "STHeitiMedium.ttc"),
        font_size=60,
        stroke_width=2,
        bgm_type="",
        **param_overrides,
    )
    srt = "".join(
        f"{index}\n00:00:0{index - 1},000 --> 00:00:0{index},000\n{text}\n\n"
        for index, text in enumerate(subtitles, start=1)
    )
    frames = []

    def write(clip, *_args, **_kwargs):
        # generate_video 返回后会关闭合成视频，所以在写出时截取画面。
        if frame_at is not None:
            frames.append(clip.get_frame(frame_at))

    with tempfile.TemporaryDirectory() as tmp_dir:
        subtitle_path = Path(tmp_dir) / "subtitle.srt"
        subtitle_path.write_text(srt, encoding="utf-8")
        source = ColorClip((1080, 1920), color=(20, 30, 60), duration=len(subtitles))
        with (
            patch.object(vd, "_open_video_clip_quietly", return_value=source),
            patch.object(vd, "AudioFileClip", return_value=FakeAudio()),
            patch.object(vd, "TextClip", wraps=TextClip) as moviepy_renderer,
            patch.object(
                subtitle_shaping, "ShapedTextClip", wraps=ShapedTextClip
            ) as khatt_renderer,
            patch.object(vd, "_write_videofile_with_codec_fallback", side_effect=write),
            patch.object(vd, "_get_configured_video_codec", return_value="libx264"),
            patch.object(vd.utils, "font_dir", return_value=font_dir or str(FONT_DIR)),
        ):
            vd.generate_video(
                video_path="combined.mp4",
                audio_path="voice.mp3",
                subtitle_path=str(subtitle_path),
                output_file=str(Path(tmp_dir) / "final.mp4"),
                params=params,
            )
    return (frames[0] if frames else None), moviepy_renderer, khatt_renderer


def subtitle_calls(renderer):
    """create_text_clip 实际绘制字幕的调用（带颜色和尺寸）。

    不含 SubtitlesClip 通过 make_textclip 的探测调用，也不含无背景样式
    为量出阿拉伯字幕自然高度而做的测量调用。
    """
    return [
        call for call in renderer.call_args_list if "size" in call.kwargs and "color" in call.kwargs
    ]


STYLES = [
    {},
    {"text_background_color": "#000000"},
    {"text_background_color": "#000000", "rounded_subtitle_background": True},
]
STYLE_IDS = ["no-background", "background", "rounded-background"]


@pytest.mark.parametrize("overrides", STYLES, ids=STYLE_IDS)
def test_only_arabic_subtitles_go_through_khatt(overrides):
    subtitles = ["Hello world", "مرحبا بالعالم", "你好世界"]
    frame, moviepy_renderer, khatt_renderer = render_subtitled_video(
        subtitles, frame_at=1.5, **overrides
    )
    khatt_calls = subtitle_calls(khatt_renderer)
    moviepy_calls = subtitle_calls(moviepy_renderer)
    assert [call.kwargs["text"] for call in khatt_calls] == [RLM + "مرحبا بالعالم"]
    assert all(call.kwargs["font"] == FALLBACK_FONT for call in khatt_calls)
    # 其他语言的调用与修改前完全相同：原字体、原文本、没有方向标记。
    # （Windows 上 generate_video 会把字体路径中的反斜杠换成正斜杠，所以按 Path 比较。）
    assert [call.kwargs["text"] for call in moviepy_calls] == ["Hello world", "你好世界"]
    assert all(Path(call.kwargs["font"]) == FONT_DIR / "STHeitiMedium.ttc" for call in moviepy_calls)
    assert (frame >= 250).all(axis=2).any()  # 阿拉伯字幕那一秒画出了白色文字


def test_rounded_background_fits_the_shaped_arabic_text():
    _, _, khatt_renderer = render_subtitled_video(
        ["مرحبا بالعالم"], text_background_color="#000000", rounded_subtitle_background=True
    )
    (call,) = subtitle_calls(khatt_renderer)
    pad_x = int(60 * 0.4)
    expected = subtitle_shaping.text_width(call.kwargs["text"], FALLBACK_FONT, 60) + 2 * pad_x
    assert call.kwargs["size"][0] == expected  # 按整形宽度，而不是 STHeiti 的缺字宽度


@pytest.mark.parametrize("overrides", STYLES, ids=STYLE_IDS)
def test_quranic_pause_marks_are_not_clipped(overrides):
    # Amiri 的停顿符号高出字体上沿；无背景样式的固定高度不能把它们裁掉
    # （裁掉时 khatt 会发出 TextOverflowWarning，本文件将其视为失败）。
    # 这节经文在 60px、2px 描边时需要 152px 高，按公式只有 147px。
    render_subtitled_video(
        ["وَٱلضُّحَىٰ ۖ وَٱلَّيْلِ إِذَا سَجَىٰ ۗ"],
        font_dir=KHATT_FONT_DIR,
        font_name="Amiri-Regular.ttf",
        **overrides,
    )


def test_make_textclip_routes_arabic_through_khatt():
    # SubtitlesClip 会用 make_textclip 探测第一条字幕。
    _, moviepy_renderer, khatt_renderer = render_subtitled_video(["مرحبا", "Hello"])
    probes = [call for call in khatt_renderer.call_args_list if "size" not in call.kwargs]
    assert probes and all(call.kwargs["font"] == FALLBACK_FONT for call in probes)
    # MoviePy 自己用 "T" 探测是否有透明蒙版；除此之外不应有阿拉伯文交给 MoviePy。
    moviepy_probes = [c for c in moviepy_renderer.call_args_list if "size" not in c.kwargs]
    assert {call.kwargs["text"] for call in moviepy_probes} <= {"T"}


def test_one_arabic_font_for_the_whole_video(monkeypatch):
    # Rubik 有阿拉伯字母但没有乌尔都语的 ے：整条视频的阿拉伯字幕都改用
    # 后备字体，而不是逐条在两种字体之间切换；换行也按这个字体测量。
    measured_fonts = set()
    original = subtitle_shaping.text_width

    def spy(text, font, size, *args):
        measured_fonts.add(font)
        return original(text, font, size, *args)

    monkeypatch.setattr(subtitle_shaping, "text_width", spy)
    _, _, khatt_renderer = render_subtitled_video(
        ["مرحبا", "پاکستان ے"], font_dir=KHATT_FONT_DIR, font_name="Rubik-Regular.ttf"
    )
    calls = subtitle_calls(khatt_renderer)
    assert len(calls) == 2
    assert {call.kwargs["font"] for call in calls} == {FALLBACK_FONT}
    assert measured_fonts == {FALLBACK_FONT}


def test_user_font_with_arabic_glyphs_is_used():
    _, _, khatt_renderer = render_subtitled_video(
        ["مرحبا", "سلام"], font_dir=KHATT_FONT_DIR, font_name="Rubik-Regular.ttf"
    )
    assert {Path(call.kwargs["font"]) for call in subtitle_calls(khatt_renderer)} == {
        Path(KHATT_FONT_DIR) / "Rubik-Regular.ttf"
    }


def warnings_while(render):
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        render()
    finally:
        logger.remove(sink)
    return messages


def test_font_fallback_is_logged_once_per_video():
    messages = warnings_while(
        lambda: [render_subtitled_video(["مرحبا", "بالعالم", "سلام"]) for _ in range(2)]
    )
    fallback = f"using {subtitle_shaping.FALLBACK_FONT}"
    assert sum(fallback in message for message in messages) == 2  # 每条视频一次


@pytest.mark.filterwarnings("ignore::khatt.UnsupportedCharacterWarning")
def test_characters_no_font_can_draw_are_reported():
    # 后备字体和所选字体都没有的字符（这里是表情符号）会被跳过：日志要说明。
    messages = warnings_while(lambda: render_subtitled_video(["مرحبا 😀 你好"]))
    skipped = [message for message in messages if "skipped" in message]
    assert skipped and all("😀" in message and "你" not in message for message in skipped)


@pytest.mark.filterwarnings("error::khatt.UnsupportedCharacterWarning")
def test_mixed_arabic_and_chinese_cue_keeps_the_chinese():
    # 维护者在 #1698 中报告：同一条字幕里的中文被后备字体跳过。现在中文
    # 由所选字体绘制，渲染结果中的中文与单独用该字体绘制的完全相同。
    clip = shaped_clip(MIXED_CUE, font=YAHEI_FONT)
    chinese = ShapedTextClip(text="中文测试", font=YAHEI_FONT, font_size=100, color="white")
    chinese_width = ink_width(chinese)
    # 从右到左的段落里，中文在阿拉伯文左边：画面最左侧就是这几个汉字。
    left = clip.mask.get_frame(0)[:, :chinese_width] > 0.5
    alone = chinese.mask.get_frame(0) > 0.5
    rows = np.nonzero(left.any(axis=1))[0]
    alone_rows = np.nonzero(alone.any(axis=1))[0]
    assert np.array_equal(
        left[rows.min() : rows.max() + 1],
        alone[alone_rows.min() : alone_rows.max() + 1, :chinese_width],
    )
    # 阿拉伯文仍由后备字体整形，宽度不变，紧跟在中文右边。
    arabic = shaped_clip("مرحبا بالعالم", font=YAHEI_FONT)
    assert ink_width(clip) > chinese_width + ink_width(arabic)


@pytest.mark.filterwarnings("error::khatt.UnsupportedCharacterWarning")
@pytest.mark.parametrize("overrides", STYLES, ids=STYLE_IDS)
def test_mixed_cue_in_a_video_draws_the_chinese_with_the_selected_font(overrides):
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        frame, _, khatt_renderer = render_subtitled_video(
            [MIXED_CUE], frame_at=0.5, font_name="MicrosoftYaHeiBold.ttc", **overrides
        )
    finally:
        logger.remove(sink)
    (call,) = subtitle_calls(khatt_renderer)
    assert call.kwargs["font"] == FALLBACK_FONT
    assert [Path(font) for font in call.kwargs["fallback_fonts"]] == [Path(YAHEI_FONT)]
    assert not any("skipped" in message for message in messages)
    assert (frame >= 250).all(axis=2).any()
    if overrides.get("rounded_subtitle_background"):
        # 圆角背景的宽度也计入了中文。
        text_w = subtitle_shaping.text_width(
            call.kwargs["text"], FALLBACK_FONT, 60, call.kwargs["fallback_fonts"]
        )
        assert call.kwargs["size"][0] == text_w + 2 * int(60 * 0.4)


def test_wrapping_a_mixed_cue_measures_the_chinese():
    wrapped, _ = wrap_text(MIXED_CUE * 3, 500, font=YAHEI_FONT, fontsize=60)
    for line in wrapped.split("\n"):
        width = subtitle_shaping.text_width(line, FALLBACK_FONT, 60, [YAHEI_FONT])
        assert width <= 500


def test_wrap_text_leaves_other_languages_alone(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("non-Arabic subtitles must be measured as before")

    monkeypatch.setattr(subtitle_shaping, "text_width", forbidden)
    wrapped, _ = wrap_text("Hello world " * 20, 600, font=DEFAULT_FONT, fontsize=60)
    assert len(wrapped.split("\n")) > 1
