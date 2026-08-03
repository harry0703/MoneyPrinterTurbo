"""
소재 하나를 카드뉴스 한 편으로 바꾼다.

수집기(`sources`)와 렌더러(`cardnews`) 사이를 잇는다. 어느 쪽도 상대를 모르게 두고,
여기서만 둘의 모양을 안다.
"""

from dataclasses import dataclass

from loguru import logger

from app.services import llm
from app.services.cardnews import Card
from app.services.sources.base import SourceItem


@dataclass(frozen=True)
class CardScript:
    """카드와 카드별 나레이션. 둘의 길이는 항상 같다."""

    cards: tuple[Card, ...]
    narrations: tuple[str, ...]

    @property
    def narration_text(self) -> str:
        """전체 나레이션. 길이 가늠이나 미리듣기에 쓴다."""
        return " ".join(self.narrations)


def _footer(item: SourceItem) -> str:
    """
    출처 줄. 어디서 왔고 반응이 어땠는지를 남긴다.

    남의 프로젝트를 소개하는 채널이라 출처 표기는 예의가 아니라 최소 조건이다.
    """
    parts = [_SOURCE_LABELS.get(item.source, item.source)]
    if item.points:
        parts.append(f"{item.points} points")
    link = item.url or item.discussion_url
    if link:
        parts.append(link.split("://", 1)[-1])
    return " · ".join(part for part in parts if part)


_SOURCE_LABELS = {"hackernews": "Hacker News"}


def build_card_script(item: SourceItem, language: str = "ko-KR") -> CardScript | None:
    """
    소재에서 카드 대본을 만든다. 쓸 만한 게 안 나오면 ``None``.

    실패를 예외로 올리지 않는 이유는 위와 같다. 하루치 소재 중 하나가 카드가 되지
    않았다고 나머지까지 멈출 이유가 없다.
    """
    entries = llm.generate_card_script(
        title=item.title,
        url=item.url,
        source=item.source,
        points=item.points,
        body_text=item.text,
        language=language,
    )
    if not entries:
        logger.warning(f"no card script for {item.source}:{item.item_id}")
        return None

    footer = _footer(item)
    cards = []
    narrations = []
    for index, entry in enumerate(entries, start=1):
        cards.append(
            Card(
                index_label=f"{index:02d}",
                title=entry["title"],
                body=tuple(entry.get("bullets") or ()),
                # 출처는 첫 장과 마지막 장에만 둔다. 매 장에 반복하면 읽는 데
                # 방해가 되고, 없으면 어디서 온 이야기인지 알 수 없다.
                footer=footer if index in (1, len(entries)) else "",
            )
        )
        narrations.append(entry["narration"])

    return CardScript(cards=tuple(cards), narrations=tuple(narrations))
