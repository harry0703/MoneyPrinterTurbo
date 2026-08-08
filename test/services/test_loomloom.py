import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.loomloom import (
    LoomLoomAPIError,
    LoomLoomConfigurationError,
    LoomLoomRun,
    LoomLoomRunError,
    LoomLoomScriptBackend,
    LoomLoomSettings,
    LoomLoomVideoBackend,
    video_settings_from_mapping,
)


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _DownloadResponse:
    status_code = 200
    headers = {"content-length": "11"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        del chunk_size
        return iter((b"video-bytes",))


class TestLoomLoomSettings(unittest.TestCase):
    def test_requires_public_api_connection_settings(self):
        with self.assertRaisesRegex(
            LoomLoomConfigurationError,
            "loomloom_base_url, loomloom_api_token, loomloom_market_listing_id",
        ):
            LoomLoomSettings.from_mapping({})

    def test_normalizes_settings_without_exposing_token(self):
        settings = LoomLoomSettings.from_mapping(
            {
                "loomloom_base_url": "https://example.test/loom/v1/",
                "loomloom_api_token": "secret-token",
                "loomloom_market_listing_id": "listing-1",
            }
        )

        self.assertEqual(settings.base_url, "https://example.test/loom/v1")
        self.assertNotIn("secret-token", repr(settings))

    def test_builds_separate_video_listing_settings(self):
        settings = video_settings_from_mapping(
            {
                "loomloom_base_url": "https://example.test/loom/v1",
                "loomloom_api_token": "secret-token",
                "loomloom_market_listing_id": "script-listing",
                "loomloom_video_market_listing_id": "video-listing",
                "loomloom_video_market_listing_version_id": "video-version",
            }
        )

        self.assertEqual(settings.market_listing_id, "video-listing")
        self.assertEqual(settings.listing_version_id, "video-version")
        self.assertEqual(settings.run_timeout_seconds, 1800)


class TestLoomLoomScriptBackend(unittest.TestCase):
    def setUp(self):
        self.settings = LoomLoomSettings(
            base_url="https://example.test/loom/v1",
            api_token="test-token",
            market_listing_id="listing/1",
            listing_version_id="version-1",
            result_port_name="result",
            poll_interval_seconds=0.01,
            run_timeout_seconds=1,
        )
        self.session = MagicMock()
        self.backend = LoomLoomScriptBackend(
            self.settings,
            session=self.session,
        )

    def test_prepares_one_independent_input_row_per_candidate(self):
        batch = self.backend.prepare_script_batch(
            subject="人工智能改变生活",
            candidate_count=3,
            language="zh-CN",
            duration_seconds=45,
            style="知识类",
        )

        self.assertEqual(len(batch.input_rows), 3)
        self.assertEqual(batch.input_rows[0]["candidateIndex"], "1")
        self.assertEqual(batch.input_rows[2]["candidateIndex"], "3")
        self.assertEqual(
            batch.input_rows[0]["requirements"],
            "输出语言：zh-CN\n目标时长（秒）：45\n风格或附加要求：知识类",
        )
        self.assertEqual(batch.input_rows[0]["subject"], "人工智能改变生活")

    def test_quote_uses_market_listing_public_contract(self):
        self.session.request.return_value = _Response(
            200,
            {
                "quoteId": "quote-1",
                "listingVersionId": "version-1",
                "currency": "CNY",
                "taskCount": 2,
                "estimatedBuyerPayableT": 12345,
                "estimatedBuyerPayable": {"amount": "0.0012345", "currency": "CNY"},
            },
        )
        batch = self.backend.prepare_script_batch(subject="主题", candidate_count=2)

        result = self.backend.quote(batch)

        self.assertEqual(result.quote_id, "quote-1")
        self.assertEqual(result.task_count, 2)
        self.assertEqual(result.estimated_buyer_payable_amount, "0.0012345")
        request = self.session.request.call_args
        self.assertEqual(request.args[0], "POST")
        self.assertEqual(
            request.args[1],
            "https://example.test/loom/v1/marketListings/listing%2F1:quote",
        )
        self.assertEqual(
            request.kwargs["headers"]["Authorization"], "Bearer test-token"
        )
        self.assertEqual(request.kwargs["json"]["listingVersionId"], "version-1")
        self.assertEqual(len(request.kwargs["json"]["inputRows"]), 2)

    def test_execute_requires_explicit_confirmation_before_network(self):
        batch = self.backend.prepare_script_batch(subject="主题", candidate_count=1)

        with self.assertRaisesRegex(ValueError, "confirm=True"):
            self.backend.execute(
                batch,
                client_request_id="request-1",
                listing_version_id="version-1",
                confirm=False,
            )

        self.session.request.assert_not_called()

    def test_execute_sends_stable_request_id_and_returns_run(self):
        self.session.request.return_value = _Response(
            201,
            {
                "runId": "run-1",
                "runTransactionId": "transaction-1",
                "transactionStatus": "running",
                "listingVersionId": "version-1",
            },
        )
        batch = self.backend.prepare_script_batch(subject="主题", candidate_count=1)

        result = self.backend.execute(
            batch,
            client_request_id="request-1",
            listing_version_id="quoted-version-1",
            confirm=True,
        )

        self.assertEqual(result.run_id, "run-1")
        payload = self.session.request.call_args.kwargs["json"]
        self.assertEqual(payload["clientRequestId"], "request-1")
        self.assertEqual(payload["listingVersionId"], "quoted-version-1")
        self.assertIs(payload["confirm"], True)

    def test_request_can_use_a_per_user_credential_provider(self):
        settings = LoomLoomSettings(
            base_url="https://example.test/loom/v1",
            api_token="",
            market_listing_id="listing-1",
        )
        session = MagicMock()
        session.request.return_value = _Response(
            200,
            {
                "quoteId": "quote-1",
                "listingVersionId": "version-1",
                "taskCount": 1,
                "estimatedBuyerPayableT": 0,
            },
        )
        backend = LoomLoomScriptBackend(
            settings,
            session=session,
            credential_provider=lambda: "current-user-token",
        )
        batch = backend.prepare_script_batch(subject="主题", candidate_count=1)

        backend.quote(batch)

        self.assertEqual(
            session.request.call_args.kwargs["headers"]["Authorization"],
            "Bearer current-user-token",
        )

    def test_wait_for_run_polls_until_completed(self):
        running = LoomLoomRun("run-1", "running", 1, 0, 0, 0, "")
        completed = LoomLoomRun("run-1", "completed", 1, 1, 0, 0, "")
        self.backend.get_run = MagicMock(side_effect=[running, completed])
        self.backend._sleep = MagicMock()

        result = self.backend.wait_for_run("run-1")

        self.assertEqual(result.status, "completed")
        self.backend._sleep.assert_called_once_with(0.01)

    def test_wait_for_run_surfaces_terminal_failure(self):
        failed = LoomLoomRun("run-1", "failed", 1, 0, 1, 0, "model timeout")
        self.backend.get_run = MagicMock(return_value=failed)

        with self.assertRaisesRegex(LoomLoomRunError, "model timeout"):
            self.backend.wait_for_run("run-1")

    def test_get_script_results_follows_pagination_and_ignores_step_id(self):
        successful_artifact = {
            "stepId": "internal-step-that-may-change",
            "portName": "result",
            "inlineText": json.dumps(
                {
                    "script": "第一条脚本",
                    "videoTerms": ["人工智能", "日常生活"],
                },
                ensure_ascii=False,
            ),
        }
        self.session.request.side_effect = [
            _Response(
                200,
                {
                    "items": [
                        {
                            "rowIndex": 0,
                            "status": "completed",
                            "artifacts": [successful_artifact],
                        }
                    ],
                    "nextPageToken": "page-2",
                },
            ),
            _Response(
                200,
                {
                    "items": [
                        {
                            "rowIndex": 1,
                            "status": "failed",
                            "errorMessage": "model timeout",
                            "artifacts": [],
                        }
                    ]
                },
            ),
        ]

        result = self.backend.get_script_results("run-1")

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].script, "第一条脚本")
        self.assertEqual(result.candidates[0].video_terms, ("人工智能", "日常生活"))
        self.assertEqual(result.errors[0].message, "model timeout")
        second_request = self.session.request.call_args_list[1]
        self.assertEqual(second_request.kwargs["params"]["pageToken"], "page-2")

    def test_get_script_results_accepts_json_code_fence_from_model(self):
        self.session.request.return_value = _Response(
            200,
            {
                "items": [
                    {
                        "rowIndex": 0,
                        "status": "completed",
                        "artifacts": [
                            {
                                "portName": "result",
                                "inlineText": (
                                    "```json\n"
                                    '{"script":"第一条脚本","videoTerms":["AI"]}\n'
                                    "```"
                                ),
                            }
                        ],
                    }
                ]
            },
        )

        result = self.backend.get_script_results("run-1")

        self.assertEqual(result.candidates[0].script, "第一条脚本")
        self.assertEqual(result.candidates[0].video_terms, ("AI",))

    def test_result_contract_requires_one_inline_json_result_artifact(self):
        self.session.request.return_value = _Response(
            200,
            {
                "items": [
                    {
                        "rowIndex": 0,
                        "status": "completed",
                        "artifacts": [
                            {
                                "portName": "result",
                                "inlineText": '{"script":"missing terms"}',
                            }
                        ],
                    }
                ]
            },
        )

        result = self.backend.get_script_results("run-1")

        self.assertEqual(result.candidates, ())
        self.assertIn("videoTerms", result.errors[0].message)

    def test_api_error_exposes_status_but_not_arbitrary_response_body(self):
        self.session.request.return_value = _Response(
            402,
            {"error": "insufficient balance", "sensitive": "do-not-copy"},
        )
        batch = self.backend.prepare_script_batch(subject="主题", candidate_count=1)

        with self.assertRaisesRegex(
            LoomLoomAPIError, "HTTP 402: insufficient balance"
        ) as captured:
            self.backend.quote(batch)

        self.assertNotIn("do-not-copy", str(captured.exception))


class TestLoomLoomVideoBackend(unittest.TestCase):
    def setUp(self):
        self.settings = LoomLoomSettings(
            base_url="https://example.test/loom/v1",
            api_token="test-token",
            market_listing_id="video-listing",
            listing_version_id="video-version",
            result_port_name="output",
        )
        self.session = MagicMock()
        self.backend = LoomLoomVideoBackend(self.settings, session=self.session)

    def test_prepares_one_video_row_per_scene(self):
        batch = self.backend.prepare_video_batch(
            subject="AI 办公效率",
            scene_prompts=["office worker", "AI assistant"],
            aspect_ratio="9:16",
        )

        self.assertEqual(len(batch.input_rows), 2)
        self.assertEqual(batch.input_rows[0]["aspectRatio"], "9:16")
        self.assertEqual(batch.input_rows[1]["sceneIndex"], "2")
        self.assertIn("office worker", batch.input_rows[0]["scenePrompt"])
        self.assertIn("No text", batch.input_rows[0]["scenePrompt"])

    def test_downloads_video_artifacts_without_forwarding_api_token(self):
        self.session.request.return_value = _Response(
            200,
            {
                "items": [
                    {
                        "rowIndex": 0,
                        "status": "completed",
                        "artifacts": [
                            {
                                "portName": "output",
                                "mimeType": "video/mp4",
                                "accessUrl": "https://objects.test/video.mp4?signature=x",
                            }
                        ],
                    }
                ]
            },
        )
        self.session.get.return_value = _DownloadResponse()

        with tempfile.TemporaryDirectory() as directory:
            paths = self.backend.download_video_results("run-1", directory)

            self.assertEqual(Path(paths[0]).read_bytes(), b"video-bytes")
        self.session.get.assert_called_once_with(
            "https://objects.test/video.mp4?signature=x",
            stream=True,
            timeout=(5.0, self.settings.request_timeout_seconds),
        )

    def test_rejects_non_video_result_artifact(self):
        self.session.request.return_value = _Response(
            200,
            {
                "items": [
                    {
                        "rowIndex": 0,
                        "status": "completed",
                        "artifacts": [
                            {
                                "portName": "output",
                                "mimeType": "text/plain",
                                "accessUrl": "https://objects.test/result.txt",
                            }
                        ],
                    }
                ]
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(LoomLoomAPIError, "video/mp4"):
                self.backend.download_video_results("run-1", directory)
