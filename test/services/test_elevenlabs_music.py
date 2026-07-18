import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import elevenlabs_music


class _StreamingResponse:
    """提供 ElevenLabs 配乐服务实际使用的最小 Response 接口。"""

    def __init__(
        self,
        chunks=None,
        *,
        status_code=200,
        payload=None,
        iter_error=None,
    ):
        self.chunks = chunks or []
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.reason = "OK" if self.ok else "Request failed"
        self.text = "" if self.ok else "request failed"
        self.payload = payload if payload is not None else {"user_id": "test"}
        self.iter_error = iter_error

    def iter_content(self, chunk_size):
        if self.iter_error:
            raise self.iter_error
        return iter(self.chunks)

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestElevenLabsMusicService(unittest.TestCase):
    def test_api_key_prefers_config_and_falls_back_to_environment(self):
        with (
            patch.object(
                elevenlabs_music.config,
                "elevenlabs",
                {"api_key": "config-key"},
            ),
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "env-key"}),
        ):
            self.assertEqual(elevenlabs_music.get_api_key(), "config-key")

        with (
            patch.object(
                elevenlabs_music.config,
                "elevenlabs",
                {"api_key": ""},
            ),
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "env-key"}),
        ):
            self.assertEqual(elevenlabs_music.get_api_key(), "env-key")

    def test_model_and_timeout_reject_invalid_configuration(self):
        """第三方请求配置异常时必须回退安全默认值，不能让任务直接崩溃。"""
        test_cases = [
            ({"music_model_id": "music_v1"}, "music_v1", (15, 600)),
            (
                {"music_model_id": "unknown", "music_timeout": 0.2},
                "music_v2",
                (15, 1),
            ),
            (
                {"music_model_id": "", "music_timeout": float("inf")},
                "music_v2",
                (15, 600),
            ),
            (
                {"music_timeout": 2000},
                "music_v2",
                (15, 1800),
            ),
        ]
        for configured, expected_model, expected_timeout in test_cases:
            with self.subTest(configured=configured), patch.object(
                elevenlabs_music.config, "elevenlabs", configured
            ):
                self.assertEqual(elevenlabs_music._model_id(), expected_model)
                self.assertEqual(
                    elevenlabs_music._request_timeout(), expected_timeout
                )

    def test_connection_uses_non_billing_user_endpoint(self):
        response = _StreamingResponse(payload={"tier": "creator"})
        with (
            patch.object(
                elevenlabs_music.config,
                "elevenlabs",
                {"api_key": "test-key"},
            ),
            patch.object(
                elevenlabs_music.requests,
                "get",
                return_value=response,
            ) as request,
        ):
            result = elevenlabs_music.test_connection()

        self.assertEqual(result, {"tier": "creator"})
        self.assertTrue(
            request.call_args.args[0].endswith("/v1/user/subscription")
        )
        self.assertEqual(
            request.call_args.kwargs["headers"]["xi-api-key"], "test-key"
        )

    def test_connection_converts_http_network_and_payload_errors(self):
        failure_cases = [
            (_StreamingResponse(status_code=401), None, "401"),
            (
                None,
                elevenlabs_music.requests.Timeout("timed out"),
                "failed to connect",
            ),
            (
                _StreamingResponse(payload=[]),
                None,
                "unexpected subscription response",
            ),
            (
                _StreamingResponse(payload={"user_id": "test"}),
                None,
                "does not include an account tier",
            ),
        ]
        for response, request_error, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                patch.object(
                    elevenlabs_music.config,
                    "elevenlabs",
                    {"api_key": "test-key"},
                ),
                patch.object(
                    elevenlabs_music.requests,
                    "get",
                    return_value=response,
                    side_effect=request_error,
                ),
            ):
                with self.assertRaisesRegex(
                    elevenlabs_music.ElevenLabsMusicError,
                    expected_message,
                ):
                    elevenlabs_music.test_connection()

    def test_generation_access_only_blocks_deterministic_account_errors(self):
        """
        免费套餐和无效 Key 必须阻止昂贵任务；订阅接口范围或网络问题无法证明
        Music API 不可用，只能记录警告并交给实际生成请求确认。
        """
        deterministic_errors = [
            elevenlabs_music.ElevenLabsPaidPlanRequiredError("paid plan"),
            elevenlabs_music.ElevenLabsAuthenticationError("invalid key"),
        ]
        for error in deterministic_errors:
            with (
                self.subTest(error=type(error).__name__),
                patch.object(
                    elevenlabs_music,
                    "test_connection",
                    side_effect=error,
                ),
                self.assertRaises(type(error)),
            ):
                elevenlabs_music.validate_generation_access()

        with (
            patch.object(
                elevenlabs_music,
                "test_connection",
                side_effect=elevenlabs_music.ElevenLabsMusicError(
                    "subscription endpoint is restricted"
                ),
            ),
            patch.object(elevenlabs_music.logger, "warning") as warning,
        ):
            self.assertIsNone(elevenlabs_music.validate_generation_access())

        self.assertIn("inconclusive", str(warning.call_args))

    def test_connection_rejects_free_plan_before_music_generation(self):
        """免费套餐不支持 Music API，应在上传视频前给出明确错误。"""
        response = _StreamingResponse(payload={"tier": "free"})
        with (
            patch.object(
                elevenlabs_music.config,
                "elevenlabs",
                {"api_key": "test-key"},
            ),
            patch.object(
                elevenlabs_music.requests,
                "get",
                return_value=response,
            ),
        ):
            with self.assertRaisesRegex(
                elevenlabs_music.ElevenLabsMusicError,
                "requires a paid plan",
            ):
                elevenlabs_music.test_connection()

    def test_create_video_proxy_removes_audio_and_limits_dimensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"source-video")

            def create_proxy(command, **_kwargs):
                Path(command[-1]).write_bytes(b"proxy-video")
                return elevenlabs_music.subprocess.CompletedProcess(
                    command, 0, "", ""
                )

            with (
                patch.object(
                    elevenlabs_music.utils,
                    "get_ffmpeg_binary",
                    return_value="test-ffmpeg",
                ),
                patch.object(
                    elevenlabs_music.subprocess,
                    "run",
                    side_effect=create_proxy,
                ) as run,
            ):
                proxy_path = elevenlabs_music._create_video_proxy(str(source))

            command = run.call_args.args[0]
            self.assertEqual(command[0], "test-ffmpeg")
            self.assertIn("-an", command)
            self.assertIn(
                "force_original_aspect_ratio=decrease",
                command[command.index("-vf") + 1],
            )
            self.assertEqual(Path(proxy_path).read_bytes(), b"proxy-video")
            Path(proxy_path).unlink()

    def test_create_video_proxy_cleans_partial_files_on_failures(self):
        failures = [
            (
                elevenlabs_music.subprocess.TimeoutExpired("ffmpeg", 600),
                "timed out",
            ),
            (OSError("ffmpeg missing"), "failed to run FFmpeg"),
            (
                elevenlabs_music.subprocess.CompletedProcess(
                    ["ffmpeg"], 1, "", "encoder unavailable"
                ),
                "encoder unavailable",
            ),
        ]
        for result_or_error, expected_message in failures:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                source = Path(temp_dir) / "source.mp4"
                source.write_bytes(b"source-video")
                run_kwargs = (
                    {"return_value": result_or_error}
                    if isinstance(
                        result_or_error,
                        elevenlabs_music.subprocess.CompletedProcess,
                    )
                    else {"side_effect": result_or_error}
                )
                with patch.object(
                    elevenlabs_music.subprocess, "run", **run_kwargs
                ):
                    with self.assertRaisesRegex(
                        elevenlabs_music.ElevenLabsMusicError,
                        expected_message,
                    ):
                        elevenlabs_music._create_video_proxy(str(source))

                self.assertEqual(
                    list(
                        Path(temp_dir).glob(
                            ".elevenlabs-music-proxy-*"
                        )
                    ),
                    [],
                )

    def test_stream_audio_rejects_empty_and_oversized_responses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "music.mp3"
            with self.assertRaisesRegex(
                elevenlabs_music.ElevenLabsMusicError, "no audio"
            ):
                elevenlabs_music._stream_audio(
                    _StreamingResponse([]), str(output_path)
                )

            with (
                patch.object(
                    elevenlabs_music,
                    "MAX_GENERATED_AUDIO_BYTES",
                    3,
                ),
                self.assertRaisesRegex(
                    elevenlabs_music.ElevenLabsMusicError, "50 MB"
                ),
            ):
                elevenlabs_music._stream_audio(
                    _StreamingResponse([b"four"]), str(output_path)
                )

    def test_request_bgm_sends_official_multipart_and_publishes_atomically(self):
        audio_bytes = b"generated-mp3"
        response = _StreamingResponse([audio_bytes])
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "proxy.mp4"
            output_path = Path(temp_dir) / "music.mp3"
            video_path.write_bytes(b"video")
            with (
                patch.object(
                    elevenlabs_music.config,
                    "elevenlabs",
                    {
                        "api_key": "test-key",
                        "music_model_id": "music_v2",
                    },
                ),
                patch.object(
                    elevenlabs_music.requests,
                    "post",
                    return_value=response,
                ) as post,
                patch.object(
                    elevenlabs_music.bgm_service,
                    "validate_audio_file",
                ) as validate_audio,
            ):
                result = elevenlabs_music._request_bgm(
                    str(video_path), str(output_path), "warm cinematic"
                )

            self.assertEqual(result, str(output_path))
            self.assertEqual(output_path.read_bytes(), audio_bytes)
            validate_audio.assert_called_once()
            self.assertEqual(
                post.call_args.kwargs["data"],
                {
                    "model_id": "music_v2",
                    "description": "warm cinematic",
                },
            )
            self.assertEqual(
                post.call_args.kwargs["params"]["output_format"],
                "mp3_44100_128",
            )
            # 生产接口实际接收 ``videos``；使用文档示例中的 ``videos[]`` 会
            # 返回 422 Field required，因此测试固定真实可用的协议字段。
            self.assertEqual(post.call_args.kwargs["files"][0][0], "videos")
            self.assertEqual(post.call_args.kwargs["stream"], True)
            self.assertEqual(
                list(Path(temp_dir).glob(".elevenlabs-music-*")), []
            )

    def test_request_bgm_preserves_existing_output_after_failures(self):
        failure_cases = [
            (_StreamingResponse(status_code=403), None, "403"),
            (
                _StreamingResponse(
                    iter_error=elevenlabs_music.requests.ConnectionError(
                        "stream lost"
                    )
                ),
                None,
                "failed to request",
            ),
            (
                _StreamingResponse([b"invalid-audio"]),
                elevenlabs_music.bgm_service.BgmUploadError("invalid"),
                "cannot decode",
            ),
        ]
        for response, validation_error, expected_message in failure_cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                video_path = Path(temp_dir) / "proxy.mp4"
                output_path = Path(temp_dir) / "music.mp3"
                video_path.write_bytes(b"video")
                output_path.write_bytes(b"existing-music")
                with (
                    patch.object(
                        elevenlabs_music.config,
                        "elevenlabs",
                        {"api_key": "test-key"},
                    ),
                    patch.object(
                        elevenlabs_music.requests,
                        "post",
                        return_value=response,
                    ),
                    patch.object(
                        elevenlabs_music.bgm_service,
                        "validate_audio_file",
                        side_effect=validation_error,
                    ),
                ):
                    with self.assertRaisesRegex(
                        elevenlabs_music.ElevenLabsMusicError,
                        expected_message,
                    ):
                        elevenlabs_music._request_bgm(
                            str(video_path), str(output_path), ""
                        )

                self.assertEqual(output_path.read_bytes(), b"existing-music")
                self.assertEqual(
                    list(Path(temp_dir).glob(".elevenlabs-music-*")), []
                )

    def test_generate_bgm_validates_boundaries_before_proxy_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"video")
            with (
                patch.object(
                    elevenlabs_music.config,
                    "elevenlabs",
                    {"api_key": "test-key"},
                ),
                patch.object(
                    elevenlabs_music, "_create_video_proxy"
                ) as create_proxy,
            ):
                for duration in (0, -1, float("nan"), 601):
                    with self.subTest(duration=duration):
                        with self.assertRaises(
                            elevenlabs_music.ElevenLabsMusicError
                        ):
                            elevenlabs_music.generate_bgm(
                                str(source),
                                str(Path(temp_dir) / "music.mp3"),
                                duration,
                            )
                with self.assertRaisesRegex(
                    elevenlabs_music.ElevenLabsMusicError, "1000"
                ):
                    elevenlabs_music.generate_bgm(
                        str(source),
                        str(Path(temp_dir) / "music.mp3"),
                        5,
                        "x" * 1001,
                    )
                create_proxy.assert_not_called()

    def test_generate_bgm_cleans_proxy_when_request_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            proxy = Path(temp_dir) / "proxy.mp4"
            source.write_bytes(b"video")
            proxy.write_bytes(b"proxy")
            with (
                patch.object(
                    elevenlabs_music.config,
                    "elevenlabs",
                    {"api_key": "test-key"},
                ),
                patch.object(
                    elevenlabs_music,
                    "_create_video_proxy",
                    return_value=str(proxy),
                ),
                patch.object(
                    elevenlabs_music,
                    "_request_bgm",
                    side_effect=elevenlabs_music.ElevenLabsMusicError(
                        "network failed"
                    ),
                ),
            ):
                with self.assertRaises(
                    elevenlabs_music.ElevenLabsMusicError
                ):
                    elevenlabs_music.generate_bgm(
                        str(source),
                        str(Path(temp_dir) / "music.mp3"),
                        5,
                    )

            self.assertFalse(proxy.exists())


if __name__ == "__main__":
    unittest.main()
