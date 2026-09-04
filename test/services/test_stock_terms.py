import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import llm
from app.services import task as task_service


class TestTwoLaneTermsPrompt(unittest.TestCase):
    def test_stock_safe_rule_in_prompt(self):
        captured = {}

        def fake_generate(prompt, app_config=None):
            captured["prompt"] = prompt
            return '["server room"]'

        with patch.object(llm, "_generate_response", side_effect=fake_generate):
            terms = llm.generate_terms("Nvidia buys Hugging Face", "script", amount=2)
        self.assertIn("STOCK-SAFE RULE", captured.get("prompt", ""))
        self.assertIn("never a brand", captured.get("prompt", ""))
        self.assertEqual(terms, ["server room"])


class TestReplacementTerms(unittest.TestCase):
    def test_empty_input_no_llm_call(self):
        with patch.object(llm, "_generate_response") as gen:
            self.assertEqual(llm.suggest_replacement_terms([]), [])
            gen.assert_not_called()

    def test_replacements_parsed(self):
        with patch.object(
            llm, "_generate_response", return_value='["server room", "business handshake"]'
        ):
            out = llm.suggest_replacement_terms(["Hugging Face", "Jensen Huang"])
        self.assertEqual(out, ["server room", "business handshake"])

    def test_provider_error_returns_empty(self):
        with patch.object(
            llm, "_generate_response", return_value="Error: boom"
        ):
            self.assertEqual(llm.suggest_replacement_terms(["x"]), [])


class TestTermGuards(unittest.TestCase):
    def test_bad_terms_rejected(self):
        self.assertTrue(task_service._is_bad_term(""))
        self.assertTrue(task_service._is_bad_term("çip devi"))
        self.assertTrue(task_service._is_bad_term("chip giant weekly duel report"))
        self.assertFalse(task_service._is_bad_term("server room"))

    def test_dedup_cleans_wrapped_terms(self):
        self.assertEqual(
            task_service._dedup_terms(["['server room']", "server room", "chip factory"]),
            ["server room", "chip factory"],
        )

    def test_terms_look_english(self):
        self.assertFalse(task_service._terms_look_english(["çip devi", "çok büyük"]))
        self.assertTrue(
            task_service._terms_look_english(["chip factory", "server room", "AI race"])
        )


if __name__ == "__main__":
    unittest.main()
