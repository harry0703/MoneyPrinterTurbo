import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import sonilo


class _StreamingResponse:
    """Provide the minimal requests.Response interface actually used by the Sonilo service."""

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
        """The read timeout must remain a positive integer accepted by Requests, with a bounded maximum wait."""
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
        """The public docs' hyphenated spelling must be normalized to the project's internal service identifier."""
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
        """A 200 response missing the canonical service list must not report a successful connection to the WebUI."""
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
        """Both network interruptions and non-JSON responses in the connectivity test convert to stable domain exceptions."""
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
        """A successful proxy must strip the audio track, constrain dimensions, and let the caller take over the generated file."""
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
        """FFmpeg timeouts, non-executables, and encode failures must never leave hidden proxy files behind."""
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
        """Even when FFmpeg reports success, re-validate that the proxy file exists, is non-empty, and under the size cap."""
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
        """Server errors, completion-only events, and oversized audio must not be published as valid BGM."""
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
                # All cases share a smaller size cap; error events and empty results are unaffected by the value,
                # and the over-limit case needs no 30 MB allocation in the test.
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
        """HTTP, stream-read, and audio-validation failures must neither overwrite existing results nor leave partial files."""
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
        """Filesystem failures must also convert to degradable exceptions and clean up proxies already generated."""
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
        """Missing credentials or input files should fail fast without calling FFmpeg or external APIs."""
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


if __name__ == "__main__":
    unittest.main()
