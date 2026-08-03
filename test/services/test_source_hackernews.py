"""Hacker News 소재 수집기."""

import json
import unittest
from unittest.mock import patch

from app.services.sources import hackernews
from app.services.sources.base import MAX_TITLE_LENGTH, SourceItem


def _hit(**overrides):
    hit = {
        "objectID": "1",
        "title": "Show HN: A tiny thing",
        "url": "https://example.com/thing",
        "points": 120,
        "num_comments": 30,
        "author": "someone",
        "created_at": "2026-08-02T00:00:00Z",
        "_tags": ["story", "show_hn"],
    }
    hit.update(overrides)
    return hit


def _fetch(body, **kwargs):
    payload = json.dumps(body).encode("utf-8")
    with patch.object(hackernews.requests, "get") as get:
        response = get.return_value
        response.__enter__ = lambda self_: self_
        response.__exit__ = lambda *a: False
        response.raw.read.return_value = payload
        return hackernews.fetch_items(**kwargs)


class TestParsing(unittest.TestCase):
    def test_a_hit_becomes_an_item_with_a_discussion_link(self):
        """
        글 링크와 토론 링크는 다른 값이다. 카드에는 둘 다 쓸 자리가 있다.
        """
        items = _fetch({"hits": [_hit()]})

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source, "hackernews")
        self.assertEqual(item.title, "Show HN: A tiny thing")
        self.assertEqual(item.url, "https://example.com/thing")
        self.assertEqual(item.discussion_url, "https://news.ycombinator.com/item?id=1")
        self.assertEqual(item.points, 120)

    def test_items_come_back_by_points(self):
        """
        검색은 최신순으로 준다. 카드로 만들 것은 반응이 큰 쪽이 먼저다.
        """
        items = _fetch(
            {
                "hits": [
                    _hit(objectID="1", points=10),
                    _hit(objectID="2", points=900),
                    _hit(objectID="3", points=300),
                ]
            }
        )

        self.assertEqual([item.points for item in items], [900, 300, 10])

    def test_a_hit_without_a_title_is_dropped(self):
        """댓글이 검색에 섞여 들어온다. 제목이 없으면 카드로 만들 수 없다."""
        items = _fetch({"hits": [_hit(title=None, comment_text="just a reply")]})
        self.assertEqual(items, [])

    def test_a_link_that_is_not_http_is_dropped(self):
        """
        출처 링크는 화면에 찍히고 사람이 눌러 볼 값이다. 외부에서 온 문자열이라
        스킴을 확인해야 한다.
        """
        for hostile in ("javascript:alert(1)", "file:///etc/passwd", "data:text/html,x"):
            with self.subTest(url=hostile):
                items = _fetch({"hits": [_hit(url=hostile)]})
                self.assertEqual(items[0].url, "")
                # 링크만 버리고 글 자체는 남긴다. 토론 링크로 여전히 쓸 수 있다.
                self.assertTrue(items[0].discussion_url)

    def test_a_broken_score_does_not_break_the_item(self):
        """점수 필드가 없거나 숫자가 아닌 글이 섞여 있다."""
        items = _fetch({"hits": [_hit(points=None, num_comments="많음")]})
        self.assertEqual(items[0].points, 0)
        self.assertEqual(items[0].comment_count, 0)


class TestBounds(unittest.TestCase):
    def test_an_oversized_body_is_dropped(self):
        """
        응답은 외부 입력이다. 통째로 올려 파싱하면 거대한 본문 하나에 흔들린다.
        본문에 멀쩡한 글을 담아, 상한을 빼면 그 글이 돌아오도록 해 둔다.
        """
        filler = " " * (hackernews.MAX_RESPONSE_BYTES + 10)
        payload = json.dumps({"hits": [_hit()], "note": filler}).encode("utf-8")
        with patch.object(hackernews.requests, "get") as get:
            response = get.return_value
            response.__enter__ = lambda self_: self_
            response.__exit__ = lambda *a: False
            response.raw.read.return_value = payload
            self.assertIsNone(hackernews.fetch_items())

    def test_the_request_asks_for_a_bounded_page(self):
        """상한이 없으면 한 번에 받아 오는 양이 요청자에 따라 달라진다."""
        with patch.object(hackernews.requests, "get") as get:
            response = get.return_value
            response.__enter__ = lambda self_: self_
            response.__exit__ = lambda *a: False
            response.raw.read.return_value = b'{"hits": []}'
            hackernews.fetch_items(limit=10_000)

        self.assertLessEqual(
            get.call_args.kwargs["params"]["hitsPerPage"], hackernews.MAX_HITS
        )

    def test_an_id_that_is_not_a_number_is_dropped(self):
        """
        이 값이 토론 주소에 그대로 들어간다. HN 의 글 번호는 숫자이므로, 그렇지
        않은 값으로 주소를 만들면 엉뚱한 곳을 가리키는 링크가 카드에 실린다.
        """
        for hostile in ("1&x=2", "../../admin", "1 OR 1", "x" * 200):
            with self.subTest(item_id=hostile):
                self.assertEqual(_fetch({"hits": [_hit(objectID=hostile)]}), [])

    def test_tags_are_capped_in_count_and_length(self):
        """태그는 소스가 몇 개든 붙여 보낼 수 있다."""
        items = _fetch({"hits": [_hit(_tags=["t" * 500] * 100)]})
        item = items[0]
        self.assertLessEqual(len(item.tags), 10)
        self.assertTrue(all(len(tag) <= 40 for tag in item.tags))

    def test_a_long_timestamp_is_clipped(self):
        """소스가 준 시각 문자열도 기록과 프롬프트로 흘러간다."""
        items = _fetch({"hits": [_hit(created_at="9" * 5000)]})
        self.assertLessEqual(len(items[0].created_at), 40)

    def test_a_long_title_is_clipped(self):
        """제목은 그대로 프롬프트와 카드로 흘러간다."""
        items = _fetch({"hits": [_hit(title="x" * 10_000)]})
        self.assertEqual(len(items[0].title), MAX_TITLE_LENGTH)

    def test_control_characters_do_not_survive(self):
        """제어문자가 섞이면 로그와 자막에 그대로 들어간다."""
        item = SourceItem(source="s", item_id="1", title="a\x1b[2Jb")
        self.assertNotIn("\x1b", item.title)


class TestFailures(unittest.TestCase):
    def test_a_network_failure_reports_that_it_could_not_reach_the_source(self):
        """
        예외를 올리면 매일 도는 자동화가 소스 하나 때문에 멈춘다. 그렇다고 빈
        목록으로 돌려주면 '오늘 새 글이 없다' 와 구분되지 않아, 부르는 쪽이
        잠깐의 장애에 계속 다시 물어보게 된다.
        """
        with patch.object(
            hackernews.requests, "get", side_effect=RuntimeError("no network")
        ):
            self.assertIsNone(hackernews.fetch_items())

    def test_an_unexpected_body_reports_the_same_way(self):
        """`hits` 가 목록이 아니면 순회할 수 없다."""
        self.assertIsNone(_fetch({"hits": "nope"}))
        self.assertIsNone(_fetch(["not", "an", "object"]))

    def test_a_quiet_day_and_an_outage_look_different(self):
        """
        조건에 맞는 글이 없는 날도 정상적인 결과다. 장애와 같은 값으로 돌려주면
        부르는 쪽이 둘을 구분하지 못해, 조용한 날마다 계속 다시 물어본다.
        """
        self.assertEqual(_fetch({"hits": []}), [])
        with patch.object(
            hackernews.requests, "get", side_effect=RuntimeError("no network")
        ):
            self.assertIsNone(hackernews.fetch_items())


if __name__ == "__main__":
    unittest.main()
