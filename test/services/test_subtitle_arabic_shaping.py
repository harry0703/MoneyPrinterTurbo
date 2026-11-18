"""Regression tests for Arabic-script subtitle shaping.

These tests check the glyphs actually rendered, not just strings: vowel marks must sit on their letters,
letters must join, text must run right to left, and regardless of whether Pillow has Raqm, text never goes through
Pillow's text layout (so it's never shaped twice).
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
# The project's default subtitle font, which has no Arabic glyphs, used to cover the font fallback path.
DEFAULT_FONT = str(FONT_DIR / "STHeitiMedium.ttc")
# The font the maintainer used to reproduce Arabic and Chinese in the same subtitle.
YAHEI_FONT = str(FONT_DIR / "MicrosoftYaHeiBold.ttc")
MIXED_CUE = "مرحبا بالعالم 中文测试"
ARABIC_FONT = str(khatt_font_path("amiri"))
FALLBACK_FONT = str(khatt_font_path(subtitle_shaping.FALLBACK_FONT))
# The directory of khatt's bundled fonts, so generate_video can pick these fonts directly.
KHATT_FONT_DIR = str(khatt_font_path("amiri").parent)
RLM, LRM = subtitle_shaping.RLM, subtitle_shaping.LRM

# khatt emits TextOverflowWarning when text exceeds the canvas and content is clipped: always treated as a failure here.
pytestmark = pytest.mark.filterwarnings("error::khatt.TextOverflowWarning")


def shaped_clip(text, font=DEFAULT_FONT, **kwargs):
    return subtitle_shaping.text_clip(
        TextClip, text=text, font=font, font_size=100, color="white", **kwargs
    )


def ink_box(clip):
    """The area of the subtitle clip that actually has ink (left, top, right, bottom)."""
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
        ("سلام دنیا", True),  # Persian
        ("ٹھیک ہے", True),  # Urdu
        ("Breaking news: عاجل", True),
        ("ﻻ", True),  # Presentation form (lam-alef ligature)
        ("﷽", True),  # Basmala ligature (symbol category)
        ("Hello world", False),
        ("你好，世界", False),
        ("नमस्ते", False),
        ("", False),
        (None, False),
        ("﻿BOM", False),  # The byte order mark isn't an Arabic letter
        ("שלום עולם", False),  # Hebrew
        ("ދިވެހި، ބަސް", False),  # Dhivehi (Thaana) uses the Arabic comma
        ("ܫܠܡܐ؟", False),  # Syriac uses the Arabic question mark
        ("ߒߞߏ؛", False),  # N'Ko uses the Arabic semicolon
        ("١٢٣ ٤٥٦", False),  # Only Arabic-Indic digits
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
    # When only emoji are missing, keep the user's chosen font rather than switching to the fallback.
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
    # Regardless of whether Pillow has Raqm, Arabic-script subtitles never go through Pillow's text layout,
    # so there's no double shaping, and results don't vary by environment.
    def forbidden(*args, **kwargs):
        raise AssertionError("Pillow text layout must not be used for Arabic subtitles")

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", forbidden)
    monkeypatch.setattr(ImageDraw.ImageDraw, "multiline_text", forbidden)
    assert ink_width(shaped_clip("بِتَ مرحبا")) > 0


@pytest.mark.parametrize("font", [DEFAULT_FONT, ARABIC_FONT])
def test_vowel_marks_stay_on_their_letters(font):
    # The maintainer's reproduction case: unshaped, the Kasra sticks out past the rightmost glyph (width 107 → 145 at 100px).
    plain = ink_box(shaped_clip("بت", font=font))
    marked = ink_box(shaped_clip("بِتَ", font=font))
    assert abs((marked[2] - marked[0]) - (plain[2] - plain[0])) <= 2
    # Vowel marks sit above and below letters, so the ink only gets taller vertically.
    assert marked[1] < plain[1]
    assert marked[3] > plain[3]


def ink_runs(clip):
    """Count the contiguous runs of inked columns from left to right: a joined word is one run."""
    columns = (clip.mask.get_frame(0) > 0.5).any(axis=0)
    starts = columns & ~np.concatenate(([False], columns[:-1]))
    return int(starts.sum())


@pytest.mark.parametrize("word", ["سسس", "ببب"])
def test_letters_join(word):
    # Unshaped (Pillow without Raqm) these letters are three separate isolated glyphs; shaped, they join into one run.
    assert ink_runs(shaped_clip(word)) == 1
    assert ink_runs(shaped_clip(" ".join(word))) == 3


def test_right_to_left_order():
    # Alef is a tall vertical stroke and Beh a short glyph: laid out right to left, Alef must be on the right.
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
    # Lines only break at spaces, so words are never split.
    assert " ".join(strip_marks(line) for line in lines).split() == ARABIC_PARAGRAPH.split()
    font, _ = subtitle_shaping.resolve_font(DEFAULT_FONT, ARABIC_PARAGRAPH)
    assert all(subtitle_shaping.text_width(line, font, 60) <= 600 for line in lines)
    assert height > 0


def test_arabic_wraps_by_shaped_width_even_without_raqm(monkeypatch):
    # Pillow on Windows has no Raqm: Arabic widths measured by Pillow are those of disconnected, reversed
    # letters. Wrapping must still follow the shaped width: no line too wide, and each filled greedily as much as possible.
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
    # Automatically wrapped lines keep the original paragraph direction: each line of a right-to-left paragraph starts with RLM,
    # and each line of a left-to-right paragraph containing Arabic starts with LRM.
    rtl, _ = wrap_text("مرحبا بالعالم Khatt 2026 جديد " * 4, 300, font=ARABIC_FONT, fontsize=48)
    ltr, _ = wrap_text("Hello مرحبا world بالعالم " * 4, 300, font=ARABIC_FONT, fontsize=48)
    assert len(rtl.split("\n")) > 1 and len(ltr.split("\n")) > 1
    for line in rtl.split("\n"):
        assert line.startswith(RLM) and subtitle_shaping.is_rtl_paragraph(line)
    for line in ltr.split("\n"):
        assert line.startswith(LRM) and not subtitle_shaping.is_rtl_paragraph(line)


def test_hand_broken_lines_keep_their_own_direction():
    # Bilingual subtitles: one Arabic line and one English translation line, each keeping its own direction.
    wrapped, _ = wrap_text("مرحبا بالعالم\nHello, world!", 900, font=ARABIC_FONT, fontsize=48)
    arabic_line, english_line = wrapped.split("\n")
    assert arabic_line == RLM + "مرحبا بالعالم"
    assert strip_marks(english_line) == "Hello, world!"
    assert not subtitle_shaping.is_rtl_paragraph(english_line)


def test_translation_lines_are_measured_as_khatt_draws_them(monkeypatch):
    # A subtitle containing Arabic script is drawn entirely by khatt, and the English translation line must also be measured with khatt.
    measured = []
    original = subtitle_shaping.text_width

    def spy(text, *args):
        measured.append(strip_marks(text))
        return original(text, *args)

    monkeypatch.setattr(subtitle_shaping, "text_width", spy)
    wrap_text("مرحبا\nHello, world!", 900, font=ARABIC_FONT, fontsize=48)
    assert "Hello, world!" in measured


def test_lines_are_measured_in_the_direction_they_render():
    # The second line wrapped from a right-to-left paragraph starts with English. Mixed-line widths differ by direction,
    # so measurement must use the rendering direction (right to left), not the direction judged from the leading English.
    word = "الاستـ" + "ـ" * 16 + "ـقبال"  # A word stretched with Kashida to exactly fill the first line
    line = "Khatt 1.5 مرحبا بكم"
    rtl_width = subtitle_shaping.text_width(RLM + line, ARABIC_FONT, 48)
    ltr_width = subtitle_shaping.text_width(LRM + line, ARABIC_FONT, 48)
    assert rtl_width < ltr_width  # Precondition: measuring left to right would be wider
    wrapped, _ = wrap_text(f"{word} {line}", rtl_width, font=ARABIC_FONT, fontsize=48)
    assert wrapped.split("\n") == [RLM + word, RLM + line]  # The second line just fits


def test_arabic_words_are_never_split_across_lines():
    # The Chinese/Japanese line-start punctuation adjustment moves the last character of the previous line to the next; Arabic words
    # can't be split that way, or letter joining would break.
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
    # Pure Arabic: the fallback font supplies the glyphs, so it's no longer falsely reported as unsupported.
    assert vd.subtitle_font_supports_text(DEFAULT_FONT, "مرحبا بالعالم")
    # Arabic mixed with Chinese: the fallback font draws Arabic and the chosen font draws Chinese, so both can be drawn.
    assert vd.subtitle_font_supports_text(DEFAULT_FONT, "مرحبا 你好")
    # Detection for other languages stays unchanged.
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
    """Run generate_video's subtitle flow with a real ColorClip, returning the frame at the given time and the renderer calls."""
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
        # generate_video closes the composite video after returning, so the frame is captured while writing.
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
    """The calls create_text_clip actually makes to draw subtitles (with color and size).

    Excludes SubtitlesClip's probe calls via make_textclip, and the measurement calls the no-background style
    makes to measure the natural height of Arabic subtitles.
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
    # Calls for other languages are exactly the same as before the change: original font, original text, no direction marks.
    # (On Windows generate_video replaces backslashes in the font path with forward slashes, so compare as Paths.)
    assert [call.kwargs["text"] for call in moviepy_calls] == ["Hello world", "你好世界"]
    assert all(Path(call.kwargs["font"]) == FONT_DIR / "STHeitiMedium.ttc" for call in moviepy_calls)
    assert (frame >= 250).all(axis=2).any()  # White text was drawn during the second with the Arabic subtitle


def test_rounded_background_fits_the_shaped_arabic_text():
    _, _, khatt_renderer = render_subtitled_video(
        ["مرحبا بالعالم"], text_background_color="#000000", rounded_subtitle_background=True
    )
    (call,) = subtitle_calls(khatt_renderer)
    pad_x = int(60 * 0.4)
    expected = subtitle_shaping.text_width(call.kwargs["text"], FALLBACK_FONT, 60) + 2 * pad_x
    assert call.kwargs["size"][0] == expected  # By shaped width, not STHeiti's missing-glyph width


@pytest.mark.parametrize("overrides", STYLES, ids=STYLE_IDS)
def test_quranic_pause_marks_are_not_clipped(overrides):
    # Amiri's pause marks rise above the font's ascender; the fixed height of the no-background style must not clip them
    # (when clipped khatt emits TextOverflowWarning, which this file treats as a failure).
    # This verse needs 152px of height at 60px with a 2px stroke, while the formula gives only 147px.
    render_subtitled_video(
        ["وَٱلضُّحَىٰ ۖ وَٱلَّيْلِ إِذَا سَجَىٰ ۗ"],
        font_dir=KHATT_FONT_DIR,
        font_name="Amiri-Regular.ttf",
        **overrides,
    )


def test_make_textclip_routes_arabic_through_khatt():
    # SubtitlesClip probes the first subtitle with make_textclip.
    _, moviepy_renderer, khatt_renderer = render_subtitled_video(["مرحبا", "Hello"])
    probes = [call for call in khatt_renderer.call_args_list if "size" not in call.kwargs]
    assert probes and all(call.kwargs["font"] == FALLBACK_FONT for call in probes)
    # MoviePy itself probes for a transparency mask with "T"; apart from that no Arabic text should be handed to MoviePy.
    moviepy_probes = [c for c in moviepy_renderer.call_args_list if "size" not in c.kwargs]
    assert {call.kwargs["text"] for call in moviepy_probes} <= {"T"}


def test_one_arabic_font_for_the_whole_video(monkeypatch):
    # Rubik has Arabic letters but not Urdu's ے: all Arabic subtitles of the whole video switch to
    # the fallback font rather than alternating between two fonts subtitle by subtitle; wrapping is measured with this font too.
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
    assert sum(fallback in message for message in messages) == 2  # Once per video


@pytest.mark.filterwarnings("ignore::khatt.UnsupportedCharacterWarning")
def test_characters_no_font_can_draw_are_reported():
    # Characters neither the fallback font nor the chosen font has (here, emoji) are skipped: the log must say so.
    messages = warnings_while(lambda: render_subtitled_video(["مرحبا 😀 你好"]))
    skipped = [message for message in messages if "skipped" in message]
    assert skipped and all("😀" in message and "你" not in message for message in skipped)


@pytest.mark.filterwarnings("error::khatt.UnsupportedCharacterWarning")
def test_mixed_arabic_and_chinese_cue_keeps_the_chinese():
    # The maintainer reported in #1698: Chinese in the same subtitle was skipped by the fallback font. Now Chinese
    # is drawn by the chosen font, and the rendered Chinese is identical to drawing it with that font alone.
    clip = shaped_clip(MIXED_CUE, font=YAHEI_FONT)
    chinese = ShapedTextClip(text="中文测试", font=YAHEI_FONT, font_size=100, color="white")
    chinese_width = ink_width(chinese)
    # In a right-to-left paragraph Chinese sits left of the Arabic: the leftmost part of the frame is these characters.
    left = clip.mask.get_frame(0)[:, :chinese_width] > 0.5
    alone = chinese.mask.get_frame(0) > 0.5
    rows = np.nonzero(left.any(axis=1))[0]
    alone_rows = np.nonzero(alone.any(axis=1))[0]
    assert np.array_equal(
        left[rows.min() : rows.max() + 1],
        alone[alone_rows.min() : alone_rows.max() + 1, :chinese_width],
    )
    # The Arabic is still shaped by the fallback font with unchanged width, right after the Chinese.
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
        # The rounded background's width also includes the Chinese.
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
