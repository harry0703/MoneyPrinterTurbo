import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.asgi import warn_if_api_unprotected


class TestAsgiAuthWarning(unittest.TestCase):
    def test_empty_api_key_warns_for_non_loopback_host(self):
        warning = warn_if_api_unprotected("", "0.0.0.0")

        self.assertTrue(warning)
        self.assertIn("API authentication is disabled", warning)

    def test_empty_api_key_allows_loopback_hosts(self):
        for listen_host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(listen_host=listen_host):
                self.assertIsNone(warn_if_api_unprotected("", listen_host))

    def test_non_empty_api_key_never_warns(self):
        for listen_host in ("0.0.0.0", "127.0.0.1", "localhost", "::1"):
            with self.subTest(listen_host=listen_host):
                self.assertIsNone(warn_if_api_unprotected("secret", listen_host))

    def test_whitespace_only_api_key_warns_for_non_loopback_host(self):
        warning = warn_if_api_unprotected("  \t\n", "0.0.0.0")

        self.assertTrue(warning)


if __name__ == "__main__":
    unittest.main()
