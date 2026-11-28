"""Preparación del guion para una narración natural en español.

MeloTTS pronuncia mal los números con separadores, los símbolos y muchas siglas.
Aquí se expanden a palabras, se aplica un glosario técnico conservador y se
segmenta el texto en frases con una pausa declarada. Los "estilos" ajustan
ritmo y pausas: no son emociones del modelo y así se informa en el panel.
"""

from __future__ import annotations

import re

from app.services.personal_studio.presets import NARRATION_STYLES, TECH_TERMS

_UNITS = (
    "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
    "catorce quince dieciséis diecisiete dieciocho diecinueve veinte veintiuno "
    "veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete "
    "veintiocho veintinueve"
).split()
_TENS = {
    30: "treinta",
    40: "cuarenta",
    50: "cincuenta",
    60: "sesenta",
    70: "setenta",
    80: "ochenta",
    90: "noventa",
}
_HUNDREDS = {
    100: "cien",
    200: "doscientos",
    300: "trescientos",
    400: "cuatrocientos",
    500: "quinientos",
    600: "seiscientos",
    700: "setecientos",
    800: "ochocientos",
    900: "novecientos",
}

_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_CURRENCY = re.compile(r"[$€]\s*(\d+(?:[.,]\d+)*)")
_THOUSANDS = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_DECIMAL = re.compile(r"^\d+[.,]\d+$")
_SPACES = re.compile(r"[ \t\u00a0]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _below_hundred(number: int) -> str:
    if number < 30:
        return _UNITS[number]
    tens = (number // 10) * 10
    unit = number % 10
    return _TENS[tens] + (f" y {_UNITS[unit]}" if unit else "")


def _below_thousand(number: int) -> str:
    if number < 100:
        return _below_hundred(number)
    if number == 100:
        return "cien"
    hundreds = (number // 100) * 100
    rest = number % 100
    if hundreds == 100:
        word = "cien" if rest == 0 else "ciento"
    else:
        word = _HUNDREDS[hundreds]
    return word + (f" {_below_hundred(rest)}" if rest else "")


def number_to_words(number: int) -> str:
    if number < 0:
        return "menos " + number_to_words(-number)
    if number < 1000:
        return _below_thousand(number)
    if number < 1_000_000:
        thousands, rest = divmod(number, 1000)
        prefix = "mil" if thousands == 1 else f"{_below_thousand(thousands)} mil"
        return prefix + (f" {_below_thousand(rest)}" if rest else "")
    millions, rest = divmod(number, 1_000_000)
    prefix = "un millón" if millions == 1 else f"{number_to_words(millions)} millones"
    return prefix + (f" {number_to_words(rest)}" if rest else "")


def _expand_token(token: str) -> str:
    normalized = token.strip()
    if not normalized:
        return normalized
    if _THOUSANDS.fullmatch(normalized):
        return number_to_words(int(normalized.replace(".", "")))
    if _DECIMAL.fullmatch(normalized):
        whole, fraction = re.split(r"[.,]", normalized, maxsplit=1)
        digits = " ".join(number_to_words(int(digit)) for digit in fraction)
        return f"{number_to_words(int(whole))} coma {digits}"
    if normalized.isdigit():
        value = int(normalized)
        if len(normalized) >= 7:
            return " ".join(number_to_words(int(digit)) for digit in normalized)
        return number_to_words(value)
    return normalized


def expand_numbers(text: str) -> str:
    text = _PERCENT.sub(lambda match: _expand_token(match.group(1)) + " por ciento", text)
    text = _CURRENCY.sub(lambda match: _expand_token(match.group(1)) + " pesos", text)
    return re.sub(r"\d+(?:[.,]\d+)*", lambda match: _expand_token(match.group(0)), text)


def apply_glossary(text: str, enabled: bool = True) -> str:
    if not enabled:
        return text
    for term, replacement in TECH_TERMS.items():
        text = re.sub(rf"\b{re.escape(term)}\b", replacement, text, flags=re.IGNORECASE)
    return text


def normalize_text(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("…", "...").replace("—", ", ").replace("–", ", ")
    text = _SPACES.sub(" ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def style_parameters(style: str) -> dict:
    return NARRATION_STYLES.get(style, NARRATION_STYLES["conversacional"])


def split_sentences(text: str, max_chars: int = 180) -> list[str]:
    """Divide por puntuación y luego por comas/espacios si la frase es larga."""
    sentences: list[str] = []
    for block in re.split(r"\n+", text):
        for sentence in _SENTENCE_END.split(block.strip()):
            sentence = sentence.strip()
            if not sentence:
                continue
            while len(sentence) > max_chars:
                cut = sentence.rfind(",", 0, max_chars)
                if cut < max_chars * 0.4:
                    cut = sentence.rfind(" ", 0, max_chars)
                if cut <= 0:
                    cut = max_chars
                sentences.append(sentence[:cut].strip(" ,"))
                sentence = sentence[cut + 1 :].strip()
            if sentence:
                sentences.append(sentence)
    return sentences


def segment_script(
    text: str,
    style: str = "conversacional",
    *,
    expand: bool = True,
    glossary: bool = True,
    max_chars: int | None = None,
) -> list[dict]:
    """Devuelve ``[{text, pause_after}]`` listo para el trabajador de voz."""
    params = style_parameters(style)
    prepared = normalize_text(text)
    if expand:
        prepared = expand_numbers(prepared)
    prepared = apply_glossary(prepared, glossary)
    prepared = re.sub(r"\s+([,.;:!?])", r"\1", prepared)
    sentences = split_sentences(prepared, max_chars or params["max_chars"])
    if not sentences:
        raise ValueError("El guion no contiene texto narrable")
    segments: list[dict] = []
    for index, sentence in enumerate(sentences):
        pause = float(params["pause"])
        if sentence.endswith(("?", "!")):
            pause += 0.12
        if sentence.endswith("..."):
            pause += 0.2
        if index == len(sentences) - 1:
            pause = 0.05
        segments.append({"text": sentence, "pause_after": round(pause, 3)})
    return segments


def plain_text(segments: list[dict]) -> str:
    return " ".join(segment["text"] for segment in segments).strip()


def estimate_duration(segments: list[dict], characters_per_second: float = 14.0) -> float:
    """Estimación solo para el panel antes de sintetizar; no se usa para cortar."""
    speech = sum(len(segment["text"]) for segment in segments) / max(
        4.0, characters_per_second
    )
    pauses = sum(float(segment.get("pause_after") or 0) for segment in segments)
    return max(1.0, speech + pauses)
