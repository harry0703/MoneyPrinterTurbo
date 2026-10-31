"""组合符必须附着于保留的字符，不能由已删除的 emoji 留下空标签。"""

import json
import unicodedata
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.asgi import app
from app.services import llm


@pytest.mark.parametrize(
    "tag",
    [
        "#भारत",
        "#বাংলা",
        "#தமிழ்",
        "#ท่องเที่ยว",
        "#سَلَام",
        "#שָׁלוֹם",
        unicodedata.normalize("NFD", "#việtnam"),
        "#邊\ufe00",
        "#邊\U000e0100",
        "#ᠠ\u180b",
    ],
)
def test_hashtag_keeps_marks_attached_to_retained_letters(tag):
    """保留真实语言的元音、声调及 CJK 字形变体，不全局删除 Mark 字符。"""
    assert llm._normalize_hashtags([tag], count=5) == [tag]


@pytest.mark.parametrize(
    "tag", ["#☕️", "#*️⃣", "#👩‍💻️", "#\u0301", "#\u093e", "#\ufe0f", "#\U000e0100"]
)
def test_hashtag_drops_marks_without_a_retained_base(tag):
    assert llm._normalize_hashtags([tag], count=5) == []


@pytest.mark.parametrize(
    "decorated", ["#coffee☕️", "#☕️coffee", "#co☕️ffee", "#coffee!\u0301"]
)
def test_removed_characters_do_not_leave_marks_that_break_deduplication(decorated):
    assert llm._normalize_hashtags([decorated, "#coffee"], count=3) == ["#coffee"]


def test_emoji_only_hashtags_do_not_consume_the_result_limit():
    assert llm._normalize_hashtags(
        ["#☕️", "#Travel", "#Coffee", "#Shorts"], count=3
    ) == ["#Travel", "#Coffee", "#Shorts"]


@pytest.mark.parametrize(
    "decorated,plain",
    [
        ("#1️⃣", "#1"),
        ("#top1️⃣", "#top1"),
        ("#1\u20e3", "#1"),
        ("#1\ufe0e", "#1"),
        ("#ℹ️", "#ℹ"),
    ],
)
def test_emoji_marks_after_retained_digits_or_letters_do_not_break_deduplication(
    decorated, plain
):
    assert llm._normalize_hashtags([decorated, plain], count=3) == [plain]


def test_string_hashtags_keep_language_marks_after_discarding_emoji():
    assert llm._normalize_hashtags("#☕️ #भारत, #বাংলা #தமிழ் #ท่องเที่ยว", count=5) == [
        "#भारत",
        "#বাংলা",
        "#தமிழ்",
        "#ท่องเที่ยว",
    ]


@pytest.mark.parametrize("platform", list(llm.SOCIAL_PLATFORMS))
def test_social_metadata_api_uses_cleaned_tags_without_displacing_valid_ones(platform):
    """固定模型输出，真实运行 API 的解析、清洗、去重和数量限制。"""
    response_text = json.dumps(
        {
            "title": "旅行",
            "caption": "清晨旅行。",
            "hashtags": [
                "#☕️",
                "#coffee☕️",
                "#coffee",
                "#भारत",
                "#বাংলা",
                "#தமிழ்",
                "#ท่องเที่ยว",
            ],
        },
        ensure_ascii=False,
    )
    with patch.object(llm, "_generate_response", return_value=response_text):
        response = TestClient(app).post(
            "/api/v1/social-metadata",
            json={"video_subject": "旅行", "platform": platform},
        )

    assert response.status_code == 200
    expected = ["#coffee", "#भारत", "#বাংলা", "#தமிழ்", "#ท่องเที่ยว"]
    assert (
        response.json()["data"]["hashtags"]
        == expected[: llm.SOCIAL_PLATFORMS[platform]["hashtag_count"]]
    )


def test_keycap_tags_do_not_displace_other_youtube_tags():
    response_text = json.dumps(
        {
            "title": "旅行",
            "caption": "收藏旅行技巧。",
            "hashtags": ["#1️⃣", "#1", "#Travel", "#Coffee"],
        },
        ensure_ascii=False,
    )
    with patch.object(llm, "_generate_response", return_value=response_text):
        response = TestClient(app).post(
            "/api/v1/social-metadata",
            json={"video_subject": "旅行", "platform": "youtube_shorts"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["hashtags"] == ["#1", "#Travel", "#Coffee"]
