from pathlib import Path

import pytest
from PIL import ImageFont
from moviepy import TextClip

from app.services import video
from app.utils import utils


@pytest.mark.parametrize("text", ["SAFE TEXT\nMORE SAFE", "hello world\nwide text here"])
def test_manual_subtitle_lines_fit_without_rewrapping(text):
    font_path = str(Path(utils.font_dir()) / "MicrosoftYaHeiBold.ttc")
    font = ImageFont.truetype(font_path, 60)
    width = max(font.getbbox(line)[2] - font.getbbox(line)[0] for line in text.split("\n"))
    wrapped, height = video.wrap_text(text, width, font=font_path, fontsize=60)
    assert wrapped == text
    assert height == 2 * sum(font.getmetrics())
    with TextClip(text=wrapped, font=font_path, font_size=60, size=(width, None)) as rendered:
        with TextClip(text=text, font=font_path, font_size=60, size=(width, None)) as expected:
            assert rendered.h == expected.h


def test_long_manual_line_wraps_without_splitting_the_next_line():
    font_path = str(Path(utils.font_dir()) / "MicrosoftYaHeiBold.ttc")
    font = ImageFont.truetype(font_path, 60)
    text = "hello world and more words\nSAFE TEXT"
    width = font.getbbox("SAFE TEXT")[2]
    wrapped, height = video.wrap_text(text, width, font=font_path, fontsize=60)
    assert wrapped.endswith("\nSAFE TEXT")
    assert " ".join(wrapped.split()) == " ".join(text.split())
    for line in wrapped.split("\n"):
        assert font.getbbox(line)[2] - font.getbbox(line)[0] <= width
    assert height == len(wrapped.split("\n")) * sum(font.getmetrics())
