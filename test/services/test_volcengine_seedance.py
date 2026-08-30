import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, state as sm, task as task_service
from app.services import volcengine_seedance as seedance


class TestVolcEngineSeedanceService(unittest.TestCase):
    def setUp(self):
        self.original_app = dict(config.app)
        self.original_proxy = dict(config.proxy)
        config.app.update(
            {
                "volcengine_seedance_api_key": "ark-test-key",
                "volcengine_seedance_model": seedance.DEFAULT_MODEL_ID,
                "volcengine_seedance_base_url": seedance.DEFAULT_BASE_URL,
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

    def test_api_key_uses_one_provider_specific_environment_name(self):
        with patch.dict(
            os.environ,
            {
                "VOLCENGINE_ARK_API_KEY": "env-key",
                "ARK_API_KEY": "generic-key-must-be-ignored",
            },
            clear=False,
        ):
            self.assertEqual(seedance.get_api_key(), "ark-test-key")
            config.app["volcengine_seedance_api_key"] = ""
            config.app["volcengine_api_key"] = "shared-ark-key"
            self.assertEqual(seedance.get_api_key(), "env-key")
            os.environ["VOLCENGINE_ARK_API_KEY"] = ""
            self.assertEqual(seedance.get_api_key(), "shared-ark-key")
            config.app["volcengine_api_key"] = ""
            self.assertEqual(seedance.get_api_key(), "")

    def test_missing_api_key_fails_before_submission(self):
        config.app["volcengine_seedance_api_key"] = ""
        config.app["volcengine_api_key"] = ""
        with (
            patch.dict(
                os.environ,
                {"VOLCENGINE_ARK_API_KEY": ""},
                clear=False,
            ),
            patch.object(seedance.requests, "post") as post,
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceError):
                seedance.generate_videos("sunrise", 5)
        post.assert_not_called()

    def test_empty_search_term_fails_before_paid_submission(self):
        for invalid in ("", "   ", None, 0, False):
            with self.subTest(invalid=invalid):
                with patch.object(seedance.requests, "post") as post:
                    with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                        seedance.generate_videos(invalid, 5)

                self.assertIn("search term must not be empty", str(raised.exception))
                post.assert_not_called()

    def test_search_term_is_trimmed_consistently_in_request_and_source_record(self):
        submit = self._response({"id": "cgt-trimmed"})
        completed = self._response(
            {
                "id": "cgt-trimmed",
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/trimmed.mp4"},
            }
        )
        with (
            patch.object(seedance.requests, "post", return_value=submit) as post,
            patch.object(seedance.requests, "get", return_value=completed),
        ):
            result = seedance.generate_videos("  smart home  ", 5)

        self.assertEqual(
            post.call_args.kwargs["json"]["content"],
            [{"type": "text", "text": "smart home"}],
        )
        self.assertEqual(result[0].source_info["search_term"], "smart home")

    def test_submit_poll_and_parse_successful_video(self):
        submit = self._response({"id": "cgt-123"})
        polls = [
            self._response({"id": "cgt-123", "status": "running"}),
            self._response(
                {
                    "id": "cgt-123",
                    "status": "succeeded",
                    "content": {
                        "video_url": "https://cdn.example.com/video.mp4?sig=abc"
                    },
                }
            ),
        ]

        with (
            patch.object(seedance.requests, "post", return_value=submit) as post,
            patch.object(seedance.requests, "get", side_effect=polls) as get,
            patch.object(seedance.time, "sleep") as sleep,
        ):
            result = seedance.generate_videos(
                "sunrise over mountains",
                minimum_duration=5,
                video_aspect=VideoAspect.portrait,
            )

        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item.provider, "volcengine_seedance")
        self.assertEqual(item.url, "https://cdn.example.com/video.mp4?sig=abc")
        self.assertEqual(item.duration, 5)
        self.assertEqual(item.source_info["asset_id"], "cgt-123")
        self.assertEqual(item.source_info["rendition"]["width"], 1080)
        self.assertEqual(item.source_info["rendition"]["height"], 1920)

        self.assertEqual(
            post.call_args.args[0],
            f"{seedance.DEFAULT_BASE_URL}/contents/generations/tasks",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer ark-test-key",
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "model": seedance.DEFAULT_MODEL_ID,
                "content": [
                    {"type": "text", "text": "sunrise over mountains"}
                ],
                "ratio": "9:16",
                "duration": 5,
                "resolution": "1080p",
                "watermark": False,
            },
        )
        self.assertEqual(get.call_count, 2)
        self.assertTrue(
            all("/contents/generations/tasks/cgt-123" in call.args[0] for call in get.call_args_list)
        )
        sleep.assert_called_once_with(seedance.DEFAULT_POLL_INTERVAL_SECONDS)

    def test_rendition_size_matches_real_ark_outputs(self):
        self.assertEqual(
            seedance._rendition_size(VideoAspect.portrait, "480p"),
            (480, 864),
        )
        self.assertEqual(
            seedance._rendition_size(VideoAspect.landscape, "720p"),
            (1280, 720),
        )
        self.assertEqual(
            seedance._rendition_size(VideoAspect.square, "1080p"),
            (1080, 1080),
        )

    def test_invalid_resolution_fails_before_paid_submission(self):
        for invalid in ("480", "", "   ", None, 0, False, "4k"):
            with self.subTest(invalid=invalid):
                config.app["volcengine_seedance_resolution"] = invalid
                with patch.object(seedance.requests, "post") as post:
                    with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                        seedance.generate_videos("city", 5)

                self.assertIn(
                    "Unsupported Seedance resolution", str(raised.exception)
                )
                post.assert_not_called()

    def test_resolution_defaults_only_when_missing_and_normalizes_supported_value(self):
        config.app.pop("volcengine_seedance_resolution", None)
        self.assertEqual(seedance._resolution(), seedance.DEFAULT_RESOLUTION)

        config.app["volcengine_seedance_resolution"] = " 720P "
        self.assertEqual(seedance._resolution(), "720p")

    def test_configured_model_base_url_and_duration_bounds_are_applied(self):
        config.app.update(
            {
                "volcengine_seedance_model": "ep-custom",
                "volcengine_seedance_base_url": "https://ark.example.test/api/v3/",
                "volcengine_seedance_min_duration": 4,
                "volcengine_seedance_max_duration": 8,
                "volcengine_seedance_resolution": "720p",
                "volcengine_seedance_watermark": True,
            }
        )
        submit = self._response({"id": "cgt-bounds"})
        completed = self._response(
            {
                "id": "cgt-bounds",
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/bounds.mp4"},
            }
        )
        with (
            patch.object(seedance.requests, "post", return_value=submit) as post,
            patch.object(seedance.requests, "get", return_value=completed),
        ):
            result = seedance.generate_videos("city", 99, VideoAspect.landscape)

        self.assertEqual(result[0].duration, 8)
        self.assertEqual(
            post.call_args.args[0],
            "https://ark.example.test/api/v3/contents/generations/tasks",
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "ep-custom")
        self.assertEqual(payload["duration"], 8)
        self.assertEqual(payload["resolution"], "720p")
        self.assertTrue(payload["watermark"])

    def test_rejected_submission_raises_clear_error_without_polling(self):
        rejected = self._response(
            {
                "error": {
                    "code": "InputTextSensitiveContentDetected",
                    "message": "rejected ark-test-key",
                }
            },
            status_code=400,
        )
        with (
            patch.object(seedance.requests, "post", return_value=rejected),
            patch.object(seedance.requests, "get") as get,
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                seedance.generate_videos("unsafe", 5)

        get.assert_not_called()
        self.assertNotIn("ark-test-key", str(raised.exception))

    def test_submission_network_or_server_error_is_unconfirmed_and_not_retried(self):
        for side_effect, response in (
            (requests.exceptions.ConnectionError("offline"), None),
            (None, self._response({"message": "bad gateway"}, status_code=502)),
        ):
            with self.subTest(response=response):
                with patch.object(
                    seedance.requests,
                    "post",
                    side_effect=side_effect,
                    return_value=response,
                ) as post:
                    with self.assertRaises(
                        seedance.VolcEngineSeedanceUnconfirmedTaskError
                    ):
                        seedance.generate_videos("sunrise", 5)
                self.assertEqual(post.call_count, 1)

    def test_poll_retries_transient_errors_on_same_task(self):
        submit = self._response({"id": "cgt-retry"})
        rate_limited = self._response({}, status_code=429)
        completed = self._response(
            {
                "id": "cgt-retry",
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/retry.mp4"},
            }
        )
        with (
            patch.object(seedance.requests, "post", return_value=submit) as post,
            patch.object(
                seedance.requests,
                "get",
                side_effect=[
                    rate_limited,
                    requests.exceptions.ConnectionError("offline"),
                    completed,
                ],
            ) as get,
            patch.object(seedance.time, "sleep") as sleep,
        ):
            result = seedance.generate_videos("sunrise", 5)

        self.assertEqual(len(result), 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    def test_poll_retry_exhaustion_preserves_remote_task_id(self):
        submit = self._response({"id": "cgt-stuck"})
        with (
            patch.object(seedance.requests, "post", return_value=submit),
            patch.object(
                seedance.requests,
                "get",
                side_effect=requests.exceptions.ConnectionError("offline"),
            ) as get,
            patch.object(seedance.time, "sleep"),
        ):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ) as raised:
                seedance.generate_videos("sunrise", 5)

        self.assertEqual(raised.exception.task_id, "cgt-stuck")
        self.assertEqual(get.call_count, seedance.MAX_POLL_RETRIES + 1)

    def test_running_task_timeout_preserves_remote_task_id(self):
        submit = self._response({"id": "cgt-running"})
        running = self._response({"id": "cgt-running", "status": "running"})
        clock = iter([0.0, 1.0, seedance.DEFAULT_RUN_TIMEOUT_SECONDS + 1])
        with (
            patch.object(seedance.requests, "post", return_value=submit),
            patch.object(seedance.requests, "get", return_value=running),
            patch.object(seedance.time, "monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ) as raised:
                seedance.generate_videos("sunrise", 5)

        self.assertEqual(raised.exception.task_id, "cgt-running")

    def test_network_retry_stops_when_total_run_deadline_is_reached(self):
        # 第一次请求前仍有 59 秒；请求异常返回时总截止时间已经过去，不能继续
        # 执行其余五次网络重试，也不能再进入退避 sleep。
        config.app["volcengine_seedance_run_timeout"] = 60
        clock = iter([0.0, 1.0, 61.0])
        with (
            patch.object(
                seedance.requests,
                "get",
                side_effect=requests.exceptions.Timeout("slow"),
            ) as get,
            patch.object(seedance.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(seedance.time, "sleep") as sleep,
        ):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ) as raised:
                seedance._wait_for_task(
                    task_id="cgt-network-timeout",
                    tasks_url="https://ark.example.test/tasks",
                    headers={},
                    api_key="ark-test-key",
                )

        self.assertEqual(raised.exception.task_id, "cgt-network-timeout")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["timeout"], (29.5, 29.5))
        sleep.assert_not_called()

    def test_expired_run_deadline_stops_before_remote_poll(self):
        config.app["volcengine_seedance_run_timeout"] = 60
        clock = iter([0.0, 61.0])
        with (
            patch.object(seedance.requests, "get") as get,
            patch.object(seedance.time, "monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ) as raised:
                seedance._wait_for_task(
                    task_id="cgt-expired",
                    tasks_url="https://ark.example.test/tasks",
                    headers={},
                    api_key="ark-test-key",
                )

        self.assertEqual(raised.exception.task_id, "cgt-expired")
        get.assert_not_called()

    def test_active_poll_sleep_is_capped_by_remaining_deadline(self):
        config.app.update(
            {
                "volcengine_seedance_run_timeout": 60,
                "volcengine_seedance_poll_interval": 5,
            }
        )
        running = self._response({"id": "cgt-running", "status": "running"})
        # 第一次响应完成时只剩 0.25 秒，应只休眠剩余时间；下一轮在发起
        # 网络请求前发现截止时间已过，避免额外一次远端请求。
        clock = iter([0.0, 59.0, 59.75, 60.1])
        with (
            patch.object(seedance.requests, "get", return_value=running) as get,
            patch.object(seedance.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(seedance.time, "sleep") as sleep,
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceUnconfirmedTaskError):
                seedance._wait_for_task(
                    task_id="cgt-running",
                    tasks_url="https://ark.example.test/tasks",
                    headers={},
                    api_key="ark-test-key",
                )

        self.assertEqual(get.call_count, 1)
        sleep.assert_called_once_with(0.25)

    def test_retry_backoff_is_capped_by_remaining_deadline(self):
        config.app["volcengine_seedance_run_timeout"] = 60
        clock = iter([0.0, 59.0, 59.75, 60.1])
        with (
            patch.object(
                seedance.requests,
                "get",
                side_effect=requests.exceptions.Timeout("slow"),
            ) as get,
            patch.object(seedance.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(seedance.time, "sleep") as sleep,
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceUnconfirmedTaskError):
                seedance._wait_for_task(
                    task_id="cgt-retry-deadline",
                    tasks_url="https://ark.example.test/tasks",
                    headers={},
                    api_key="ark-test-key",
                )

        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["timeout"], (0.5, 0.5))
        sleep.assert_called_once_with(0.25)

    def test_non_retryable_poll_response_stops_and_redacts_secret(self):
        unauthorized = self._response(
            {"error": {"code": "Unauthorized", "message": "ark-test-key"}},
            status_code=401,
        )
        with (
            patch.object(seedance.requests, "get", return_value=unauthorized) as get,
            patch.object(seedance.time, "sleep") as sleep,
        ):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ) as raised:
                seedance._wait_for_task(
                    task_id="cgt-unauthorized",
                    tasks_url="https://ark.example.test/tasks",
                    headers={},
                    api_key="ark-test-key",
                )

        self.assertEqual(raised.exception.task_id, "cgt-unauthorized")
        self.assertNotIn("ark-test-key", str(raised.exception))
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_malformed_poll_payload_preserves_remote_task_id(self):
        for payload in ([], None, "running"):
            with self.subTest(payload=payload):
                with patch.object(
                    seedance.requests, "get", return_value=self._response(payload)
                ):
                    with self.assertRaises(
                        seedance.VolcEngineSeedanceUnconfirmedTaskError
                    ) as raised:
                        seedance._wait_for_task(
                            task_id="cgt-malformed",
                            tasks_url="https://ark.example.test/tasks",
                            headers={},
                            api_key="ark-test-key",
                        )

                self.assertEqual(raised.exception.task_id, "cgt-malformed")

    def test_all_terminal_status_aliases_preserve_remote_task_id(self):
        for status in seedance.TERMINAL_FAILURE_STATUSES:
            with self.subTest(status=status):
                terminal = self._response(
                    {"id": "cgt-terminal", "status": status, "error": {}}
                )
                with patch.object(seedance.requests, "get", return_value=terminal):
                    with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                        seedance._wait_for_task(
                            task_id="cgt-terminal",
                            tasks_url="https://ark.example.test/tasks",
                            headers={},
                            api_key="ark-test-key",
                        )

                self.assertEqual(raised.exception.task_id, "cgt-terminal")

    def test_unknown_remote_status_is_unconfirmed_and_preserves_task_id(self):
        unknown = self._response({"id": "cgt-unknown", "status": "pausing"})
        with patch.object(seedance.requests, "get", return_value=unknown):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ) as raised:
                seedance._wait_for_task(
                    task_id="cgt-unknown",
                    tasks_url="https://ark.example.test/tasks",
                    headers={},
                    api_key="ark-test-key",
                )

        self.assertEqual(raised.exception.task_id, "cgt-unknown")

    def test_terminal_failure_preserves_remote_task_id(self):
        submit = self._response({"id": "cgt-failed"})
        failed = self._response(
            {
                "id": "cgt-failed",
                "status": "failed",
                "error": {"code": "OutputVideoSensitiveContentDetected"},
            }
        )
        with (
            patch.object(seedance.requests, "post", return_value=submit),
            patch.object(seedance.requests, "get", return_value=failed),
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                seedance.generate_videos("sunrise", 5)

        self.assertEqual(raised.exception.task_id, "cgt-failed")

    def test_missing_task_id_is_treated_as_unconfirmed(self):
        for payload in ({}, {"id": "   "}, [], None):
            with self.subTest(payload=payload):
                with (
                    patch.object(
                        seedance.requests, "post", return_value=self._response(payload)
                    ),
                    patch.object(seedance.requests, "get") as get,
                ):
                    with self.assertRaises(
                        seedance.VolcEngineSeedanceUnconfirmedTaskError
                    ):
                        seedance.generate_videos("sunrise", 5)
                get.assert_not_called()

    def test_succeeded_task_without_video_url_stops_as_protocol_error(self):
        submit = self._response({"id": "cgt-no-url"})
        completed = self._response(
            {"id": "cgt-no-url", "status": "succeeded", "content": {}}
        )
        with (
            patch.object(seedance.requests, "post", return_value=submit),
            patch.object(seedance.requests, "get", return_value=completed),
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                seedance.generate_videos("sunrise", 5)

        self.assertEqual(raised.exception.task_id, "cgt-no-url")


class TestVolcEngineSeedanceMaterialIntegration(unittest.TestCase):
    @staticmethod
    def _item(term: str, url: str) -> MaterialInfo:
        return MaterialInfo(
            provider="volcengine_seedance",
            url=url,
            duration=5,
            source_info={
                "provider": "volcengine_seedance",
                "search_term": term,
                "asset_id": f"task-{term}",
            },
        )

    def test_on_demand_generation_stops_when_duration_is_covered(self):
        with (
            patch.object(
                seedance,
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
                task_id="seedance-materials",
                search_terms=["one", "two", "three"],
                source="volcengine_seedance",
                audio_duration=10,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/one.mp4", "/tmp/two.mp4"])
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(persist.call_args.args[0], "seedance-materials")
        self.assertEqual(len(persist.call_args.args[1]), 2)

    def test_non_positive_audio_duration_avoids_paid_submission(self):
        for audio_duration in (0, -1, -0.1):
            with self.subTest(audio_duration=audio_duration):
                with (
                    patch.object(seedance, "generate_videos") as generate,
                    patch.object(material, "_persist_material_sources") as persist,
                ):
                    result = material.download_videos(
                        task_id="seedance-no-audio",
                        search_terms=["one", "two"],
                        source="volcengine_seedance",
                        audio_duration=audio_duration,
                        max_clip_duration=5,
                    )

                self.assertEqual(result, [])
                generate.assert_not_called()
                persist.assert_called_once_with("seedance-no-audio", [])

    def test_non_finite_or_invalid_audio_duration_fails_before_paid_submission(self):
        for audio_duration in (float("nan"), float("inf"), float("-inf"), None, "bad"):
            with self.subTest(audio_duration=audio_duration):
                with patch.object(seedance, "generate_videos") as generate:
                    with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                        material.download_videos(
                            task_id="seedance-invalid-audio",
                            search_terms=["one", "two"],
                            source="volcengine_seedance",
                            audio_duration=audio_duration,
                            max_clip_duration=5,
                        )

                self.assertIn("audio duration", str(raised.exception))
                generate.assert_not_called()

    def test_invalid_clip_duration_fails_before_paid_submission(self):
        for clip_duration in (0, -1, None, "bad", float("nan"), float("inf")):
            with self.subTest(clip_duration=clip_duration):
                with patch.object(seedance, "generate_videos") as generate:
                    with self.assertRaises(seedance.VolcEngineSeedanceError) as raised:
                        material.download_videos(
                            task_id="seedance-invalid-clip",
                            search_terms=["one", "two"],
                            source="volcengine_seedance",
                            audio_duration=10,
                            max_clip_duration=clip_duration,
                        )

                self.assertIn("clip duration", str(raised.exception))
                generate.assert_not_called()

    def test_unconfirmed_task_stops_later_paid_submissions(self):
        with (
            patch.object(
                seedance,
                "generate_videos",
                side_effect=seedance.VolcEngineSeedanceUnconfirmedTaskError(
                    "unknown", task_id="cgt-stuck"
                ),
            ) as generate,
            patch.object(material, "save_video") as save,
        ):
            with self.assertRaises(
                seedance.VolcEngineSeedanceUnconfirmedTaskError
            ):
                material.download_videos(
                    task_id="seedance-unconfirmed",
                    search_terms=["one", "two"],
                    source="volcengine_seedance",
                    audio_duration=10,
                    max_clip_duration=5,
                )

        self.assertEqual(generate.call_count, 1)
        save.assert_not_called()

    def test_download_failure_stops_later_paid_submissions(self):
        first_item = self._item("one", "https://cdn.example.com/one.mp4")
        with (
            patch.object(seedance, "generate_videos", return_value=[first_item]) as generate,
            patch.object(material, "_save_generated_video_with_retry", return_value=""),
        ):
            with self.assertRaises(seedance.VolcEngineSeedanceDownloadError) as raised:
                material.download_videos(
                    task_id="seedance-download-failed",
                    search_terms=["one", "two"],
                    source="volcengine_seedance",
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
                seedance,
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
            with self.assertRaises(seedance.VolcEngineSeedanceDownloadError) as raised:
                material.download_videos(
                    task_id="seedance-partial-download",
                    search_terms=["one", "two", "three"],
                    source="volcengine_seedance",
                    audio_duration=15,
                    max_clip_duration=5,
                )

        self.assertEqual(raised.exception.task_id, "task-two")
        self.assertEqual(generate.call_count, 2)
        persisted_task_id, persisted_sources = persist.call_args.args
        self.assertEqual(persisted_task_id, "seedance-partial-download")
        self.assertEqual(len(persisted_sources), 1)
        self.assertEqual(persisted_sources[0]["asset_id"], "task-one")

    def test_task_preflight_rejects_missing_ark_key_before_script_generation(self):
        params = VideoParams(
            video_subject="Seedance preflight",
            video_source="volcengine_seedance",
        )
        memory_state = sm.MemoryState()
        with (
            patch.object(seedance, "is_enabled", return_value=False),
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service, "generate_script") as generate_script,
        ):
            result = task_service.start(
                "seedance-preflight", params, stop_at="materials"
            )

        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("Ark API key", result["error"])
        generate_script.assert_not_called()

    def test_task_records_seedance_material_error_and_remote_task_id(self):
        params = VideoParams(
            video_subject="Seedance material failure",
            video_source="volcengine_seedance",
        )
        memory_state = sm.MemoryState()
        error = seedance.VolcEngineSeedanceUnconfirmedTaskError(
            "remote state unknown", task_id="cgt-recover"
        )
        with (
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service.material, "download_videos", side_effect=error),
        ):
            result = task_service.get_video_materials(
                task_id="seedance-material-error",
                params=params,
                video_terms=["scene"],
                audio_duration=5,
            )

        self.assertIsNone(result)
        failed = memory_state.get_task("seedance-material-error")
        self.assertEqual(failed["failed_stage"], "materials")
        self.assertEqual(failed["volcengine_seedance_task_id"], "cgt-recover")

    def test_task_records_remote_id_from_terminal_provider_error(self):
        params = VideoParams(
            video_subject="Seedance terminal failure",
            video_source="volcengine_seedance",
        )
        memory_state = sm.MemoryState()
        # 终态失败和协议异常使用基础错误类型。这里验证它们与“状态未知”
        # 异常保持同一恢复信息契约，不会在任务状态中丢失远端任务 ID。
        error = seedance.VolcEngineSeedanceError(
            "remote task failed", task_id="cgt-terminal"
        )
        with (
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service.material, "download_videos", side_effect=error),
        ):
            result = task_service.get_video_materials(
                task_id="seedance-terminal-error",
                params=params,
                video_terms=["scene"],
                audio_duration=5,
            )

        self.assertIsNone(result)
        failed = memory_state.get_task("seedance-terminal-error")
        self.assertEqual(failed["failed_stage"], "materials")
        self.assertEqual(failed["volcengine_seedance_task_id"], "cgt-terminal")

    def test_task_records_paid_task_id_when_generated_video_download_fails(self):
        params = VideoParams(
            video_subject="Seedance download failure",
            video_source="volcengine_seedance",
        )
        memory_state = sm.MemoryState()
        error = seedance.VolcEngineSeedanceDownloadError(
            "generated video download failed",
            task_id="cgt-paid-result",
        )
        with (
            patch.object(task_service.sm, "state", memory_state),
            patch.object(task_service.material, "download_videos", side_effect=error),
        ):
            result = task_service.get_video_materials(
                task_id="seedance-download-error",
                params=params,
                video_terms=["scene"],
                audio_duration=5,
            )

        self.assertIsNone(result)
        failed = memory_state.get_task("seedance-download-error")
        self.assertEqual(failed["failed_stage"], "materials")
        self.assertEqual(failed["volcengine_seedance_task_id"], "cgt-paid-result")


if __name__ == "__main__":
    unittest.main()
