"""发布标题降级时识别中日文句界，同时保留英文数字和原有元数据。"""

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import config
from app.controllers.v1 import llm as llm_controller
from app.services import llm


@pytest.mark.parametrize("failure", ["missing_key", "invalid_json", "exception"])
@pytest.mark.parametrize(
    "subject,script,expected",
    [
        ("", "大家好。今天聊聊信用卡。", "大家好。"),
        ("", "こんにちは。今日は旅行の話です。", "こんにちは。"),
        ("", "怎么省钱？今天分享三个方法。", "怎么省钱？"),
        ("", "注意！这里有个小技巧。", "注意！"),
        ("", "本当？一緒に確認しましょう。", "本当？"),
        ("", "注目！新しい機能です。", "注目！"),
        ("", "大家好。 \n今天聊聊信用卡。", "大家好。"),
        ("", "Version 2.0 is ready. Learn more.", "Version 2.0 is ready."),
        ("", "No. 1 tip is simple. Save more.", "No. 1 tip is simple."),
        ("", "Mr. Smith arrives today. Bring a coat.", "Mr. Smith arrives today."),
        ("", "Meet at 10:30 a.m. today. Be early.", "Meet at 10:30 a.m. today."),
        ("", "Fig. 3 shows the trend. See the chart.", "Fig. 3 shows the trend."),
        ("", "1. Save a little each week. Start now.", "1. Save a little each week."),
        ("", "U.S. policy changed. Details follow.", "U.S. policy changed."),
        ("", "My score is 42. Next we discuss savings.", "My score is 42."),
        ("", "I chose option A. Next we discuss savings.", "I chose option A."),
        ("", "Ready? Learn more.", "Ready?"),
        ("", "Welcome! Learn more.", "Welcome!"),
        ("", "没有句号的脚本", "没有句号的脚本"),
        ("", "", ""),
        (" \n ", "大家好。今天聊聊信用卡。", "大家好。"),
        ("信用卡指南", "大家好。今天聊聊信用卡。", "信用卡指南"),
    ],
)
def test_social_title_fallback_sentence_boundaries(failure, subject, script, expected):
    if failure == "missing_key":
        # 不替换响应函数，实际经过无密钥校验及降级逻辑。
        context = patch.object(
            config, "app", {"llm_provider": "openai", "openai_api_key": ""}
        )
    elif failure == "invalid_json":
        context = patch.object(llm, "_generate_response", return_value="not JSON")
    else:
        context = patch.object(
            llm, "_generate_response", side_effect=RuntimeError("provider unavailable")
        )
    with context:
        result = llm.generate_social_metadata(subject, script)

    assert result["title"] == expected
    assert result["caption"] == (script or subject).strip()
    assert result["hashtags"] == ["#shorts", "#viral", "#trending", "#fyp", "#video"]


@pytest.mark.parametrize(
    "platform,limit",
    [("tiktok", 100), ("youtube_shorts", 100), ("instagram_reels", 125), ("facebook_reels", 125)],
)
def test_social_title_fallback_keeps_platform_limits(platform, limit):
    script = "中" * 150 + "。这是第二句。"
    result = llm._fallback_social_metadata("", script, platform)
    assert result["title"] == "中" * limit
    assert result["caption"] == script


@pytest.mark.parametrize(
    "script,expected",
    [("大家好。今天聊聊信用卡。", "大家好。"), ("こんにちは。今日は旅行の話です。", "こんにちは。")],
)
def test_social_metadata_api_missing_key_uses_first_sentence(script, expected):
    app = FastAPI()
    app.include_router(llm_controller.router)
    with (
        patch.object(config, "app", {"llm_provider": "openai", "openai_api_key": ""}),
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/v1/social-metadata",
            json={"video_subject": "", "video_script": script},
        )
    assert response.status_code == 200
    assert response.json()["data"]["title"] == expected
    assert response.json()["data"]["caption"] == script


def test_social_metadata_success_preserves_model_title():
    metadata = {"title": "信用卡。实用指南", "caption": "收藏这些技巧。", "hashtags": ["#生活"]}
    with patch.object(llm, "_generate_response", return_value=json.dumps(metadata)):
        result = llm.generate_social_metadata("", "大家好。今天聊聊信用卡。")
    assert result == metadata
