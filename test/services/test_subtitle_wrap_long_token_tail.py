from pathlib import Path

from PIL import ImageFont

from app.services.video import wrap_text

FONT_PATH = str(
    Path(__file__).resolve().parents[2] / "resource/fonts/BeVietnamPro-Medium.ttf"
)


def _width(font, text):
    left, _, right, _ = font.getbbox(text)
    return right - left


def test_word_after_split_long_token_joins_its_last_fragment():
    # A token wider than the line is split by character. Its last fragment
    # does not fill the line, so the following short word must be placed
    # beside it instead of always starting another subtitle line.
    font = ImageFont.truetype(FONT_PATH, 60)
    text = "Supercalifragilisticexpialidocious is"

    wrapped, height = wrap_text(text, 400, font=FONT_PATH, fontsize=60)

    lines = wrapped.splitlines()
    assert lines[-1].endswith(" is")
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
    assert all(_width(font, line) <= 400 for line in lines)
    ascent, descent = font.getmetrics()
    assert height == len(lines) * (ascent + descent)


def test_word_after_split_long_token_still_wraps_when_it_does_not_fit():
    font = ImageFont.truetype(FONT_PATH, 60)
    text = "Supercalifragilisticexpialidocious extraordinarily"

    wrapped, _ = wrap_text(text, 400, font=FONT_PATH, fontsize=60)

    lines = wrapped.splitlines()
    assert all(_width(font, line) <= 400 for line in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
