import os
import unittest
from unittest.mock import patch

from webui.auth import authenticate, is_auth_enabled


class TestWebuiAuth(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.dict(os.environ, {}, clear=True)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_auth_is_disabled_when_credentials_are_missing(self):
        self.assertFalse(is_auth_enabled())
        self.assertFalse(authenticate("user", "pass"))

    def test_auth_is_enabled_and_checks_credentials(self):
        os.environ["MPT_WEBUI_USERNAME"] = "me"
        os.environ["MPT_WEBUI_PASSWORD"] = "secret"

        self.assertTrue(is_auth_enabled())
        self.assertTrue(authenticate("me", "secret"))
        self.assertFalse(authenticate("me", "wrong"))
        self.assertFalse(authenticate("someone", "secret"))
