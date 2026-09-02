import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, ofox, state as sm, task as task_service


class TestOFoxService(unittest.TestCase):
    def setUp(self):
        self.original_app = dict(config.app)
        self.original_proxy = dict(config.proxy)
        config.app.update(
            {
                "ofox_api_key": "ofox-test-key",
                "ofox_text_to_video_model": ofox.DEFAULT_MODEL_ID,
                "ofox_base_url": ofox.DEFAULT_BASE_URL,
            }
        )
        config.proxy.clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app)
        config.proxy.clear()
        config.proxy.update(self.original_proxy)

    @staticmethod
    def _response(payload, status_code=200):
        return SimpleNamespace(status_code=status_code, json=lambda: payload)

    def test_api_key_prefers_config_then_provider_specific_environment_name(self):
        with patch.dict(
            os.environ,
            {"OFOX_API_KEY": "env-key"},
            clear=False,
        ):
            self.assertEqual(ofox.get_api_key(), "ofox-test-key")
            config.app["ofox_api_key"] = ""
            self.assertEqual(ofox.get_api_key(), "env-key")
            os.environ["OFOX_API_KEY"] = ""
            self.assertEqual(ofox.get_api_key(), "")

    def test_missing_api_key_fails_before_submission(self):
        config.app["ofox_api_key"] = ""
        with (
            patch.dict(os.environ, {"OFOX_API_KEY": ""}, clear=False),
            patch.object(ofox.requests, "post") as post,
        ):
            with self.assertRaises(ofox.OFoxError):
                ofox.generate_videos("sunrise", 5)
        post.assert_not_called()

    def test_empty_search_term_fails_before_paid_submission(self):
        for invalid in ("", "   ", None, 0, False):
            with self.subTest(invalid=invalid):
                with patch.object(ofox.requests, "post") as post:
                    with self.assertRaises(ofox.OFoxError) as raised:
                        ofox.generate_videos(invalid, 5)

                self.assertIn("search term must not be empty", str(raised.exception))
                post.assert_not_called()

    def test_search_term_is_trimmed_consistently_in_request_and_source_record(self):
        submit = self._response({"id": "vid-trimmed", "status": "queued"}, 202)
        completed = self._response(
            {
                "id": "vid-trimmed",
                "status": "completed",
                "unsigned_urls": ["https://cdn.example.com/trimmed.mp4"],
            }
        )
        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            result = ofox.generate_videos("  smart home  ", 5)

        self.assertEqual(post.call_args.kwargs["json"]["prompt"], "smart home")
        self.assertEqual(result[0].source_info["search_term"], "smart home")

    def test_submit_poll_and_parse_successful_video(self):
        submit = self._response({"id": "vid-123", "status": "queued"}, 202)
        polls = [
            self._response({"id": "vid-123", "status": "in_progress"}),
            self._response(
                {
                    "id": "vid-123",
                    "status": "completed",
                    "unsigned_urls": ["https://cdn.example.com/video.mp4?sig=abc"],
                    "usage": {"video_seconds": 5, "video_cost": "0.5"},
                }
            ),
        ]

        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(ofox.requests, "get", side_effect=polls) as get,
            patch.object(ofox.time, "sleep") as sleep,
        ):
            result = ofox.generate_videos(
                "sunrise over mountains",
                minimum_duration=5,
                video_aspect=VideoAspect.portrait,
            )

        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item.provider, "ofox")
        self.assertEqual(item.url, "https://cdn.example.com/video.mp4?sig=abc")
        self.assertEqual(item.duration, 5)
        self.assertEqual(item.source_info["asset_id"], "vid-123")

        self.assertEqual(post.call_args.args[0], f"{ofox.DEFAULT_BASE_URL}/videos")
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer ofox-test-key",
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "model": ofox.DEFAULT_MODEL_ID,
                "prompt": "sunrise over mountains",
                "duration": 5,
                "resolution": "720p",
                "aspect_ratio": "9:16",
                "provider": {"type": ofox.DEFAULT_PROVIDER_TYPE},
            },
        )
        self.assertEqual(get.call_count, 2)
        self.assertTrue(
            all("/videos/vid-123" in call.args[0] for call in get.call_args_list)
        )
        sleep.assert_called_once_with(ofox.DEFAULT_POLL_INTERVAL_SECONDS)

    def test_resolution_defaults_only_when_blank_and_passes_configured_value(self):
        config.app.pop("ofox_resolution", None)
        self.assertEqual(ofox._resolution(), ofox.DEFAULT_RESOLUTION)

        config.app["ofox_resolution"] = "   "
        self.assertEqual(ofox._resolution(), ofox.DEFAULT_RESOLUTION)

        # 分辨率白名单随远端模型目录变化，本地不做校验；配置值原样提交，
        # 由服务端按模型给出明确的 400 拒绝（不创建付费任务）。
        config.app["ofox_resolution"] = " 480p "
        self.assertEqual(ofox._resolution(), "480p")

    def test_provider_pinning_defaults_to_byteplus_and_stays_configurable(self):
        # 未配置时默认钉定国际厂商 byteplus（内容政策一致、路由可预期）。
        submit = self._response({"id": "vid-route", "status": "queued"}, 202)
        completed = self._response(
            {
                "id": "vid-route",
                "status": "completed",
                "unsigned_urls": ["https://cdn.example.com/route.mp4"],
            }
        )
        config.app.pop("ofox_provider", None)
        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            ofox.generate_videos("sunrise", 5)
        self.assertEqual(
            post.call_args.kwargs["json"]["provider"], {"type": "byteplus"}
        )

        # None 视同未配置（配置解析异常时的兜底），仍走默认。
        config.app["ofox_provider"] = None
        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            ofox.generate_videos("sunrise", 5)
        self.assertEqual(
            post.call_args.kwargs["json"]["provider"], {"type": "byteplus"}
        )

        # 显式配置为空字符串 = 不钉定，交回网关按权重自动分发。
        for blank in ("", "   "):
            with self.subTest(blank=blank):
                config.app["ofox_provider"] = blank
                with (
                    patch.object(ofox.requests, "post", return_value=submit) as post,
                    patch.object(ofox.requests, "get", return_value=completed),
                ):
                    ofox.generate_videos("sunrise", 5)
                self.assertNotIn("provider", post.call_args.kwargs["json"])

        # 配置其它厂商名则钉定那一家；非法厂商名由服务端以 400
        # invalid_provider_type 拒绝（不创建付费任务），走常规 4xx 路径。
        config.app["ofox_provider"] = " volcengine "
        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            ofox.generate_videos("sunrise", 5)
        self.assertEqual(
            post.call_args.kwargs["json"]["provider"], {"type": "volcengine"}
        )

    def test_server_rejected_resolution_raises_clear_error_without_polling(self):
        config.app["ofox_resolution"] = "1080p"
        rejected = self._response(
            {
                "error": {
                    "code": "unsupported_parameter",
                    "message": 'resolution "1080p" not supported; allowed: [480p 720p]',
                }
            },
            status_code=400,
        )
        with (
            patch.object(ofox.requests, "post", return_value=rejected),
            patch.object(ofox.requests, "get") as get,
        ):
            with self.assertRaises(ofox.OFoxError) as raised:
                ofox.generate_videos("city", 5)

        get.assert_not_called()
        self.assertIn("not supported", str(raised.exception))

    def test_configured_model_base_url_and_duration_bounds_are_applied(self):
        config.app.update(
            {
                "ofox_text_to_video_model": "alibaba/wan-2.7",
                "ofox_base_url": "https://ofox.example.test/v1/",
                "ofox_min_duration": 2,
                "ofox_max_duration": 8,
                "ofox_resolution": "480p",
            }
        )
        submit = self._response({"id": "vid-bounds", "status": "queued"}, 202)
        completed = self._response(
            {
                "id": "vid-bounds",
                "status": "completed",
                "unsigned_urls": ["https://cdn.example.com/bounds.mp4"],
            }
        )
        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            result = ofox.generate_videos("city", 99, VideoAspect.landscape)

        self.assertEqual(result[0].duration, 8)
        self.assertEqual(post.call_args.args[0], "https://ofox.example.test/v1/videos")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "alibaba/wan-2.7")
        self.assertEqual(payload["duration"], 8)
        self.assertEqual(payload["resolution"], "480p")
        self.assertEqual(payload["aspect_ratio"], "16:9")

    def test_rejected_submission_raises_clear_error_without_polling(self):
        rejected = self._response(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "rejected ofox-test-key",
                }
            },
            status_code=400,
        )
        with (
            patch.object(ofox.requests, "post", return_value=rejected),
            patch.object(ofox.requests, "get") as get,
        ):
            with self.assertRaises(ofox.OFoxError) as raised:
                ofox.generate_videos("unsafe", 5)

        get.assert_not_called()
        self.assertNotIn("ofox-test-key", str(raised.exception))

    def test_submission_network_or_server_error_is_unconfirmed_and_not_retried(self):
        for side_effect, response in (
            (requests.exceptions.ConnectionError("offline"), None),
            (None, self._response({"message": "bad gateway"}, status_code=502)),
        ):
            with self.subTest(response=response):
                with patch.object(
                    ofox.requests,
                    "post",
                    side_effect=side_effect,
                    return_value=response,
                ) as post:
                    with self.assertRaises(ofox.OFoxUnconfirmedTaskError):
                        ofox.generate_videos("sunrise", 5)
                self.assertEqual(post.call_count, 1)

    def test_pending_status_is_active_and_polling_continues(self):
        # 官方成功路径为 pending → queued → in_progress → completed；首次轮询
        # 拿到 pending 属于正常在途状态，不能当作未知状态终止任务。
        submit = self._response({"id": "vid-pending", "status": "queued"}, 202)
        polls = [
            self._response({"id": "vid-pending", "status": "pending"}),
            self._response({"id": "vid-pending", "status": "queued"}),
            self._response({"id": "vid-pending", "status": "in_progress"}),
            self._response(
                {
                    "id": "vid-pending",
                    "status": "completed",
                    "unsigned_urls": ["https://cdn.example.com/pending.mp4"],
                }
            ),
        ]
        with (
            patch.object(ofox.requests, "post", return_value=submit),
            patch.object(ofox.requests, "get", side_effect=polls) as get,
            patch.object(ofox.time, "sleep"),
        ):
            result = ofox.generate_videos("sunrise", 5)

        self.assertEqual(len(result), 1)
        self.assertEqual(get.call_count, 4)

    def test_mirror_urls_are_preferred_over_unsigned_urls(self):
        submit = self._response({"id": "vid-mirror", "status": "queued"}, 202)
        completed = self._response(
            {
                "id": "vid-mirror",
                "status": "completed",
                "mirror_urls": ["https://cdn.ofox.ai/videos/vid-mirror.mp4?sig=abc"],
                "unsigned_urls": ["https://upstream.example.com/tmp.mp4"],
            }
        )
        with (
            patch.object(ofox.requests, "post", return_value=submit),
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            result = ofox.generate_videos("sunrise", 5)

        self.assertEqual(
            result[0].url, "https://cdn.ofox.ai/videos/vid-mirror.mp4?sig=abc"
        )

    def test_missing_or_invalid_mirror_urls_fall_back_to_unsigned_urls(self):
        # mirror_urls 仅在上游开启镜像时返回；缺失、为空或不含合法直链时都
        # 必须回退到 unsigned_urls，不能让任务失败。
        for mirror in (None, [], ["not-a-url", 123]):
            with self.subTest(mirror=mirror):
                submit = self._response({"id": "vid-fallback", "status": "queued"}, 202)
                body = {
                    "id": "vid-fallback",
                    "status": "completed",
                    "unsigned_urls": ["https://upstream.example.com/ok.mp4"],
                }
                if mirror is not None:
                    body["mirror_urls"] = mirror
                completed = self._response(body)
                with (
                    patch.object(ofox.requests, "post", return_value=submit),
                    patch.object(ofox.requests, "get", return_value=completed),
                ):
                    result = ofox.generate_videos("sunrise", 5)

                self.assertEqual(result[0].url, "https://upstream.example.com/ok.mp4")

    def test_poll_retries_transient_errors_on_same_task(self):
        submit = self._response({"id": "vid-retry", "status": "queued"}, 202)
        rate_limited = self._response({}, status_code=429)
        completed = self._response(
            {
                "id": "vid-retry",
                "status": "completed",
                "unsigned_urls": ["https://cdn.example.com/retry.mp4"],
            }
        )
        with (
            patch.object(ofox.requests, "post", return_value=submit) as post,
            patch.object(
                ofox.requests,
                "get",
                side_effect=[
                    rate_limited,
                    requests.exceptions.ConnectionError("offline"),
                    completed,
                ],
            ) as get,
            patch.object(ofox.time, "sleep") as sleep,
        ):
            result = ofox.generate_videos("sunrise", 5)

        self.assertEqual(len(result), 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    def test_poll_retry_exhaustion_preserves_remote_task_id(self):
        submit = self._response({"id": "vid-stuck", "status": "queued"}, 202)
        with (
            patch.object(ofox.requests, "post", return_value=submit),
            patch.object(
                ofox.requests,
                "get",
                side_effect=requests.exceptions.ConnectionError("offline"),
            ) as get,
            patch.object(ofox.time, "sleep"),
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                ofox.generate_videos("sunrise", 5)

        self.assertEqual(raised.exception.task_id, "vid-stuck")
        self.assertEqual(get.call_count, ofox.MAX_POLL_RETRIES + 1)

    def test_running_task_timeout_preserves_remote_task_id(self):
        submit = self._response({"id": "vid-running", "status": "queued"}, 202)
        running = self._response({"id": "vid-running", "status": "in_progress"})
        clock = iter([0.0, 1.0, ofox.DEFAULT_RUN_TIMEOUT_SECONDS + 1])
        with (
            patch.object(ofox.requests, "post", return_value=submit),
            patch.object(ofox.requests, "get", return_value=running),
            patch.object(ofox.time, "monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                ofox.generate_videos("sunrise", 5)

        self.assertEqual(raised.exception.task_id, "vid-running")

    def test_network_retry_stops_when_total_run_deadline_is_reached(self):
        # 第一次请求前仍有 59 秒；请求异常返回时总截止时间已经过去，不能继续
        # 执行其余五次网络重试，也不能再进入退避 sleep。
        config.app["ofox_run_timeout"] = 60
        clock = iter([0.0, 1.0, 61.0])
        with (
            patch.object(
                ofox.requests,
                "get",
                side_effect=requests.exceptions.Timeout("slow"),
            ) as get,
            patch.object(ofox.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(ofox.time, "sleep") as sleep,
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                ofox._wait_for_task(
                    task_id="vid-network-timeout",
                    videos_url="https://ofox.example.test/v1/videos",
                    headers={},
                    api_key="ofox-test-key",
                )

        self.assertEqual(raised.exception.task_id, "vid-network-timeout")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["timeout"], (29.5, 29.5))
        sleep.assert_not_called()

    def test_expired_run_deadline_stops_before_remote_poll(self):
        config.app["ofox_run_timeout"] = 60
        clock = iter([0.0, 61.0])
        with (
            patch.object(ofox.requests, "get") as get,
            patch.object(ofox.time, "monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                ofox._wait_for_task(
                    task_id="vid-expired",
                    videos_url="https://ofox.example.test/v1/videos",
                    headers={},
                    api_key="ofox-test-key",
                )

        self.assertEqual(raised.exception.task_id, "vid-expired")
        get.assert_not_called()

    def test_active_poll_sleep_is_capped_by_remaining_deadline(self):
        config.app.update(
            {
                "ofox_run_timeout": 60,
                "ofox_poll_interval": 5,
            }
        )
        running = self._response({"id": "vid-running", "status": "in_progress"})
        # 第一次响应完成时只剩 0.25 秒，应只休眠剩余时间；下一轮在发起
        # 网络请求前发现截止时间已过，避免额外一次远端请求。
        clock = iter([0.0, 59.0, 59.75, 60.1])
        with (
            patch.object(ofox.requests, "get", return_value=running) as get,
            patch.object(ofox.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(ofox.time, "sleep") as sleep,
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError):
                ofox._wait_for_task(
                    task_id="vid-running",
                    videos_url="https://ofox.example.test/v1/videos",
                    headers={},
                    api_key="ofox-test-key",
                )

        self.assertEqual(get.call_count, 1)
        sleep.assert_called_once_with(0.25)

    def test_retry_backoff_is_capped_by_remaining_deadline(self):
        config.app["ofox_run_timeout"] = 60
        clock = iter([0.0, 59.0, 59.75, 60.1])
        with (
            patch.object(
                ofox.requests,
                "get",
                side_effect=requests.exceptions.Timeout("slow"),
            ) as get,
            patch.object(ofox.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(ofox.time, "sleep") as sleep,
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError):
                ofox._wait_for_task(
                    task_id="vid-retry-deadline",
                    videos_url="https://ofox.example.test/v1/videos",
                    headers={},
                    api_key="ofox-test-key",
                )

        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["timeout"], (0.5, 0.5))
        sleep.assert_called_once_with(0.25)

    def test_non_retryable_poll_response_stops_and_redacts_secret(self):
        unauthorized = self._response(
            {"error": {"code": "unauthorized", "message": "ofox-test-key"}},
            status_code=401,
        )
        with (
            patch.object(ofox.requests, "get", return_value=unauthorized) as get,
            patch.object(ofox.time, "sleep") as sleep,
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                ofox._wait_for_task(
                    task_id="vid-unauthorized",
                    videos_url="https://ofox.example.test/v1/videos",
                    headers={},
                    api_key="ofox-test-key",
                )

        self.assertEqual(raised.exception.task_id, "vid-unauthorized")
        self.assertNotIn("ofox-test-key", str(raised.exception))
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_malformed_poll_payload_preserves_remote_task_id(self):
        for payload in ([], None, "in_progress"):
            with self.subTest(payload=payload):
                with patch.object(
                    ofox.requests, "get", return_value=self._response(payload)
                ):
                    with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                        ofox._wait_for_task(
                            task_id="vid-malformed",
                            videos_url="https://ofox.example.test/v1/videos",
                            headers={},
                            api_key="ofox-test-key",
                        )

                self.assertEqual(raised.exception.task_id, "vid-malformed")

    def test_all_terminal_failure_statuses_end_the_task_without_billing_doubt(self):
        # 远端明确失败（如触发内容审核）意味着任务已结束、无计费悬念。返回
        # None 让上层跳过该关键词继续生成，而不是中止整条视频。
        for status in ofox.TERMINAL_FAILURE_STATUSES:
            with self.subTest(status=status):
                terminal = self._response(
                    {"id": "vid-terminal", "status": status, "error": {}}
                )
                with patch.object(ofox.requests, "get", return_value=terminal):
                    result = ofox._wait_for_task(
                        task_id="vid-terminal",
                        videos_url="https://ofox.example.test/v1/videos",
                        headers={},
                        api_key="ofox-test-key",
                    )

                self.assertIsNone(result)

    def test_terminal_failure_returns_empty_result_from_generate(self):
        submit = self._response({"id": "vid-failed", "status": "queued"}, 202)
        failed = self._response(
            {
                "id": "vid-failed",
                "status": "failed",
                "error": {"code": "content_policy", "message": "rejected"},
            }
        )
        with (
            patch.object(ofox.requests, "post", return_value=submit),
            patch.object(ofox.requests, "get", return_value=failed),
        ):
            result = ofox.generate_videos("sunrise", 5)

        self.assertEqual(result, [])

    def test_unknown_remote_status_is_unconfirmed_and_preserves_task_id(self):
        unknown = self._response({"id": "vid-unknown", "status": "pausing"})
        with patch.object(ofox.requests, "get", return_value=unknown):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError) as raised:
                ofox._wait_for_task(
                    task_id="vid-unknown",
                    videos_url="https://ofox.example.test/v1/videos",
                    headers={},
                    api_key="ofox-test-key",
                )

        self.assertEqual(raised.exception.task_id, "vid-unknown")

    def test_missing_task_id_is_treated_as_unconfirmed(self):
        for payload in ({}, {"id": "   "}, [], None):
            with self.subTest(payload=payload):
                with (
                    patch.object(
                        ofox.requests,
                        "post",
                        return_value=self._response(payload, 202),
                    ),
                    patch.object(ofox.requests, "get") as get,
                ):
                    with self.assertRaises(ofox.OFoxUnconfirmedTaskError):
                        ofox.generate_videos("sunrise", 5)
                get.assert_not_called()

    def test_completed_task_without_downloadable_url_stops_as_protocol_error(self):
        for urls in (None, [], ["not-a-url"], [123, {"url": "x"}]):
            with self.subTest(urls=urls):
                submit = self._response({"id": "vid-no-url", "status": "queued"}, 202)
                completed = self._response(
                    {"id": "vid-no-url", "status": "completed", "unsigned_urls": urls}
                )
                with (
                    patch.object(ofox.requests, "post", return_value=submit),
                    patch.object(ofox.requests, "get", return_value=completed),
                ):
                    with self.assertRaises(ofox.OFoxError) as raised:
                        ofox.generate_videos("sunrise", 5)

                self.assertEqual(raised.exception.task_id, "vid-no-url")

    def test_first_valid_unsigned_url_is_selected(self):
        submit = self._response({"id": "vid-multi", "status": "queued"}, 202)
        completed = self._response(
            {
                "id": "vid-multi",
                "status": "completed",
                "unsigned_urls": [
                    None,
                    "ftp://invalid.example.com/a.mp4",
                    "https://cdn.example.com/first-valid.mp4",
                    "https://cdn.example.com/second.mp4",
                ],
            }
        )
        with (
            patch.object(ofox.requests, "post", return_value=submit),
            patch.object(ofox.requests, "get", return_value=completed),
        ):
            result = ofox.generate_videos("sunrise", 5)

        self.assertEqual(result[0].url, "https://cdn.example.com/first-valid.mp4")


class TestOFoxMaterialIntegration(unittest.TestCase):
    @staticmethod
    def _item(term: str, url: str) -> MaterialInfo:
        return MaterialInfo(
            provider="ofox",
            url=url,
            duration=5,
            source_info={
                "provider": "ofox",
                "search_term": term,
                "asset_id": f"task-{term}",
            },
        )

    def test_on_demand_generation_stops_when_duration_is_covered(self):
        with (
            patch.object(
                ofox,
                "generate_videos",
                side_effect=[
                    [self._item("one", "https://cdn.example.com/one.mp4")],
                    [self._item("two", "https://cdn.example.com/two.mp4")],
                ],
            ) as generate,
            patch.object(
                material,
                "save_video",
                side_effect=["/tmp/one.mp4", "/tmp/two.mp4"],
            ),
            patch.object(material, "_persist_material_sources") as persist,
        ):
            result = material.download_videos(
                task_id="ofox-materials",
                search_terms=["one", "two", "three"],
                source="ofox",
                audio_duration=10,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/one.mp4", "/tmp/two.mp4"])
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(persist.call_args.args[0], "ofox-materials")
        self.assertEqual(len(persist.call_args.args[1]), 2)

    def test_failed_keyword_is_skipped_and_generation_continues(self):
        # 单个关键词被远端明确判失败（generate_videos 返回空列表）时应跳过该
        # 片段继续下一个关键词，而不是中止整条视频。
        with (
            patch.object(
                ofox,
                "generate_videos",
                side_effect=[
                    [],
                    [self._item("two", "https://cdn.example.com/two.mp4")],
                    [self._item("three", "https://cdn.example.com/three.mp4")],
                ],
            ) as generate,
            patch.object(
                material,
                "save_video",
                side_effect=["/tmp/two.mp4", "/tmp/three.mp4"],
            ),
            patch.object(material, "_persist_material_sources"),
        ):
            result = material.download_videos(
                task_id="ofox-skip-failed",
                search_terms=["one", "two", "three"],
                source="ofox",
                audio_duration=10,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/two.mp4", "/tmp/three.mp4"])
        self.assertEqual(generate.call_count, 3)

    def test_non_positive_audio_duration_avoids_paid_submission(self):
        for audio_duration in (0, -1, -0.1):
            with self.subTest(audio_duration=audio_duration):
                with (
                    patch.object(ofox, "generate_videos") as generate,
                    patch.object(material, "_persist_material_sources") as persist,
                ):
                    result = material.download_videos(
                        task_id="ofox-no-audio",
                        search_terms=["one", "two"],
                        source="ofox",
                        audio_duration=audio_duration,
                        max_clip_duration=5,
                    )

                self.assertEqual(result, [])
                generate.assert_not_called()
                persist.assert_called_once_with("ofox-no-audio", [])

    def test_non_finite_or_invalid_audio_duration_fails_before_paid_submission(self):
        for audio_duration in (float("nan"), float("inf"), float("-inf"), None, "bad"):
            with self.subTest(audio_duration=audio_duration):
                with patch.object(ofox, "generate_videos") as generate:
                    with self.assertRaises(ofox.OFoxError) as raised:
                        material.download_videos(
                            task_id="ofox-invalid-audio",
                            search_terms=["one", "two"],
                            source="ofox",
                            audio_duration=audio_duration,
                            max_clip_duration=5,
                        )

                self.assertIn("audio duration", str(raised.exception))
                generate.assert_not_called()

    def test_invalid_clip_duration_fails_before_paid_submission(self):
        for clip_duration in (0, -1, None, "bad", float("nan"), float("inf")):
            with self.subTest(clip_duration=clip_duration):
                with patch.object(ofox, "generate_videos") as generate:
                    with self.assertRaises(ofox.OFoxError) as raised:
                        material.download_videos(
                            task_id="ofox-invalid-clip",
                            search_terms=["one", "two"],
                            source="ofox",
                            audio_duration=10,
                            max_clip_duration=clip_duration,
                        )

                self.assertIn("clip duration", str(raised.exception))
                generate.assert_not_called()

    def test_unconfirmed_task_stops_later_paid_submissions(self):
        with (
            patch.object(
                ofox,
                "generate_videos",
                side_effect=ofox.OFoxUnconfirmedTaskError(
                    "unknown", task_id="vid-stuck"
                ),
            ) as generate,
            patch.object(material, "save_video") as save,
        ):
            with self.assertRaises(ofox.OFoxUnconfirmedTaskError):
                material.download_videos(
                    task_id="ofox-unconfirmed",
                    search_terms=["one", "two"],
                    source="ofox",
                    audio_duration=10,
                    max_clip_duration=5,
                )

        self.assertEqual(generate.call_count, 1)
        save.assert_not_called()

    def test_download_failure_stops_later_paid_submissions(self):
        first_item = self._item("one", "https://cdn.example.com/one.mp4")
        with (
            patch.object(
                ofox, "generate_videos", return_value=[first_item]
            ) as generate,
            patch.object(material, "_save_generated_video_with_retry", return_value=""),
        ):
            with self.assertRaises(ofox.OFoxDownloadError) as raised:
                material.download_videos(
                    task_id="ofox-download-failed",
                    search_terms=["one", "two"],
                    source="ofox",
                    audio_duration=10,
                    max_clip_duration=5,
                )

        self.assertEqual(raised.exception.task_id, "task-one")
        self.assertEqual(generate.call_count, 1)

    def test_later_download_failure_preserves_prior_material_sources(self):
        first_item = self._item("one", "https://cdn.example.com/one.mp4")
        second_item = self._item("two", "https://cdn.example.com/two.mp4")
        with (
            patch.object(
                ofox,
                "generate_videos",
                side_effect=[[first_item], [second_item]],
            ) as generate,
            patch.object(
                material,
                "_save_generated_video_with_retry",
                side_effect=["/tmp/one.mp4", ""],
            ),
            patch.object(material, "_persist_material_sources") as persist,
        ):
            with self.assertRaises(ofox.OFoxDownloadError) as raised:
                material.download_videos(
                    task_id="ofox-partial-download",
                    search_terms=["one", "two", "three"],
                    source="ofox",
                    audio_duration=15,
                    max_clip_duration=5,
                )

        self.assertEqual(raised.exception.task_id, "task-two")
        self.assertEqual(generate.call_count, 2)
        persisted_task_id, persisted_sources = persist.call_args.args
        self.assertEqual(persisted_task_id, "ofox-partial-download")
        self.assertEqual(len(persisted_sources), 1)
        self.assertEqual(persisted_sources[0]["asset_id"], "task-one")

    def test_task_preflight_rejects_missing_ofox_key_before_script_generation(self):
        params = VideoParams(
            video_subject="OFox preflight",
            video_source="ofox",
        )
        memory_state = sm.MemoryState()
        with (
            patch.object(ofox, "is_enabled", return_value=False),
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service, "generate_script") as generate_script,
        ):
            result = task_service.start("ofox-preflight", params, stop_at="materials")

        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("OFox API key", result["error"])
        generate_script.assert_not_called()

    def test_task_records_ofox_material_error_and_remote_task_id(self):
        params = VideoParams(
            video_subject="OFox material failure",
            video_source="ofox",
        )
        memory_state = sm.MemoryState()
        error = ofox.OFoxUnconfirmedTaskError(
            "remote state unknown", task_id="vid-recover"
        )
        with (
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service.material, "download_videos", side_effect=error),
        ):
            result = task_service.get_video_materials(
                task_id="ofox-material-error",
                params=params,
                video_terms=["scene"],
                audio_duration=5,
            )

        self.assertIsNone(result)
        failed = memory_state.get_task("ofox-material-error")
        self.assertEqual(failed["failed_stage"], "materials")
        self.assertEqual(failed["ofox_task_id"], "vid-recover")

    def test_task_records_paid_task_id_when_generated_video_download_fails(self):
        params = VideoParams(
            video_subject="OFox download failure",
            video_source="ofox",
        )
        memory_state = sm.MemoryState()
        error = ofox.OFoxDownloadError(
            "generated video download failed",
            task_id="vid-paid-result",
        )
        with (
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service.material, "download_videos", side_effect=error),
        ):
            result = task_service.get_video_materials(
                task_id="ofox-download-error",
                params=params,
                video_terms=["scene"],
                audio_duration=5,
            )

        self.assertIsNone(result)
        failed = memory_state.get_task("ofox-download-error")
        self.assertEqual(failed["failed_stage"], "materials")
        self.assertEqual(failed["ofox_task_id"], "vid-paid-result")


if __name__ == "__main__":
    unittest.main()
