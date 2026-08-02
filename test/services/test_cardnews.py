"""카드뉴스 렌더링."""

import unittest

from PIL import Image, ImageDraw

from app.services import cardnews
from app.services.cardnews import Card

WHITE = (255, 255, 255)


def _draw():
    return ImageDraw.Draw(Image.new("RGB", (1080, 1920), WHITE))


def _column_has_ink(image, top, bottom):
    """세로 구간 안에 배경이 아닌 픽셀이 있는지."""
    crop = image.crop((0, top, image.width, bottom))
    return any(pixel != WHITE for pixel in crop.getdata())


class TestCardBounds(unittest.TestCase):
    """카드에 실리는 글은 LLM 과 외부 소스에서 온다."""

    def test_a_card_caps_its_text(self):
        card = Card(
            title="가" * 5000,
            body=tuple(f"항목 {i}" for i in range(50)),
            footer="나" * 5000,
        )
        self.assertEqual(len(card.title), cardnews.MAX_TITLE_LENGTH)
        self.assertEqual(len(card.body), cardnews.MAX_BODY_LINES)
        self.assertEqual(len(card.footer), cardnews.MAX_FOOTER_LENGTH)

    def test_control_characters_do_not_reach_the_canvas(self):
        """제어문자는 글꼴에 따라 두부로 그려지거나 줄을 깨뜨린다."""
        self.assertNotIn("\x1b", Card(title="a\x1b[2Jb").title)


class TestWrapping(unittest.TestCase):
    def test_a_long_run_without_spaces_is_broken(self):
        """
        한국어는 띄어쓰기 없이 길게 이어지는 경우가 흔하다. 공백만 보고 끊으면
        줄이 화면 밖으로 나간다.
        """
        draw = _draw()
        font = cardnews._font(cardnews.BODY_FONT, 40)
        lines = cardnews.wrap_text(draw, "가" * 200, font, 800)

        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(int(draw.textlength(line, font=font)), 800)

    def test_words_are_packed_until_the_line_is_full(self):
        """
        폭이 남는데도 한 줄에 한 단어씩 내려보내면, 카드가 세로로 길어져 아래
        내용이 밀려난다. 들어갈 만큼은 채워야 한다.
        """
        draw = _draw()
        font = cardnews._font(cardnews.BODY_FONT, 40)
        # 두 단어는 들어가고 세 단어는 넘치는 폭을 만든다.
        width = int(draw.textlength("하나 둘", font=font)) + 4
        self.assertLess(int(draw.textlength("하나 둘 셋", font=font)), 10_000)

        lines = cardnews.wrap_text(draw, "하나 둘 셋 넷", font, width)

        self.assertEqual(lines, ["하나 둘", "셋 넷"])


class TestFooter(unittest.TestCase):
    def test_an_overlong_footer_ends_with_an_ellipsis(self):
        """
        잘라 내기만 하면 `Hacker News · 206 points ·` 처럼 구분자만 남아, 뒤에
        뭔가 있었다는 사실조차 보이지 않는다.
        """
        draw = _draw()
        font = cardnews._font(cardnews.BODY_FONT, 40)
        fitted = cardnews.fit_single_line(
            draw, "Hacker News · 206 points · github.com/very/long/path", font, 400
        )

        self.assertTrue(fitted.endswith("…"))
        self.assertFalse(fitted.rstrip("…").endswith("·"))
        self.assertLessEqual(int(draw.textlength(fitted, font=font)), 400)

    def test_a_short_footer_is_left_alone(self):
        draw = _draw()
        font = cardnews._font(cardnews.BODY_FONT, 40)
        self.assertEqual(cardnews.fit_single_line(draw, "HN · 206", font, 800), "HN · 206")


class TestLayout(unittest.TestCase):
    def test_nothing_is_drawn_in_the_shorts_safe_area(self):
        """
        유튜브 쇼츠는 화면 아래쪽에 제목·채널명·버튼을 얹는다. 그 자리에 글을 두면
        가려진다.
        """
        card = Card(
            index_label="01",
            title="제목이 아주 길어서 여러 줄로 접히는 경우를 보기 위한 문장입니다",
            body=tuple("본문이 길게 이어지는 줄입니다" for _ in range(5)),
            footer="Hacker News · 206 points",
        )
        image = cardnews.render_card(card)
        safe_top = image.height - int(image.height * cardnews.BOTTOM_SAFE_RATIO)

        self.assertFalse(_column_has_ink(image, safe_top, image.height))

    def test_the_card_actually_has_text_on_it(self):
        """안전 영역만 비면 되는 게 아니라, 위쪽에는 글이 있어야 한다."""
        image = cardnews.render_card(Card(title="제목"))
        self.assertTrue(_column_has_ink(image, 0, image.height // 2))


class TestClip(unittest.TestCase):
    def test_each_card_gets_its_own_duration(self):
        """카드가 화면에 머무는 시간은 그 카드 나레이션 길이에서 나온다."""
        clip = cardnews.build_card_news_clip(
            [Card(title="하나"), Card(title="둘")], [2.0, 5.0]
        )
        try:
            self.assertAlmostEqual(clip.duration, 7.0)
        finally:
            clip.close()

    def test_a_missing_duration_reuses_the_last_one(self):
        """카드가 아예 안 나오는 것보다 낫다."""
        clip = cardnews.build_card_news_clip(
            [Card(title="하나"), Card(title="둘"), Card(title="셋")], [2.0]
        )
        try:
            self.assertAlmostEqual(clip.duration, 6.0)
        finally:
            clip.close()

    def test_a_card_never_flashes_by(self):
        """읽을 시간이 없는 카드는 없는 것과 같다."""
        clip = cardnews.build_card_news_clip([Card(title="하나")], [0.0])
        try:
            self.assertGreaterEqual(clip.duration, cardnews.MIN_CARD_SECONDS)
        finally:
            clip.close()

    def test_a_broken_duration_falls_back_instead_of_raising(self):
        """
        이 값은 나레이션 길이 계산에서 나온다. 0 이나 NaN 이 섞일 수 있고,
        그대로 넘기면 읽을 수 없는 카드나 끝나지 않는 렌더링이 된다.
        """
        for broken in (float("inf"), float("nan"), None, "삼초", -5):
            with self.subTest(duration=broken):
                clip = cardnews.build_card_news_clip([Card(title="하나")], [broken])
                try:
                    self.assertTrue(0 < clip.duration <= cardnews.MAX_CARD_SECONDS)
                finally:
                    clip.close()

    def test_an_absurd_duration_is_capped(self):
        """카드 한 장이 한 시간이면 영상이 아니라 정지 화면이다."""
        clip = cardnews.build_card_news_clip([Card(title="하나")], [100_000])
        try:
            self.assertEqual(clip.duration, cardnews.MAX_CARD_SECONDS)
        finally:
            clip.close()

    def test_an_endless_stream_of_cards_is_cut_off_before_it_is_built(self):
        """
        먼저 목록으로 만들면 상한이 걸리기도 전에 메모리를 태운다.
        """
        from itertools import count

        def forever():
            for index in count():
                yield Card(title=f"카드 {index}")

        clip = cardnews.build_card_news_clip(forever(), [1.0])
        try:
            self.assertEqual(clip.duration, float(cardnews.MAX_CARDS))
        finally:
            clip.close()

    def test_an_endless_body_is_cut_off_too(self):
        """본문 줄도 같은 경로로 들어온다."""
        from itertools import count

        card = Card(title="제목", body=(f"줄 {i}" for i in count()))
        self.assertEqual(len(card.body), cardnews.MAX_BODY_LINES)

    def test_no_cards_is_an_error(self):
        with self.assertRaises(ValueError):
            cardnews.build_card_news_clip([], [1.0])


if __name__ == "__main__":
    unittest.main()
