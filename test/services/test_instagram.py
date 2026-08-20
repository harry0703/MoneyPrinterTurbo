import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from app.services import instagram


class _ConfigPatch:
    """临时替换 config.instagram，避免测试读到真实凭据。"""

    def __init__(self, **values):
        defaults = {
            "enabled": True,
            "username": "creator",
            "password": "secret",
            "verification_code": "",
            "proxy": "",
            "max_uploads_per_hour": 3,
            "max_uploads_per_day": 10,
        }
        defaults.update(values)
        self.values = defaults

    def __enter__(self):
        self._patcher = patch.object(instagram.config, "instagram", self.values, create=True)
        self._patcher.start()
        return self.values

    def __exit__(self, *exc_info):
        self._patcher.stop()


class InstagramSettingsTest(unittest.TestCase):
    def test_disabled_without_credentials(self):
        """只打开开关但没有凭据时不应被视为可用，否则会在发布阶段才失败。"""
        with _ConfigPatch(username="", password=""):
            self.assertFalse(instagram.is_enabled())

    def test_enabled_with_credentials(self):
        with _ConfigPatch():
            self.assertTrue(instagram.is_enabled())

    def test_rate_limits_never_drop_below_one(self):
        """配置成 0 会让发布永远被拒，必须兜底为至少 1。"""
        with _ConfigPatch(max_uploads_per_hour=0, max_uploads_per_day=0):
            settings = instagram.InstagramSettings.from_config()
        self.assertEqual(settings.max_uploads_per_hour, 1)
        self.assertEqual(settings.max_uploads_per_day, 1)


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        patcher = patch.object(instagram.utils, "storage_dir", return_value=self.temp_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _account(self, username="creator"):
        return instagram.InstagramAccount(label=username, username=username, password="x")

    def test_allows_upload_when_history_is_empty(self):
        with _ConfigPatch():
            instagram.check_rate_limit(self._account())

    def test_blocks_after_hourly_limit(self):
        """达到小时上限必须在发出请求之前就拒绝，保护账号而不是试探服务端。"""
        now = time.time()
        account = self._account()
        instagram._write_history(account, [now - 60, now - 120, now - 180])
        with _ConfigPatch(max_uploads_per_hour=3):
            with self.assertRaises(instagram.InstagramRateLimitError) as ctx:
                instagram.check_rate_limit(account, now=now)
        self.assertIn("hourly limit", str(ctx.exception))

    def test_hourly_window_expires(self):
        """超过一小时的记录不应继续占用配额。"""
        now = time.time()
        account = self._account()
        instagram._write_history(account, [now - 4000, now - 5000, now - 6000])
        with _ConfigPatch(max_uploads_per_hour=3):
            instagram.check_rate_limit(account, now=now)

    def test_blocks_after_daily_limit(self):
        now = time.time()
        # 分散到不同小时，确保触发的是日上限而不是小时上限。
        account = self._account()
        instagram._write_history(account, [now - 3700 * (index + 1) for index in range(10)])
        with _ConfigPatch(max_uploads_per_hour=3, max_uploads_per_day=10):
            with self.assertRaises(instagram.InstagramRateLimitError) as ctx:
                instagram.check_rate_limit(account, now=now)
        self.assertIn("daily limit", str(ctx.exception))

    def test_corrupted_history_is_ignored(self):
        """历史文件损坏不应让发布永久失败。"""
        account = self._account()
        with open(instagram._history_file(account), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(instagram._read_history(account), [])


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        patcher = patch.object(instagram.utils, "storage_dir", return_value=self.temp_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.video_path = os.path.join(self.temp_dir, "final-1.mp4")
        with open(self.video_path, "wb") as handle:
            handle.write(b"fake video")

    def _account(self, username="creator"):
        return instagram.InstagramAccount(label=username, username=username, password="x")

    def _worker_result(self, payload, returncode=0, stderr=""):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=json.dumps(payload), stderr=stderr
        )

    def test_missing_video_is_rejected_before_any_request(self):
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker") as worker:
                with self.assertRaises(instagram.InstagramError):
                    instagram.publish_reel(video_path="/nope/missing.mp4")
        worker.assert_not_called()

    def test_disabled_service_refuses_to_publish(self):
        with _ConfigPatch(enabled=False):
            with self.assertRaises(instagram.InstagramNotConfiguredError):
                instagram.publish_reel(video_path=self.video_path)

    def test_successful_publish_records_quota(self):
        payload = {"ok": True, "media_pk": "1", "code": "AbC", "url": "https://x/reel/AbC/"}
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                result = instagram.publish_reel(video_path=self.video_path)

        self.assertTrue(result["ok"])
        self.assertEqual(len(instagram._read_history(self._account())), 1)

    def test_failed_publish_does_not_consume_quota(self):
        """失败不应占用配额，否则几次网络抖动就会耗尽当天额度。"""
        payload = {"ok": False, "error_type": "upload", "error": "boom"}
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                with self.assertRaises(instagram.InstagramError):
                    instagram.publish_reel(video_path=self.video_path)

        self.assertEqual(instagram._read_history(self._account()), [])

    def test_auth_errors_map_to_dedicated_exception(self):
        payload = {"ok": False, "error_type": "challenge", "error": "checkpoint required"}
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                with self.assertRaises(instagram.InstagramAuthError):
                    instagram.publish_reel(video_path=self.video_path)

    def test_rate_limit_errors_map_to_dedicated_exception(self):
        payload = {"ok": False, "error_type": "rate_limit", "error": "feedback_required"}
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                with self.assertRaises(instagram.InstagramRateLimitError):
                    instagram.publish_reel(video_path=self.video_path)

    def test_caption_is_truncated_to_platform_limit(self):
        captured = {}

        def fake_worker(request):
            captured.update(request)
            return {"ok": True, "media_pk": "1", "code": "A", "url": "u"}

        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", side_effect=fake_worker):
                instagram.publish_reel(video_path=self.video_path, caption="x" * 5000)

        self.assertEqual(len(captured["caption"]), 2200)

    def test_credentials_are_passed_to_worker_but_not_logged(self):
        """凭据必须进入请求体，但不能出现在服务层日志里。"""
        captured = {}

        def fake_worker(request):
            captured.update(request)
            return {"ok": True, "media_pk": "1", "code": "A", "url": "u"}

        # 项目使用 loguru，stdlib 的 assertLogs 捕获不到，必须挂载临时 sink。
        records = []
        sink_id = instagram.logger.add(lambda message: records.append(str(message)), level="DEBUG")
        try:
            with _ConfigPatch(password="top-secret"):
                with patch.object(instagram, "_run_worker", side_effect=fake_worker):
                    instagram.publish_reel(video_path=self.video_path)
        finally:
            instagram.logger.remove(sink_id)

        self.assertEqual(captured["password"], "top-secret")
        self.assertTrue(records, "expected the publish path to log something")
        self.assertNotIn("top-secret", "\n".join(records))


class WorkerProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        patcher = patch.object(instagram.utils, "storage_dir", return_value=self.temp_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_result_is_read_from_last_stdout_line(self):
        """独立环境可能打印安装提示，解析必须只认最后一行 JSON。"""
        stdout = 'Installed 14 packages\n{"ok": true, "code": "A"}'
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with patch.object(subprocess, "run", return_value=completed):
            with patch.object(instagram, "_worker_command", return_value=["true"]):
                with patch.object(os.path, "isfile", return_value=True):
                    result = instagram._run_worker({"action": "check"})
        self.assertTrue(result["ok"])

    def test_empty_output_raises_domain_error(self):
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="crash")
        with patch.object(subprocess, "run", return_value=completed):
            with patch.object(instagram, "_worker_command", return_value=["true"]):
                with patch.object(os.path, "isfile", return_value=True):
                    with self.assertRaises(instagram.InstagramError):
                        instagram._run_worker({"action": "check"})

    def test_missing_uv_reports_actionable_error(self):
        with patch.object(instagram.shutil, "which", return_value=None):
            with self.assertRaises(instagram.InstagramError) as ctx:
                instagram._worker_command("/tmp/worker.py")
        self.assertIn("uv", str(ctx.exception))


class ImportSessionTest(unittest.TestCase):
    """
    账密登录会校验客户端版本号，instagrapi 内置的那串被判过期后就登不进去，
    而它必须与真实应用一致，本地改不出来。这条路径是当时唯一的出口。
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        patcher = patch.object(instagram.utils, "storage_dir", return_value=self.temp_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_session_id_reaches_the_worker(self):
        with _ConfigPatch():
            with patch.object(
                instagram, "_run_worker", return_value={"ok": True}
            ) as worker:
                instagram.import_session("SESSION-123")
        self.assertEqual(worker.call_args[0][0]["sessionid"], "SESSION-123")

    def test_it_asks_the_worker_only_to_check(self):
        """导入不应该顺手发布任何东西。"""
        with _ConfigPatch():
            with patch.object(
                instagram, "_run_worker", return_value={"ok": True}
            ) as worker:
                instagram.import_session("SESSION-123")
        self.assertEqual(worker.call_args[0][0]["action"], "check")

    def test_an_empty_session_id_never_reaches_the_worker(self):
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker") as worker:
                with self.assertRaises(instagram.InstagramNotConfiguredError):
                    instagram.import_session("   ")
        worker.assert_not_called()

    def test_surrounding_whitespace_is_stripped(self):
        """从浏览器复制 cookie 很容易带上空白，原样送出会得到一个无效会话。"""
        with _ConfigPatch():
            with patch.object(
                instagram, "_run_worker", return_value={"ok": True}
            ) as worker:
                instagram.import_session("  SESSION-123\n")
        self.assertEqual(worker.call_args[0][0]["sessionid"], "SESSION-123")

    def test_a_rejected_session_raises(self):
        payload = {"ok": False, "error_type": "auth", "error": "login_required"}
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                with self.assertRaises(instagram.InstagramAuthError):
                    instagram.import_session("SESSION-123")

    def test_an_outdated_client_is_reported_as_an_auth_problem(self):
        """"版本过期"不是上传失败，把它归到上传类会让人去查视频文件。"""
        payload = {
            "ok": False,
            "error_type": "app_version",
            "error": "Your version of Instagram is out of date.",
        }
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                with self.assertRaises(instagram.InstagramAuthError):
                    instagram.import_session("SESSION-123")

    def test_the_result_names_the_account(self):
        with _ConfigPatch():
            with patch.object(instagram, "_run_worker", return_value={"ok": True}):
                result = instagram.import_session("SESSION-123")
        self.assertIn("account", result)


class ThumbnailTest(unittest.TestCase):
    """
    instagrapi 自己抽封面要靠 MoviePy，而它和 instagrapi 对 Pillow 的版本要求
    互相冲突——隔离工作进程正是为了避开这一点。封面因此必须由主进程备好。
    """

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.video_path = os.path.join(cls.temp_dir, "clip.mp4")
        subprocess.run(
            [
                instagram.utils.get_ffmpeg_binary(),
                "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=180x320:rate=10:duration=1",
                "-pix_fmt", "yuv420p", cls.video_path,
            ],
            capture_output=True, timeout=120, check=True,
        )

    def test_a_real_video_yields_a_jpeg(self):
        path = instagram._extract_thumbnail(self.video_path)
        self.addCleanup(instagram._remove_quietly, path)
        self.assertTrue(path.endswith(".jpg"))
        self.assertGreater(os.path.getsize(path), 0)

    def test_a_broken_video_returns_nothing_instead_of_raising(self):
        """封面抽不出来不该拖垮整条发布：没有封面也好过不发。"""
        broken = os.path.join(self.temp_dir, "broken.mp4")
        with open(broken, "wb") as handle:
            handle.write(b"not a video")
        self.assertEqual(instagram._extract_thumbnail(broken), "")

    def test_no_temporary_file_is_left_behind_on_failure(self):
        broken = os.path.join(self.temp_dir, "broken2.mp4")
        with open(broken, "wb") as handle:
            handle.write(b"nope")
        before = len(os.listdir(tempfile.gettempdir()))
        instagram._extract_thumbnail(broken)
        self.assertLessEqual(len(os.listdir(tempfile.gettempdir())), before)

    def test_remove_quietly_tolerates_a_missing_file(self):
        instagram._remove_quietly(os.path.join(self.temp_dir, "never-existed"))

    def test_the_thumbnail_path_reaches_the_worker(self):
        with _ConfigPatch():
            with patch.object(instagram.utils, "storage_dir",
                              return_value=self.temp_dir):
                with patch.object(
                    instagram, "_run_worker",
                    return_value={"ok": True, "url": "https://x"},
                ) as worker:
                    instagram.publish_reel(video_path=self.video_path)
        self.assertTrue(worker.call_args[0][0]["thumbnail"])

    def test_the_temporary_cover_is_removed_after_publishing(self):
        captured = {}

        def capture(request):
            captured["thumbnail"] = request["thumbnail"]
            return {"ok": True, "url": "https://x"}

        with _ConfigPatch():
            with patch.object(instagram.utils, "storage_dir",
                              return_value=self.temp_dir):
                with patch.object(instagram, "_run_worker", side_effect=capture):
                    instagram.publish_reel(video_path=self.video_path)

        self.assertFalse(os.path.exists(captured["thumbnail"]))

    def test_the_cover_is_removed_even_when_publishing_fails(self):
        """失败路径也要清理，否则每次失败都在 /tmp 留下一张图。"""
        captured = {}

        def capture(request):
            captured["thumbnail"] = request["thumbnail"]
            return {"ok": False, "error_type": "upload", "error": "nope"}

        with _ConfigPatch():
            with patch.object(instagram.utils, "storage_dir",
                              return_value=self.temp_dir):
                with patch.object(instagram, "_run_worker", side_effect=capture):
                    with self.assertRaises(instagram.InstagramError):
                        instagram.publish_reel(video_path=self.video_path)

        self.assertFalse(os.path.exists(captured["thumbnail"]))


if __name__ == "__main__":
    unittest.main()


class MultiAccountTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        patcher = patch.object(instagram.utils, "storage_dir", return_value=self.temp_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.video_path = os.path.join(self.temp_dir, "final-1.mp4")
        with open(self.video_path, "wb") as handle:
            handle.write(b"fake video")

        self.multi = {
            "enabled": True,
            "max_uploads_per_hour": 3,
            "max_uploads_per_day": 10,
            "accounts": [
                {"label": "science", "username": "sci_acc", "password": "p1", "proxy": "http://a:1"},
                {"label": "travel", "username": "trip_acc", "password": "p2"},
            ],
        }

    def _patch(self, values=None):
        return patch.object(
            instagram.config, "instagram", values or self.multi, create=True
        )

    def test_all_accounts_are_parsed(self):
        with self._patch():
            accounts = instagram.list_accounts()
        self.assertEqual([a.label for a in accounts], ["science", "travel"])

    def test_single_account_config_still_works(self):
        """旧的单账号写法必须继续可用，避免升级后配置失效。"""
        legacy = {"enabled": True, "username": "solo", "password": "p"}
        with self._patch(legacy):
            accounts = instagram.list_accounts()
            self.assertEqual(len(accounts), 1)
            # 单账号时无需显式指定即可解析。
            self.assertEqual(instagram.resolve_account().username, "solo")

    def test_ambiguous_account_must_be_named(self):
        """配置多个账号却不指定目标时，必须报错而不是默默用第一个。"""
        with self._patch():
            with self.assertRaises(instagram.InstagramAccountNotFoundError):
                instagram.resolve_account()

    def test_account_resolves_by_label_or_username(self):
        with self._patch():
            self.assertEqual(instagram.resolve_account("travel").username, "trip_acc")
            self.assertEqual(instagram.resolve_account("sci_acc").label, "science")

    def test_unknown_account_lists_available_ones(self):
        with self._patch():
            with self.assertRaises(instagram.InstagramAccountNotFoundError) as ctx:
                instagram.resolve_account("nope")
        self.assertIn("science", str(ctx.exception))

    def test_sessions_are_isolated_per_account(self):
        """共用会话文件会让平台把两个账号视为同一实体，必须分开。"""
        with self._patch():
            first = instagram.session_file(instagram.resolve_account("science"))
            second = instagram.session_file(instagram.resolve_account("travel"))
        self.assertNotEqual(first, second)

    def test_quota_is_tracked_per_account(self):
        """一个账号用满配额不应阻止另一个账号发布。"""
        payload = {"ok": True, "media_pk": "1", "code": "A", "url": "u"}
        with self._patch():
            with patch.object(instagram, "_run_worker", return_value=payload):
                for _ in range(3):
                    instagram.publish_reel(video_path=self.video_path, account="science")

                # science 已达小时上限。
                with self.assertRaises(instagram.InstagramRateLimitError):
                    instagram.publish_reel(video_path=self.video_path, account="science")

                # travel 不受影响。
                result = instagram.publish_reel(
                    video_path=self.video_path, account="travel"
                )
        self.assertTrue(result["ok"])

    def test_per_account_proxy_is_forwarded(self):
        """每个账号使用自己的出口，是避免账号被关联的前提。"""
        captured = {}

        def fake_worker(request):
            captured.update(request)
            return {"ok": True, "media_pk": "1", "code": "A", "url": "u"}

        with self._patch():
            with patch.object(instagram, "_run_worker", side_effect=fake_worker):
                instagram.publish_reel(video_path=self.video_path, account="science")

        self.assertEqual(captured["proxy"], "http://a:1")

    def test_incomplete_accounts_are_ignored(self):
        """缺少密码的条目不应被当成可用账号。"""
        partial = {
            "enabled": True,
            "accounts": [
                {"label": "ok", "username": "u", "password": "p"},
                {"label": "broken", "username": "u2"},
            ],
        }
        with self._patch(partial):
            self.assertEqual([a.label for a in instagram.list_accounts()], ["ok"])

    def test_slug_is_filesystem_safe(self):
        account = instagram.InstagramAccount(
            label="x", username="Weird/Name:1", password="p"
        )
        self.assertEqual(account.slug, "weird_name_1")
