from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services.trends.models import ScoredTopic, SourceStatus, TrendSnapshot


WEBUI_MAIN = Path(__file__).parents[2] / "webui" / "Main.py"


def snapshot():
    topic = ScoredTopic(
        "Ocean mystery",
        "emerging",
        71,
        {"listenability": 30, "curiosity": 15},
        "inferred",
        (),
        ("Why the deep ocean remains unknown",),
    )
    punjabi = ScoredTopic("ਪੰਜਾਬ", "emerging", 24, {}, "inferred", (), ())
    tamil = ScoredTopic("வெள்ளம்", "emerging", 24, {}, "inferred", (), ())
    topics = (topic, punjabi, tamil)
    return TrendSnapshot(
        datetime(2026, 9, 2, tzinfo=UTC),
        topics,
        {"google_trends": SourceStatus.AVAILABLE},
        {
            "youtube_shorts": topics,
            "tiktok": topics,
            "instagram_reels": topics,
        },
    )


def run_trends_app():
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
    app.session_state["ui_language"] = "en"
    app.session_state["nav_view"] = "trends"
    app.run()
    return app


def test_page_has_separate_platform_tabs():
    with (
        patch.object(config, "app", dict(config.app)),
        patch.object(config, "ui", dict(config.ui, language="en")),
        patch.object(config, "try_save_config", return_value=True),
        patch(
            "app.services.trends.storage.TrendStore.load_latest",
            return_value=snapshot(),
        ),
    ):
        app = run_trends_app()

    assert [str(item.value) for item in app.exception] == []
    assert [tab.label for tab in app.tabs[:3]] == [
        "YouTube Shorts",
        "TikTok",
        "Instagram Reels",
    ]


def test_use_topic_fills_studio_without_generation():
    with (
        patch.object(config, "app", dict(config.app)),
        patch.object(config, "ui", dict(config.ui, language="en")),
        patch.object(config, "try_save_config", return_value=True),
        patch(
            "app.services.trends.storage.TrendStore.load_latest",
            return_value=snapshot(),
        ),
        patch("app.services.webui_task.submit_generation") as start,
    ):
        app = run_trends_app()
        next(
            button
            for button in app.button
            if button.key == "trend_use_youtube_shorts_ocean-mystery"
        ).click().run()

        assert app.session_state["nav_view"] == "studio"
        assert app.session_state["video_subject"] == "Ocean mystery"
        assert app.session_state["video_script_prompt"]
        start.assert_not_called()
