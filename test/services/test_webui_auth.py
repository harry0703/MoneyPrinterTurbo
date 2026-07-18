import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webui.auth import (
    authenticate,
    create_persistent_session,
    is_auth_enabled,
    validate_persistent_session,
)


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

    def test_persistent_session_survives_new_session_validation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            os.environ["MPT_WEBUI_USERNAME"] = "me"
            os.environ["MPT_WEBUI_PASSWORD"] = "secret"
            os.environ["MPT_WEBUI_SESSION_FILE"] = str(
                Path(temporary_directory) / "sessions.json"
            )

            token = create_persistent_session("me")

            self.assertTrue(validate_persistent_session(token))
            self.assertTrue(Path(os.environ["MPT_WEBUI_SESSION_FILE"]).is_file())
            self.assertNotIn(token, Path(os.environ["MPT_WEBUI_SESSION_FILE"]).read_text())

    def test_persistent_session_is_invalidated_when_credentials_change(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            os.environ["MPT_WEBUI_USERNAME"] = "me"
            os.environ["MPT_WEBUI_PASSWORD"] = "secret"
            os.environ["MPT_WEBUI_SESSION_FILE"] = str(
                Path(temporary_directory) / "sessions.json"
            )

            token = create_persistent_session("me")
            os.environ["MPT_WEBUI_PASSWORD"] = "changed"

            self.assertFalse(validate_persistent_session(token))
