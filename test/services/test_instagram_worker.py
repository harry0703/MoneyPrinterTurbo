import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "instagram_worker", os.path.join(ROOT, "scripts", "instagram_worker.py")
)
worker = importlib.util.module_from_spec(_spec)
sys.modules["instagram_worker"] = worker
_spec.loader.exec_module(worker)

# 实际收到的 429 报文，逐字保留：分类逻辑正是在它上面出的错。
RATE_LIMITED = (
    "HTTPSConnectionPool(host='b.i.instagram.com', port=443): Max retries exceeded "
    "with url: /api/v1/bloks/async_action/com.bloks.www.bloks.caa.login.async."
    "send_login_request/ (Caused by ResponseError('too many 429 error responses'))"
)


class ClassifyErrorTest(unittest.TestCase):
    def test_a_429_is_a_rate_limit_not_a_transient_failure(self):
        """
        429 的报文里带着 "Max retries exceeded"。按"重试/超时"的字样归类会把
        "请你慢一点"当成"网络抖了一下"，于是立刻再撞几次，把限制拖得更久。
        """
        self.assertEqual(worker.classify_error(RATE_LIMITED), "rate_limit")

    def test_server_errors_stay_transient(self):
        for text in ("502 Bad Gateway", "500 Server Error", "request timed out"):
            self.assertEqual(worker.classify_error(text), "transient", text)

    def test_challenge_and_auth_are_not_transient(self):
        self.assertEqual(worker.classify_error("challenge_required"), "challenge")
        self.assertEqual(worker.classify_error("checkpoint_required"), "challenge")
        self.assertEqual(worker.classify_error("login_required"), "auth")

    def test_feedback_required_is_a_rate_limit(self):
        self.assertEqual(worker.classify_error("feedback_required"), "rate_limit")

    def test_rate_limit_wins_over_transient_markers(self):
        """两类字样同时出现时必须判成限流，否则又会走上重试的路。"""
        self.assertEqual(
            worker.classify_error("429 too many requests, connection reset"),
            "rate_limit",
        )

    def test_unknown_errors_fall_back_to_upload(self):
        self.assertEqual(worker.classify_error("something else entirely"), "upload")


class CalmRetriesTest(unittest.TestCase):
    class _Session:
        def __init__(self):
            self.mounted = {}

        def mount(self, prefix, adapter):
            self.mounted[prefix] = adapter

    class _Client:
        def __init__(self):
            self.private = CalmRetriesTest._Session()
            self.public = CalmRetriesTest._Session()

    def _policy(self):
        client = self._Client()
        worker._calm_retries(client)
        return client, client.private.mounted["https://"].max_retries

    def test_429_is_never_retried_at_the_http_layer(self):
        """一次登录变成几百个请求，就是这一层默认对 429 重试造成的。"""
        _, retry = self._policy()
        self.assertNotIn(429, retry.status_forcelist)

    def test_server_errors_are_still_retried(self):
        _, retry = self._policy()
        for status in (500, 502, 503, 504):
            self.assertIn(status, retry.status_forcelist)

    def test_retry_budget_is_small(self):
        _, retry = self._policy()
        self.assertLessEqual(retry.total, 3)

    def test_retry_after_header_is_honoured(self):
        _, retry = self._policy()
        self.assertTrue(retry.respect_retry_after_header)

    def test_both_sessions_are_covered(self):
        client, _ = self._policy()
        self.assertIn("https://", client.private.mounted)
        self.assertIn("https://", client.public.mounted)

    def test_a_client_without_sessions_is_tolerated(self):
        class Bare:
            private = None
            public = None

        worker._calm_retries(Bare())  # 不应抛出


class LoginFailureClassificationTest(unittest.TestCase):
    """登录阶段和发布阶段必须用同一套分类，否则同一个 429 会得到两种说法。"""

    def test_a_throttled_login_is_a_rate_limit(self):
        self.assertEqual(
            worker.classify_error(
                "429 Client Error: Too Many Requests for url: "
                "https://b.i.instagram.com/api/v1/bloks/async_action/"
                "com.bloks.www.bloks.caa.login.async.send_login_request/"
            ),
            "rate_limit",
        )

    def test_an_outdated_client_is_its_own_category(self):
        self.assertEqual(
            worker.classify_error("Your version of Instagram is out of date."),
            "app_version",
        )
        self.assertEqual(
            worker.classify_error("Please upgrade your app to log in"),
            "app_version",
        )


class SessionExpiryTest(unittest.TestCase):
    """
    会话失效后自动改用账密登录，会撞上一个必然失败的接口，并把出口 IP 一起
    拖进限流。这条路径必须停在人的面前。
    """

    def test_session_expired_is_a_permission_error(self):
        self.assertTrue(issubclass(worker.SessionExpired, PermissionError))

    def test_the_message_says_how_to_recover(self):
        error = worker.SessionExpired(
            "stored session was rejected; re-import it with "
            "publish_instagram.py --import-session <sessionid>"
        )
        self.assertIn("--import-session", str(error))


if __name__ == "__main__":
    unittest.main()
