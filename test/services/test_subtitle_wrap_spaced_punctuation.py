from pathlib import Path

import pytest
from PIL import ImageFont

from app.services.video import wrap_text

FONT_PATH = str(
    Path(__file__).resolve().parents[2] / "resource/fonts/BeVietnamPro-Medium.ttf"
)


@pytest.mark.parametrize(
    "words, punctuation",
    [("Comment allez-vous", "?"), ("Bonjour tout le monde", "!")],
)
def test_wrapped_spaced_punctuation_keeps_previous_word_whole(words, punctuation):
    # French typography puts a space before ? ! : ; so the mark is its own
    # word. When only that mark wraps, the previous word must move with it
    # instead of being split letter by letter.
    font = ImageFont.truetype(FONT_PATH, 60)
    left, _, right, _ = font.getbbox(words)
    max_width = right - left + 5
    text = f"{words} {punctuation}"

    wrapped, height = wrap_text(text, max_width, font=FONT_PATH, fontsize=60)

    lines = wrapped.splitlines()
    last_word = words.rsplit(" ", 1)[1]
    assert lines == [words.rsplit(" ", 1)[0], f"{last_word} {punctuation}"]
    assert " ".join(lines) == text
    ascent, descent = font.getmetrics()
    assert height == 2 * (ascent + descent)


def test_character_wrapped_punctuation_still_borrows_one_character():
    # Unspaced CJK text keeps the existing behavior of pulling the final
    # character down so a closing mark never starts a line by itself.
    font = ImageFont.truetype(FONT_PATH, 60)
    left, _, right, _ = font.getbbox("ab" * 4)
    wrapped, _ = wrap_text("ab" * 4 + "。", right - left + 2, font=FONT_PATH, fontsize=60)

    lines = wrapped.splitlines()
    assert "".join(lines) == "ab" * 4 + "。"
    assert not lines[-1].startswith("。")


@pytest.mark.parametrize("word", ["Bonjour", "Cafe\u0301"])
@pytest.mark.parametrize("punctuation", ["!", "?", ":", ";"])
def test_single_word_before_spaced_punctuation_is_not_split(word, punctuation):
    font = ImageFont.truetype(FONT_PATH, 60)
    left, _, right, _ = font.getbbox(word)
    max_width = right - left + 2
    text = f"{word} {punctuation}"
    full_left, _, full_right, _ = font.getbbox(text)
    assert full_right - full_left > max_width

    wrapped, height = wrap_text(text, max_width, font=FONT_PATH, fontsize=60)

    assert wrapped.splitlines() == [word, punctuation]
    assert " ".join(wrapped.splitlines()) == text
    ascent, descent = font.getmetrics()
    assert height == 2 * (ascent + descent)
