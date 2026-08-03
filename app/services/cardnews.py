"""
카드뉴스를 그린다.

한 장씩 정지 이미지로 그린 뒤 이어 붙여 영상으로 만든다. 스톡 영상을 찾아 붙이는
방식과 달리 화면에 나오는 것이 곧 내용이라, 소재가 내용과 어긋나는 문제가 없다.

전환은 컷이다. 카드뉴스는 넘기는 맛으로 읽는 형식이고, 페이드는 글자를 읽는 시간을
빼앗는다.
"""

import math
import os
from dataclasses import dataclass, field
from itertools import islice

import numpy as np
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from app.utils import utils

# 세로 영상 기준. 카드 한 장이 화면 하나다.
CANVAS_SIZE = (1080, 1920)
BACKGROUND_COLOR = "#FFFFFF"
TITLE_COLOR = "#111111"
BODY_COLOR = "#333333"
ACCENT_COLOR = "#2563EB"
FOOTER_COLOR = "#8A8A8A"

TITLE_FONT = "Pretendard-Bold.ttf"
BODY_FONT = "Pretendard-Regular.ttf"

# 유튜브 쇼츠는 화면 아래쪽에 제목·채널명·버튼을 얹는다. 그 자리에 글을 두면 가려진다.
BOTTOM_SAFE_RATIO = 0.16
SIDE_MARGIN_RATIO = 0.09
TOP_MARGIN_RATIO = 0.14

MAX_CARDS = 12
MAX_TITLE_LENGTH = 120
MAX_BODY_LINES = 5
MAX_BODY_LINE_LENGTH = 120
MAX_FOOTER_LENGTH = 80
MIN_CARD_SECONDS = 0.5
# 카드 한 장이 이보다 오래 머물면 영상이 아니라 정지 화면이다. 잘못된 값 하나로
# 끝나지 않는 렌더링이 시작되는 것도 막는다.
MAX_CARD_SECONDS = 60.0


@dataclass
class Card:
    """카드 한 장. 화면에 나올 글이 전부 여기에 있다."""

    title: str
    body: tuple[str, ...] = field(default_factory=tuple)
    footer: str = ""
    index_label: str = ""

    def __post_init__(self):
        self.title = _clip(self.title, MAX_TITLE_LENGTH)
        self.footer = _clip(self.footer, MAX_FOOTER_LENGTH)
        self.index_label = _clip(self.index_label, 8)
        # islice 로 앞에서 끊는다. 먼저 tuple 로 만들면 끝없는 이터러블 하나에
        # 상한이 걸리기도 전에 메모리를 태운다.
        self.body = tuple(
            cleaned
            for line in islice(self.body, MAX_BODY_LINES)
            if (cleaned := _clip(line, MAX_BODY_LINE_LENGTH))
        )


def _clip(value, limit: int) -> str:
    text = str(value or "")
    text = "".join(char for char in text if char.isprintable())
    return " ".join(text.split())[:limit]


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(utils.font_dir(), name)
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        # 글꼴이 없으면 글자가 아예 안 그려지는 것보다 기본 글꼴이 낫다. 한글은
        # 깨지지만 무엇이 잘못됐는지는 화면에 남는다.
        logger.error(f"card news font is missing: {path}")
        return ImageFont.load_default(size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """
    폭에 맞게 줄을 나눈다.

    공백에서 먼저 끊고, 한 덩어리가 폭을 넘으면 글자 단위로 끊는다. 한국어는 띄어쓰기
    없이 길게 이어지는 경우가 흔해서 공백만 보면 줄이 화면 밖으로 나간다.
    """
    lines: list[str] = []
    current = ""
    for word in str(text or "").split():
        candidate = f"{current} {word}".strip()
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        # 단어 하나가 이미 폭을 넘으면 글자 단위로 잘라 넣는다.
        while _text_width(draw, word, font) > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and _text_width(draw, word[:cut], font) > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def fit_single_line(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """
    한 줄에 들어가게 줄인다. 넘치면 말줄임표를 붙인다.

    잘라 내기만 하면 `Hacker News · 206 points ·` 처럼 구분자만 남아, 뒤에 뭔가
    있었다는 사실조차 보이지 않는다.
    """
    text = str(text or "")
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    cut = len(text)
    while cut > 0 and _text_width(draw, text[:cut] + ellipsis, font) > max_width:
        cut -= 1
    return (text[:cut].rstrip(" ·-") + ellipsis) if cut else ellipsis


def render_card(card: Card, size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """카드 한 장을 이미지로 그린다."""
    width, height = size
    canvas = Image.new("RGB", size, BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)

    side = int(width * SIDE_MARGIN_RATIO)
    text_width = width - side * 2
    cursor = int(height * TOP_MARGIN_RATIO)
    bottom_limit = height - int(height * BOTTOM_SAFE_RATIO)

    if card.index_label:
        index_font = _font(TITLE_FONT, int(height * 0.026))
        draw.text((side, cursor), card.index_label, font=index_font, fill=ACCENT_COLOR)
        cursor += int(height * 0.052)

    title_font = _font(TITLE_FONT, int(height * 0.049))
    title_leading = int(height * 0.061)
    for line in wrap_text(draw, card.title, title_font, text_width):
        if cursor + title_leading > bottom_limit:
            break
        draw.text((side, cursor), line, font=title_font, fill=TITLE_COLOR)
        cursor += title_leading

    if card.body:
        cursor += int(height * 0.028)
        body_font = _font(BODY_FONT, int(height * 0.030))
        body_leading = int(height * 0.044)
        bullet_indent = int(width * 0.035)
        for entry in card.body:
            wrapped = wrap_text(draw, entry, body_font, text_width - bullet_indent)
            for offset, line in enumerate(wrapped):
                if cursor + body_leading > bottom_limit:
                    break
                if offset == 0:
                    draw.text((side, cursor), "·", font=body_font, fill=ACCENT_COLOR)
                draw.text(
                    (side + bullet_indent, cursor), line, font=body_font, fill=BODY_COLOR
                )
                cursor += body_leading
            cursor += int(height * 0.010)

    if card.footer:
        footer_font = _font(BODY_FONT, int(height * 0.022))
        footer_y = bottom_limit - int(height * 0.030)
        draw.text(
            (side, footer_y),
            fit_single_line(draw, card.footer, footer_font, text_width),
            font=footer_font,
            fill=FOOTER_COLOR,
        )

    return canvas


def _card_seconds(value) -> float:
    """
    카드가 머무는 시간을 쓸 수 있는 범위로 만든다.

    이 값은 나레이션 길이 계산에서 나오므로 0 이나 NaN 이 섞일 수 있고, 그대로
    넘기면 읽을 수 없는 카드나 끝나지 않는 렌더링이 된다.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = MIN_CARD_SECONDS
    if not math.isfinite(seconds):
        seconds = MIN_CARD_SECONDS
    return max(MIN_CARD_SECONDS, min(seconds, MAX_CARD_SECONDS))


# 오디오 쪽도 같은 값으로 맞춰야 한다. 영상만 조이면 그 차이만큼 소리가 밀린다.
card_seconds = _card_seconds


def build_card_news_clip(
    cards, durations, size: tuple[int, int] = CANVAS_SIZE
):
    """
    카드들을 이어 붙인 영상 클립을 만든다.

    ``durations`` 는 카드마다 화면에 머무는 초다. 나레이션 길이에서 나오므로 카드마다
    다르고, 여기서는 받아 쓰기만 한다. 개수가 모자라면 마지막 값을 이어 쓴다 —
    카드가 아예 안 나오는 것보다 낫다.
    """
    from moviepy import ImageClip, concatenate_videoclips

    cards = list(islice(cards, MAX_CARDS))
    if not cards:
        raise ValueError("card news needs at least one card")

    durations = [_card_seconds(value) for value in islice(durations, MAX_CARDS)]
    if not durations:
        raise ValueError("card news needs at least one duration")

    clips = []
    for index, card in enumerate(cards):
        seconds = durations[index] if index < len(durations) else durations[-1]
        frame = np.array(render_card(card, size))
        clips.append(ImageClip(frame).with_duration(seconds))

    logger.info(f"built a card news clip with {len(clips)} cards")
    return concatenate_videoclips(clips, method="chain")
