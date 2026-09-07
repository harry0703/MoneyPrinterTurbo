import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.integrations.provider_router import generate_with_provider


class TestExternalIntegrations(unittest.TestCase):
    def test_unknown_provider_returns_controlled_error(self):
        result = generate_with_provider("unknown-provider", {"prompt": "demo"})

        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("error"), "unsupported provider")

    def test_missing_prompt_validation(self):
        result = generate_with_provider("getimg", {"prompt": ""})

        self.assertFalse(result.get("success"))
        self.assertIn("prompt", result.get("error", ""))

    def test_missing_api_key_is_graceful(self):
        with patch.dict(os.environ, {"GETIMG_API_KEY": ""}, clear=False):
            result = generate_with_provider("getimg", {"prompt": "hello world"})

        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("provider"), "getimg")
        self.assertEqual(result.get("error"), "Missing API key")


if __name__ == "__main__":
    unittest.main()
