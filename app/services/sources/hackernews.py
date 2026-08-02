"""
Hacker News 에서 소재를 모아 온다.

Algolia 검색 API 를 쓴다. 공식 Firebase API 는 글 하나마다 요청을 보내야 해서 상위
목록을 훑는 데 수백 번이 필요하지만, 검색 API 는 점수·시간 조건을 서버에서 걸어
한 번에 받아 온다. 둘 다 키가 없고 요금도 없다.
"""

import json
import time
from urllib.parse import urlparse

import requests
from loguru import logger

from app.services.sources.base import MAX_ID_LENGTH, SourceItem

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://news.ycombinator.com/item?id={item_id}"
REQUEST_TIMEOUT_SECONDS = 20
# 응답도 외부 입력이다. 통째로 메모리에 올리기 전에 크기를 끊는다.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# 한 번에 받아 올 글 수. Algolia 가 허용하는 상한은 1000 이지만 그만큼 필요하지 않다.
MAX_HITS = 100

SOURCE_NAME = "hackernews"


def _read_bounded_json(response):
    """응답 본문을 상한까지만 읽어 파싱한다. 넘으면 ``None``."""
    with response:
        raw = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
    if len(raw) > MAX_RESPONSE_BYTES:
        logger.warning("hacker news returned an oversized body")
        return None
    return json.loads(raw)


def _is_safe_link(url: str) -> bool:
    """
    카드에 실을 수 있는 링크인지 본다.

    출처 링크는 화면에 그대로 찍히고 사람이 눌러 볼 값이다. 외부에서 온 문자열이라
    `javascript:` 나 `file:` 같은 것이 섞여 들어올 수 있으므로 http 계열만 받는다.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _to_item(hit) -> SourceItem | None:
    """검색 결과 한 건을 공통 모양으로 바꾼다. 쓸 수 없으면 ``None``."""
    if not isinstance(hit, dict):
        return None

    item_id = str(hit.get("objectID", "") or "").strip()
    title = str(hit.get("title") or hit.get("story_title") or "").strip()
    if not title:
        # 제목 없는 글은 카드로 만들 수 없다. 댓글이 검색에 섞여 들어올 때 걸린다.
        return None
    # 이 값이 토론 주소에 그대로 들어간다. HN 의 글 번호는 숫자이므로, 숫자가
    # 아니면 주소를 만들지 않고 글 자체를 버린다.
    if not item_id.isdigit() or len(item_id) > MAX_ID_LENGTH:
        logger.warning("dropped a hacker news hit with an unusable id")
        return None

    url = str(hit.get("url") or "").strip()
    if url and not _is_safe_link(url):
        logger.warning(f"dropped a hacker news link with an unusable scheme: {item_id}")
        url = ""

    def _count(field: str) -> int:
        try:
            return max(0, int(hit.get(field) or 0))
        except (TypeError, ValueError):
            return 0

    tags = hit.get("_tags")
    return SourceItem(
        source=SOURCE_NAME,
        item_id=item_id,
        title=title,
        url=url,
        discussion_url=ITEM_URL.format(item_id=item_id),
        points=_count("points"),
        comment_count=_count("num_comments"),
        author=str(hit.get("author") or ""),
        created_at=str(hit.get("created_at") or ""),
        text=str(hit.get("story_text") or hit.get("comment_text") or ""),
        tags=tuple(str(tag) for tag in tags if isinstance(tag, str))
        if isinstance(tags, list)
        else (),
    )


def fetch_items(
    min_points: int = 100,
    within_hours: int = 48,
    limit: int = 20,
    tags: str = "story",
) -> list[SourceItem]:
    """
    조건에 맞는 최근 글을 점수 높은 순으로 돌려준다.

    ``tags`` 는 Algolia 의 필터 문법을 그대로 쓴다. ``story`` 는 전체 글, ``show_hn``
    은 Show HN 만이다. 새 도구를 소개하는 채널이라면 Show HN 이 적중률이 높다.

    실패는 빈 목록으로 돌려준다. 소재 수집이 안 됐다고 예외를 올리면, 매일 도는
    자동화가 소스 하나 때문에 통째로 멈춘다.
    """
    limit = max(1, min(int(limit or 1), MAX_HITS))
    since = int(time.time()) - max(1, int(within_hours or 1)) * 3600
    params = {
        "tags": str(tags or "story"),
        "numericFilters": f"created_at_i>{since},points>={max(0, int(min_points or 0))}",
        "hitsPerPage": limit,
    }

    try:
        response = requests.get(
            SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS, stream=True
        )
        body = _read_bounded_json(response)
    except Exception as exc:
        logger.warning(f"failed to fetch hacker news items: {type(exc).__name__}")
        return []

    if not isinstance(body, dict) or not isinstance(body.get("hits"), list):
        logger.warning("hacker news returned an unexpected body")
        return []

    items = [
        item for item in (_to_item(hit) for hit in body["hits"][:limit]) if item
    ]
    # 검색은 최신순으로 준다. 카드로 만들 것은 반응이 큰 쪽이 먼저다.
    items.sort(key=lambda item: item.points, reverse=True)
    logger.info(f"fetched {len(items)} hacker news items")
    return items
