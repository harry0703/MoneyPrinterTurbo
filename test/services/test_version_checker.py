import unittest
import time
import tomllib
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

import requests

from app import __version__
from app.services import version_checker


class TestVersionChecker(unittest.TestCase):
    """验证版本比较和 GitHub 检查异常不会影响主流程。"""

    @staticmethod
    def _response(tag_name):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"tag_name": tag_name}
        return response

    @patch("app.services.version_checker.requests.get")
    def test_returns_newer_release_version(self, request_get):
        request_get.return_value = self._response("v1.4.0")

        result = version_checker.get_available_update("1.3.2")

        self.assertEqual(result, "1.4.0")
        request_get.assert_called_once_with(
            version_checker.LATEST_RELEASE_API_URL,
            headers=version_checker.RELEASE_CHECK_HEADERS,
            timeout=version_checker.RELEASE_CHECK_TIMEOUT,
        )

    @patch("app.services.version_checker.requests.get")
    def test_same_or_older_release_does_not_trigger_update(self, request_get):
        for tag_name in ("v1.3.2", "v1.3.1"):
            with self.subTest(tag_name=tag_name):
                request_get.return_value = self._response(tag_name)
                self.assertIsNone(
                    version_checker.get_available_update("v1.3.2")
                )

    @patch("app.services.version_checker.requests.get")
    def test_prerelease_comparison_uses_semantic_versions(self, request_get):
        request_get.return_value = self._response("v1.3.3")

        result = version_checker.get_available_update("1.3.3rc1")

        self.assertEqual(result, "1.3.3")

    @patch("app.services.version_checker.requests.get")
    def test_invalid_current_version_skips_network_request(self, request_get):
        result = version_checker.get_available_update("development")

        self.assertIsNone(result)
        request_get.assert_not_called()

    @patch("app.services.version_checker.requests.get")
    def test_invalid_release_tag_is_ignored(self, request_get):
        request_get.return_value = self._response("latest")

        self.assertIsNone(version_checker.get_available_update("1.3.2"))

    @patch("app.services.version_checker.requests.get")
    def test_network_failure_is_ignored(self, request_get):
        request_get.side_effect = requests.Timeout("request timed out")

        self.assertIsNone(version_checker.get_available_update("1.3.2"))

    @patch("app.services.version_checker.requests.get")
    def test_http_failure_is_ignored(self, request_get):
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("rate limited")
        request_get.return_value = response

        self.assertIsNone(version_checker.get_available_update("1.3.2"))

    @patch("app.services.version_checker.requests.get")
    def test_invalid_json_payload_is_ignored(self, request_get):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = []
        request_get.return_value = response

        self.assertIsNone(version_checker.get_available_update("1.3.2"))


class TestAsyncUpdateChecker(unittest.TestCase):
    """验证后台检查不会阻塞调用方，并且能够复用缓存结果。"""

    @staticmethod
    def _wait_for_completion(checker, current_version="1.3.2"):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            snapshot = checker.poll(current_version)
            if snapshot.complete:
                return snapshot
            time.sleep(0.005)
        raise AssertionError("background update check did not finish")

    def test_poll_returns_immediately_while_check_runs_in_background(self):
        check_started = Event()
        release_check = Event()

        def slow_check(_current_version):
            check_started.set()
            release_check.wait(timeout=1)
            return "1.4.0"

        checker = version_checker.AsyncUpdateChecker(check=slow_check)

        snapshot = checker.poll("1.3.2")

        self.assertFalse(snapshot.complete)
        self.assertTrue(check_started.wait(timeout=1))
        release_check.set()
        completed = self._wait_for_completion(checker)
        self.assertTrue(completed.complete)
        self.assertEqual(completed.available_version, "1.4.0")

    def test_concurrent_polls_share_one_background_request(self):
        check_started = Event()
        release_check = Event()
        calls = []

        def slow_check(current_version):
            calls.append(current_version)
            check_started.set()
            release_check.wait(timeout=1)
            return None

        checker = version_checker.AsyncUpdateChecker(check=slow_check)
        checker.poll("1.3.2")
        self.assertTrue(check_started.wait(timeout=1))

        second_snapshot = checker.poll("1.3.2")
        release_check.set()
        completed = self._wait_for_completion(checker)

        self.assertFalse(second_snapshot.complete)
        self.assertTrue(completed.complete)
        self.assertIsNone(completed.available_version)
        self.assertEqual(calls, ["1.3.2"])

    def test_completed_result_is_cached_until_ttl_expires(self):
        now = [100.0]
        calls = []

        def check(current_version):
            calls.append(current_version)
            return "1.4.0"

        checker = version_checker.AsyncUpdateChecker(
            check=check,
            ttl_seconds=10,
            clock=lambda: now[0],
        )
        first_result = self._wait_for_completion(checker)
        cached_result = checker.poll("1.3.2")

        self.assertEqual(first_result.available_version, "1.4.0")
        self.assertEqual(cached_result.available_version, "1.4.0")
        self.assertEqual(calls, ["1.3.2"])

        now[0] += 11
        expired_result = checker.poll("1.3.2")
        self.assertFalse(expired_result.complete)
        self._wait_for_completion(checker)
        self.assertEqual(calls, ["1.3.2", "1.3.2"])

    def test_unexpected_background_error_finishes_without_update(self):
        def failing_check(_current_version):
            raise RuntimeError("unexpected failure")

        checker = version_checker.AsyncUpdateChecker(check=failing_check)

        completed = self._wait_for_completion(checker)

        self.assertTrue(completed.complete)
        self.assertIsNone(completed.available_version)


class TestProjectVersionMetadata(unittest.TestCase):
    """防止发布时运行时版本与 Python 项目元数据不一致。"""

    def test_runtime_version_matches_pyproject(self):
        project_root = Path(__file__).resolve().parents[2]
        pyproject = tomllib.loads(
            (project_root / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(__version__, pyproject["project"]["version"])


if __name__ == "__main__":
    unittest.main()
