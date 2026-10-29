import unicodedata
from pathlib import Path

import pytest
from PIL import ImageFont

from app.services.video import wrap_text


@pytest.mark.parametrize("syllable", ["i\u0301", "i\u0308", "a\u0301"])
def test_subtitle_wrap_keeps_accent_with_its_base_character(syllable):
    font_path = Path(__file__).resolve().parents[2] / "resource/fonts/BeVietnamPro-Medium.ttf"
    text = syllable * 35
    wrapped, _ = wrap_text(text, 180, font=str(font_path), fontsize=60)
    lines = wrapped.splitlines()
    assert len(lines) > 1
    assert all(not unicodedata.category(line[0]).startswith("M") for line in lines)
    assert "".join(lines) == text
    font = ImageFont.truetype(str(font_path), 60)
    assert all(font.getbbox(line)[2] - font.getbbox(line)[0] <= 180 for line in lines)
