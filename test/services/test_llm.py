"""Real integration tests for the litellm provider in app/services/llm.py.

These tests hit a live Azure AI Foundry endpoint (amanrai-test-resource)
via litellm. They require ANTHROPIC_FOUNDRY_API_KEY to be set in the
environment. Skipped automatically if the key is missing.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

FOUNDRY_KEY = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY", "")
FOUNDRY_BASE = "https://amanrai-test-resource.services.ai.azure.com/anthropic"
FOUNDRY_MODEL = "azure_ai/claude-sonnet-4-6"

requires_key = unittest.skipUnless(FOUNDRY_KEY, "ANTHROPIC_FOUNDRY_API_KEY not set")


def _setup_litellm_config(model=FOUNDRY_MODEL):
    from app.config import config
    config.app["llm_provider"] = "litellm"
    config.app["litellm_model_name"] = model
    os.environ["AZURE_AI_API_KEY"] = FOUNDRY_KEY
    os.environ["AZURE_AI_API_BASE"] = FOUNDRY_BASE


@requires_key
class TestLiteLLMBasicCompletion(unittest.TestCase):

    def setUp(self):
        _setup_litellm_config()

    def test_simple_math_question(self):
        from app.services.llm import _generate_response
        result = _generate_response("What is 2+2? Reply with just the number.")
        self.assertNotIn("Error:", result)
        self.assertIn("4", result)

    def test_response_is_string(self):
        from app.services.llm import _generate_response
        result = _generate_response("Say hello.")
        self.assertIsInstance(result, str)
        self.assertNotIn("Error:", result)
        self.assertTrue(len(result) > 0)

    def test_newlines_are_stripped(self):
        from app.services.llm import _generate_response
        result = _generate_response("Reply with exactly: line1\\nline2")
        self.assertNotIn("\n", result)


@requires_key
class TestLiteLLMGenerateScript(unittest.TestCase):

    def setUp(self):
        _setup_litellm_config()

    def test_generate_script_returns_nonempty(self):
        from app.services.llm import generate_script
        script = generate_script(
            video_subject="The beauty of sunsets",
            language="en",
            paragraph_number=1,
        )
        self.assertIsInstance(script, str)
        self.assertTrue(len(script) > 20, f"Script too short: {repr(script)}")
        self.assertNotIn("Error:", script)

    def test_generate_terms_returns_list(self):
        from app.services.llm import generate_terms
        terms = generate_terms(
            video_subject="The beauty of sunsets",
            video_script="Sunsets paint the sky in golden hues.",
            amount=3,
        )
        self.assertIsInstance(terms, list)
        self.assertTrue(len(terms) > 0, f"No terms returned: {terms}")
        self.assertTrue(all(isinstance(t, str) for t in terms))


@requires_key
class TestLiteLLMEdgeCases(unittest.TestCase):

    def test_missing_model_name(self):
        _setup_litellm_config(model="")
        from app.services.llm import _generate_response
        result = _generate_response("test")
        self.assertIn("Error:", result)
        self.assertIn("model_name is not set", result)

    def test_nonexistent_model(self):
        _setup_litellm_config(model="azure_ai/nonexistent-model-xyz")
        from app.services.llm import _generate_response
        result = _generate_response("test")
        self.assertIn("Error:", result)

    def test_empty_prompt(self):
        _setup_litellm_config()
        from app.services.llm import _generate_response
        result = _generate_response("")
        self.assertIsInstance(result, str)

    def test_very_long_prompt(self):
        _setup_litellm_config()
        from app.services.llm import _generate_response
        long_prompt = "Tell me about AI. " * 100
        result = _generate_response(long_prompt)
        self.assertIsInstance(result, str)
        self.assertNotIn("Error:", result)

    def test_unicode_prompt(self):
        _setup_litellm_config()
        from app.services.llm import _generate_response
        result = _generate_response("用中文回答：2加2等于几？只回答数字。")
        self.assertIsInstance(result, str)
        self.assertNotIn("Error:", result)


@requires_key
class TestLiteLLMDoesNotBreakOtherProviders(unittest.TestCase):

    def test_openai_provider_still_works_structurally(self):
        from app.config import config
        config.app["llm_provider"] = "openai"
        config.app["openai_api_key"] = "sk-test-fake-key"
        config.app["openai_base_url"] = "https://api.openai.com/v1"
        config.app["openai_model_name"] = "gpt-4o-mini"

        from app.services.llm import _generate_response
        result = _generate_response("test")
        self.assertIn("Error:", result)
        self.assertNotIn("litellm", result.lower())


if __name__ == "__main__":
    unittest.main()
