import json
import os
import sys
import tempfile
import tomllib
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.llm_provider import (
    DEFAULT_LLM_PROVIDER_ID,
    LLM_PROVIDER_REGISTRY,
    LLM_PROVIDERS,
    get_llm_provider,
    normalize_provider_override,
)
from app.models.schema import VideoScriptRequest, VideoSocialMetadataRequest
from app.services import llm

RUN_INTEGRATION_TESTS = os.environ.get("MPT_RUN_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}


class TestScriptPromptOptions(unittest.TestCase):
    def test_normalize_text_response_preserves_internal_newlines(self):
        """
        Normalization only strips leading/trailing whitespace and must not remove newlines inside the body. Double newlines separate script
        paragraphs, and single newlines may be subtitle lines returned by the model on semantic grounds.
        """
        result = llm._normalize_text_response(
            "\n  第一行\n第二行\n\n第三段  \n",
            "openai",
        )

        self.assertEqual(result, "第一行\n第二行\n\n第三段")

    def test_normalize_text_response_removes_think_blocks(self):
        """
        Reasoning models may return `<think>...</think>`. The script generation pipeline must keep only
        the final body, so the thinking process doesn't end up in subtitles and voice-over.
        """
        result = llm._normalize_text_response(
            "<think>\nI should reason here.\n</think>\n测试成功",
            "minimax",
        )

        self.assertEqual(result, "测试成功")

    def test_normalize_text_response_rejects_think_only_response(self):
        """
        If the model only returns a thinking block with no final answer, it should be treated as empty content, triggering a retry or a clear error.
        """
        with self.assertRaises(ValueError):
            llm._normalize_text_response("<think>hidden reasoning</think>", "minimax")

    def test_normalize_text_response_removes_unclosed_think_block(self):
        """
        Some gateways may return only an unclosed `<think>` because of truncation. Such content must not
        enter the final script either; if no body remains after cleaning, it should be treated as an empty response.
        """
        with self.assertRaises(ValueError):
            llm._normalize_text_response("<think>hidden reasoning", "minimax")

    def test_normalize_text_response_removes_reasoning_before_unopened_close(self):
        """
        When the opening `<think>` is in the chat template, the model output only contains reasoning and the closing tag.
        Reasoning before the closing tag must not enter the script; reasoning alone is also treated as an empty response.
        """
        result = llm._normalize_text_response(
            "The user wants a sea script. Let me plan.\n</think>\n\n"
            "The ocean is vast.\n\nIt covers our planet.",
            "deepseek",
        )

        self.assertEqual(result, "The ocean is vast.\n\nIt covers our planet.")
        with self.assertRaises(ValueError):
            llm._normalize_text_response("hidden reasoning\n</THINK>\n", "ollama")

    def test_build_script_prompt_appends_advanced_requirements(self):
        """
        Advanced script requirements are only appended as extra constraints and don't replace the default system prompt.
        That way ordinary users who configure nothing still get the stable default rules, while advanced users can refine the style.
        """
        prompt = llm.build_script_prompt(
            video_subject="咖啡",
            language="zh-CN",
            paragraph_number=3,
            video_script_prompt="语气轻松，面向程序员",
        )

        self.assertIn("# Role: Video Script Generator", prompt)
        self.assertIn("- video subject: 咖啡", prompt)
        self.assertIn("- number of paragraphs: 3", prompt)
        self.assertIn("- language: zh-CN", prompt)
        self.assertIn("# Additional User Requirements:", prompt)
        self.assertIn("语气轻松，面向程序员", prompt)

    def test_custom_system_prompt_keeps_runtime_context(self):
        """
        A custom system prompt replaces the default script rules, but the video subject, language and paragraph count
        are still appended uniformly by the service layer, so advanced users can't leave out necessary context.
        """
        prompt = llm.build_script_prompt(
            video_subject="露营",
            language="en",
            paragraph_number=2,
            custom_system_prompt="Only write cinematic narration.",
        )

        self.assertNotIn("# Role: Video Script Generator", prompt)
        self.assertIn("Only write cinematic narration.", prompt)
        self.assertIn("- video subject: 露营", prompt)
        self.assertIn("- number of paragraphs: 2", prompt)
        self.assertIn("- language: en", prompt)

    def test_generate_script_sends_custom_prompt_to_llm(self):
        captured = {}

        def fake_generate_response(prompt):
            captured["prompt"] = prompt
            return "第一段。\n\n第二段。"

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_script(
                video_subject="咖啡",
                language="zh-CN",
                paragraph_number=2,
                video_script_prompt="开头更有悬念",
            )

        self.assertEqual(result, "第一段。\n\n第二段。")
        self.assertIn("- number of paragraphs: 2", captured["prompt"])
        self.assertIn("开头更有悬念", captured["prompt"])

    def test_generate_script_reuses_submitted_config_snapshot(self):
        """Applying new config after a WebUI background task ends must not change a model request that is being retried."""
        captured = {}
        app_config = {
            "llm_provider": "openai",
            "openai_api_key": "snapshot-key",
            "openai_model_name": "snapshot-model",
        }

        def fake_generate_response(prompt, app_config=None):
            captured["prompt"] = prompt
            captured["app_config"] = app_config
            return "Snapshot response"

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_script(
                video_subject="Snapshot test",
                app_config=app_config,
            )

        self.assertEqual(result, "Snapshot response")
        self.assertIs(captured["app_config"], app_config)
        self.assertEqual(captured["app_config"]["openai_api_key"], "snapshot-key")

    def test_generate_script_retries_provider_error_instead_of_using_it_as_narration(self):
        with patch.object(
            llm,
            "_generate_response",
            side_effect=["Error: temporary provider failure", "Real narration."],
        ) as generate_response:
            result = llm.generate_script(video_subject="Coffee")

        self.assertEqual(result, "Real narration.")
        self.assertEqual(generate_response.call_count, 2)

    def test_generate_script_returns_empty_when_provider_always_fails(self):
        with patch.object(
            llm, "_generate_response", return_value="Error: invalid API key"
        ):
            result = llm.generate_script(video_subject="Coffee")

        self.assertEqual(result, "")

    def test_generate_script_does_not_return_stale_quota_error_after_retries(self):
        responses = ["当日额度已消耗完"] + [
            RuntimeError("provider unavailable")
        ] * (llm._max_retries - 1)
        with patch.object(
            llm, "_generate_response", side_effect=responses
        ) as generate_response:
            result = llm.generate_script(video_subject="Coffee")

        self.assertEqual(result, "")
        self.assertEqual(generate_response.call_count, llm._max_retries)

    def test_generate_script_strips_markdown_code_fence(self):
        with patch.object(
            llm,
            "_generate_response",
            return_value="\x60\x60\x60text\n第一段。\n\n第二段。\n\x60\x60\x60",
        ):
            result = llm.generate_script(
                video_subject="テスト",
                paragraph_number=2,
            )

        self.assertEqual(result, "第一段。\n\n第二段。")
        self.assertNotIn("\x60\x60\x60", result)

    def test_generate_script_strips_each_bracket_group_independently(self):
        """
        format_response must remove each [bracket] and (paren) group in
        isolation.  The greedy form [.*] matches from the first opener to
        the *last* closer on the line, silently deleting all text in between.

        Example – greedy bug:
            "[Intro] Great content [end]"  →  "."     (all inner text lost)
        Expected with non-greedy fix:
            "[Intro] Great content [end]"  →  " Great content "
        """

        def fake_generate_response(prompt):
            # Two bracket groups and two paren groups on the same line.
            return (
                "[Scene: Beach] A beautiful day at the [location: ocean].\n\n"
                "Save (at least) 10% of your income (monthly)."
            )

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_script(video_subject="savings tips", language="en-US")

        # Each bracket / paren group should be gone, but the surrounding words
        # must survive.
        self.assertNotIn("[", result)
        self.assertNotIn("]", result)
        self.assertNotIn("(", result)
        self.assertNotIn(")", result)
        self.assertIn("A beautiful day at the", result)
        self.assertIn("10% of your income", result)

    def test_generate_terms_can_request_script_ordered_keywords(self):
        """
        Matching materials in script order depends on the LLM returning ordered keywords. No real model is called here;
        it only verifies the service layer writes the "output in script narrative order" constraint into the prompt, so
        material downloads aren't ordered while the keywords are still globally unordered topic words.
        """
        captured = {}

        def fake_generate_response(prompt):
            captured["prompt"] = prompt
            return '["opening city", "middle office", "final sunset"]'

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_terms(
                video_subject="startup story",
                video_script="First city. Then office. Finally sunset.",
                amount=3,
                match_script_order=True,
            )

        self.assertEqual(result, ["opening city", "middle office", "final sunset"])
        self.assertIn("chronological stock-video search terms", captured["prompt"])
        self.assertIn("same order as the script narration", captured["prompt"])

    def test_generate_terms_returns_empty_list_on_provider_error(self):
        """
        Provider errors must keep generate_terms' List[str] return contract.

        A non-empty ``Error: ...`` string is truthy in Python; if it were returned directly, the task layer
        would treat it as valid keywords, and the material download layer might then send search requests character by character.
        """
        with patch.object(
            llm,
            "_generate_response",
            return_value="Error: invalid API key",
        ):
            result = llm.generate_terms(
                video_subject="startup story",
                video_script="A short startup story.",
            )

        self.assertEqual(result, [])
        self.assertIsInstance(result, list)

    def test_generate_terms_retries_non_string_items_in_recovered_json(self):
        """The prose-wrapped JSON recovery path must enforce List[str] too."""
        with patch.object(
            llm,
            "_generate_response",
            side_effect=[
                'Search terms: [123, {"query": "coffee"}]',
                'Search terms: ["coffee beans", "barista tools"]',
            ],
        ) as generate_response:
            result = llm.generate_terms(
                video_subject="Coffee",
                video_script="How to brew coffee.",
            )

        self.assertEqual(result, ["coffee beans", "barista tools"])
        self.assertEqual(generate_response.call_count, 2)

    def test_video_script_request_rejects_invalid_advanced_options(self):
        """
        The API request model needs to limit advanced prompt parameters, so external calls can't bypass the WebUI
        and pass abnormal paragraph counts or overly long prompts, making model cost and results unpredictable.
        """
        with self.assertRaises(ValidationError):
            VideoScriptRequest(video_subject="咖啡", paragraph_number=0)

        with self.assertRaises(ValidationError):
            VideoScriptRequest(
                video_subject="咖啡",
                video_script_prompt="x" * (llm.MAX_SCRIPT_PROMPT_LENGTH + 1),
            )


class TestLLMConnection(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_connection_sends_one_minimal_request(self):
        """The connection test only sends one fixed minimal request and doesn't trigger script generation retries."""
        with (
            patch.object(llm, "_generate_response", return_value="OK") as generate,
            patch.object(llm, "perf_counter", side_effect=[10.0, 10.25]),
        ):
            result = llm.test_connection()

        generate.assert_called_once_with(
            prompt="Reply with exactly: OK",
            request_timeout=llm.LLM_CONNECTION_TEST_TIMEOUT_SECONDS,
            max_retries=llm.LLM_CONNECTION_TEST_MAX_RETRIES,
        )
        self.assertEqual(result, (True, "", 0.25))

    def test_connection_applies_bounded_timeout_and_disables_sdk_retries(self):
        """The connection test's short timeout and disabled retries must apply to the actual SDK client (issue #1642)."""
        config.app.update(
            {
                "llm_provider": "openai",
                "openai_api_key": "test-key",
                "openai_model_name": "test-model",
                "openai_base_url": "https://example.test/v1",
            }
        )
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                chat=types.SimpleNamespace(
                    completions=types.SimpleNamespace(create=lambda **kw: None)
                )
            )

        with patch.object(llm, "OpenAI", side_effect=create):
            llm.test_connection()

        self.assertEqual(
            captured.get("timeout"), llm.LLM_CONNECTION_TEST_TIMEOUT_SECONDS
        )
        self.assertEqual(
            captured.get("max_retries"), llm.LLM_CONNECTION_TEST_MAX_RETRIES
        )

    def test_connection_failure_hint_for_timeout_errors(self):
        """Timeout/connection failures should include troubleshooting hints, not just the raw SDK message."""
        with (
            patch.object(
                llm, "_generate_response", return_value="Error: Request timed out."
            ),
            patch.object(llm, "perf_counter", side_effect=[0.0, 5.0]),
        ):
            ok, error, elapsed = llm.test_connection()

        self.assertFalse(ok)
        self.assertEqual(elapsed, 5.0)
        self.assertIn("Request timed out.", error)
        self.assertIn(f"{llm.LLM_CONNECTION_TEST_TIMEOUT_SECONDS:.0f}s", error)
        self.assertIn("reachable", error)
        self.assertIn("proxy", error)

    def test_connection_returns_provider_error(self):
        """When the Provider returns an error, diagnosable info should be kept and the request duration reported."""
        with (
            patch.object(
                llm,
                "_generate_response",
                return_value="Error: invalid API key",
            ),
            patch.object(llm, "perf_counter", side_effect=[20.0, 20.5]),
        ):
            result = llm.test_connection()

        self.assertEqual(result, (False, "invalid API key", 0.5))

    def test_connection_rejects_empty_response(self):
        """An empty response in edge cases should show a clear error, not falsely report a successful connection."""
        with (
            patch.object(llm, "_generate_response", return_value=""),
            patch.object(llm, "perf_counter", side_effect=[30.0, 31.0]),
        ):
            result = llm.test_connection()

        self.assertEqual(result, (False, "LLM returned an empty response", 1.0))


class TestGenerateResponseTransportLimits(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    @staticmethod
    def _fake_client():
        """Return a minimal usable client so `_generate_response` goes through the request branch."""
        message = types.SimpleNamespace(content="ok")
        choice = types.SimpleNamespace(message=message)
        completion = types.SimpleNamespace(choices=[choice])
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **kwargs: completion)
            )
        )

    def test_transport_limits_forwarded_to_openai_compatible_clients(self):
        """Explicitly passed timeout/retry constraints must apply to all OpenAI-compatible clients."""
        cases = [
            (
                "openai",
                "OpenAI",
                {
                    "openai_api_key": "test-key",
                    "openai_model_name": "test-model",
                    "openai_base_url": "https://example.test/v1",
                },
            ),
            (
                "azure",
                "AzureOpenAI",
                {
                    "azure_api_key": "test-key",
                    "azure_model_name": "test-model",
                    "azure_base_url": "https://example.test",
                    "azure_api_version": "2024-02-15-preview",
                },
            ),
            (
                "cloudflare",
                "OpenAI",
                {
                    "cloudflare_api_key": "test-key",
                    "cloudflare_model_name": "test-model",
                    "cloudflare_account_id": "test-account",
                    "cloudflare_gateway_id": "test-gateway",
                },
            ),
        ]
        for provider, constructor, settings in cases:
            with self.subTest(provider=provider):
                config.app.update({"llm_provider": provider, **settings})
                with (
                    patch.object(
                        llm,
                        constructor,
                        return_value=self._fake_client(),
                    ) as client_constructor,
                    patch.object(llm, "ChatCompletion", types.SimpleNamespace),
                ):
                    result = llm._generate_response(
                        "hello",
                        request_timeout=12.5,
                        max_retries=0,
                    )

                self.assertEqual(result, "ok", result)
                kwargs = client_constructor.call_args.kwargs
                self.assertEqual(kwargs.get("timeout"), 12.5)
                self.assertEqual(kwargs.get("max_retries"), 0)

    def test_default_generation_keeps_sdk_defaults(self):
        """Without constraints the client constructor arguments stay unchanged, and the generation pipeline behaves the same."""
        config.app.update(
            {
                "llm_provider": "openai",
                "openai_api_key": "test-key",
                "openai_model_name": "test-model",
                "openai_base_url": "https://example.test/v1",
            }
        )
        with (
            patch.object(
                llm, "OpenAI", return_value=self._fake_client()
            ) as client_constructor,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("hello")

        self.assertEqual(result, "ok", result)
        client_constructor.assert_called_once_with(
            api_key="test-key",
            base_url="https://example.test/v1",
        )


class TestLiteLLMProvider(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_current_default_model_names(self):
        """The WebUI and service layer must share the same default models, so displayed and requested values don't drift."""
        self.assertEqual(get_llm_provider("openai").default_model, "gpt-5.5")
        anthropic = get_llm_provider("anthropic")
        self.assertEqual(anthropic.default_model, "claude-sonnet-5")
        self.assertEqual(anthropic.default_base_url, "https://api.anthropic.com/v1/")
        self.assertEqual(anthropic.adapter, "openai_compatible")
        self.assertTrue(anthropic.requires_api_key)
        self.assertEqual(get_llm_provider("aimlapi").default_model, "openai/gpt-5-5")
        self.assertEqual(get_llm_provider("deepseek").default_model, "deepseek-v4-pro")
        self.assertEqual(
            get_llm_provider("modelscope").default_model, "ZhipuAI/GLM-5.2"
        )
        self.assertEqual(
            get_llm_provider("gemini").default_model, "gemini-3.1-pro-preview"
        )
        openrouter = get_llm_provider("openrouter")
        self.assertEqual(openrouter.default_model, "minimax/minimax-m3:free")
        self.assertEqual(openrouter.default_base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(openrouter.adapter, "openai_compatible")
        self.assertTrue(openrouter.requires_api_key)
        api_route = get_llm_provider("api_route")
        self.assertEqual(api_route.default_model, "gpt-5.4-mini")
        self.assertEqual(api_route.default_base_url, "https://www.api-route.com/v1")
        self.assertEqual(api_route.adapter, "openai_compatible")
        self.assertTrue(api_route.requires_api_key)
        cheaperinference = get_llm_provider("cheaperinference")
        self.assertEqual(cheaperinference.default_model, "gpt-5.4-mini")
        self.assertEqual(
            cheaperinference.default_base_url,
            "https://api.cheaperinference.com/v1",
        )
        self.assertEqual(cheaperinference.adapter, "openai_compatible")
        self.assertTrue(cheaperinference.requires_api_key)
        self.assertEqual(
            cheaperinference.api_key_url,
            "https://cheaperinference.com/signup",
        )
        self.assertEqual(
            cheaperinference.model_docs_url,
            "https://cheaperinference.com/#models",
        )
        requesty = get_llm_provider("requesty")
        self.assertEqual(requesty.default_model, "openai/gpt-5.4-mini")
        self.assertEqual(requesty.default_base_url, "https://router.requesty.ai/v1")
        self.assertEqual(requesty.adapter, "openai_compatible")
        self.assertTrue(requesty.requires_api_key)
        self.assertEqual(requesty.api_key_url, "https://app.requesty.ai/api-keys")
        self.assertEqual(requesty.model_docs_url, "https://www.requesty.ai/models")
        futureinfra = get_llm_provider("futureinfra")
        self.assertEqual(futureinfra.default_model, "openai/gpt-4o-mini")
        self.assertEqual(futureinfra.default_base_url, "https://futureinfra.ai/v1/ai")
        self.assertEqual(futureinfra.adapter, "openai_compatible")
        self.assertTrue(futureinfra.requires_api_key)
        self.assertEqual(
            futureinfra.api_key_url,
            "https://futureinfra.ai/console/?screen=ai-router",
        )
        self.assertEqual(futureinfra.model_docs_url, "https://futureinfra.ai/ai/")
        yapi = get_llm_provider("yapi")
        self.assertEqual(yapi.default_model, "deepseek/deepseek-v4-flash")
        self.assertEqual(yapi.default_base_url, "https://api.y-api.bestvirtualgoods.com/v1")
        self.assertEqual(yapi.adapter, "openai_compatible")
        self.assertTrue(yapi.requires_api_key)
        self.assertEqual(
            yapi.api_key_url,
            "https://y-api.bestvirtualgoods.com/app/keys",
        )
        self.assertEqual(yapi.model_docs_url, "https://y-api.bestvirtualgoods.com/models")
        opper = get_llm_provider("opper")
        self.assertEqual(opper.default_model, "gpt-5.4-mini")
        self.assertEqual(opper.default_base_url, "https://api.opper.ai/v3/compat")
        self.assertEqual(opper.adapter, "openai_compatible")
        self.assertTrue(opper.requires_api_key)
        self.assertEqual(opper.api_key_url, "https://platform.opper.ai")
        self.assertEqual(opper.model_docs_url, "https://opper.ai/models")
        onomeo = get_llm_provider("onomeo")
        self.assertEqual(onomeo.default_model, "auto")
        self.assertEqual(onomeo.default_base_url, "https://onomeo.com/v1")
        self.assertEqual(onomeo.adapter, "openai_compatible")
        self.assertTrue(onomeo.requires_api_key)
        self.assertEqual(onomeo.api_key_url, "https://onomeo.com/dashboard")
        self.assertEqual(onomeo.model_docs_url, "https://onomeo.com/models")
        empiriolabs = get_llm_provider("empiriolabs")
        self.assertEqual(empiriolabs.default_model, "qwen3-8-flash")
        self.assertEqual(empiriolabs.default_base_url, "https://api.empiriolabs.ai/v1")
        self.assertEqual(empiriolabs.adapter, "openai_compatible")
        self.assertTrue(empiriolabs.requires_api_key)
        self.assertEqual(
            empiriolabs.api_key_url,
            "https://platform.empiriolabs.ai/dashboard/api-keys",
        )
        self.assertEqual(
            empiriolabs.model_docs_url,
            "https://docs.empiriolabs.ai/models-pricing",
        )
        runcrate = get_llm_provider("runcrate")
        self.assertEqual(runcrate.default_model, "deepseek-ai/DeepSeek-V4.1-Flash")
        self.assertEqual(runcrate.default_base_url, "https://api.runcrate.ai/v1")
        self.assertEqual(runcrate.adapter, "openai_compatible")
        self.assertTrue(runcrate.requires_api_key)
        self.assertEqual(
            runcrate.api_key_url,
            "https://www.runcrate.ai/dashboard/api-keys?utm_source=MoneyPrinterTurbo&utm_medium=directory&utm_campaign=gpu_pricing",
        )
        self.assertEqual(
            runcrate.model_docs_url,
            "https://www.runcrate.ai/inference/pricing?utm_source=MoneyPrinterTurbo&utm_medium=directory&utm_campaign=gpu_pricing",
        )
        cloudgpu = get_llm_provider("cloudgpu")
        self.assertEqual(cloudgpu.default_model, "deepseek-v4-flash")
        self.assertEqual(cloudgpu.default_base_url, "https://cloudgpu.app/v1")
        self.assertEqual(cloudgpu.adapter, "openai_compatible")
        self.assertTrue(cloudgpu.requires_api_key)
        self.assertEqual(cloudgpu.api_key_url, "https://cloudgpu.app")
        self.assertEqual(cloudgpu.model_docs_url, "https://cloudgpu.app/v1/models")
        cheapaimodel = get_llm_provider("cheapaimodel")
        self.assertEqual(cheapaimodel.default_model, "deepseek-v4-1-flash")
        self.assertEqual(cheapaimodel.default_base_url, "https://api.cheapaimodel.ai/v1")
        self.assertEqual(cheapaimodel.adapter, "openai_compatible")
        self.assertTrue(cheapaimodel.requires_api_key)
        self.assertEqual(
            cheapaimodel.api_key_url, "https://console.cheapaimodel.ai/keys"
        )
        self.assertEqual(
            cheapaimodel.model_docs_url, "https://cheapaimodel.ai/models"
        )
        uberllm = get_llm_provider("uberllm")
        self.assertEqual(uberllm.default_model, "deepseek/deepseek-v4-flash")
        self.assertEqual(uberllm.default_base_url, "https://api.uberllm.dev/v1")
        self.assertEqual(uberllm.adapter, "openai_compatible")
        self.assertTrue(uberllm.requires_api_key)
        self.assertEqual(uberllm.api_key_url, "https://uberllm.dev/signup")
        self.assertEqual(uberllm.model_docs_url, "https://uberllm.dev/models")
        iflytek = get_llm_provider("iflytek")
        self.assertEqual(iflytek.default_model, "spark-x2.5")
        self.assertEqual(
            iflytek.default_base_url,
            "https://maas-api.cn-huabei-1.xf-yun.com/v2",
        )
        self.assertEqual(iflytek.adapter, "openai_compatible")
        self.assertTrue(iflytek.requires_api_key)
        self.assertEqual(iflytek.api_key_url, "https://maas.xfyun.cn/")
        self.assertEqual(iflytek.model_docs_url, "https://maas.xfyun.cn/modelSquare")
        pollinations = get_llm_provider("pollinations")
        self.assertEqual(pollinations.default_model, "openai-fast")
        self.assertEqual(
            pollinations.default_base_url,
            "https://gen.pollinations.ai/v1",
        )
        self.assertTrue(pollinations.requires_api_key)
        self.assertEqual(pollinations.adapter, "openai_compatible")

    def test_provider_defaults_are_not_persisted_as_user_overrides(self):
        """Defaults are only for running and display; only different values should be written to user config."""
        self.assertEqual(
            normalize_provider_override("gpt-5.5", "gpt-5.5"),
            "",
        )
        self.assertEqual(
            normalize_provider_override("  gpt-5.5  ", "gpt-5.5"),
            "",
        )
        self.assertEqual(
            normalize_provider_override("gpt-5.6-custom", "gpt-5.5"),
            "gpt-5.6-custom",
        )

    def test_provider_registry_has_unique_stable_ids(self):
        """The Registry is the single data source for the Provider list; IDs must be unique and the default must exist."""
        provider_ids = [provider.provider_id for provider in LLM_PROVIDER_REGISTRY]

        self.assertEqual(len(provider_ids), len(set(provider_ids)))
        self.assertEqual(len(provider_ids), len(LLM_PROVIDERS))
        self.assertIn(DEFAULT_LLM_PROVIDER_ID, LLM_PROVIDERS)

    def test_provider_registry_preserves_product_group_order(self):
        """The dropdown order is recommended, vendor, aggregator platforms, local deployments, then other services."""
        self.assertEqual(
            [provider.provider_id for provider in LLM_PROVIDER_REGISTRY],
            [
                "moonshot",
                "kimi_code",
                "openai",
                "openai_codex",
                "openai_chatgpt",
                "anthropic",
                "gemini",
                "muse_spark",
                "deepseek",
                "qwen",
                "azure",
                "volcengine",
                "grok",
                "minimax",
                "mimo",
                "iflytek",
                "apixo",
                "apinebula",
                "jalapeno",
                "infistar",
                "shengsuanyun",
                "apimart",
                "cloudflare",
                "modelscope",
                "aihubmix",
                "aimlapi",
                "evolink",
                "openrouter",
                "api_route",
                "fluxionai",
                "cheaperinference",
                "requesty",
                "futureinfra",
                "yapi",
                "opper",
                "onomeo",
                "empiriolabs",
                "runcrate",
                "cloudgpu",
                "cheapaimodel",
                "uberllm",
                "ollama",
                "claude_code",
                "oneapi",
                "litellm",
                "groq",
                "pollinations",
            ],
        )
        self.assertEqual(
            get_llm_provider("gemini").default_label,
            "Google Gemini",
        )
        self.assertEqual(
            get_llm_provider("azure").default_label,
            "Microsoft Azure OpenAI",
        )
        shengsuanyun = get_llm_provider("shengsuanyun")
        self.assertEqual(
            shengsuanyun.api_key_url,
            "https://www.shengsuanyun.com/?from=CH_XUQ4OTSK",
        )
        self.assertEqual(
            shengsuanyun.default_model,
            "deepseek/deepseek-v4-flash",
        )
        apimart = get_llm_provider("apimart")
        self.assertEqual(
            apimart.api_key_url,
            "https://go.apimart.ai/gh-moneyprinterturbo",
        )
        self.assertEqual(apimart.default_model, "gpt-5.6-terra")
        self.assertEqual(apimart.default_base_url, "https://api.apimart.ai/v1")
        muse_spark = get_llm_provider("muse_spark")
        self.assertEqual(
            muse_spark.api_key_url,
            "https://dev.meta.ai/docs/authentication",
        )
        self.assertEqual(muse_spark.default_model, "muse-spark-1.3")
        self.assertEqual(muse_spark.default_base_url, "https://api.meta.ai/v1")
        self.assertEqual(muse_spark.adapter, "openai_compatible")
        openrouter = get_llm_provider("openrouter")
        self.assertEqual(
            openrouter.api_key_url,
            "https://openrouter.ai/settings/keys",
        )
        self.assertEqual(openrouter.default_model, "minimax/minimax-m3:free")
        self.assertEqual(openrouter.default_base_url, "https://openrouter.ai/api/v1")
        api_route = get_llm_provider("api_route")
        self.assertEqual(
            api_route.api_key_url,
            "https://www.api-route.com",
        )
        self.assertEqual(api_route.default_model, "gpt-5.4-mini")
        self.assertEqual(api_route.default_base_url, "https://www.api-route.com/v1")
        self.assertEqual(
            api_route.model_docs_url,
            "https://www.api-route.com/pricing",
        )

    def test_provider_registry_uses_conventional_locale_and_config_keys(self):
        """A unified naming convention keeps the WebUI from adding hardcoded mappings for every Provider."""
        for provider in LLM_PROVIDER_REGISTRY:
            self.assertEqual(
                provider.label_key,
                f"llm_provider_label.{provider.provider_id}",
            )
            self.assertEqual(
                provider.tips_key,
                f"llm_provider_tips.{provider.provider_id}",
            )
            self.assertEqual(
                provider.config_key("api_key"),
                f"{provider.provider_id}_api_key",
            )

    def test_registry_replaces_deprecated_provider_models(self):
        """Historical default models should be migrated automatically, so retired integration semantics aren't kept after upgrading."""
        cloudflare = get_llm_provider("cloudflare")
        gemini = get_llm_provider("gemini")

        self.assertEqual(
            cloudflare.resolve_model_name("@cf/meta/llama-3.1-8b-instruct"),
            "openai/gpt-4.1-mini",
        )
        self.assertEqual(
            gemini.resolve_model_name("gemini-pro"),
            "gemini-3.1-pro-preview",
        )
        self.assertEqual(
            cloudflare.resolve_model_name("anthropic/claude-sonnet-4-5"),
            "anthropic/claude-sonnet-4-5",
        )

        pollinations = get_llm_provider("pollinations")
        self.assertEqual(
            pollinations.resolve_model_name("default"),
            "openai-fast",
        )
        self.assertEqual(
            pollinations.resolve_base_url("https://text.pollinations.ai/openai"),
            "https://gen.pollinations.ai/v1",
        )
        self.assertEqual(
            pollinations.resolve_base_url("https://example.com/v1"),
            "https://example.com/v1",
        )

    def test_provider_tip_templates_accept_registry_defaults(self):
        """Provider tip templates in every language must safely accept the Registry defaults."""
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        for locale_file in i18n_dir.glob("*.json"):
            translations = json.loads(locale_file.read_text(encoding="utf-8"))[
                "Translation"
            ]
            for provider in LLM_PROVIDER_REGISTRY:
                tips = translations.get(provider.tips_key, "")
                if not tips:
                    continue
                default_endpoint = provider.default_service_endpoint
                rendered = tips.format(
                    api_key_url=provider.effective_api_key_url(),
                    default_model=provider.default_model,
                    default_base_url=provider.effective_default_base_url,
                    model_docs_url=(
                        default_endpoint.model_docs_url
                        if default_endpoint
                        else provider.effective_model_docs_url()
                    ),
                    docker_hint="",
                    **{
                        f"default_{field.config_suffix}": field.default_value
                        for field in provider.extra_fields
                    },
                )
                self.assertNotIn("{default_model}", rendered)
                self.assertNotIn("{default_base_url}", rendered)

    def test_primary_provider_tips_use_consistent_structure(self):
        """Chinese and English config descriptions uniformly show the API Key, Base URL and model name."""
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        for language in ("zh", "en"):
            translations = json.loads(
                (i18n_dir / f"{language}.json").read_text(encoding="utf-8")
            )["Translation"]
            for provider in LLM_PROVIDER_REGISTRY:
                tips = translations[provider.tips_key]
                self.assertTrue(tips.startswith("##### "), provider.provider_id)
                self.assertIn("**API Key**", tips, provider.provider_id)
                self.assertIn("**Base Url**", tips, provider.provider_id)
                self.assertIn("**Model Name**", tips, provider.provider_id)

        zh_kimi_tips = json.loads((i18n_dir / "zh.json").read_text(encoding="utf-8"))[
            "Translation"
        ]["llm_provider_tips.moonshot"]
        self.assertIn("推荐理由：", zh_kimi_tips)
        self.assertIn("视频创作链路匹配", zh_kimi_tips)
        self.assertIn("活动截至 2026 年 12 月 31 日", zh_kimi_tips)
        en_kimi_tips = json.loads((i18n_dir / "en.json").read_text(encoding="utf-8"))[
            "Translation"
        ]["llm_provider_tips.moonshot"]
        self.assertIn("offer ends December 31, 2026", en_kimi_tips)

    def test_required_api_key_providers_have_clickable_entry_points(self):
        """Providers that need a key must provide a unified sign-up link, so the WebUI doesn't only show text."""
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        locale_translations = {
            locale_file.stem: json.loads(locale_file.read_text(encoding="utf-8"))[
                "Translation"
            ]
            for locale_file in i18n_dir.glob("*.json")
        }

        for provider in LLM_PROVIDER_REGISTRY:
            if provider.requires_api_key:
                api_key_url = provider.effective_api_key_url()
                self.assertTrue(api_key_url, provider.provider_id)
                self.assertTrue(
                    api_key_url.startswith("https://"),
                    provider.provider_id,
                )
                for language, translations in locale_translations.items():
                    tips_template = translations.get(provider.tips_key, "")
                    if not tips_template:
                        continue
                    default_endpoint = provider.default_service_endpoint
                    tips = tips_template.format(
                        api_key_url=api_key_url,
                        default_model=provider.default_model,
                        default_base_url=provider.effective_default_base_url,
                        model_docs_url=(
                            default_endpoint.model_docs_url
                            if default_endpoint
                            else provider.effective_model_docs_url()
                        ),
                        docker_hint="",
                        **{
                            f"default_{field.config_suffix}": field.default_value
                            for field in provider.extra_fields
                        },
                    )
                    api_key_line = next(
                        line for line in tips.splitlines() if "**API Key**" in line
                    )
                    self.assertIn("](", api_key_line, provider.provider_id)
                    self.assertIn(
                        f"]({api_key_url})",
                        api_key_line,
                        f"{language}: {provider.provider_id}",
                    )

    def test_service_endpoint_registry_references_valid_stable_ids(self):
        """Service regions must be linked by a unique stable ID, not by links or display text."""
        for provider in LLM_PROVIDER_REGISTRY:
            endpoint_ids = [
                endpoint.endpoint_id for endpoint in provider.service_endpoints
            ]
            self.assertEqual(
                len(endpoint_ids),
                len(set(endpoint_ids)),
                provider.provider_id,
            )
            if not endpoint_ids:
                self.assertFalse(provider.default_service_endpoint_id)
                self.assertFalse(provider.international_service_endpoint_id)
                continue

            self.assertIn(provider.default_service_endpoint_id, endpoint_ids)
            if provider.international_service_endpoint_id:
                self.assertIn(provider.international_service_endpoint_id, endpoint_ids)

    def test_kimi_service_endpoint_selection_preserves_existing_configs(self):
        """An existing Kimi config must not be silently switched to another account system because the UI language changed."""
        provider = get_llm_provider("moonshot")

        china = provider.select_service_endpoint(
            "",
            has_api_key=True,
            prefer_international=True,
        )
        global_endpoint = provider.select_service_endpoint(
            "https://api.moonshot.ai/v1/",
            has_api_key=True,
            prefer_international=False,
        )

        self.assertEqual(china.endpoint_id, "china")
        self.assertEqual(global_endpoint.endpoint_id, "global")
        self.assertIsNone(
            provider.select_service_endpoint(
                "https://gateway.example.com/v1",
                has_api_key=True,
                prefer_international=True,
            )
        )

    def test_kimi_fresh_config_uses_interface_region(self):
        """New configs recommend a site by UI language, but the user still chooses explicitly in the WebUI."""
        provider = get_llm_provider("moonshot")

        china = provider.select_service_endpoint(
            "",
            has_api_key=False,
            prefer_international=False,
        )
        global_endpoint = provider.select_service_endpoint(
            "",
            has_api_key=False,
            prefer_international=True,
        )

        self.assertEqual(china.base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(global_endpoint.base_url, "https://api.moonshot.ai/v1")
        self.assertIn("platform.kimi.ai", global_endpoint.api_key_url)

    def test_kimi_endpoint_selection_does_not_depend_on_marketing_url(self):
        """Updating promo parameters must not change the business selection result for the international site."""
        provider = get_llm_provider("moonshot")
        global_endpoint = replace(
            provider.international_service_endpoint,
            api_key_url="https://platform.kimi.ai/?new-tracking=1",
        )
        updated_provider = replace(
            provider,
            service_endpoints=tuple(
                global_endpoint if endpoint.endpoint_id == "global" else endpoint
                for endpoint in provider.service_endpoints
            ),
        )

        selected = updated_provider.select_service_endpoint(
            "",
            has_api_key=False,
            prefer_international=True,
        )

        self.assertEqual(selected.endpoint_id, "global")
        self.assertEqual(selected.api_key_url, global_endpoint.api_key_url)

    def test_example_config_does_not_duplicate_registry_defaults(self):
        """The example config only stores user overrides; default models and addresses are maintained solely by the Registry."""
        config_path = Path(__file__).parent.parent.parent / "config.example.toml"
        app_config = tomllib.loads(config_path.read_text(encoding="utf-8"))["app"]

        for provider in LLM_PROVIDER_REGISTRY:
            if provider.default_model:
                self.assertEqual(
                    app_config.get(provider.config_key("model_name"), ""),
                    "",
                    provider.provider_id,
                )
            if provider.effective_default_base_url:
                self.assertEqual(
                    app_config.get(provider.config_key("base_url"), ""),
                    "",
                    provider.provider_id,
                )
            for field in provider.extra_fields:
                if field.default_value:
                    self.assertEqual(
                        app_config.get(provider.config_key(field.config_suffix), ""),
                        "",
                        provider.provider_id,
                    )

    def test_removed_ernie_provider_is_unsupported(self):
        """After ERNIE was removed, leftover config should return a clear error instead of making the old OAuth request."""
        config.app["llm_provider"] = "ernie"

        with patch.object(llm, "OpenAI") as openai_client:
            result = llm._generate_response("test")

        openai_client.assert_not_called()
        self.assertIn("unsupported llm provider", result)

    def test_pollinations_requires_api_key_before_request(self):
        """The new unified API requires auth, so anonymous generation requests must not be sent when the Key is missing."""
        config.app.update(
            {
                "llm_provider": "pollinations",
                "pollinations_api_key": "",
                "pollinations_base_url": "",
                "pollinations_model_name": "",
            }
        )

        with patch.object(llm, "OpenAI") as openai_client:
            result = llm._generate_response("test")

        openai_client.assert_not_called()
        self.assertIn("api_key is not set", result)

    def test_pollinations_uses_unified_openai_compatible_api(self):
        """Historical addresses and model names should be migrated automatically and called through the unified Chat Completions API."""
        config.app.update(
            {
                "llm_provider": "pollinations",
                "pollinations_api_key": "pollinations-test-key",
                "pollinations_base_url": "https://text.pollinations.ai/openai/",
                "pollinations_model_name": "default",
            }
        )

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\npollinations")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="pollinations-test-key",
            base_url="https://gen.pollinations.ai/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "openai-fast",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\npollinations")

    def test_anthropic_uses_openai_compatible_chat_completions(self):
        """Claude uses Anthropic's OpenAI-compatible endpoint and needs no extra adapter branch."""
        config.app.update(
            {
                "llm_provider": "anthropic",
                "anthropic_api_key": "anthropic-test-key",
                "anthropic_base_url": "",
                "anthropic_model_name": "",
            }
        )

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nclaude")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="anthropic-test-key",
            base_url="https://api.anthropic.com/v1/",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "claude-sonnet-5",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nclaude")

    def test_gemini_uses_google_genai_client(self):
        """The Gemini adapter should make content generation requests through the new SDK's unified Client."""
        config.app.update(
            {
                "llm_provider": "gemini",
                "gemini_api_key": "gemini-test-key",
                "gemini_base_url": "",
                "gemini_model_name": "gemini-test-model",
            }
        )
        captured = {}

        class FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return types.SimpleNamespace(text="hello\ngemini")

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs
                self.models = FakeModels()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                captured["closed"] = True

        with patch("google.genai.Client", FakeClient):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "hello\ngemini")
        self.assertEqual(
            captured["client_kwargs"],
            {"api_key": "gemini-test-key", "http_options": None},
        )
        self.assertEqual(captured["model"], "gemini-test-model")
        self.assertEqual(captured["contents"], "Say hello")
        self.assertEqual(captured["config"].max_output_tokens, 2048)
        self.assertTrue(captured["closed"])

    def test_cloudflare_requires_account_id_before_request(self):
        """Cloudflare should fail locally when the Account ID is missing, without sending an invalid request."""
        config.app.update(
            {
                "llm_provider": "cloudflare",
                "cloudflare_api_key": "test-token",
                "cloudflare_account_id": "",
                "cloudflare_model_name": "",
            }
        )

        with patch.object(llm, "OpenAI") as openai_client:
            result = llm._generate_response("test")

        openai_client.assert_not_called()
        self.assertIn("account_id is not set", result)

    def test_cloudflare_uses_ai_gateway_openai_endpoint(self):
        """The Cloudflare Provider must go through AI Gateway and no longer call the Workers AI endpoint."""
        config.app.update(
            {
                "llm_provider": "cloudflare",
                "cloudflare_api_key": "cloudflare-token",
                "cloudflare_account_id": "account-123",
                "cloudflare_gateway_id": "",
                "cloudflare_model_name": "",
            }
        )

        fake_response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="gateway\nresponse")
                )
            ]
        )

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return fake_response

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="cloudflare-token",
            base_url=(
                "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1"
            ),
            default_headers={"cf-aig-gateway-id": "default"},
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "gateway\nresponse")

    def _use_litellm_provider(self, model_name="openai/gpt-4o-mini"):
        config.app["llm_provider"] = "litellm"
        config.app["litellm_model_name"] = model_name

    def test_litellm_provider_returns_normalized_text(self):
        """
        Verify the LiteLLM provider's main path doesn't depend on the real network or private API keys.

        A fake module is injected into `sys.modules` here, directly overriding the dynamically imported
        `litellm.completion()`, so the test reliably covers the litellm branch in
        `_generate_response()`.
        """
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace()

        def _completion(**kwargs):
            self.assertEqual(kwargs["model"], "openai/gpt-4o-mini")
            self.assertEqual(
                kwargs["messages"], [{"role": "user", "content": "Say hello"}]
            )
            self.assertTrue(kwargs["drop_params"])
            message = types.SimpleNamespace(content="hello\nworld")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

        fake_litellm.completion = _completion

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "hello\nworld")

    def test_litellm_provider_uses_registry_default_model(self):
        self._use_litellm_provider(model_name="")

        fake_litellm = types.SimpleNamespace()

        def _completion(**kwargs):
            self.assertEqual(kwargs["model"], "openai/gpt-4o-mini")
            message = types.SimpleNamespace(content="default model")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

        fake_litellm.completion = _completion

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertEqual(result, "default model")

    def test_litellm_provider_handles_empty_response(self):
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace(
            completion=lambda **kwargs: types.SimpleNamespace(choices=[])
        )

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("returned empty response", result)

    def test_litellm_provider_handles_empty_message(self):
        """
        Some OpenAI-compatible gateways return HTTP 200 on content filtering or safety blocks,
        but with `choices[0].message` as None. A diagnosable error must be returned here
        rather than raising AttributeError.
        """
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace(
            completion=lambda **kwargs: types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=None)]
            )
        )

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("returned empty message", result)

    def test_sanitize_error_message_redacts_url_credentials_and_query_tokens(self):
        message = (
            "request failed for "
            "https://myuser:mypassword@proxy.example.com/v1/chat"
            "?api_key=secret-key&token=secret-token&safe=value"
        )

        result = llm._sanitize_error_message(message)

        self.assertIn("https://***:***@proxy.example.com", result)
        self.assertIn("api_key=***", result)
        self.assertIn("token=***", result)
        self.assertIn("safe=value", result)
        self.assertNotIn("myuser", result)
        self.assertNotIn("mypassword", result)
        self.assertNotIn("secret-key", result)
        self.assertNotIn("secret-token", result)

    def test_sanitize_error_message_redacts_token_only_url_userinfo(self):
        # Gateways commonly accept the API token as the URL username with no
        # password, e.g. https://<token>@gateway/v1.
        message = (
            "Connection error to https://sk-live-SECRET@gw.example.com/v1/chat; "
            "see https://gw.example.com/status?page=1 or ops@example.com"
        )

        result = llm._sanitize_error_message(message)

        self.assertIn("https://***:***@gw.example.com/v1/chat", result)
        self.assertNotIn("sk-live-SECRET", result)
        self.assertIn("https://gw.example.com/status?page=1", result)
        self.assertIn("ops@example.com", result)

    def test_openai_provider_error_redacts_embedded_base_url_credentials(self):
        """
        A custom OpenAI-compatible base_url may contain a proxy gateway's user:pass.
        SDK errors often carry the URL back in the exception message, so this verifies the `Error:` text finally returned to the WebUI/API
        doesn't leak those credentials.
        """
        config.app["llm_provider"] = "groq"
        config.app["groq_api_key"] = "groq-key"
        config.app["groq_model_name"] = "openai/gpt-oss-120b"
        config.app["groq_base_url"] = (
            "https://myuser:mypassword@proxy.example.com/openai/v1"
        )

        class FakeCompletions:
            def create(self, **kwargs):
                raise RuntimeError(
                    "connection failed: "
                    "https://myuser:mypassword@proxy.example.com/openai/v1"
                    "?access_token=secret-token"
                )

        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "OpenAI", return_value=fake_client):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("https://***:***@proxy.example.com", result)
        self.assertIn("access_token=***", result)
        self.assertNotIn("myuser", result)
        self.assertNotIn("mypassword", result)
        self.assertNotIn("secret-token", result)

    def test_openai_provider_still_uses_existing_path(self):
        config.app["llm_provider"] = "openai"
        config.app["openai_api_key"] = ""
        config.app["openai_base_url"] = "https://api.openai.com/v1"
        config.app["openai_model_name"] = "gpt-4o-mini"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())

    def _use_qwen_provider(self):
        config.app["llm_provider"] = "qwen"
        config.app["qwen_api_key"] = "qwen-key"
        config.app["qwen_model_name"] = "qwen-max"

    def _patch_dashscope_generation(self, response):
        class FakeGenerationResponse(dict):
            """dict de resposta que também aceita atributos como status_code."""

        fake_response = FakeGenerationResponse(response)
        fake_response.status_code = response.get("status_code", 200)
        fake_dashscope = types.SimpleNamespace(
            api_key="",
            Generation=types.SimpleNamespace(call=lambda **kwargs: fake_response),
        )
        fake_dashscope_response = types.SimpleNamespace(
            GenerationResponse=FakeGenerationResponse
        )

        return patch.dict(
            sys.modules,
            {
                "dashscope": fake_dashscope,
                "dashscope.api_entities": types.SimpleNamespace(),
                "dashscope.api_entities.dashscope_response": fake_dashscope_response,
            },
        )

    def test_qwen_provider_reads_chat_choices_content(self):
        """
        DashScope chat mode puts the text in `output.choices[0].message.content`.
        This covers the `output.text is None` scenario reported in issue #966, so
        `'NoneType' object has no attribute 'replace'` isn't triggered again.
        """
        self._use_qwen_provider()
        response = {
            "output": {
                "text": None,
                "choices": [{"message": {"content": "你好\n世界"}}],
            }
        }

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "你好\n世界")

    def test_qwen_provider_falls_back_to_output_text(self):
        """Keep the compatibility path for the old DashScope completion response structure."""
        self._use_qwen_provider()
        response = {"output": {"text": "旧格式\n响应"}}

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "旧格式\n响应")

    def test_qwen_provider_reports_empty_text(self):
        """An empty Qwen response should return a diagnosable error, not a low-level AttributeError."""
        self._use_qwen_provider()
        response = {
            "output": {"text": None, "choices": [{"message": {"content": None}}]}
        }

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertIn("Error:", result)
        self.assertIn("returned empty text content", result)
        self.assertNotIn("NoneType", result)

    def test_qwen_provider_reports_empty_choices(self):
        """A Qwen chat response with empty choices should return a clear error."""
        self._use_qwen_provider()
        response = {"output": {"text": None, "choices": []}}

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertIn("Error:", result)
        self.assertIn("returned empty choices", result)
        self.assertNotIn("NoneType", result)

    def test_qwen_concurrent_snapshots_keep_their_own_api_keys(self):
        class FakeGenerationResponse(dict):
            status_code = 200

        barrier = Barrier(2, timeout=5)
        calls = {}
        fake_dashscope = types.SimpleNamespace(api_key="unrelated-global-key")

        def call(**kwargs):
            barrier.wait()
            prompt = kwargs["messages"][0]["content"]
            calls[prompt] = kwargs.get("api_key")
            return FakeGenerationResponse({"output": {"text": prompt}})

        fake_dashscope.Generation = types.SimpleNamespace(call=call)
        modules = {
            "dashscope": fake_dashscope,
            "dashscope.api_entities": types.SimpleNamespace(),
            "dashscope.api_entities.dashscope_response": types.SimpleNamespace(
                GenerationResponse=FakeGenerationResponse
            ),
        }
        with patch.dict(sys.modules, modules), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                llm._generate_response,
                "first prompt",
                {"llm_provider": "qwen", "qwen_api_key": "first-key"},
            )
            second = pool.submit(
                llm._generate_response,
                "second prompt",
                {"llm_provider": "qwen", "qwen_api_key": "second-key"},
            )
            self.assertEqual(first.result(), "first prompt")
            self.assertEqual(second.result(), "second prompt")

        self.assertEqual(
            calls, {"first prompt": "first-key", "second prompt": "second-key"}
        )
        self.assertEqual(fake_dashscope.api_key, "unrelated-global-key")

    def test_apimart_provider_uses_unwrapped_openai_compatible_endpoint(self):
        """
        The APIMart docs show both `/api/v1` and `/v1` entry points. The former's example response
        has a code/data wrapper, so the OpenAI SDK can't read choices from the top level directly;
        the LLM Provider must use the standard `/v1` address to reuse the existing response parsing pipeline.
        """
        config.app["llm_provider"] = "apimart"
        config.app["apimart_api_key"] = "apimart-key"
        config.app["apimart_base_url"] = ""
        config.app["apimart_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\napimart")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="apimart-key",
            base_url="https://api.apimart.ai/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.6-terra",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\napimart")

    def test_aihubmix_provider_uses_openai_compatible_client(self):
        """
        AIHubMix is an OpenAI-compatible gateway. A fake OpenAI client is used here
        to verify the standalone Provider uses the Registry's default address and model, so the real network
        or private API Keys don't affect test stability.
        """
        config.app["llm_provider"] = "aihubmix"
        config.app["aihubmix_api_key"] = "aihubmix-key"
        config.app["aihubmix_base_url"] = ""
        config.app["aihubmix_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\naihubmix")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="aihubmix-key",
            base_url="https://aihubmix.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.4-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\naihubmix")

    def test_aimlapi_provider_uses_openai_compatible_client(self):
        config.app["llm_provider"] = "aimlapi"
        config.app["aimlapi_api_key"] = "aimlapi-key"
        config.app["aimlapi_base_url"] = ""
        config.app["aimlapi_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\naimlapi")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="aimlapi-key",
            base_url="https://api.aimlapi.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "openai/gpt-5-5",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\naimlapi")

    def test_evolink_provider_uses_openai_compatible_client(self):
        """
        EvoLink exposes OpenAI-compatible Chat Completions at direct.evolink.ai.
        The provider should keep its own default endpoint and model instead of
        requiring users to overload the generic OpenAI settings.
        """
        config.app["llm_provider"] = "evolink"
        config.app["evolink_api_key"] = "evolink-key"
        config.app["evolink_base_url"] = ""
        config.app["evolink_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nevolink")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="evolink-key",
            base_url="https://direct.evolink.ai/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nevolink")

    def test_iflytek_provider_uses_openai_compatible_client(self):
        """
        iFlytek Astron MaaS serves Spark over OpenAI-compatible Chat Completions.
        Pay-as-you-go is the default; a Token Plan base URL saved by the user
        must be used as-is because keys from one plan do not work on the other.
        """
        config.app["llm_provider"] = "iflytek"
        config.app["iflytek_api_key"] = "iflytek-key"
        config.app["iflytek_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\niflytek")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        for configured_base_url, expected_base_url in (
            ("", "https://maas-api.cn-huabei-1.xf-yun.com/v2"),
            (
                "https://maas-token-api.cn-huabei-1.xf-yun.com/v2",
                "https://maas-token-api.cn-huabei-1.xf-yun.com/v2",
            ),
        ):
            with self.subTest(base_url=configured_base_url):
                config.app["iflytek_base_url"] = configured_base_url
                fake_completions = FakeCompletions()
                fake_client = types.SimpleNamespace(
                    chat=types.SimpleNamespace(completions=fake_completions)
                )

                with (
                    patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
                    patch.object(llm, "ChatCompletion", types.SimpleNamespace),
                ):
                    result = llm._generate_response("Say hello")

                openai_client.assert_called_once_with(
                    api_key="iflytek-key",
                    base_url=expected_base_url,
                )
                self.assertEqual(
                    fake_completions.kwargs,
                    {
                        "model": "spark-x2.5",
                        "messages": [{"role": "user", "content": "Say hello"}],
                    },
                )
                self.assertEqual(result, "hello\niflytek")
    def test_openrouter_provider_uses_openai_compatible_client(self):
        """
        OpenRouter exposes OpenAI-compatible Chat Completions through one
        unified endpoint. The default model stays on a currently free text model
        suitable for script and keyword generation.
        """
        config.app["llm_provider"] = "openrouter"
        config.app["openrouter_api_key"] = "openrouter-key"
        config.app["openrouter_base_url"] = ""
        config.app["openrouter_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nopenrouter")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="openrouter-key",
            base_url="https://openrouter.ai/api/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "minimax/minimax-m3:free",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nopenrouter")

    def test_api_route_provider_uses_openai_compatible_client(self):
        """
        API Route exposes OpenAI-compatible Chat Completions through one
        unified endpoint with intelligent routing and high availability.
        """
        config.app["llm_provider"] = "api_route"
        config.app["api_route_api_key"] = "api-route-key"
        config.app["api_route_base_url"] = ""
        config.app["api_route_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\napi_route")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="api-route-key",
            base_url="https://www.api-route.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.4-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\napi_route")

    def test_volcengine_provider_uses_openai_compatible_client(self):
        """
        VolcEngine Ark exposes OpenAI-compatible Chat Completions.
        A fake OpenAI client covers the provider's default address and default model here,
        so the real network or private API keys don't affect test stability.
        """
        config.app["llm_provider"] = "volcengine"
        config.app["volcengine_api_key"] = "volcengine-key"
        config.app["volcengine_base_url"] = ""
        config.app["volcengine_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nvolcengine")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="volcengine-key",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "doubao-seed-2-1-turbo-260628",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nvolcengine")

    def test_grok_provider_still_uses_existing_path(self):
        config.app["llm_provider"] = "grok"
        config.app["grok_api_key"] = ""
        config.app["grok_base_url"] = "https://api.x.ai/v1"
        config.app["grok_model_name"] = "grok-4.3"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())

    def test_groq_provider_requires_api_key(self):
        config.app["llm_provider"] = "groq"
        config.app["groq_api_key"] = ""
        config.app["groq_base_url"] = "https://api.groq.com/openai/v1"
        config.app["groq_model_name"] = "openai/gpt-oss-120b"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())

    def test_groq_provider_uses_default_base_url(self):
        config.app["llm_provider"] = "groq"
        config.app["groq_api_key"] = "groq-test-key"
        config.app["groq_base_url"] = ""
        config.app["groq_model_name"] = "openai/gpt-oss-120b"

        fake_response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="hello\ngroq")
                )
            ]
        )
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **kwargs: fake_response)
            )
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="groq-test-key",
            base_url="https://api.groq.com/openai/v1",
        )
        self.assertEqual(result, "hello\ngroq")

    def _use_ollama_provider(self, base_url=""):
        config.app["llm_provider"] = "ollama"
        config.app["ollama_api_key"] = ""
        config.app["ollama_base_url"] = base_url
        config.app["ollama_model_name"] = "llama3"

    def _call_ollama_generate_response(self):
        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nollama")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        return openai_client, fake_completions, result

    def test_ollama_default_base_url_uses_localhost_outside_container(self):
        """
        When running directly on a machine, Ollama still defaults to localhost, so existing users aren't affected.
        """
        self._use_ollama_provider()

        with patch.object(config, "is_running_in_container", return_value=False):
            openai_client, fake_completions, result = (
                self._call_ollama_generate_response()
            )

        self.assertEqual(
            openai_client.call_args.kwargs,
            {"api_key": "ollama", "base_url": "http://localhost:11434/v1"},
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nollama")

    def test_ollama_default_base_url_uses_host_gateway_inside_container(self):
        """
        Inside a container, localhost points to the container itself; the default changes to host.docker.internal,
        so Docker Desktop users can reach Ollama on the host.
        """
        self._use_ollama_provider()

        with (
            patch.object(config, "is_running_in_container", return_value=True),
            patch.object(config, "_can_resolve_hostname", return_value=True),
        ):
            openai_client, fake_completions, result = (
                self._call_ollama_generate_response()
            )

        self.assertEqual(
            openai_client.call_args.kwargs,
            {"api_key": "ollama", "base_url": "http://host.docker.internal:11434/v1"},
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nollama")

    def test_ollama_default_base_url_falls_back_to_container_gateway(self):
        """
        Native Linux Docker can't necessarily resolve host.docker.internal. Using the container's
        default gateway as a fallback address is more reliable than returning an unresolvable hostname.
        """
        self._use_ollama_provider()

        with (
            patch.object(config, "is_running_in_container", return_value=True),
            patch.object(config, "_can_resolve_hostname", return_value=False),
            patch.object(
                config, "get_container_default_gateway_ip", return_value="172.17.0.1"
            ),
        ):
            openai_client, fake_completions, result = (
                self._call_ollama_generate_response()
            )

        self.assertEqual(
            openai_client.call_args.kwargs,
            {"api_key": "ollama", "base_url": "http://172.17.0.1:11434/v1"},
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nollama")

    def test_ollama_explicit_base_url_takes_precedence(self):
        """
        A user-configured ollama_base_url has the highest priority and isn't affected by container detection.
        """
        self._use_ollama_provider(base_url="http://ollama:11434/v1")

        with patch.object(config, "is_running_in_container", return_value=True):
            openai_client, fake_completions, result = (
                self._call_ollama_generate_response()
            )

        self.assertEqual(
            openai_client.call_args.kwargs,
            {"api_key": "ollama", "base_url": "http://ollama:11434/v1"},
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nollama")

    def test_mimo_provider_uses_openai_compatible_client(self):
        """
        The official MiMo API is compatible with the OpenAI Chat Completions protocol. A fake OpenAI
        client verifies the provider uses MiMo's separate config and default base_url, without depending on
        the real network or private API Keys.
        """
        config.app["llm_provider"] = "mimo"
        config.app["mimo_api_key"] = "mimo-key"
        config.app["mimo_base_url"] = ""
        config.app["mimo_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nmimo")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="mimo-key",
            base_url="https://api.xiaomimimo.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nmimo")

    def test_azure_provider_uses_azure_client_directly(self):
        """
        Azure OpenAI's auth, endpoint and api-version are all handled by the AzureOpenAI client.
        This test covers issue #892: the azure branch must call the client created by AzureOpenAI directly
        and must not fall into the ordinary OpenAI-compatible branch, or the Azure-specific request config would be lost.
        """
        config.app["llm_provider"] = "azure"
        config.app["azure_api_key"] = "azure-key"
        config.app["azure_base_url"] = "https://example.openai.azure.com"
        config.app["azure_model_name"] = "gpt-4o-mini"
        config.app["azure_api_version"] = "2024-02-15-preview"

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nazure")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "AzureOpenAI", return_value=fake_client) as azure_client,
            patch.object(llm, "OpenAI") as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        azure_client.assert_called_once_with(
            api_key="azure-key",
            api_version="2024-02-15-preview",
            azure_endpoint="https://example.openai.azure.com",
        )
        openai_client.assert_not_called()
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nazure")

    def test_unsupported_provider_returns_clear_error(self):
        config.app["llm_provider"] = "g" + "4f"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("unsupported llm provider", result)


class TestClaudeCodeProvider(unittest.TestCase):
    """The claude_code Provider calls the subscription account through the local claude CLI, not an HTTP API."""

    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["llm_provider"] = "claude_code"
        config.app["claude_code_model_name"] = ""
        config.app["claude_code_cli_path"] = ""
        config.app["claude_code_timeout"] = ""

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    @staticmethod
    def _completed(stdout="", stderr="", returncode=0):
        return types.SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=returncode
        )

    @staticmethod
    def _cli_payload(result, is_error=False):
        return json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": is_error,
                "result": result,
            }
        )

    # ------------------------------------------------------------- success
    def test_successful_generation_returns_cli_result_text(self):
        """Only result in the JSON returned by the CLI is the body; other fields must not leak into the script."""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("Hello world")),
            ) as run,
        ):
            self.assertEqual(llm._generate_response("write something"), "Hello world")

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/claude")
        self.assertIn("-p", command)
        self.assertEqual(
            run.call_args.kwargs["timeout"], llm.CLAUDE_CODE_DEFAULT_TIMEOUT
        )

    def test_generation_disables_tools_and_user_customizations(self):
        """Plain text generation must disable all tools and user-level customizations, so files aren't read or written and skills aren't loaded."""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response("write something")

        command = run.call_args.args[0]
        self.assertIn("--tools", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--safe-mode", command)
        self.assertIn("--system-prompt", command)
        self.assertEqual(
            command[command.index("--system-prompt") + 1],
            llm.CLAUDE_CODE_SYSTEM_PROMPT,
        )

    def test_prompt_is_sent_through_stdin_not_argv(self):
        """On Windows the npm-installed claude is claude.cmd, and cmd.exe truncates arguments at the first newline,
        losing a multi-line prompt and the isolation arguments after it, so the prompt must go through stdin."""
        prompt = "# Role: Generator\n\n## Goals:\nwrite something"
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response(prompt)

        command = run.call_args.args[0]
        self.assertFalse(any("\n" in arg for arg in command))
        self.assertNotIn(prompt, command)
        self.assertEqual(run.call_args.kwargs["input"], prompt)

    def test_model_name_is_only_passed_when_configured(self):
        """When the model name is empty, the CLI default model should be used instead of hardcoding an ID that may stop working."""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response("write something")
            self.assertNotIn("--model", run.call_args.args[0])

            config.app["claude_code_model_name"] = "claude-opus-5"
            llm._generate_response("write something")
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--model") + 1], "claude-opus-5")

    # ------------------------------------------------- credential isolation
    def test_conflicting_credentials_are_removed_from_subprocess_env(self):
        """An API Key in the environment would make the CLI bypass the subscription login and incur API charges, so it must be stripped."""
        polluted = {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-ant-api03-should-not-be-used",
            "ANTHROPIC_BASE_URL": "https://proxy.example.com",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-subscription",
        }
        env, removed = llm.build_claude_code_env(polluted)

        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)
        # The subscription token is the only auth method inside the container and must be kept.
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat01-subscription")
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertCountEqual(
            removed,
            ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK"],
        )

    def test_every_cloud_provider_switch_is_removed(self):
        """Switches such as Bedrock / Vertex / Foundry / Mantle / Gateway all switch to cloud vendor billing."""
        switches = {
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_USE_VERTEX": "1",
            "CLAUDE_CODE_USE_FOUNDRY": "1",
            "CLAUDE_CODE_USE_MANTLE": "1",
            "CLAUDE_CODE_USE_GATEWAY": "1",
            "CLAUDE_CODE_USE_ANTHROPIC_AWS": "1",
            "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD": "1",
        }
        env, removed = llm.build_claude_code_env({"PATH": "/usr/bin", **switches})

        self.assertEqual(env, {"PATH": "/usr/bin"})
        self.assertCountEqual(removed, list(switches))

    def test_foundry_credentials_are_removed(self):
        """Foundry credentials would make the CLI use Azure billing, so both credentials and switches must be stripped."""
        foundry = {
            "CLAUDE_CODE_USE_FOUNDRY": "1",
            "ANTHROPIC_FOUNDRY_API_KEY": "foundry-key",
            "ANTHROPIC_FOUNDRY_AUTH_TOKEN": "foundry-token",
            "ANTHROPIC_FOUNDRY_BASE_URL": "https://example.openai.azure.com",
            "ANTHROPIC_FOUNDRY_RESOURCE": "my-resource",
            "CLAUDE_CODE_SKIP_FOUNDRY_AUTH": "1",
        }
        env, removed = llm.build_claude_code_env(
            {"PATH": "/usr/bin", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01", **foundry}
        )

        for name in foundry:
            self.assertNotIn(name, env, name)
        self.assertCountEqual(removed, list(foundry))
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat01")

    def test_auth_bypass_switches_are_removed(self):
        """CLAUDE_CODE_SKIP_*_AUTH skips provider auth and likewise must not be passed to the subprocess."""
        bypasses = {
            "CLAUDE_CODE_SKIP_BEDROCK_AUTH": "1",
            "CLAUDE_CODE_SKIP_VERTEX_AUTH": "1",
            "CLAUDE_CODE_SKIP_MANTLE_AUTH": "1",
            "CLAUDE_CODE_SKIP_ANTHROPIC_AWS_AUTH": "1",
        }
        env, removed = llm.build_claude_code_env({"PATH": "/usr/bin", **bypasses})
        self.assertEqual(env, {"PATH": "/usr/bin"})
        self.assertCountEqual(removed, list(bypasses))

    def test_credential_location_variables_are_preserved(self):
        """*_CONFIG_DIR only points to where credentials are stored; stripping it would actually break an existing subscription login."""
        preserved = {
            "ANTHROPIC_CONFIG_DIR": "/home/user/.config/anthropic",
            "CLAUDE_CONFIG_DIR": "/home/user/.claude",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01",
        }
        env, removed = llm.build_claude_code_env(dict(preserved))
        self.assertEqual(env, preserved)
        self.assertEqual(removed, [])

    def test_unrelated_variables_are_never_removed(self):
        """Filtering only targets auth and provider switches and shouldn't affect ordinary variables like PATH and proxies."""
        env, removed = llm.build_claude_code_env(
            {"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy:3128", "HOME": "/root"}
        )
        self.assertEqual(
            env,
            {"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy:3128", "HOME": "/root"},
        )
        self.assertEqual(removed, [])

    def test_clean_environment_is_left_unchanged(self):
        env, removed = llm.build_claude_code_env({"PATH": "/usr/bin"})
        self.assertEqual(env, {"PATH": "/usr/bin"})
        self.assertEqual(removed, [])

    def test_subprocess_receives_sanitized_environment(self):
        """The adapter must actually pass the cleaned environment to the subprocess, not just compute it."""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.dict(
                os.environ, {"ANTHROPIC_API_KEY": "sk-ant-api03-x"}, clear=False
            ),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response("write something")

        self.assertNotIn("ANTHROPIC_API_KEY", run.call_args.kwargs["env"])

    # ------------------------------------------------------- timeout config
    def test_timeout_accepts_numeric_and_string_values(self):
        """In TOML 300 is an int and "300" is a str; both forms must be supported."""
        self.assertEqual(llm.coerce_claude_code_timeout(300), 300.0)
        self.assertEqual(llm.coerce_claude_code_timeout(300.5), 300.5)
        self.assertEqual(llm.coerce_claude_code_timeout("300"), 300.0)
        self.assertEqual(llm.coerce_claude_code_timeout("  300  "), 300.0)
        self.assertEqual(
            llm.coerce_claude_code_timeout(""), llm.CLAUDE_CODE_DEFAULT_TIMEOUT
        )
        self.assertEqual(
            llm.coerce_claude_code_timeout(None), llm.CLAUDE_CODE_DEFAULT_TIMEOUT
        )

    def test_timeout_rejects_non_finite_and_invalid_values(self):
        """nan / inf would make subprocess block forever, so they must be rejected at the config stage."""
        for invalid in (
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "inf",
            "-inf",
            0,
            -5,
            "abc",
            True,
            [300],
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    llm.coerce_claude_code_timeout(invalid)

    def test_integer_timeout_in_config_is_accepted(self):
        """Regression test: an int timeout once triggered 'int' object has no attribute 'strip'."""
        config.app["claude_code_timeout"] = 30
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            self.assertEqual(llm._generate_response("write something"), "ok")
        self.assertEqual(run.call_args.kwargs["timeout"], 30.0)

    def test_zero_and_false_timeouts_are_rejected_not_defaulted(self):
        """0 / false are invalid values and must raise, not be quietly replaced by the 300-second default."""
        for invalid in (0, False, "0", 0.0):
            with self.subTest(invalid=invalid):
                config.app["claude_code_timeout"] = invalid
                with patch.object(llm.shutil, "which", return_value="/usr/bin/claude"):
                    response = llm._generate_response("write something")
                self.assertTrue(response.startswith("Error:"), response)
                self.assertIn("claude_code_timeout", response)

    def test_field_default_applies_only_to_empty_values(self):
        """Registry defaults only apply when not configured; valid falsy values must go into validation as-is."""
        self.assertEqual(llm._resolve_provider_field_value(None, "300"), "300")
        self.assertEqual(llm._resolve_provider_field_value("", "300"), "300")
        self.assertEqual(llm._resolve_provider_field_value("   ", "300"), "300")
        self.assertEqual(llm._resolve_provider_field_value(0, "300"), 0)
        self.assertEqual(llm._resolve_provider_field_value(False, "300"), False)
        self.assertEqual(llm._resolve_provider_field_value("60", "300"), "60")

    def test_invalid_timeout_reports_configuration_error(self):
        config.app["claude_code_timeout"] = "soon"
        with patch.object(llm.shutil, "which", return_value="/usr/bin/claude"):
            response = llm._generate_response("write something")
        self.assertIn("claude_code_timeout", response)
        self.assertTrue(response.startswith("Error:"), response)

    # -------------------------------------------------------- failure modes
    def test_missing_cli_reports_actionable_error(self):
        with (
            patch.object(llm.shutil, "which", return_value=None),
            patch.object(llm.os.path, "isfile", return_value=False),
        ):
            response = llm._generate_response("write something")
        self.assertIn("claude CLI not found", response)

    def test_missing_login_reports_setup_token_hint(self):
        """An interactive /login can't run in a container, so the error message must give usable alternatives."""
        payload = self._cli_payload("Not logged in · Please run /login", is_error=True)
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=payload, returncode=1),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("Not logged in", response)
        self.assertIn("setup-token", response)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", response)

    def test_exhausted_quota_surfaces_cli_message(self):
        """Usage exhaustion is also is_error + a non-zero exit code, and the readable reason must be passed through as-is."""
        payload = self._cli_payload(
            "Claude usage limit reached. Your limit will reset at 5pm.", is_error=True
        )
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=payload, returncode=1),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("usage limit reached", response)

    def test_timeout_is_reported_with_configured_seconds(self):
        config.app["claude_code_timeout"] = 12
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                side_effect=llm.subprocess.TimeoutExpired(cmd="claude", timeout=12),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("timed out after 12s", response)

    def test_malformed_output_is_reported_instead_of_crashing(self):
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout="not json at all"),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("invalid response", response)

    def test_empty_output_is_reported(self):
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess, "run", return_value=self._completed(stdout="   ")
            ),
        ):
            response = llm._generate_response("write something")
        self.assertTrue(response.startswith("Error:"), response)

    def test_unsupported_cli_version_reports_upgrade_hint(self):
        """Old CLIs lack --tools / --safe-mode and should suggest upgrading rather than dumping raw stderr."""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(
                    stderr="error: unknown option '--safe-mode'", returncode=1
                ),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("upgrade", response.lower())
        self.assertIn(llm.CLAUDE_CODE_MIN_CLI_VERSION, response)


class TestRuntimeEnvironmentDetection(unittest.TestCase):
    def test_container_detection_ignores_plain_linux_cgroup_file(self):
        """
        Ordinary Linux also has /proc/1/cgroup, so the file's existence alone can't mean it's a container.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            cgroup_path = Path(tmp_dir) / "cgroup"
            cgroup_path.write_text("0::/init.scope\n", encoding="utf-8")

            self.assertFalse(
                config.is_running_in_container(
                    dockerenv_path=str(Path(tmp_dir) / "missing-dockerenv"),
                    containerenv_path=str(Path(tmp_dir) / "missing-containerenv"),
                    cgroup_path=str(cgroup_path),
                )
            )

    def test_container_detection_accepts_dockerenv_marker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dockerenv_path = Path(tmp_dir) / ".dockerenv"
            dockerenv_path.write_text("", encoding="utf-8")

            self.assertTrue(
                config.is_running_in_container(
                    dockerenv_path=str(dockerenv_path),
                    containerenv_path=str(Path(tmp_dir) / "missing-containerenv"),
                    cgroup_path=str(Path(tmp_dir) / "missing-cgroup"),
                )
            )

    def test_container_detection_accepts_cgroup_container_marker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cgroup_path = Path(tmp_dir) / "cgroup"
            cgroup_path.write_text(
                "0::/system.slice/docker-abcdef.scope\n",
                encoding="utf-8",
            )

            self.assertTrue(
                config.is_running_in_container(
                    dockerenv_path=str(Path(tmp_dir) / "missing-dockerenv"),
                    containerenv_path=str(Path(tmp_dir) / "missing-containerenv"),
                    cgroup_path=str(cgroup_path),
                )
            )

    def test_container_gateway_ip_decodes_default_route(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            route_path = Path(tmp_dir) / "route"
            route_path.write_text(
                "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                "eth0\t00000000\t010011AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n",
                encoding="utf-8",
            )

            self.assertEqual(
                config.get_container_default_gateway_ip(str(route_path)),
                "172.17.0.1",
            )

    def test_container_gateway_ip_ignores_missing_default_route(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            route_path = Path(tmp_dir) / "route"
            route_path.write_text(
                "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                "eth0\t0011AC0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n",
                encoding="utf-8",
            )

            self.assertEqual(
                config.get_container_default_gateway_ip(str(route_path)), ""
            )


class TestSocialMetadata(unittest.TestCase):
    """Generic short-video publishing metadata generation."""

    def test_build_prompt_auto_language_uses_source_language(self):
        """
        When language defaults to auto, it shouldn't be fixed to a particular country or language; the model
        should follow the language of the video subject and script, widening the API's applicability.
        """
        prompt = llm.build_social_metadata_prompt(
            video_subject="上海一日游",
            video_script="今天带你快速看完上海经典路线。",
            language="auto",
            platform="tiktok",
        )

        self.assertIn("TikTok", prompt)
        self.assertIn("Use the same language as the video subject and script", prompt)
        self.assertIn("上海一日游", prompt)
        self.assertIn("array of exactly 5 strings", prompt)

    def test_build_prompt_accepts_explicit_language(self):
        prompt = llm.build_social_metadata_prompt(
            video_subject="Coffee tips",
            language="en-US",
            platform="youtube_shorts",
        )

        self.assertIn("YouTube Shorts", prompt)
        self.assertIn('Write "title" and "caption" in this language: en-US', prompt)
        self.assertIn("array of exactly 3 strings", prompt)

    def test_unknown_platform_falls_back_to_tiktok(self):
        prompt = llm.build_social_metadata_prompt(
            video_subject="x",
            platform="unsupported-platform",
        )

        self.assertIn("TikTok", prompt)

    def test_normalize_hashtags_from_string_dedupes_and_clamps(self):
        tags = llm._normalize_hashtags("#fyp fyp, trending #Trending viral", count=2)

        self.assertEqual(tags, ["#fyp", "#trending"])

    def test_normalize_hashtags_from_string_splits_cjk_separators(self):
        tags = llm._normalize_hashtags("#旅行，#美食、#日常；#東京#グルメ", count=5)

        self.assertEqual(tags, ["#旅行", "#美食", "#日常", "#東京", "#グルメ"])

    def test_normalize_hashtags_from_list_keeps_unicode_letters(self):
        tags = llm._normalize_hashtags(
            ["上海 旅行", "#việt nam", "  ", "@bad!chars"], count=5
        )

        self.assertEqual(tags, ["#上海旅行", "#việtnam", "#badchars"])

    def test_normalize_hashtags_keeps_combining_marks(self):
        tags = llm._normalize_hashtags(["#भारत", "#বাংলা", "#தமிழ்", "#ท่องเที่ยว"], count=5)

        self.assertEqual(tags, ["#भारत", "#বাংলা", "#தமிழ்", "#ท่องเที่ยว"])

    def test_parse_social_metadata_recovers_embedded_json(self):
        raw = 'Sure: {"title":"T","caption":"C","hashtags":["#x"]} thanks'
        result = llm._parse_social_metadata(raw, "tiktok")

        self.assertEqual(result["title"], "T")
        self.assertEqual(result["caption"], "C")
        self.assertEqual(result["hashtags"], ["#x"])

    def test_parse_social_metadata_requires_title_or_caption(self):
        with self.assertRaises(ValueError):
            llm._parse_social_metadata('{"hashtags":["#x"]}', "tiktok")

    def test_generate_social_metadata_uses_llm_response(self):
        payload = (
            '{"title":"上海一日游","caption":"收藏这条路线，下次直接出发！",'
            '"hashtags":["#上海","#旅行","#shorts"]}'
        )
        with patch.object(llm, "_generate_response", return_value=payload):
            result = llm.generate_social_metadata(
                video_subject="上海一日游",
                video_script="今天带你快速看完上海经典路线。",
                language="zh-CN",
                platform="tiktok",
            )

        self.assertEqual(result["title"], "上海一日游")
        self.assertEqual(result["caption"], "收藏这条路线，下次直接出发！")
        self.assertEqual(result["hashtags"], ["#上海", "#旅行", "#shorts"])

    def test_generate_social_metadata_falls_back_to_generic_hashtags(self):
        with patch.object(
            llm, "_generate_response", return_value="Error: api_key is not set"
        ):
            result = llm.generate_social_metadata(
                video_subject="Coffee tips",
                video_script="Save these three coffee tips.",
                platform="instagram_reels",
            )

        self.assertEqual(result["title"], "Coffee tips")
        self.assertEqual(result["caption"], "Save these three coffee tips.")
        self.assertEqual(len(result["hashtags"]), 8)
        self.assertEqual(result["hashtags"][0], "#shorts")

    def test_request_model_defaults_to_auto_language_tiktok(self):
        body = VideoSocialMetadataRequest(video_subject="Test")

        self.assertEqual(body.language, "auto")
        self.assertEqual(body.platform, "tiktok")

    def test_request_model_rejects_oversized_social_metadata_fields(self):
        """
        The external API can't accept unlimited-length scripts and language parameters, or LLM
        token costs would balloon. The schema layer blocks them first, and the service layer adds a fallback for internal calls.
        """
        with self.assertRaises(ValidationError):
            VideoSocialMetadataRequest(video_subject="x" * 501)

        with self.assertRaises(ValidationError):
            VideoSocialMetadataRequest(video_subject="x", video_script="x" * 8001)

        with self.assertRaises(ValidationError):
            VideoSocialMetadataRequest(video_subject="x", language="x" * 65)

    def test_build_prompt_clamps_direct_service_inputs(self):
        prompt = llm.build_social_metadata_prompt(
            video_subject="x" * 600,
            video_script="y" * 9000,
            language="en",
        )

        self.assertIn("x" * llm.MAX_SOCIAL_SUBJECT_LENGTH, prompt)
        self.assertNotIn("x" * (llm.MAX_SOCIAL_SUBJECT_LENGTH + 1), prompt)
        self.assertIn("y" * llm.MAX_SOCIAL_SCRIPT_LENGTH, prompt)
        self.assertNotIn("y" * (llm.MAX_SOCIAL_SCRIPT_LENGTH + 1), prompt)

    def test_social_metadata_endpoint_response_shape(self):
        from fastapi.testclient import TestClient

        from app.asgi import app

        request_body = {
            "video_subject": "Tokyo coffee shops",
            "video_script": "Three quiet coffee shops for your next Tokyo morning.",
            "language": "en",
            "platform": "youtube_shorts",
        }
        llm_response = (
            '{"title":"3 Quiet Tokyo Coffee Shops",'
            '"caption":"Save these spots for your next Tokyo morning.",'
            '"hashtags":["#Tokyo","#Coffee","#Shorts"]}'
        )

        with patch.object(llm, "_generate_response", return_value=llm_response):
            response = TestClient(app).post(
                "/api/v1/social-metadata",
                json=request_body,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": 200,
                "message": "success",
                "data": {
                    "title": "3 Quiet Tokyo Coffee Shops",
                    "caption": "Save these spots for your next Tokyo morning.",
                    "hashtags": ["#Tokyo", "#Coffee", "#Shorts"],
                },
            },
        )


FOUNDRY_KEY = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY", "")
FOUNDRY_BASE = "https://amanrai-test-resource.services.ai.azure.com/anthropic"
FOUNDRY_MODEL = "azure_ai/claude-sonnet-4-6"


@unittest.skipUnless(
    RUN_INTEGRATION_TESTS and FOUNDRY_KEY,
    "MPT_RUN_INTEGRATION_TESTS and ANTHROPIC_FOUNDRY_API_KEY not set",
)
class TestLiteLLMLiveIntegration(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["llm_provider"] = "litellm"
        config.app["litellm_model_name"] = FOUNDRY_MODEL
        os.environ["AZURE_AI_API_KEY"] = FOUNDRY_KEY
        os.environ["AZURE_AI_API_BASE"] = FOUNDRY_BASE

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_live_litellm_completion(self):
        result = llm._generate_response("What is 2+2? Reply with just the number.")

        self.assertNotIn("Error:", result)
        self.assertIn("4", result)


class TestRetryWarningBoundary(unittest.TestCase):
    """'trying again' must not be logged on the last retry attempt."""

    def _trying_again_count(self, mock_logger: object, fragment: str) -> int:
        return sum(
            1 for call in mock_logger.warning.call_args_list if fragment in str(call)
        )

    def test_generate_script_no_spurious_warning_on_last_attempt(self):
        with (
            patch.object(
                llm,
                "_generate_response",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch.object(llm, "logger") as mock_logger,
        ):
            llm.generate_script(video_subject="test subject")

        count = self._trying_again_count(mock_logger, "trying again")
        self.assertEqual(
            count,
            llm._max_retries - 1,
            "Warning must not fire on the final attempt — no further retry will occur",
        )

    def test_generate_terms_no_spurious_warning_on_last_attempt(self):
        with (
            patch.object(
                llm,
                "_generate_response",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch.object(llm, "logger") as mock_logger,
        ):
            llm.generate_terms(
                video_subject="test subject",
                video_script="some script text",
            )

        count = self._trying_again_count(mock_logger, "trying again")
        self.assertEqual(
            count,
            llm._max_retries - 1,
            "Warning must not fire on the final attempt — no further retry will occur",
        )


if __name__ == "__main__":
    unittest.main()
