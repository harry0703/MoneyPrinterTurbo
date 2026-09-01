from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from xml.etree import ElementTree

import requests

from app.services.trends.models import SourceStatus, TrendSignal

_TIMEOUT = (3.05, 10)
_MAX_ATTEMPTS = 2
_GOOGLE_TRENDS_URL = "https://trends.google.com/trending/rss?geo={market}"
_YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class GoogleTrendsRssSource:
    def __init__(self, session: requests.Session):
        self.session = session

    def fetch(
        self, markets: Iterable[str], collected_at: datetime
    ) -> tuple[list[TrendSignal], SourceStatus]:
        signals: list[TrendSignal] = []
        failures = 0
        for market in _markets(markets):
            url = _GOOGLE_TRENDS_URL.format(market=market)
            try:
                response = _get(self.session, url)
                root = ElementTree.fromstring(response.content)
                if root.tag != "rss":
                    raise ValueError("unexpected Google Trends RSS root")
            except (ElementTree.ParseError, ValueError, requests.RequestException):
                failures += 1
                continue
            for rank, item in enumerate(root.findall("./channel/item"), start=1):
                topic = (item.findtext("title") or "").strip()
                if topic:
                    signals.append(
                        TrendSignal(
                            topic=topic,
                            market=market,
                            rank=rank,
                            collected_at=collected_at,
                            source="google_trends",
                            source_reference=url,
                            source_confidence=0.8,
                        )
                    )
        return signals, _status(signals, failures)


class YouTubeMostPopularSource:
    def __init__(self, session: requests.Session, api_key: str):
        self.session = session
        self.api_key = api_key.strip()

    def fetch(
        self, markets: Iterable[str], collected_at: datetime
    ) -> tuple[list[TrendSignal], SourceStatus]:
        if not self.api_key:
            return [], SourceStatus.UNAVAILABLE

        signals: list[TrendSignal] = []
        failures = 0
        for market in _markets(markets):
            try:
                response = _get(
                    self.session,
                    _YOUTUBE_VIDEOS_URL,
                    params={
                        "part": "snippet,statistics",
                        "chart": "mostPopular",
                        "maxResults": 50,
                        "regionCode": market,
                        "key": self.api_key,
                    },
                )
                payload = json.loads(response.content)
                items = payload.get("items") if isinstance(payload, dict) else None
                if not isinstance(items, list):
                    raise ValueError("missing YouTube video items")
            except (json.JSONDecodeError, ValueError, requests.RequestException):
                failures += 1
                continue
            for rank, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                snippet = item.get("snippet")
                video_id = item.get("id")
                topic = snippet.get("title", "").strip() if isinstance(snippet, dict) else ""
                if topic and isinstance(video_id, str) and video_id:
                    signals.append(
                        TrendSignal(
                            topic=topic,
                            market=market,
                            rank=rank,
                            collected_at=collected_at,
                            source="youtube_most_popular",
                            source_reference=f"https://www.youtube.com/watch?v={video_id}",
                            source_confidence=0.7,
                        )
                    )
        return signals, _status(signals, failures)


def _get(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = session.get(url, timeout=_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.HTTPError as error:
            response = error.response
            if not (
                response is not None
                and (response.status_code == 429 or response.status_code >= 500)
            ):
                raise
            if attempt == _MAX_ATTEMPTS - 1:
                raise
        except (requests.ConnectionError, requests.Timeout):
            if attempt == _MAX_ATTEMPTS - 1:
                raise
    raise RuntimeError("unreachable")


def _markets(markets: Iterable[str]) -> tuple[str, ...]:
    return tuple(market.strip().upper() for market in markets if market.strip())


def _status(signals: list[TrendSignal], failures: int) -> SourceStatus:
    if failures:
        return SourceStatus.DEGRADED if signals else SourceStatus.UNAVAILABLE
    return SourceStatus.AVAILABLE
