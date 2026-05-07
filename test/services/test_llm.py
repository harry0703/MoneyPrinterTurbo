import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import llm


class TestLiteLLMProvider(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _use_litellm_provider(self, model_name="openai/gpt-4o-mini"):
        config.app["llm_provider"] = "litellm"
        config.app["litellm_model_name"] = model_name

    def test_litellm_provider_returns_normalized_text(self):
        """
        验证 LiteLLM provider 的主路径不依赖真实网络和私有 API key。

        这里用 fake module 注入 `sys.modules`，直接覆盖动态 import 的
        `litellm.completion()`，确保测试稳定覆盖 `_generate_response()` 里的
        litellm 分支。
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

        self.assertEqual(result, "helloworld")

    def test_litellm_provider_requires_model_name(self):
        self._use_litellm_provider(model_name="")

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("model_name is not set", result)

    def test_litellm_provider_handles_empty_response(self):
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace(
            completion=lambda **kwargs: types.SimpleNamespace(choices=[])
        )

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("returned empty response", result)

    def test_openai_provider_still_uses_existing_path(self):
        config.app["llm_provider"] = "openai"
        config.app["openai_api_key"] = ""
        config.app["openai_base_url"] = "https://api.openai.com/v1"
        config.app["openai_model_name"] = "gpt-4o-mini"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())


FOUNDRY_KEY = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY", "")
FOUNDRY_BASE = "https://amanrai-test-resource.services.ai.azure.com/anthropic"
FOUNDRY_MODEL = "azure_ai/claude-sonnet-4-6"


@unittest.skipUnless(FOUNDRY_KEY, "ANTHROPIC_FOUNDRY_API_KEY not set")
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


if __name__ == "__main__":
    unittest.main()
