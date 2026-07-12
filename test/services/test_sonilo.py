import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import sonilo


def _event(**kwargs):
    return json.dumps(kwargs)


def _chunk(data: bytes, stream_index=0):
    return _event(
        type="audio_chunk",
        data=base64.b64encode(data).decode("ascii"),
        stream_index=stream_index,
    )


def _mock_streaming_response(lines, status_code=200, body=b""):
    """构造 `with requests.post(...) as response` 语义下的流式响应 mock。"""
    response = MagicMock()
    response.status_code = status_code
    response.content = body
    response.iter_lines.return_value = list(lines)
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestSoniloService(unittest.TestCase):
    """
    Sonilo 集成是完全 opt-in 的：未配置 sonilo_api_key 时所有函数都必须是
    无副作用的 no-op，行为与不接入 Sonilo 完全一致。任何 API 失败（超时、
    HTTP 错误、流中断）都必须降级为“无背景音乐”，绝不允许中断成片任务。
    这些用例全部 mock requests，CI 不依赖真实网络或真实 API key。
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app.pop("sonilo_api_key", None)
        config.app.pop("sonilo_base_url", None)
        config.app.pop("sonilo_timeout_seconds", None)
        config.app.pop("sonilo_bgm_prompt", None)
        self._env_patcher = patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop("SONILO_API_KEY", None)

        self._temp_dir = tempfile.TemporaryDirectory()
        self.video_path = os.path.join(self._temp_dir.name, "combined-1.mp4")
        with open(self.video_path, "wb") as f:
            f.write(b"fake video bytes")
        self.save_path = os.path.join(self._temp_dir.name, "final-1-sonilo-bgm.m4a")

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self._env_patcher.stop()
        self._temp_dir.cleanup()

    # ---------------- disabled / no-op behavior ----------------

    def test_disabled_when_no_api_key(self):
        self.assertFalse(sonilo.is_enabled())
        with patch("app.services.sonilo.requests.post") as post:
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")
        post.assert_not_called()
        self.assertFalse(os.path.exists(self.save_path))

    def test_env_var_enables_as_fallback(self):
        os.environ["SONILO_API_KEY"] = " sk_env_test "
        self.assertTrue(sonilo.is_enabled())
        self.assertEqual(sonilo.get_api_key(), "sk_env_test")

    def test_config_key_takes_priority_over_env(self):
        config.app["sonilo_api_key"] = "sk_config"
        os.environ["SONILO_API_KEY"] = "sk_env"
        self.assertEqual(sonilo.get_api_key(), "sk_config")

    # ---------------- local pre-checks (no upload) ----------------

    def test_skips_video_longer_than_api_limit(self):
        config.app["sonilo_api_key"] = "sk_test"
        with patch("app.services.sonilo.requests.post") as post:
            result = sonilo.generate_bgm(
                self.video_path,
                self.save_path,
                video_duration=sonilo.MAX_VIDEO_DURATION_SECONDS + 1,
            )
        self.assertEqual(result, "")
        post.assert_not_called()

    def test_skips_missing_video_file(self):
        config.app["sonilo_api_key"] = "sk_test"
        with patch("app.services.sonilo.requests.post") as post:
            result = sonilo.generate_bgm(
                os.path.join(self._temp_dir.name, "missing.mp4"),
                self.save_path,
                60,
            )
        self.assertEqual(result, "")
        post.assert_not_called()

    # ---------------- successful generation ----------------

    def test_generates_bgm_from_ndjson_stream(self):
        config.app["sonilo_api_key"] = "sk_test"
        lines = [
            _event(type="stage_start", stage="analyze"),
            "not-json garbage line",
            _chunk(b"first-"),
            _event(type="title", data="Matched Track"),
            _chunk(b"second"),
            _event(type="complete"),
        ]
        response = _mock_streaming_response(lines)
        with patch(
            "app.services.sonilo.requests.post", return_value=response
        ) as post:
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)

        self.assertEqual(result, self.save_path)
        with open(self.save_path, "rb") as f:
            self.assertEqual(f.read(), b"first-second")

        _, kwargs = post.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer sk_test"
        )
        self.assertTrue(kwargs["stream"])
        self.assertIn("video", kwargs["files"])
        # 未配置风格提示时不携带 prompt 表单字段。
        self.assertIsNone(kwargs["data"])

    def test_optional_style_prompt_is_sent(self):
        config.app["sonilo_api_key"] = "sk_test"
        config.app["sonilo_bgm_prompt"] = "calm lofi beat"
        response = _mock_streaming_response([_chunk(b"x"), _event(type="complete")])
        with patch(
            "app.services.sonilo.requests.post", return_value=response
        ) as post:
            sonilo.generate_bgm(self.video_path, self.save_path, 60)
        _, kwargs = post.call_args
        self.assertEqual(kwargs["data"], {"prompt": "calm lofi beat"})

    def test_keeps_first_audio_stream_by_index(self):
        config.app["sonilo_api_key"] = "sk_test"
        lines = [
            _chunk(b"alt-take", stream_index=1),
            _chunk(b"main-take", stream_index=0),
            _event(type="complete"),
        ]
        response = _mock_streaming_response(lines)
        with patch("app.services.sonilo.requests.post", return_value=response):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, self.save_path)
        with open(self.save_path, "rb") as f:
            self.assertEqual(f.read(), b"main-take")

    # ---------------- failure degradation (never raise) ----------------

    def test_error_event_falls_back_without_bgm(self):
        config.app["sonilo_api_key"] = "sk_test"
        lines = [_chunk(b"partial"), _event(type="error", message="gpu on fire")]
        response = _mock_streaming_response(lines)
        with patch("app.services.sonilo.requests.post", return_value=response):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")
        self.assertFalse(os.path.exists(self.save_path))

    def test_http_error_falls_back_without_bgm(self):
        config.app["sonilo_api_key"] = "sk_test"
        response = _mock_streaming_response(
            [], status_code=401, body=b'{"detail": "bad key"}'
        )
        with patch("app.services.sonilo.requests.post", return_value=response):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")

    def test_timeout_falls_back_without_bgm(self):
        config.app["sonilo_api_key"] = "sk_test"
        with patch(
            "app.services.sonilo.requests.post",
            side_effect=requests.exceptions.ConnectTimeout("boom"),
        ):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")

    def test_connection_error_falls_back_without_bgm(self):
        config.app["sonilo_api_key"] = "sk_test"
        with patch(
            "app.services.sonilo.requests.post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")

    def test_stream_without_complete_event_falls_back(self):
        config.app["sonilo_api_key"] = "sk_test"
        response = _mock_streaming_response([_chunk(b"partial")])
        with patch("app.services.sonilo.requests.post", return_value=response):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")

    def test_completed_stream_without_audio_falls_back(self):
        config.app["sonilo_api_key"] = "sk_test"
        response = _mock_streaming_response([_event(type="complete")])
        with patch("app.services.sonilo.requests.post", return_value=response):
            result = sonilo.generate_bgm(self.video_path, self.save_path, 60)
        self.assertEqual(result, "")

    def test_custom_base_url_and_timeout_are_used(self):
        config.app["sonilo_api_key"] = "sk_test"
        config.app["sonilo_base_url"] = "https://sonilo.example.com/"
        config.app["sonilo_timeout_seconds"] = 42
        response = _mock_streaming_response([_chunk(b"x"), _event(type="complete")])
        with patch(
            "app.services.sonilo.requests.post", return_value=response
        ) as post:
            sonilo.generate_bgm(self.video_path, self.save_path, 60)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://sonilo.example.com/v1/video-to-music")
        self.assertEqual(kwargs["timeout"][1], 42.0)


if __name__ == "__main__":
    unittest.main()
