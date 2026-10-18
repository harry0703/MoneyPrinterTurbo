"""Leitura do arte.json e desenho de texto com ffmpeg, compartilhados pelos scripts da skill."""

import json
import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
FONTS = os.path.join(REPO, "resource", "fonts")

DEFAULTS = {
    "texto_na_tela": {"font": "BeVietnamPro-Bold.ttf", "color": "#FFFFFF", "size": 96,
                      "box": True, "box_color": "#000000@0.55"},
    "thumbnail": {"font": "BeVietnamPro-Bold.ttf", "color": "#FFFFFF", "accent": "#FFD400"},
}


def load(project: str | None) -> dict:
    """arte.json do projeto mesclado sobre os padrões (seção por seção)."""
    data = {}
    path = os.path.join(project, "arte.json") if project else ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    return {key: {**DEFAULTS.get(key, {}), **data.get(key, {})} for key in {*DEFAULTS, *data}}


def font_path(name: str) -> str:
    path = name if os.path.isabs(name) else os.path.join(FONTS, name)
    if not os.path.exists(path):
        raise SystemExit(f"fonte não encontrada: {path} (use um arquivo de resource/fonts/)")
    return path


def _quote(value: str) -> str:
    # valor entre aspas simples dentro de um filtergraph do ffmpeg
    return "'" + value.replace("\\", "\\\\").replace("'", "'\\''") + "'"


def drawtext(text: str, textfile: str, *, font: str, color: str, size: int, x: str, y: str,
             box: bool = False, box_color: str = "#000000@0.55", border: int = 0) -> str:
    """Filtro drawtext lendo o texto de um arquivo (evita escapar acentos, ':' e '%')."""
    os.makedirs(os.path.dirname(textfile), exist_ok=True)
    with open(textfile, "w", encoding="utf-8") as f:
        f.write(text)
    parts = [
        f"fontfile={_quote(font_path(font))}", f"textfile={_quote(textfile)}", "expansion=none",
        f"fontcolor={color}", f"fontsize={size}", f"x={x}", f"y={y}", "line_spacing=12",
    ]
    if box:
        parts += ["box=1", f"boxcolor={box_color}", f"boxborderw={max(12, size // 4)}"]
    if border:
        parts += [f"borderw={border}", "bordercolor=black@0.85"]
    return "drawtext=" + ":".join(parts)
