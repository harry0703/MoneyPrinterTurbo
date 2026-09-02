import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import webhook_notifier


class TestWebhookNotifier(unittest.TestCase):
    def _payload_kwargs(self, **overrides):
        kwargs = dict(
            task_id="task-1",
            video_id="vid-1",
            url="https://www.youtube.com/watch?v=vid-1",
            title="Title",
            description="Description",
            tags=["a", "b"],
            privacy_status="public",
            video_subject="Subject",
            video_language="pt-BR",
        )
        kwargs.update(overrides)
        return kwargs

    @patch("app.services.webhook_notifier.requests.post")
    @patch("app.services.webhook_notifier.config")
    def test_skips_when_webhook_url_not_configured(self, mock_config, mock_post):
        mock_config.app = {"youtube_publish_webhook_url": ""}

        webhook_notifier.notify_video_published(**self._payload_kwargs())

        mock_post.assert_not_called()

    @patch("app.services.webhook_notifier.requests.post")
    @patch("app.services.webhook_notifier.config")
    def test_posts_expected_payload_when_configured(self, mock_config, mock_post):
        mock_config.app = {
            "youtube_publish_webhook_url": "https://n8n.example/webhook/money-printer"
        }
        mock_post.return_value = MagicMock(status_code=200)

        webhook_notifier.notify_video_published(**self._payload_kwargs())

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], "https://n8n.example/webhook/money-printer")
        self.assertEqual(call_kwargs["timeout"], webhook_notifier.WEBHOOK_TIMEOUT_SECONDS)
        self.assertEqual(
            call_kwargs["json"],
            {
                "event": "video.published",
                "platform": "youtube",
                "task_id": "task-1",
                "video_id": "vid-1",
                "url": "https://www.youtube.com/watch?v=vid-1",
                "title": "Title",
                "description": "Description",
                "tags": ["a", "b"],
                "privacy_status": "public",
                "subject": "Subject",
                "language": "pt-BR",
                "success": True,
            },
        )

    @patch("app.services.webhook_notifier.requests.post")
    @patch("app.services.webhook_notifier.config")
    def test_never_raises_on_request_failure(self, mock_config, mock_post):
        mock_config.app = {
            "youtube_publish_webhook_url": "https://n8n.example/webhook/money-printer"
        }
        mock_post.side_effect = ConnectionError("boom")

        try:
            webhook_notifier.notify_video_published(**self._payload_kwargs())
        except Exception as exc:  # pragma: no cover - test fails via assertion below
            self.fail(f"notify_video_published raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
