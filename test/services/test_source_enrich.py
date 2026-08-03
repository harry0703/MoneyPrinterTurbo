"""소재 본문 읽어 오기."""

import ipaddress
import unittest
from unittest.mock import MagicMock, patch

from app.services.sources import enrich
from app.services.sources.base import MAX_TEXT_LENGTH, SourceItem

PUBLIC_IP = "93.184.216.34"


def _response(body: str = "hello", status: int = 200, content_type: str = "text/html",
              location: str = ""):
    """`requests.get` 이 돌려주는 것과 같은 모양의 응답."""
    response = MagicMock()
    response.status_code = status
    response.is_redirect = bool(location)
    response.headers = {"Content-Type": content_type}
    if location:
        response.headers["Location"] = location
    response.raw.read.return_value = body.encode("utf-8")
    return response


class _Fetch:
    """`getaddrinfo` 와 `requests.get` 을 함께 대신한다."""

    def __init__(self, responses, addresses=None):
        self.responses = list(responses)
        self.addresses = addresses or {}
        self.get = None

    def _resolve(self, host, *_args, **_kwargs):
        # 실제 `getaddrinfo` 는 주소를 그대로 적은 곳을 조회 없이 그 주소로 돌려준다.
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = self.addresses.get(host, PUBLIC_IP)
        return [(2, 1, 6, "", (address, 0))]

    def __enter__(self):
        self._patches = [
            patch.object(enrich.socket, "getaddrinfo", side_effect=self._resolve),
            patch.object(enrich.requests, "get", side_effect=self.responses),
        ]
        self.get = [entry.start() for entry in self._patches][1]
        return self

    def __exit__(self, *_exc):
        for entry in reversed(self._patches):
            entry.stop()
        return False


class TestPublicOnly(unittest.TestCase):
    """
    주소는 밖에서 온다. 검사 없이 요청을 보내면 이 기계가 내부망에 대신 요청을
    보내 주는 통로가 된다.
    """

    def test_a_private_address_is_refused(self):
        for host in (
            "127.0.0.1",
            "localhost",
            "10.0.0.5",
            "192.168.1.1",
            "169.254.169.254",  # 클라우드 메타데이터
            "[::1]",
        ):
            with self.subTest(host=host):
                with _Fetch([_response()], addresses={"localhost": "127.0.0.1"}) as fetch:
                    self.assertEqual(enrich.fetch_body(f"http://{host}/x"), "")
                    fetch.get.assert_not_called()

    def test_a_name_that_points_inside_is_refused(self):
        """스킴과 이름만 보면 사내 이름 하나로 그대로 통과한다."""
        with _Fetch([_response()], addresses={"intranet.example": "10.1.2.3"}) as fetch:
            self.assertEqual(enrich.fetch_body("https://intranet.example/x"), "")
            fetch.get.assert_not_called()

    def test_only_http_schemes_are_read(self):
        with _Fetch([_response()]) as fetch:
            for hostile in ("file:///etc/passwd", "gopher://x.test/1", "ftp://x.test/f"):
                with self.subTest(url=hostile):
                    self.assertEqual(enrich.fetch_body(hostile), "")
            fetch.get.assert_not_called()

    def test_a_host_that_does_not_resolve_is_refused(self):
        with patch.object(enrich.socket, "getaddrinfo", side_effect=OSError("nope")):
            with patch.object(enrich.requests, "get") as get:
                self.assertEqual(enrich.fetch_body("https://nowhere.test/x"), "")
                get.assert_not_called()


class TestRedirects(unittest.TestCase):
    def test_a_redirect_into_a_private_address_is_refused(self):
        """
        리다이렉트를 requests 에 맡기면 첫 주소만 공인이면 통과한다. 남의 서버가
        302 한 번으로 이 기계를 내부망에 보낼 수 있다.
        """
        with _Fetch(
            [_response(location="http://169.254.169.254/latest/meta-data/"),
             _response("secrets")],
        ) as fetch:
            self.assertEqual(enrich.fetch_body("https://x.test/a"), "")
            self.assertEqual(fetch.get.call_count, 1)
            # 따라가는 일을 requests 에 넘기면 매 단계를 볼 방법이 없다. 위의
            # 결과만으로는 그 차이가 드러나지 않으므로 여기서 못 박는다.
            self.assertFalse(fetch.get.call_args.kwargs["allow_redirects"])

    def test_a_relative_redirect_follows_the_original_host(self):
        """상대 주소로 보내는 곳이 많다. 그대로 검사하면 스킴이 없어 버려진다."""
        with _Fetch([_response(location="/moved"), _response("도착한 글")]) as fetch:
            self.assertEqual(enrich.fetch_body("https://x.test/a"), "도착한 글")
            self.assertEqual(fetch.get.call_args_list[1].args[0], "https://x.test/moved")

    def test_a_redirect_loop_ends(self):
        loop = [_response(location="https://x.test/a") for _ in range(20)]
        with _Fetch(loop) as fetch:
            self.assertEqual(enrich.fetch_body("https://x.test/a"), "")
            self.assertLessEqual(fetch.get.call_count, enrich.MAX_REDIRECTS + 1)


class TestBounds(unittest.TestCase):
    def test_the_body_is_read_up_to_a_limit(self):
        """본문은 외부 입력이다. 통째로 올리면 거대한 페이지 하나에 흔들린다."""
        with _Fetch([_response("글")]) as fetch:
            enrich.fetch_body("https://x.test/a")
        response = fetch.responses[0]
        response.raw.read.assert_called_once_with(
            enrich.MAX_BODY_BYTES, decode_content=True
        )

    def test_the_returned_text_is_capped(self):
        """이 값은 그대로 프롬프트로 흘러간다."""
        with _Fetch([_response("가" * (MAX_TEXT_LENGTH * 3))]):
            self.assertEqual(len(enrich.fetch_body("https://x.test/a")), MAX_TEXT_LENGTH)

    def test_something_that_is_not_text_is_skipped(self):
        with _Fetch([_response("\x00\x01binary", content_type="image/png")]):
            self.assertEqual(enrich.fetch_body("https://x.test/a.png"), "")

    def test_an_error_page_is_not_used_as_the_body(self):
        with _Fetch([_response("<h1>404 Not Found</h1>", status=404)]):
            self.assertEqual(enrich.fetch_body("https://x.test/gone"), "")

    def test_a_network_failure_is_not_raised(self):
        """소재 하나의 본문을 못 읽었다고 매일 도는 자동화가 멈출 이유는 없다."""
        with patch.object(enrich.socket, "getaddrinfo", side_effect=self._public):
            with patch.object(enrich.requests, "get", side_effect=RuntimeError("gone")):
                self.assertEqual(enrich.fetch_body("https://x.test/a"), "")

    @staticmethod
    def _public(*_args, **_kwargs):
        return [(2, 1, 6, "", (PUBLIC_IP, 0))]


class TestGithub(unittest.TestCase):
    def test_a_repository_link_reads_the_readme(self):
        """
        저장소 첫 화면 HTML 은 대부분 화면 장식이다. README 가 곧 그 프로젝트가
        자기를 설명하는 말이다.
        """
        with _Fetch([_response("# thing\n\n무엇을 하는 물건인지")]) as fetch:
            body = enrich.fetch_body("https://github.com/someone/thing")

        self.assertIn("무엇을 하는 물건인지", body)
        self.assertEqual(
            fetch.get.call_args.args[0],
            "https://api.github.com/repos/someone/thing/readme",
        )

    def test_the_readme_is_asked_for_as_text(self):
        """이 헤더가 없으면 GitHub 은 base64 를 담은 JSON 을 준다."""
        with _Fetch([_response("# thing")]) as fetch:
            enrich.fetch_body("https://github.com/someone/thing")
        self.assertEqual(
            fetch.get.call_args.kwargs["headers"]["Accept"], enrich.GITHUB_RAW_ACCEPT
        )

    def test_the_readme_media_type_is_read_as_text(self):
        """
        GitHub 은 위 헤더로 받은 README 를 `application/vnd.github.raw` 로 표시한다.
        마크다운 원문인데도 `text/` 가 아니라, 이름을 적어 두지 않으면 걸러진다.
        """
        readme = _response(
            "# thing\n\n무엇을 하는 물건",
            content_type="application/vnd.github.raw; charset=utf-8",
        )
        with _Fetch([readme]):
            self.assertIn(
                "무엇을 하는 물건", enrich.fetch_body("https://github.com/someone/thing")
            )

    def test_a_repository_without_a_readme_falls_back_to_the_page(self):
        with _Fetch([_response(status=404), _response("<p>페이지 글</p>")]) as fetch:
            self.assertEqual(enrich.fetch_body("https://github.com/someone/thing"), "페이지 글")
            self.assertEqual(
                fetch.get.call_args_list[1].args[0], "https://github.com/someone/thing"
            )

    def test_a_path_that_is_not_a_repository_is_read_as_a_page(self):
        for url in (
            "https://github.com/someone",
            "https://github.com/someone/thing/../../admin",
            "https://github.com/some one/thing",
        ):
            with self.subTest(url=url):
                with _Fetch([_response("페이지")]) as fetch:
                    enrich.fetch_body(url)
                    self.assertNotIn("api.github.com", fetch.get.call_args.args[0])


class TestStripMarkup(unittest.TestCase):
    def test_script_and_style_contents_do_not_survive(self):
        """태그만 지우면 스크립트 본문이 문장인 척 남는다."""
        html = "<p>진짜 글</p><script>var x = 1;</script><style>.a{color:red}</style>"
        stripped = enrich.strip_markup(html)
        self.assertIn("진짜 글", stripped)
        self.assertNotIn("var x", stripped)
        self.assertNotIn("color:red", stripped)

    def test_entities_become_characters(self):
        self.assertEqual(enrich.strip_markup("<p>a &amp; b</p>"), "a & b")

    def test_badge_lines_are_dropped(self):
        """README 맨 위의 배지 줄은 링크와 이미지뿐이다."""
        readme = "[![build](https://img.test/b.svg)](https://ci.test)\n\n무엇을 하는 물건"
        self.assertEqual(enrich.strip_markup(readme).strip(), "무엇을 하는 물건")


class TestWithBody(unittest.TestCase):
    def _item(self, **overrides):
        values = {
            "source": "hackernews",
            "item_id": "42",
            "title": "Show HN: A tiny thing",
            "url": "https://x.test/thing",
        }
        values.update(overrides)
        return SourceItem(**values)

    def test_an_item_that_already_has_text_is_left_alone(self):
        """Ask HN 처럼 본문이 딸려 오는 글이 있다. 다시 읽을 이유가 없다."""
        with patch.object(enrich, "fetch_body") as fetch_body:
            item = self._item(text="글쓴이가 쓴 본문")
            self.assertIs(enrich.with_body(item), item)
            fetch_body.assert_not_called()

    def test_an_item_without_a_link_is_left_alone(self):
        with patch.object(enrich, "fetch_body") as fetch_body:
            item = self._item(url="")
            self.assertIs(enrich.with_body(item), item)
            fetch_body.assert_not_called()

    def test_the_body_is_filled_in(self):
        with patch.object(enrich, "fetch_body", return_value="읽어 온 글"):
            self.assertEqual(enrich.with_body(self._item()).text, "읽어 온 글")

    def test_a_body_that_could_not_be_read_leaves_the_item_usable(self):
        with patch.object(enrich, "fetch_body", return_value=""):
            item = self._item()
            filled = enrich.with_body(item)
            self.assertEqual(filled.text, "")
            self.assertEqual(filled.title, item.title)

    def test_the_read_body_is_normalized_like_any_other_field(self):
        """
        밖에서 읽어 온 글이다. 제어문자가 섞이면 로그와 프롬프트에 그대로 들어가고,
        길이 제한이 빠지면 프롬프트가 통째로 부풀어 오른다.
        """
        hostile = "a\x1b[2Jb " + "가" * (MAX_TEXT_LENGTH * 2)
        with patch.object(enrich, "fetch_body", return_value=hostile):
            text = enrich.with_body(self._item()).text
        self.assertNotIn("\x1b", text)
        self.assertLessEqual(len(text), MAX_TEXT_LENGTH)


class TestUsedWhenWritingCards(unittest.TestCase):
    def test_the_body_reaches_the_card_prompt(self):
        """
        제목만으로 카드를 쓰면 "설명 없음" 같은 장이 나온다. 본문을 읽어 와도
        프롬프트까지 닿지 않으면 아무것도 달라지지 않는다.
        """
        from app.services import cardscript, llm

        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return [
                {"title": f"제목 {i}", "bullets": ["하나"], "narration": "말"}
                for i in range(3)
            ]

        item = SourceItem(
            source="hackernews", item_id="42", title="Show HN: A tiny thing",
            url="https://x.test/thing",
        )
        with patch.object(enrich, "fetch_body", return_value="이 도구가 하는 일"):
            with patch.object(llm, "generate_card_script", side_effect=fake):
                cardscript.build_card_script(item)

        self.assertEqual(captured["body_text"], "이 도구가 하는 일")


if __name__ == "__main__":
    unittest.main()
