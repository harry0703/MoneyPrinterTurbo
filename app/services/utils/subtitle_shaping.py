"""Shaping adaptation layer for Arabic-script subtitles.

Arabic, Persian, Urdu and other Arabic-script languages must first choose glyphs by context and join letters,
then be laid out right to left, to display correctly; vowel marks must also be positioned on their letters by OpenType rules.
Pillow only shapes text when built with Raqm, and common installs such as on Windows lack Raqm,
so letters come apart, order is reversed and vowel marks are misplaced.

Here subtitles containing Arabic script are measured and drawn by khatt (HarfBuzz shaping + FreeType rasterization,
bundled in the wheel, with no system library dependency); khatt never calls Pillow's text layout,
so the result is the same whether or not Pillow has Raqm, and text is never shaped twice.
Other languages still go through MoviePy's native TextClip, with unchanged rendering.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

import khatt
from khatt.fonts import font_path as khatt_font_path
from khatt.video import TextClip as ShapedTextClip
from loguru import logger

# Unicode blocks related to Arabic script: basic, supplement, extended A/B and presentation forms A/B
# (excluding the U+FEFF byte order mark).
_ARABIC_SCRIPT_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x0870, 0x089F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFC),
)

# Direction marks: invisible, they only decide the direction of a line of text as a paragraph.
RLM = "‏"
LRM = "‎"

# None of the project's bundled fonts contain Arabic glyphs. When the selected font lacks glyphs, use khatt's bundled
# Noto Naskh Arabic (SIL OFL 1.1), which covers Arabic, Persian and Urdu.
FALLBACK_FONT = "noto-naskh"


def _is_arabic_char(char: str) -> bool:
    # Only look at letters, marks and symbols (L/M/S categories): the Arabic comma, question mark and Arabic-Indic digits
    # are also shared by Dhivehi (Thaana), Syriac and N'Ko, so they can't be used to decide the text is Arabic script.
    return unicodedata.category(char)[0] in "LMS" and any(
        start <= ord(char) <= end for start, end in _ARABIC_SCRIPT_RANGES
    )


def needs_shaping(text: str | None) -> bool:
    """Whether the text contains Arabic letters that need shaping."""
    return any(_is_arabic_char(char) for char in text or "")


def is_rtl_paragraph(text: str) -> bool:
    """Determine paragraph direction from the first strong directional character (Unicode Bidirectional Algorithm rules P2/P3)."""
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in ("R", "AL"):
            return True
        if direction == "L":
            return False
    return False


def direction_mark(text: str) -> str:
    """Direction mark matching the paragraph direction of ``text``.

    khatt treats each line as an independent paragraph and determines its direction from the first strong directional character of the line. Automatically wrapped
    lines must keep the original paragraph's direction, otherwise the word order of lines starting with English or digits would be reversed, so every line
    is prefixed with this mark.
    """
    return RLM if is_rtl_paragraph(text) else LRM


def resolve_font(font_path: str, text: str) -> tuple[str, bool]:
    """Return the font file actually used to draw ``text``, and whether a fallback font was used.

    Only falls back when the selected font lacks Arabic glyphs; if what's missing is only other characters such as emoji,
    the user's chosen font is kept, and khatt skips them as before with a warning.
    """
    try:
        missing = khatt.missing_characters(text, font_path)
    except (KeyError, ValueError) as exc:
        # Still keep subtitles readable when the font file doesn't exist or khatt can't read it.
        logger.warning(f"cannot check subtitle font glyphs, using {FALLBACK_FONT}: {exc}")
        return str(khatt_font_path(FALLBACK_FONT)), True
    if any(_is_arabic_char(char) for char in missing):
        return str(khatt_font_path(FALLBACK_FONT)), True
    return font_path, False


def fallback_fonts(shaped_font: str, font_path: str) -> list[str]:
    """Which fonts to use for characters ``shaped_font`` can't draw when drawing Arabic-script subtitles.

    When a fallback font is used, characters in the same subtitle that the fallback font lacks (e.g. Chinese following
    Arabic text) are still drawn with the user's chosen font; khatt falls back run by run per character, so nothing is lost.
    """
    if not font_path or shaped_font == font_path:
        return []
    try:
        khatt_font_path(font_path)
    except (KeyError, ValueError):
        return []  # The selected font can't be read; resolve_font has already warned
    return [font_path]


def video_font(font_path: str, subtitles: Iterable[str]) -> str:
    """Choose a single font for all Arabic-script subtitles of one video.

    If each subtitle chose its own font, subtitles in the same video could switch back and forth between two fonts,
    so the choice is made once over all subtitles; font fallback and undrawable characters are each reported once.
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
    skipped = khatt.missing_characters(
        text, font, fallback_fonts=fallback_fonts(font, font_path)
    )
    if skipped:
        # E.g. emoji: neither the fallback font nor the selected font has these glyphs, so they're skipped when drawing.
        logger.warning(
            "characters in Arabic-script subtitles that the subtitle font cannot "
            f"draw are skipped: {''.join(skipped[:20])}"
        )
    return font


def supports_text(font_path: str, text: str) -> bool:
    """Whether the fonts actually drawing ``text`` (the fallback plus the selected font when needed) can draw all of its characters."""
    font, _ = resolve_font(font_path, text)
    return not khatt.missing_characters(
        text, font, fallback_fonts=fallback_fonts(font, font_path)
    )


def text_width(
    text: str, font_path: str, font_size: int, fallbacks: Iterable[str] = ()
) -> int:
    """Measure single-line text width (pixels) using the actual shaped glyphs; see :func:`fallback_fonts` for ``fallbacks``."""
    left, _, right, _ = khatt.text_bbox(
        text, font=font_path, size_px=int(font_size), fallback_fonts=list(fallbacks)
    )
    return right - left


def text_clip(native, *, shaped_font: str | None = None, **kwargs):
    """Create a subtitle TextClip: Arabic-script text is drawn by khatt, everything else goes to ``native``.

    ``native`` is the MoviePy ``TextClip`` used by the caller; non-Arabic text is passed to it
    unchanged, exactly as before this change. The other parameters match MoviePy 2.2's ``TextClip``.
    ``shaped_font`` is the font for drawing Arabic-script text (see :func:`video_font`);
    when omitted it's determined from ``font`` and this text; characters it can't draw are drawn with ``font``.
    """
    text = kwargs.get("text")
    if not needs_shaping(text):
        return native(**kwargs)
    font = kwargs.get("font") or ""
    if shaped_font is None:
        shaped_font, _ = resolve_font(font, text)
    return ShapedTextClip(
        **{**kwargs, "font": shaped_font},
        fallback_fonts=fallback_fonts(shaped_font, font),
    )
