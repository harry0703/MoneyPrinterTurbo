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


class StatsTest(unittest.TestCase):
    """
    看一次数据面板应当只花一次调用。逐条去查每个链接的计数，会把一次浏览
    变成十几个请求，那正是最该避免的访问模式。
    """

    class Clip:
        def __init__(self, code, plays=None, views=None, likes=3, comments=1,
                     caption="x", taken_at=None):
            import datetime
            self.code = code
            self.play_count = plays
            self.view_count = views
            self.like_count = likes
            self.comment_count = comments
            self.caption_text = caption
            self.taken_at = taken_at or datetime.datetime(2026, 8, 20, 21, 31)

    class Info:
        username = "triple.t.polyester"
        follower_count = 42
        following_count = 7
        media_count = 3

    class Client:
        """默认让网页接口可用，与真实优先顺序一致。"""

        user_id = "1"

        def __init__(self, clips, gql=None):
            self.clips = clips
            self.gql = clips if gql is None else gql
            self.clip_calls = []
            self.gql_calls = []

        def user_info(self, user_id):
            return StatsTest.Info()

        def user_medias_gql(self, user_id, amount):
            self.gql_calls.append(amount)
            if self.gql is False:
                raise RuntimeError("gql unavailable")
            return self.gql[:amount]

        def user_clips(self, user_id, amount):
            self.clip_calls.append(amount)
            return self.clips[:amount]

    def test_one_call_returns_the_whole_batch(self):
        client = self.Client([self.Clip(f"c{i}") for i in range(5)])
        worker._stats(client, {"amount": 5})
        self.assertEqual(len(client.gql_calls), 1)

    def test_the_web_endpoint_is_preferred(self):
        """
        私有接口那一版之后，四个账号里有三个的会话随即失效。网页接口更接近
        浏览器自己会发的请求，先走它。
        """
        client = self.Client([self.Clip("a")])
        self.assertEqual(worker._stats(client, {})["source"], "gql")
        self.assertEqual(client.clip_calls, [])

    def test_it_falls_back_when_the_web_endpoint_fails(self):
        client = self.Client([self.Clip("a")], gql=False)
        self.assertEqual(worker._stats(client, {})["source"], "v1")
        self.assertEqual(len(client.clip_calls), 1)

    def test_an_empty_web_answer_also_falls_back(self):
        """取到空列表和取不到是一回事，账号明明有作品。"""
        client = self.Client([self.Clip("a")], gql=[])
        self.assertEqual(worker._stats(client, {})["source"], "v1")

    def test_the_path_taken_is_reported(self):
        """悄悄降级就等于没有做这个选择，结果里必须看得见走了哪条路。"""
        client = self.Client([self.Clip("a")])
        self.assertIn("source", worker._stats(client, {}))

    def test_the_account_totals_are_reported(self):
        result = worker._stats(self.Client([]), {})
        self.assertEqual(result["followers"], 42)
        self.assertEqual(result["username"], "triple.t.polyester")

    def test_play_count_falls_back_to_view_count(self):
        """播放数按接口版本落在两个字段中的一个，缺哪个都不该显示成 0。"""
        client = self.Client([self.Clip("a", plays=None, views=120)])
        self.assertEqual(worker._stats(client, {})["media"][0]["plays"], 120)

    def test_play_count_is_preferred_when_both_are_present(self):
        client = self.Client([self.Clip("a", plays=99, views=120)])
        self.assertEqual(worker._stats(client, {})["media"][0]["plays"], 99)

    def test_a_missing_count_reads_as_zero_not_none(self):
        client = self.Client([self.Clip("a")])
        self.assertEqual(worker._stats(client, {})["media"][0]["plays"], 0)

    def test_the_timestamp_survives_as_text(self):
        """结果要经过 JSON 送回主进程，datetime 到那里会直接炸掉。"""
        client = self.Client([self.Clip("a")])
        import json
        json.dumps(worker._stats(client, {}))

    def test_the_amount_is_clamped(self):
        client = self.Client([self.Clip(f"c{i}") for i in range(60)])
        worker._stats(client, {"amount": 500})
        self.assertLessEqual(client.gql_calls[0], 50)

    def test_a_missing_amount_uses_a_sane_default(self):
        client = self.Client([self.Clip("a")])
        worker._stats(client, {})
        self.assertEqual(client.gql_calls[0], 12)

    def test_long_captions_are_truncated(self):
        client = self.Client([self.Clip("a", caption="x" * 500)])
        self.assertLessEqual(
            len(worker._stats(client, {})["media"][0]["caption"]), 120
        )
