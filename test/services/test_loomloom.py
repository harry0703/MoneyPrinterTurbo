import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.loomloom import (
    DEFAULT_BASE_URL,
    DEFAULT_SCRIPT_MARKET_LISTING_ID,
    DEFAULT_VIDEO_MARKET_LISTING_ID,
    MAX_VIDEO_ARTIFACT_BYTES,
    LoomLoomAPIError,
    LoomLoomConfigurationError,
    LoomLoomRun,
    LoomLoomRunError,
    LoomLoomScriptBackend,
    LoomLoomSettings,
    LoomLoomVideoBackend,
    resolve_api_token,
    video_settings_from_mapping,
)


def _video_capability_payload(
    *, models=None, default_model_id="model-a", include_target_profile=True
):
    matches = [
        {
            "profile": {
                "profileId": "unrelated.profile",
                "operations": {"defaultModelId": "wrong-model"},
            },
            "eligibleModels": [
                {"modelId": "wrong-model", "displayName": "Wrong Model"}
            ],
        }
    ]
    if include_target_profile:
        matches.append(
            {
                "profile": {
                    "profileId": "video.text-to-video.aspect-ratio.v1",
                    "operations": {"defaultModelId": default_model_id},
                    "definition": {
                        "constraints": {
                            "ports": {"aspect_ratio": {"enum": ["16:9", "9:16"]}}
                        }
                    },
                },
                "eligibleModels": (
                    [
                        {"modelId": "model-a", "displayName": "Model A"},
                        {"modelId": "model-b", "displayName": "Model B"},
                    ]
                    if models is None
                    else models
                ),
            }
        )
    return {"matches": matches}


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

    def __init__(self, *, headers=None):
        self.headers = headers or {"content-length": "11"}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        del chunk_size
        return iter((b"video-bytes",))

    def close(self):
        self.closed = True


class TestLoomLoomSettings(unittest.TestCase):
    def test_requires_api_key_when_config_is_empty(self):
        with self.assertRaisesRegex(
            LoomLoomConfigurationError,
            "loomloom_api_token",
        ):
            LoomLoomSettings.from_mapping({})

    def test_does_not_read_api_key_from_process_environment(self):
        with patch.dict(os.environ, {"SHENGSUANYUN_API_KEY": "environment-key"}):
            self.assertEqual(resolve_api_token({}), "")

    def test_selected_shengsuanyun_provider_reuses_its_api_key(self):
        values = {
            "llm_provider": "shengsuanyun",
            "shengsuanyun_api_key": "provider-key",
            "loomloom_api_token": "standalone-key",
        }

        self.assertEqual(resolve_api_token(values), "provider-key")

    def test_uses_public_defaults_with_configured_api_key(self):
        settings = LoomLoomSettings.from_mapping(
            {"loomloom_api_token": "configured-key"},
        )

        self.assertEqual(settings.base_url, DEFAULT_BASE_URL)
        self.assertEqual(settings.api_token, "configured-key")
        self.assertEqual(settings.market_listing_id, DEFAULT_SCRIPT_MARKET_LISTING_ID)

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

    def test_video_settings_use_fixed_default_skillbot(self):
        settings = video_settings_from_mapping(
            {
                "loomloom_api_token": "secret-token",
                "loomloom_market_listing_id": "ignored-user-listing",
            }
        )

        self.assertEqual(settings.market_listing_id, DEFAULT_VIDEO_MARKET_LISTING_ID)
        self.assertEqual(
            settings.market_listing_id,
            "01a06563-7331-773a-b9b2-25989a0dd70e",
        )
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

    def test_execute_retries_transient_failure_with_same_idempotency_key(self):
        self.session.request.side_effect = [
            _Response(503, {"error": "temporarily unavailable"}),
            _Response(
                201,
                {
                    "runId": "run-1",
                    "runTransactionId": "transaction-1",
                    "transactionStatus": "running",
                    "listingVersionId": "version-1",
                },
            ),
        ]
        self.backend._sleep = MagicMock()
        batch = self.backend.prepare_script_batch(subject="主题", candidate_count=1)

        result = self.backend.execute(
            batch,
            client_request_id="stable-request-id",
            listing_version_id="quoted-version-1",
            confirm=True,
        )

        self.assertEqual(result.run_id, "run-1")
        self.assertEqual(self.session.request.call_count, 2)
        request_ids = [
            call.kwargs["json"]["clientRequestId"]
            for call in self.session.request.call_args_list
        ]
        self.assertEqual(request_ids, ["stable-request-id", "stable-request-id"])
        self.backend._sleep.assert_called_once_with(1.0)

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

    def test_wait_for_run_recovers_from_transient_poll_failure(self):
        completed = LoomLoomRun("run-1", "completed", 1, 1, 0, 0, "")
        self.backend.get_run = MagicMock(
            side_effect=[
                LoomLoomAPIError("temporary", retryable=True),
                completed,
            ]
        )
        self.backend._clock = MagicMock(side_effect=[0, 0, 0, 0.1])
        self.backend._sleep = MagicMock()

        result = self.backend.wait_for_run("run-1")

        self.assertEqual(result.status, "completed")
        self.backend._sleep.assert_called_once_with(0.01)

    def test_wait_for_run_logs_a_heartbeat_for_long_running_jobs(self):
        running = LoomLoomRun("run-1", "running", 1, 0, 0, 0, "")
        completed = LoomLoomRun("run-1", "completed", 1, 1, 0, 0, "")
        self.backend.get_run = MagicMock(side_effect=[running, running, completed])
        self.backend.settings = replace(self.backend.settings, run_timeout_seconds=100)
        self.backend._clock = MagicMock(side_effect=[0, 0, 0, 31, 32])
        self.backend._sleep = MagicMock()

        with patch("app.services.loomloom.logger.info") as log_info:
            result = self.backend.wait_for_run("run-1")

        self.assertEqual(result.status, "completed")
        self.assertEqual(log_info.call_count, 3)
        self.assertIn("status=running", log_info.call_args_list[0].args[0])
        self.assertIn("finished=1/1", log_info.call_args_list[-1].args[0])

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

    def test_api_error_redacts_bearer_token_echoed_by_server(self):
        self.session.request.return_value = _Response(
            400,
            {"error": "invalid credential test-token"},
        )
        batch = self.backend.prepare_script_batch(subject="主题", candidate_count=1)

        with self.assertRaises(LoomLoomAPIError) as captured:
            self.backend.quote(batch)

        self.assertNotIn("test-token", str(captured.exception))
        self.assertIn("[redacted]", str(captured.exception))


class TestLoomLoomVideoBackend(unittest.TestCase):
    def setUp(self):
        self.settings = LoomLoomSettings(
            base_url="https://example.test/loom/v1",
            api_token="test-token",
            market_listing_id=DEFAULT_VIDEO_MARKET_LISTING_ID,
            result_port_name="output",
        )
        self.session = MagicMock()
        self.backend = LoomLoomVideoBackend(self.settings, session=self.session)

    def test_resolves_exact_video_profile_and_ignores_other_profiles(self):
        self.session.request.return_value = _Response(200, _video_capability_payload())

        capability = self.backend.resolve_video_capability()

        self.assertEqual(
            [(model.model_id, model.display_name) for model in capability.models],
            [("model-a", "Model A"), ("model-b", "Model B")],
        )
        self.assertEqual(capability.default_model_id, "model-a")
        self.assertEqual(capability.aspect_ratios, ("16:9", "9:16"))
        request = self.session.request.call_args
        self.assertEqual(
            request.args,
            (
                "GET",
                "https://example.test/loom/v1/authoringCapabilities:resolve",
            ),
        )
        self.assertEqual(
            request.kwargs["params"],
            {"inputModality": "text", "outputModality": "video"},
        )

    def test_resolver_rejects_missing_empty_or_invalid_default_profile(self):
        cases = (
            (
                _video_capability_payload(include_target_profile=False),
                "profile .* is unavailable",
            ),
            (_video_capability_payload(models=[]), "no eligible models"),
            (
                _video_capability_payload(default_model_id="removed-model"),
                "default model is not eligible",
            ),
        )
        for payload, error in cases:
            with self.subTest(error=error):
                self.session.request.return_value = _Response(200, payload)
                with self.assertRaisesRegex(LoomLoomConfigurationError, error):
                    self.backend.resolve_video_capability()

    def test_resolver_rejects_non_string_model_fields(self):
        """服务返回 null/数值时应在目录阶段报错，不把伪 ID 传进付费请求。"""
        for field in ("modelId", "displayName"):
            for value in (None, 123, {}, []):
                with self.subTest(field=field, value=value):
                    model = {"modelId": "model-a", "displayName": "Model A"}
                    model[field] = value
                    self.session.request.return_value = _Response(
                        200, _video_capability_payload(models=[model])
                    )
                    with self.assertRaisesRegex(LoomLoomAPIError, "must be strings"):
                        self.backend.resolve_video_capability()

    def test_prepares_one_video_row_per_scene(self):
        """默认 SkillBot 必须按场景逐行报价，并携带固定的视频安全要求。"""
        batch = self.backend.prepare_video_batch(
            subject="AI 办公效率",
            scene_prompts=["office worker", "AI assistant"],
            model_id="google/veo3.1-fast-preview",
            aspect_ratio="9:16",
        )

        self.assertEqual(len(batch.input_rows), 2)
        self.assertEqual(batch.input_rows[0]["aspectRatio"], "9:16")
        self.assertEqual(
            {row["modelChoice"] for row in batch.input_rows},
            {"google/veo3.1-fast-preview"},
        )
        self.assertIn("office worker", batch.input_rows[0]["prompt"])
        self.assertIn("Scene 2", batch.input_rows[1]["prompt"])
        self.assertIn("No text", batch.input_rows[0]["prompt"])
        self.assertNotIn("scenePrompt", batch.input_rows[0])
        self.assertNotIn("sceneIndex", batch.input_rows[0])

    def test_video_batch_accepts_only_supported_aspect_ratios(self):
        for aspect_ratio in ("16:9", "9:16"):
            with self.subTest(aspect_ratio=aspect_ratio):
                batch = self.backend.prepare_video_batch(
                    subject="subject",
                    scene_prompts=["scene"],
                    model_id="model-a",
                    aspect_ratio=aspect_ratio,
                )
                self.assertEqual(batch.input_rows[0]["aspectRatio"], aspect_ratio)

        with self.assertRaisesRegex(ValueError, "aspect_ratio"):
            self.backend.prepare_video_batch(
                subject="subject",
                scene_prompts=["scene"],
                model_id="model-a",
                aspect_ratio="1:1",
            )

    def test_video_quote_uses_new_listing_and_public_input_contract(self):
        self.session.request.return_value = _Response(
            200,
            {
                "quoteId": "quote-1",
                "listingVersionId": "listing-version-1",
                "currency": "CNY",
                "taskCount": 1,
                "estimatedBuyerPayableT": 0,
            },
        )
        batch = self.backend.prepare_video_batch(
            subject="subject",
            scene_prompts=["scene"],
            model_id="model-a",
            aspect_ratio="16:9",
        )

        self.backend.quote(batch)

        request = self.session.request.call_args
        self.assertEqual(
            request.args[1],
            "https://example.test/loom/v1/marketListings/"
            "01a06563-7331-773a-b9b2-25989a0dd70e:quote",
        )
        self.assertEqual(
            request.kwargs["json"],
            {
                "inputRows": [
                    {
                        "prompt": batch.input_rows[0]["prompt"],
                        "modelChoice": "model-a",
                        "aspectRatio": "16:9",
                    }
                ]
            },
        )

    def test_downloads_video_artifact_without_forwarding_api_key(self):
        """签名产物地址无需 Bearer Key，避免把账户凭证泄漏给对象存储。"""
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
        response = _DownloadResponse()
        self.session.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            paths = self.backend.download_video_results("run-1", directory)
            self.assertEqual(Path(paths[0]).read_bytes(), b"video-bytes")

        self.session.get.assert_called_once_with(
            "https://objects.test/video.mp4?signature=x",
            stream=True,
            timeout=(5.0, self.settings.request_timeout_seconds),
        )
        self.assertTrue(response.closed)

    def test_closes_download_response_when_artifact_is_too_large(self):
        """大小预检拒绝下载时也必须立即释放流式 HTTP 连接。"""
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
                                "accessUrl": "https://objects.test/large.mp4",
                            }
                        ],
                    }
                ]
            },
        )
        response = _DownloadResponse(
            headers={"content-length": str(MAX_VIDEO_ARTIFACT_BYTES + 1)}
        )
        self.session.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(LoomLoomAPIError, "download limit"):
                self.backend.download_video_results("run-1", directory)

        self.assertTrue(response.closed)

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
