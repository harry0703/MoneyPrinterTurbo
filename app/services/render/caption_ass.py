"""Build an ASS subtitle file matching the local MoviePy caption layout.

Captions are burned with libass (ffmpeg), which sizes glyphs and spaces lines
differently from PIL. So we measure the text with PIL, the same library video.py
uses, and write an ASS that positions every line and draws the box explicitly,
loading the font via fontsdir. Standard library plus Pillow only.
"""

import re
import struct
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import ImageFont


def _read_win_metrics(font_path: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Read (unitsPerEm, usWinAscent, usWinDescent) from the font's sfnt tables.

    libass maps the ASS font size onto the win-metric height, not the em square,
    so we need these to scale the size and correct the vertical anchor. Handles
    TTF/OTF and TTC (font 0); returns Nones if the tables are missing.
    """
    try:
        data = Path(font_path).read_bytes()
    except OSError:
        return None, None, None
    if len(data) < 12:
        return None, None, None

    def u16(o: int) -> int:
        return struct.unpack(">H", data[o:o + 2])[0]

    def u32(o: int) -> int:
        return struct.unpack(">I", data[o:o + 4])[0]

    try:
        dir_off = u32(12) if data[0:4] == b"ttcf" else 0  # TTC: first font's table dir
        num_tables = u16(dir_off + 4)
        tables = {}
        rec = dir_off + 12
        for _ in range(num_tables):
            tables[data[rec:rec + 4]] = u32(rec + 8)
            rec += 16
        if b"head" not in tables or b"OS/2" not in tables:
            return None, None, None
        upm = u16(tables[b"head"] + 18)
        os2 = tables[b"OS/2"]
        return upm, u16(os2 + 74), u16(os2 + 76)
    except (struct.error, IndexError):
        return None, None, None


def _ts_to_seconds(ts: str) -> float:
    parts = ts.strip().replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])
    except ValueError:
        return 0.0


def _parse_srt(path: str) -> List[Tuple[float, float, str]]:
    content = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    cues = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        i = 1 if re.match(r"^\d+$", lines[0].strip()) else 0
        m = re.match(r"(\S+)\s*-->\s*(\S+)", lines[i])
        if not m:
            continue
        text = " ".join(lines[i + 1:]).strip()
        if text:
            cues.append((_ts_to_seconds(m.group(1)), _ts_to_seconds(m.group(2)), text))
    return cues


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:  # rounding spill carries up through the units
        cs, s = 0, s + 1
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, h = 0, h + 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _hex_to_ass(hex_color: str, alpha: int = 0) -> str:
    # ASS colors are &HAABBGGRR: bytes reversed from web, alpha 00=opaque..FF=clear.
    h = hex_color.lstrip("#")
    if len(h) >= 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H{alpha:02X}{b}{g}{r}".upper()
    return "&H00FFFFFF"


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    # Greedy word wrap by pixel width, like video.py's wrap_text. Words wider than
    # the line (CJK runs) fall back to wrapping by character.
    def width(s: str) -> int:
        box = font.getbbox(s)
        return box[2] - box[0]

    if width(text) <= max_width:
        return [text]
    lines = []
    cur = ""
    for word in text.split(" "):
        if width(word) > max_width:
            if cur:
                lines.append(cur)
                cur = ""
            piece = ""
            for ch in word:
                if piece and width(piece + ch) > max_width:
                    lines.append(piece)
                    piece = ch
                else:
                    piece += ch
            cur = piece
            continue
        candidate = (cur + " " + word).strip()
        if not cur or width(candidate) <= max_width:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _sanitize(text: str) -> str:
    # Drop ASS override braces so subtitle text can't inject tags.
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _rect_path(w: int, h: int) -> str:
    return f"m 0 0 l {w} 0 l {w} {h} l 0 {h}"


def _rounded_rect_path(w: int, h: int, r: int) -> str:
    # Corners are quarter-circle beziers; 0.5523 is the circle approximation.
    r = max(0, min(r, w // 2, h // 2))
    if r == 0:
        return _rect_path(w, h)
    c = round(r * 0.5523)
    return (
        f"m {r} 0 l {w - r} 0 "
        f"b {w - r + c} 0 {w} {r - c} {w} {r} "
        f"l {w} {h - r} "
        f"b {w} {h - r + c} {w - r + c} {h} {w - r} {h} "
        f"l {r} {h} "
        f"b {r - c} {h} 0 {h - r + c} 0 {h - r} "
        f"l 0 {r} "
        f"b 0 {r - c} {r - c} 0 {r} 0"
    )


def _font_family(font_path: str) -> str:
    # The ASS Fontname must match the font's family so libass resolves it from
    # fontsdir. PIL reads it from the file.
    try:
        name, _ = ImageFont.truetype(font_path, 32).getname()
        return name or "Arial"
    except Exception:
        return "Arial"


def build_caption_ass(subtitle_path: str, params, width: int, height: int,
                      font_path: str) -> str:
    """Render the SRT into an ASS string matching the local caption layout."""
    fs = int(getattr(params, "font_size", 48) or 48)
    font = ImageFont.truetype(font_path, fs)
    upm, win_asc, win_desc = _read_win_metrics(font_path)
    have_metrics = bool(upm and win_asc is not None and win_desc is not None)
    win_h = (win_asc + win_desc) if have_metrics else 0
    # Scale the ASS size so libass renders glyphs at fs pixels (PIL's em size).
    ass_fs = round(fs * win_h / upm) if have_metrics else fs
    # \an5 centers a line on its tall win box, dropping the baseline below the
    # \pos point. We undo that per cue, since the ink offset depends on the
    # glyphs the first and last line carry.
    baseline_off = ((win_asc - win_desc) / 2.0 / upm * fs) if have_metrics else 0.0
    metric_ascent = font.getmetrics()[0]

    interline = int(fs * 0.25)
    vertical_padding = int(fs * 0.35)
    max_width = int(width * 0.9)        # wrap and box width, like video.py
    box_pad_x = int(fs * 0.6)           # rounded-box horizontal padding
    box_radius = max(8, int(fs * 0.4))  # rounded-box corner radius

    fore = getattr(params, "text_fore_color", "#FFFFFF") or "#FFFFFF"
    stroke_color = getattr(params, "stroke_color", "#000000") or "#000000"
    stroke_w = int(float(getattr(params, "stroke_width", 0) or 0))  # video.py also int()s this

    bg_raw = getattr(params, "text_background_color", True)
    box_on = bool(bg_raw)
    box_color = bg_raw if isinstance(bg_raw, str) and bg_raw.startswith("#") else "#000000"
    rounded = bool(getattr(params, "rounded_subtitle_background", False))
    box_alpha = (255 - 140) if rounded else 0  # video.py uses alpha 140 when rounded

    pos = getattr(params, "subtitle_position", "bottom")
    custom_pos = float(getattr(params, "custom_position", 70.0) or 70.0)

    def clip_top(clip_h: int) -> float:
        if pos == "top":
            return height * 0.05
        if pos == "center":
            return (height - clip_h) / 2
        if pos == "custom":
            y = (height - clip_h) * (custom_pos / 100.0)
            return max(10.0, min(y, height - clip_h - 10.0))
        return height * 0.95 - clip_h

    primary = _hex_to_ass(fore)
    outline = _hex_to_ass(stroke_color)
    # A \p fill takes color (\c, BGR) and alpha separately.
    box_hex = box_color.lstrip("#")
    box_c = f"&H{box_hex[4:6]}{box_hex[2:4]}{box_hex[0:2]}".upper() if len(box_hex) >= 6 else "&H000000"
    box_a = f"&H{box_alpha:02X}"

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",  # we wrap ourselves, libass must not re-wrap
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Box,Arial,1,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,"
        "100,100,0,0,1,0,0,7,0,0,0,1",
        # Outline only; the box is a separate layer. Weight comes from the font file.
        f"Style: Txt,{_font_family(font_path)},{ass_fs},{primary},&H000000FF,{outline},"
        f"&H00000000,0,0,0,0,100,100,0,0,1,{stroke_w},0,5,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events = []
    for start, end, text in _parse_srt(subtitle_path):
        lines = _wrap(text, font, max_width)
        n = len(lines)
        bbox = font.getbbox(text)  # single-line height, as video.py measures it
        single_h = bbox[3] - bbox[1]
        clip_h = int(n * single_h + vertical_padding + interline * n)
        ct = clip_top(clip_h)
        st, et = _ass_time(start), _ass_time(end)

        if box_on:
            # Solid: opaque bar at 90% width. Rounded: ~55% translucent, fits the
            # widest line plus padding, rounded corners (video.py's two styles).
            if rounded:
                widest = max(font.getbbox(ln)[2] - font.getbbox(ln)[0] for ln in lines)
                box_w = min(max_width, widest + 2 * box_pad_x)
                path = _rounded_rect_path(box_w, clip_h, box_radius)
            else:
                box_w = max_width
                path = _rect_path(box_w, clip_h)
            box_x = (width - box_w) // 2
            events.append(
                f"Dialogue: 0,{st},{et},Box,,0,0,0,,"
                f"{{\\pos({box_x},{round(ct)})\\an7\\p1\\c{box_c}\\alpha{box_a}}}"
                f"{path}{{\\p0}}"
            )
        # PIL stacks lines by getbbox("A")[3] + spacing; center the block in the
        # clip, then shift up so the ink (not the win box) is centered.
        line_pitch = font.getbbox("A")[3] + interline
        center_y = ct + clip_h / 2.0
        ink_asc_top = metric_ascent - font.getbbox(lines[0])[1]
        ink_desc_bot = font.getbbox(lines[-1])[3] - metric_ascent
        anchor_dy = baseline_off + (ink_desc_bot - ink_asc_top) / 2.0
        for i, ln in enumerate(lines):
            cy = center_y + (i - (n - 1) / 2.0) * line_pitch - anchor_dy
            events.append(
                f"Dialogue: 1,{st},{et},Txt,,0,0,0,,"
                f"{{\\pos({round(width / 2)},{round(cy)})}}{_sanitize(ln)}"
            )

    return "\n".join(header + events) + "\n"
