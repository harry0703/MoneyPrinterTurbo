import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import sonilo


class _StreamingResponse:
    """提供 requests.Response 在 Sonilo 服务中实际使用的最小接口。"""

    def __init__(
        self,
        events=None,
        *,
        status_code=200,
        payload=None,
        iter_error=None,
    ):
        self.events = events or []
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.reason = "OK" if self.ok else "Request failed"
        self.text = "" if self.ok else "request failed"
        self.payload = payload if payload is not None else {"services": []}
        self.iter_error = iter_error

    def iter_lines(self):
        if self.iter_error:
            raise self.iter_error
        return iter(self.events)

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _event(event_type, **values):
    return json.dumps({"type": event_type, **values}).encode("utf-8")


class _SfxResponse:
    """提供音效任务管线中 requests.Response 实际被使用的最小接口。"""

    def __init__(self, *, status_code=200, payload=None, chunks=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.reason = "OK" if self.ok else "Request failed"
        self.text = "" if self.ok else "request failed"
        self.payload = payload
        self.chunks = chunks or []

    def json(self):
        if self.payload is None:
            raise ValueError("invalid json")
        return self.payload

    def iter_content(self, chunk_size=None):
        return iter(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestSoniloService(unittest.TestCase):
    def test_api_key_prefers_config_and_falls_back_to_environment(self):
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "config-key"}),
            patch.dict(os.environ, {"SONILO_API_KEY": "env-key"}),
        ):
            self.assertEqual(sonilo.get_api_key(), "config-key")

        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": ""}),
            patch.dict(os.environ, {"SONILO_API_KEY": "env-key"}),
        ):
            self.assertEqual(sonilo.get_api_key(), "env-key")

    def test_request_timeout_clamps_fractional_and_invalid_values(self):
        """读取超时必须保持为 Requests 接受的正整数，并限制最大等待时间。"""
        test_cases = [
            (0.5, (15, 1)),
            (1.1, (15, 2)),
            (1800.5, (15, 1800)),
            (0, (15, 600)),
            (-1, (15, 600)),
            (float("inf"), (15, 600)),
            ("invalid", (15, 600)),
        ]
        for configured_timeout, expected in test_cases:
            with self.subTest(configured_timeout=configured_timeout), patch.object(
                sonilo.config,
                "app",
                {"sonilo_timeout": configured_timeout},
            ):
                self.assertEqual(sonilo._request_timeout(), expected)

    def test_connection_uses_non_billing_services_endpoint(self):
        response = _StreamingResponse(
            payload={"available_services": ["video_to_music"]}
        )
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo.requests, "get", return_value=response) as request,
        ):
            result = sonilo.test_connection()

        self.assertEqual(result, {"available_services": ["video_to_music"]})
        self.assertTrue(request.call_args.args[0].endswith("/v1/account/services"))
        self.assertEqual(
            request.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )

    def test_connection_accepts_documented_hyphenated_service_id(self):
        """公开文档的连字符写法必须归一化为项目内部服务标识。"""
        response = _StreamingResponse(
            payload={"available_services": ["video-to-music"]}
        )
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo.requests, "get", return_value=response),
        ):
            result = sonilo.test_connection()

        self.assertEqual(result, {"available_services": ["video-to-music"]})

    def test_connection_rejects_malformed_service_lists(self):
        """200 响应缺少规范服务列表时不能向 WebUI 报告连接成功。"""
        invalid_payloads = [
            {},
            {"available_services": "video_to_music"},
            {"available_services": ["video_to_music", 1]},
        ]
        for payload in invalid_payloads:
            with (
                self.subTest(payload=payload),
                patch.object(
                    sonilo.config, "app", {"sonilo_api_key": "test-key"}
                ),
                patch.object(
                    sonilo.requests,
                    "get",
                    return_value=_StreamingResponse(payload=payload),
                ),
            ):
                with self.assertRaisesRegex(sonilo.SoniloError, "service list"):
                    sonilo.test_connection()

    def test_connection_rejects_key_without_video_to_music_service(self):
        response = _StreamingResponse(
            payload={"available_services": ["text_to_music"]}
        )
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo.requests, "get", return_value=response),
        ):
            with self.assertRaisesRegex(sonilo.SoniloError, "not available"):
                sonilo.test_connection()

    def test_connection_converts_network_and_invalid_json_errors(self):
        """连接测试的网络中断和非 JSON 响应都转换为稳定的领域异常。"""
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(
                sonilo.requests,
                "get",
                side_effect=sonilo.requests.Timeout("timed out"),
            ),
        ):
            with self.assertRaisesRegex(sonilo.SoniloError, "failed to connect"):
                sonilo.test_connection()

        response = _StreamingResponse(payload={})
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo.requests, "get", return_value=response),
            patch.object(response, "json", side_effect=ValueError("invalid json")),
        ):
            with self.assertRaisesRegex(sonilo.SoniloError, "invalid service response"):
                sonilo.test_connection()

    def test_create_video_proxy_uses_expected_ffmpeg_policy(self):
        """成功代理必须去音轨、限制尺寸，并由调用方接管生成文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"source-video")

            def create_proxy(command, **_kwargs):
                Path(command[-1]).write_bytes(b"proxy-video")
                return sonilo.subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.object(
                    sonilo.utils, "get_ffmpeg_binary", return_value="test-ffmpeg"
                ),
                patch.object(
                    sonilo.subprocess, "run", side_effect=create_proxy
                ) as run,
            ):
                proxy_path = sonilo._create_video_proxy(str(source))

            command = run.call_args.args[0]
            self.assertEqual(command[0], "test-ffmpeg")
            self.assertIn("-an", command)
            self.assertIn("force_original_aspect_ratio=decrease", command[command.index("-vf") + 1])
            self.assertEqual(Path(proxy_path).read_bytes(), b"proxy-video")
            Path(proxy_path).unlink()

    def test_create_video_proxy_cleans_file_after_execution_failures(self):
        """FFmpeg 超时、不可执行或编码失败时均不能遗留隐藏代理文件。"""
        failure_cases = [
            (
                sonilo.subprocess.TimeoutExpired("ffmpeg", 600),
                "timed out",
            ),
            (OSError("ffmpeg missing"), "failed to run FFmpeg"),
            (
                sonilo.subprocess.CompletedProcess(
                    ["ffmpeg"], 1, "", "encoder unavailable"
                ),
                "encoder unavailable",
            ),
        ]
        for result_or_error, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                source = Path(temp_dir) / "source.mp4"
                source.write_bytes(b"source-video")
                run_kwargs = (
                    {"return_value": result_or_error}
                    if isinstance(result_or_error, sonilo.subprocess.CompletedProcess)
                    else {"side_effect": result_or_error}
                )
                with patch.object(sonilo.subprocess, "run", **run_kwargs):
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, expected_message
                    ):
                        sonilo._create_video_proxy(str(source))

                self.assertEqual(list(Path(temp_dir).glob(".sonilo-proxy-*")), [])

    def test_create_video_proxy_rejects_empty_and_oversized_outputs(self):
        """FFmpeg 返回成功也必须再次校验代理文件存在、非空且未超上限。"""
        for output_size, expected_size in (
            (0, 0),
            (1, sonilo.MAX_PROXY_BYTES + 1),
        ):
            with (
                self.subTest(expected_size=expected_size),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                source = Path(temp_dir) / "source.mp4"
                source.write_bytes(b"source-video")

                def create_proxy(command, **_kwargs):
                    Path(command[-1]).write_bytes(b"x" * output_size)
                    return sonilo.subprocess.CompletedProcess(command, 0, "", "")

                with (
                    patch.object(sonilo.subprocess, "run", side_effect=create_proxy),
                    patch.object(
                        sonilo.os.path,
                        "getsize",
                        return_value=expected_size,
                    ),
                ):
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, "empty or exceeds"
                    ):
                        sonilo._create_video_proxy(str(source))

                self.assertEqual(list(Path(temp_dir).glob(".sonilo-proxy-*")), [])

    def test_stream_audio_selects_first_track_and_requires_complete(self):
        first_chunk = b"first-track"
        second_chunk = b"second-track"
        response = _StreamingResponse(
            [
                _event(
                    "audio_chunk",
                    stream_index=1,
                    data=base64.b64encode(second_chunk).decode(),
                ),
                _event(
                    "audio_chunk",
                    stream_index=0,
                    data=base64.b64encode(first_chunk).decode(),
                ),
                _event("complete"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "music.m4a"
            size, _ = sonilo._stream_audio(response, str(output))
            self.assertEqual(output.read_bytes(), first_chunk)
            self.assertEqual(size, len(first_chunk))

        incomplete = _StreamingResponse(
            [
                _event(
                    "audio_chunk",
                    stream_index=0,
                    data=base64.b64encode(first_chunk).decode(),
                )
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(sonilo.SoniloError, "before completion"):
                sonilo._stream_audio(
                    incomplete, str(Path(temp_dir) / "incomplete.m4a")
                )

    def test_stream_audio_rejects_malformed_json_and_base64(self):
        invalid_cases = [
            [b"not-json"],
            [_event("audio_chunk", stream_index=0, data="%%%")],
            [_event("audio_chunk", stream_index=0, data=""), _event("complete")],
        ]
        for events in invalid_cases:
            with self.subTest(events=events), tempfile.TemporaryDirectory() as temp_dir:
                with self.assertRaises(sonilo.SoniloError):
                    sonilo._stream_audio(
                        _StreamingResponse(events), str(Path(temp_dir) / "bad.m4a")
                    )

    def test_stream_audio_rejects_error_empty_and_oversized_results(self):
        """服务端错误、仅完成事件和超体积音频都不能发布为有效 BGM。"""
        oversized_chunk = base64.b64encode(b"1234").decode()
        cases = [
            ([_event("error", message="credit exhausted")], "credit exhausted"),
            ([_event("complete")], "no audio data"),
            (
                [
                    _event("audio_chunk", stream_index=0, data=oversized_chunk),
                    _event("complete"),
                ],
                "exceeds",
            ),
        ]
        for events, expected_message in cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                output = Path(temp_dir) / "music.m4a"
                # 所有用例统一缩小体积上限；错误事件和空结果不受该值影响，
                # 超限用例则无需在测试中分配 30 MB 数据。
                with (
                    patch.object(sonilo, "MAX_GENERATED_AUDIO_BYTES", 3),
                    self.assertRaisesRegex(sonilo.SoniloError, expected_message),
                ):
                    sonilo._stream_audio(_StreamingResponse(events), str(output))

    def test_request_bgm_validates_then_atomically_publishes_audio(self):
        audio_bytes = b"synthetic-fmp4-audio"
        response = _StreamingResponse(
            [
                _event(
                    "audio_chunk",
                    stream_index=0,
                    data=base64.b64encode(audio_bytes).decode(),
                ),
                _event("complete"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "proxy.mp4"
            output_path = Path(temp_dir) / "music.m4a"
            video_path.write_bytes(b"video")
            with (
                patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
                patch.object(sonilo.requests, "post", return_value=response) as post,
                patch.object(
                    sonilo.bgm_service, "validate_audio_file"
                ) as validate_audio,
            ):
                result = sonilo._request_bgm(
                    str(video_path), str(output_path), "warm"
                )

            self.assertEqual(result, str(output_path))
            self.assertEqual(output_path.read_bytes(), audio_bytes)
            validate_audio.assert_called_once()
            self.assertEqual(post.call_args.kwargs["data"], {"prompt": "warm"})
            self.assertEqual(post.call_args.kwargs["stream"], True)
            self.assertEqual(list(Path(temp_dir).glob(".sonilo-audio-*")), [])

    def test_request_bgm_preserves_existing_output_and_cleans_temp_on_failures(self):
        """HTTP、流读取和音频校验失败都不能覆盖已有结果或留下半成品。"""
        audio_event = _event(
            "audio_chunk",
            stream_index=0,
            data=base64.b64encode(b"invalid-audio").decode(),
        )
        failure_cases = [
            (
                _StreamingResponse(status_code=401),
                None,
                "401",
            ),
            (
                _StreamingResponse(
                    iter_error=sonilo.requests.ConnectionError("stream lost")
                ),
                None,
                "failed to request",
            ),
            (
                _StreamingResponse([audio_event, _event("complete")]),
                sonilo.bgm_service.BgmUploadError("invalid audio"),
                "cannot decode",
            ),
        ]
        for response, validation_error, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                video_path = Path(temp_dir) / "proxy.mp4"
                output_path = Path(temp_dir) / "music.m4a"
                video_path.write_bytes(b"video")
                output_path.write_bytes(b"existing-music")
                with (
                    patch.object(
                        sonilo.config, "app", {"sonilo_api_key": "test-key"}
                    ),
                    patch.object(sonilo.requests, "post", return_value=response),
                    patch.object(
                        sonilo.bgm_service,
                        "validate_audio_file",
                        side_effect=validation_error,
                    ),
                ):
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, expected_message
                    ):
                        sonilo._request_bgm(
                            str(video_path), str(output_path), ""
                        )

                self.assertEqual(output_path.read_bytes(), b"existing-music")
                self.assertEqual(list(Path(temp_dir).glob(".sonilo-audio-*")), [])

    def test_generate_bgm_cleans_proxy_when_request_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            proxy = Path(temp_dir) / "proxy.mp4"
            source.write_bytes(b"video")
            proxy.write_bytes(b"proxy")
            with (
                patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
                patch.object(
                    sonilo, "_create_video_proxy", return_value=str(proxy)
                ),
                patch.object(
                    sonilo,
                    "_request_bgm",
                    side_effect=sonilo.SoniloError("network failed"),
                ),
            ):
                with self.assertRaises(sonilo.SoniloError):
                    sonilo.generate_bgm(
                        str(source), str(Path(temp_dir) / "music.m4a"), 5
                    )

            self.assertFalse(proxy.exists())

    def test_generate_bgm_converts_file_errors_and_cleans_proxy(self):
        """文件系统失败也必须转换为可降级异常，并清理已经生成的代理。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            proxy = Path(temp_dir) / "proxy.mp4"
            source.write_bytes(b"video")
            proxy.write_bytes(b"proxy")
            with (
                patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
                patch.object(
                    sonilo, "_create_video_proxy", return_value=str(proxy)
                ),
                patch.object(
                    sonilo,
                    "_request_bgm",
                    side_effect=OSError("disk full"),
                ),
            ):
                with self.assertRaisesRegex(sonilo.SoniloError, "file operation"):
                    sonilo.generate_bgm(
                        str(source), str(Path(temp_dir) / "music.m4a"), 5
                    )

            self.assertFalse(proxy.exists())

    def test_generate_bgm_rejects_invalid_duration_and_long_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"video")
            with patch.object(
                sonilo.config, "app", {"sonilo_api_key": "test-key"}
            ):
                for duration in (0, -1, float("nan"), 361):
                    with self.subTest(duration=duration):
                        with self.assertRaises(sonilo.SoniloError):
                            sonilo.generate_bgm(
                                str(source), str(Path(temp_dir) / "music.m4a"), duration
                            )
                with self.assertRaisesRegex(sonilo.SoniloError, "2000"):
                    sonilo.generate_bgm(
                        str(source),
                        str(Path(temp_dir) / "music.m4a"),
                        5,
                        "x" * 2001,
                    )

    def test_generate_bgm_rejects_missing_key_and_input_before_proxy_work(self):
        """缺少凭证或输入文件时应快速失败，不能调用 FFmpeg 或外部 API。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"video")
            with (
                patch.object(sonilo.config, "app", {"sonilo_api_key": ""}),
                patch.dict(os.environ, {}, clear=True),
                patch.object(sonilo, "_create_video_proxy") as create_proxy,
            ):
                with self.assertRaisesRegex(sonilo.SoniloError, "API key"):
                    sonilo.generate_bgm(
                        str(source), str(Path(temp_dir) / "music.m4a"), 5
                    )
                create_proxy.assert_not_called()

            with (
                patch.object(
                    sonilo.config, "app", {"sonilo_api_key": "test-key"}
                ),
                patch.object(sonilo, "_create_video_proxy") as create_proxy,
            ):
                with self.assertRaisesRegex(sonilo.SoniloError, "does not exist"):
                    sonilo.generate_bgm(
                        str(Path(temp_dir) / "missing.mp4"),
                        str(Path(temp_dir) / "music.m4a"),
                        5,
                    )
                create_proxy.assert_not_called()

    def test_connection_checks_only_required_services(self):
        """连接测试按启用功能校验服务，仅音效的 Key 不应因缺少配乐失败。"""
        response = _StreamingResponse(payload={"available_services": ["video-to-sfx"]})
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo.requests, "get", return_value=response),
        ):
            result = sonilo.test_connection(
                required_service_ids=(sonilo.VIDEO_TO_SFX_SERVICE_ID,)
            )
            self.assertEqual(
                result, {"available_services": ["video-to-sfx"]}
            )

            with self.assertRaisesRegex(sonilo.SoniloError, "not available"):
                sonilo.test_connection(
                    required_service_ids=(
                        sonilo.VIDEO_TO_MUSIC_SERVICE_ID,
                        sonilo.VIDEO_TO_SFX_SERVICE_ID,
                    )
                )

    def test_request_sfx_polls_downloads_then_atomically_publishes_audio(self):
        """完整任务管线：提交、轮询到终态、下载校验后原子发布。"""
        audio_bytes = b"synthetic-sfx-audio"
        submit_response = _SfxResponse(
            status_code=202, payload={"task_id": "task-123"}
        )
        poll_responses = [
            _SfxResponse(payload={"status": "processing"}),
            _SfxResponse(
                payload={
                    "status": "succeeded",
                    "audio": {"url": "https://cdn.example.com/task-123.m4a"},
                }
            ),
        ]
        download_response = _SfxResponse(chunks=[audio_bytes])
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "proxy.mp4"
            output_path = Path(temp_dir) / "sfx.m4a"
            video_path.write_bytes(b"video")
            with (
                patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
                patch.object(sonilo, "SFX_POLL_INTERVAL_SECONDS", 0),
                patch.object(
                    sonilo.requests, "post", return_value=submit_response
                ) as post,
                patch.object(
                    sonilo.requests,
                    "get",
                    side_effect=[*poll_responses, download_response],
                ) as get,
                patch.object(
                    sonilo.bgm_service, "validate_audio_file"
                ) as validate_audio,
            ):
                result = sonilo._request_sfx(
                    str(video_path), str(output_path), "rain"
                )

            self.assertEqual(result, str(output_path))
            self.assertEqual(output_path.read_bytes(), audio_bytes)
            validate_audio.assert_called_once()
            self.assertTrue(post.call_args.args[0].endswith("/v1/video-to-sfx"))
            self.assertEqual(post.call_args.kwargs["data"], {"prompt": "rain"})
            poll_call = get.call_args_list[0]
            self.assertTrue(poll_call.args[0].endswith("/v1/tasks/task-123"))
            self.assertEqual(
                poll_call.kwargs["headers"]["Authorization"], "Bearer test-key"
            )
            # 产物 URL 是预签名的：下载请求绝不能携带 Authorization 请求头。
            download_call = get.call_args_list[-1]
            self.assertEqual(
                download_call.args[0], "https://cdn.example.com/task-123.m4a"
            )
            self.assertNotIn("headers", download_call.kwargs)
            self.assertEqual(download_call.kwargs["stream"], True)
            self.assertEqual(list(Path(temp_dir).glob(".sonilo-sfx-*")), [])

    def test_submit_sfx_task_rejects_http_errors_and_missing_task_id(self):
        """提交失败与缺失 task_id 都必须转换为稳定的领域异常。"""
        failure_cases = [
            (_SfxResponse(status_code=401), "401"),
            (_SfxResponse(payload={}), "no task_id"),
            (_SfxResponse(payload=None), "invalid task response"),
        ]
        for response, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                video_path = Path(temp_dir) / "proxy.mp4"
                video_path.write_bytes(b"video")
                with (
                    patch.object(
                        sonilo.config, "app", {"sonilo_api_key": "test-key"}
                    ),
                    patch.object(sonilo.requests, "post", return_value=response),
                ):
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, expected_message
                    ):
                        sonilo._submit_sfx_task(str(video_path), "")

    def test_poll_sfx_task_fails_fast_when_task_is_not_found(self):
        """404 表示任务不存在或不是音效任务，禁止继续轮询消耗时间。"""
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo, "SFX_POLL_INTERVAL_SECONDS", 0),
            patch.object(
                sonilo.requests,
                "get",
                return_value=_SfxResponse(status_code=404),
            ) as get,
        ):
            with self.assertRaisesRegex(sonilo.SoniloError, "not found"):
                sonilo._poll_sfx_task("task-404")

        get.assert_called_once()

    def test_poll_sfx_task_retries_transient_failures_until_terminal(self):
        """网络抖动、5xx 与非法响应体都不终止轮询，任务仍在服务端继续。"""
        terminal_body = {"status": "failed", "error": {"message": "no credit"}}
        responses = [
            sonilo.requests.ConnectionError("connection reset"),
            _SfxResponse(status_code=500),
            _SfxResponse(payload=None),
            _SfxResponse(payload={"status": "processing"}),
            _SfxResponse(payload=terminal_body),
        ]
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo, "SFX_POLL_INTERVAL_SECONDS", 0),
            patch.object(sonilo.requests, "get", side_effect=responses) as get,
        ):
            result = sonilo._poll_sfx_task("task-retry")

        self.assertEqual(result, terminal_body)
        self.assertEqual(get.call_count, len(responses))

    def test_poll_sfx_task_times_out_after_configured_deadline(self):
        """超出总时长上限后必须抛出可降级异常，而不是无限轮询。"""
        with (
            patch.object(sonilo.config, "app", {"sonilo_api_key": "test-key"}),
            patch.object(sonilo, "SFX_POLL_INTERVAL_SECONDS", 0),
            patch.object(sonilo, "_sfx_deadline_seconds", return_value=0.0),
            patch.object(
                sonilo.requests,
                "get",
                return_value=_SfxResponse(payload={"status": "processing"}),
            ),
        ):
            with self.assertRaisesRegex(sonilo.SoniloError, "timed out"):
                sonilo._poll_sfx_task("task-slow")

    def test_download_sfx_audio_rejects_failed_and_artifact_less_tasks(self):
        """失败任务与缺失产物的成功任务都不能进入下载或发布环节。"""
        failure_cases = [
            (
                {"status": "failed", "error": {"message": "credit exhausted"}},
                "credit exhausted",
            ),
            ({"status": "failed", "error": "quota exceeded"}, "quota exceeded"),
            ({"status": "failed"}, "unknown error"),
            ({"status": "succeeded"}, "no audio artifact"),
            ({"status": "succeeded", "audio": {}}, "no audio artifact"),
        ]
        for task_body, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                with patch.object(sonilo.requests, "get") as get:
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, expected_message
                    ):
                        sonilo._download_sfx_audio(
                            task_body,
                            str(Path(temp_dir) / "sfx.m4a"),
                            "task-bad",
                        )
                get.assert_not_called()

    def test_download_sfx_audio_rejects_empty_and_oversized_artifacts(self):
        """下载体积必须与配乐使用同一上限，空产物同样不能发布。"""
        task_body = {
            "status": "succeeded",
            "audio": {"url": "https://cdn.example.com/task.m4a"},
        }
        cases = [
            (_SfxResponse(chunks=[]), "no audio data"),
            (_SfxResponse(chunks=[b"1234"]), "exceeds"),
            (_SfxResponse(status_code=403), "download failed"),
        ]
        for response, expected_message in cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                with (
                    patch.object(sonilo, "MAX_GENERATED_AUDIO_BYTES", 3),
                    patch.object(sonilo.requests, "get", return_value=response),
                ):
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, expected_message
                    ):
                        sonilo._download_sfx_audio(
                            task_body,
                            str(Path(temp_dir) / "sfx.m4a"),
                            "task-size",
                        )

    def test_request_sfx_preserves_existing_output_and_cleans_temp_on_failures(self):
        """提交、轮询、下载和校验失败都不能覆盖已有结果或留下半成品。"""
        succeeded_poll = _SfxResponse(
            payload={
                "status": "succeeded",
                "audio": {"url": "https://cdn.example.com/task.m4a"},
            }
        )
        failure_cases = [
            (
                _SfxResponse(status_code=401),
                [],
                None,
                "401",
            ),
            (
                _SfxResponse(status_code=202, payload={"task_id": "task-a"}),
                [_SfxResponse(status_code=404)],
                None,
                "not found",
            ),
            (
                _SfxResponse(status_code=202, payload={"task_id": "task-b"}),
                [succeeded_poll, _SfxResponse(chunks=[b"invalid-audio"])],
                sonilo.bgm_service.BgmUploadError("invalid audio"),
                "cannot decode",
            ),
        ]
        for submit_response, get_responses, validation_error, expected in (
            failure_cases
        ):
            with (
                self.subTest(expected_message=expected),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                video_path = Path(temp_dir) / "proxy.mp4"
                output_path = Path(temp_dir) / "sfx.m4a"
                video_path.write_bytes(b"video")
                output_path.write_bytes(b"existing-sfx")
                with (
                    patch.object(
                        sonilo.config, "app", {"sonilo_api_key": "test-key"}
                    ),
                    patch.object(sonilo, "SFX_POLL_INTERVAL_SECONDS", 0),
                    patch.object(
                        sonilo.requests, "post", return_value=submit_response
                    ),
                    patch.object(
                        sonilo.requests, "get", side_effect=get_responses
                    ),
                    patch.object(
                        sonilo.bgm_service,
                        "validate_audio_file",
                        side_effect=validation_error,
                    ),
                ):
                    with self.assertRaisesRegex(sonilo.SoniloError, expected):
                        sonilo._request_sfx(
                            str(video_path), str(output_path), ""
                        )

                self.assertEqual(output_path.read_bytes(), b"existing-sfx")
                self.assertEqual(list(Path(temp_dir).glob(".sonilo-sfx-*")), [])

    def test_generate_sfx_enforces_stricter_duration_limit_than_music(self):
        """音效上限是 180 秒；180 秒以内继续执行，超过则上传前直接失败。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"video")
            with patch.object(
                sonilo.config, "app", {"sonilo_api_key": "test-key"}
            ):
                for duration in (0, -1, float("nan"), 181, 360):
                    with self.subTest(duration=duration):
                        with self.assertRaises(sonilo.SoniloError):
                            sonilo.generate_sfx(
                                str(source),
                                str(Path(temp_dir) / "sfx.m4a"),
                                duration,
                            )
                with self.assertRaisesRegex(sonilo.SoniloError, "2000"):
                    sonilo.generate_sfx(
                        str(source),
                        str(Path(temp_dir) / "sfx.m4a"),
                        5,
                        "x" * 2001,
                    )
                with (
                    patch.object(
                        sonilo, "_create_video_proxy", return_value="proxy.mp4"
                    ),
                    patch.object(
                        sonilo, "_request_sfx", return_value="sfx.m4a"
                    ) as request_sfx,
                ):
                    result = sonilo.generate_sfx(
                        str(source), str(Path(temp_dir) / "sfx.m4a"), 180
                    )
                self.assertEqual(result, "sfx.m4a")
                request_sfx.assert_called_once()

    def test_generate_sfx_cleans_proxy_and_converts_file_errors(self):
        """任务失败与文件系统失败都必须清理代理并保持可降级异常。"""
        failure_cases = [
            (sonilo.SoniloError("task failed"), "task failed"),
            (OSError("disk full"), "file operation"),
        ]
        for request_error, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                source = Path(temp_dir) / "source.mp4"
                proxy = Path(temp_dir) / "proxy.mp4"
                source.write_bytes(b"video")
                proxy.write_bytes(b"proxy")
                with (
                    patch.object(
                        sonilo.config, "app", {"sonilo_api_key": "test-key"}
                    ),
                    patch.object(
                        sonilo, "_create_video_proxy", return_value=str(proxy)
                    ),
                    patch.object(
                        sonilo, "_request_sfx", side_effect=request_error
                    ),
                ):
                    with self.assertRaisesRegex(
                        sonilo.SoniloError, expected_message
                    ):
                        sonilo.generate_sfx(
                            str(source), str(Path(temp_dir) / "sfx.m4a"), 5
                        )

                self.assertFalse(proxy.exists())

    def test_generate_sfx_rejects_missing_key_and_input_before_proxy_work(self):
        """缺少凭证或输入文件时应快速失败，不能调用 FFmpeg 或外部 API。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"video")
            with (
                patch.object(sonilo.config, "app", {"sonilo_api_key": ""}),
                patch.dict(os.environ, {}, clear=True),
                patch.object(sonilo, "_create_video_proxy") as create_proxy,
            ):
                with self.assertRaisesRegex(sonilo.SoniloError, "API key"):
                    sonilo.generate_sfx(
                        str(source), str(Path(temp_dir) / "sfx.m4a"), 5
                    )
                create_proxy.assert_not_called()

            with (
                patch.object(
                    sonilo.config, "app", {"sonilo_api_key": "test-key"}
                ),
                patch.object(sonilo, "_create_video_proxy") as create_proxy,
            ):
                with self.assertRaisesRegex(sonilo.SoniloError, "does not exist"):
                    sonilo.generate_sfx(
                        str(Path(temp_dir) / "missing.mp4"),
                        str(Path(temp_dir) / "sfx.m4a"),
                        5,
                    )
                create_proxy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
