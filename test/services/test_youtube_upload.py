import builtins
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import youtube_upload
from app.services.youtube_upload import YouTubeUploadService


_CONFIG_BASE = {
    "youtube_enabled": True,
    "youtube_client_id": "client-id",
    "youtube_client_secret": "client-secret",
    "youtube_refresh_token": "refresh-token",
    "youtube_auto_upload": True,
    "youtube_privacy_status": "unlisted",
    "youtube_category_id": "27",
    "youtube_made_for_kids": False,
    "youtube_contains_synthetic_media": True,
}


class FakeHttpError(Exception):
    def __init__(self, status, reason="", content=b""):
        super().__init__(reason or f"HTTP {status}")
        self.resp = SimpleNamespace(status=status)
        self.reason = reason
        self.content = content


def _api_error_body(code, message, *reasons):
    """构造与 YouTube 接口一致的错误响应体。"""
    return json.dumps(
        {
            "error": {
                "code": code,
                "message": message,
                "errors": [
                    {"message": message, "reason": reason} for reason in reasons
                ],
            }
        }
    ).encode("utf-8")


class FakeGoogleAuthError(Exception):
    pass


class FakeRequest:
    """模拟 googleapiclient 的断点续传请求，按脚本逐块返回结果。"""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return None, step


class FakeMedia:
    def __init__(self, path, chunksize=None, resumable=None, mimetype=None):
        self.path = path
        self.chunksize = chunksize
        self.resumable = resumable
        self.mimetype = mimetype
        self.closed = False
        self._stream = SimpleNamespace(close=self._close)

    def _close(self):
        self.closed = True

    def stream(self):
        return self._stream


def _fake_modules(steps, refresh_error=None):
    """构造一次上传所需的全部假对象，并记录调用参数供断言使用。"""
    state = SimpleNamespace(
        credentials_kwargs=None,
        build_args=None,
        insert_kwargs=None,
        media=None,
        request=FakeRequest(steps),
        refreshed=False,
    )

    class FakeCredentials:
        def __init__(self, **kwargs):
            state.credentials_kwargs = kwargs

        def refresh(self, request):
            if refresh_error is not None:
                raise refresh_error
            state.refreshed = True

    def fake_build(service, version, credentials=None, cache_discovery=None):
        state.build_args = (service, version, cache_discovery)

        def insert(**kwargs):
            state.insert_kwargs = kwargs
            return state.request

        return SimpleNamespace(videos=lambda: SimpleNamespace(insert=insert))

    def fake_media(path, **kwargs):
        state.media = FakeMedia(path, **kwargs)
        return state.media

    modules = SimpleNamespace(
        GoogleAuthError=FakeGoogleAuthError,
        Request=lambda: object(),
        Credentials=FakeCredentials,
        build=fake_build,
        HttpError=FakeHttpError,
        MediaFileUpload=fake_media,
    )
    return modules, state


class TestYouTubeMetadataNormalization(unittest.TestCase):
    def test_privacy_status_falls_back_to_public(self):
        """接口只接受三种取值，非法配置不能变成一次被拒绝的上传。"""
        self.assertEqual(youtube_upload.normalize_privacy_status("UNLISTED"), "unlisted")
        self.assertEqual(youtube_upload.normalize_privacy_status("draft"), "public")
        self.assertEqual(youtube_upload.normalize_privacy_status(None), "public")

    def test_title_strips_rejected_characters_and_truncates(self):
        """尖括号和换行会让 YouTube 直接拒绝整次上传，必须在本地清理。"""
        title = youtube_upload.normalize_title("<b>Coffee</b>\nMorning ritual")

        self.assertEqual(title, "bCoffee/b Morning ritual")
        self.assertEqual(
            len(youtube_upload.normalize_title("A" * 200)),
            youtube_upload.MAX_TITLE_LENGTH,
        )

    def test_title_falls_back_when_metadata_is_empty(self):
        self.assertEqual(youtube_upload.normalize_title("", "Coffee"), "Coffee")
        self.assertEqual(
            youtube_upload.normalize_title("   ", ""), youtube_upload.DEFAULT_TITLE
        )

    def test_tags_drop_hashes_duplicates_and_respect_total_budget(self):
        """标签总长度超过 500 字符时接口会报错，超出部分应提前丢弃。"""
        tags = youtube_upload.normalize_tags(
            ["#coffee", "Coffee", " ", None, "morning ritual"]
        )

        self.assertEqual(tags, ["coffee", "morning ritual"])

        long_tags = youtube_upload.normalize_tags([f"tag{i}" * 10 for i in range(20)])
        used = sum(len(tag) for tag in long_tags) + max(len(long_tags) - 1, 0)
        self.assertLessEqual(used, youtube_upload.MAX_TAGS_TOTAL_LENGTH)
        self.assertTrue(long_tags)

    def test_description_is_truncated_to_api_limit(self):
        description = youtube_upload.normalize_description("d" * 6000)

        self.assertEqual(len(description), youtube_upload.MAX_DESCRIPTION_LENGTH)


class TestYouTubeUploadService(unittest.TestCase):
    @patch(
        "app.services.youtube_upload.config.app",
        {**_CONFIG_BASE, "youtube_enabled": False},
    )
    @patch("app.services.youtube_upload._load_google_modules")
    def test_unconfigured_service_skips_upload(self, load_modules):
        """未启用时不能建立连接，也不能消耗每天有限的上传配额。"""
        result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("not configured", result["error"])
        self.assertEqual(result["platform"], "youtube")
        load_modules.assert_not_called()

    @patch(
        "app.services.youtube_upload.config.app",
        {**_CONFIG_BASE, "youtube_refresh_token": ""},
    )
    @patch("app.services.youtube_upload._load_google_modules")
    def test_missing_refresh_token_is_treated_as_unconfigured(self, load_modules):
        result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        load_modules.assert_not_called()

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=False)
    @patch("app.services.youtube_upload._load_google_modules")
    def test_missing_video_skips_upload(self, load_modules, _exists):
        """成片不存在时应在建立连接之前返回明确错误。"""
        result = YouTubeUploadService().upload_video("/missing/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("Video file not found", result["error"])
        load_modules.assert_not_called()

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_successful_upload_sends_full_metadata(self, _exists):
        modules, state = _fake_modules([{"id": "vid123", "status": {"privacyStatus": "unlisted"}}])

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video(
                "/fake/v.mp4",
                "Morning Coffee",
                description="A better morning.",
                tags=["#coffee", "#shorts"],
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["video_id"], "vid123")
        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=vid123")
        self.assertEqual(result["privacy_status"], "unlisted")

        self.assertTrue(state.refreshed)
        self.assertEqual(state.build_args, ("youtube", "v3", False))
        self.assertEqual(
            state.credentials_kwargs["token_uri"], youtube_upload.TOKEN_URI
        )
        self.assertEqual(
            state.credentials_kwargs["scopes"], [youtube_upload.UPLOAD_SCOPE]
        )

        body = state.insert_kwargs["body"]
        self.assertEqual(state.insert_kwargs["part"], "snippet,status")
        self.assertEqual(body["snippet"]["title"], "Morning Coffee")
        self.assertEqual(body["snippet"]["description"], "A better morning.")
        self.assertEqual(body["snippet"]["tags"], ["coffee", "shorts"])
        self.assertEqual(body["snippet"]["categoryId"], "27")
        self.assertEqual(body["status"]["privacyStatus"], "unlisted")
        self.assertFalse(body["status"]["selfDeclaredMadeForKids"])
        self.assertTrue(body["status"]["containsSyntheticMedia"])

        self.assertTrue(state.media.resumable)
        self.assertEqual(state.media.chunksize, youtube_upload.UPLOAD_CHUNK_SIZE)
        # 任务目录清理前必须释放文件句柄，否则 Windows 上无法删除成片。
        self.assertTrue(state.media.closed)

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_explicit_privacy_status_overrides_configuration(self, _exists):
        """任务排队时快照的隐私状态必须优先于运行期的配置改动。"""
        modules, state = _fake_modules([{"id": "vid123"}])

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video(
                "/fake/v.mp4", "Title", privacy_status="private"
            )

        self.assertTrue(result["success"])
        self.assertEqual(state.insert_kwargs["body"]["status"]["privacyStatus"], "private")
        self.assertEqual(result["privacy_status"], "private")

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    @patch("app.services.youtube_upload.time.sleep")
    def test_retriable_server_errors_are_retried(self, sleep, _exists):
        """5xx 属于可恢复故障，断点续传应继续而不是让整次发布失败。"""
        modules, state = _fake_modules(
            [FakeHttpError(503), None, FakeHttpError(500), {"id": "vid123"}]
        )

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertTrue(result["success"])
        self.assertEqual(state.request.calls, 4)
        self.assertEqual(sleep.call_count, 2)

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    @patch("app.services.youtube_upload.time.sleep")
    def test_retries_stop_at_the_configured_limit(self, sleep, _exists):
        modules, state = _fake_modules(
            [FakeHttpError(503)] * (youtube_upload.MAX_RETRIABLE_ATTEMPTS + 2)
        )

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("503", result["error"])
        self.assertEqual(
            state.request.calls, youtube_upload.MAX_RETRIABLE_ATTEMPTS + 1
        )
        self.assertTrue(state.media.closed)

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    @patch("app.services.youtube_upload.time.sleep")
    def test_missing_channel_error_explains_how_to_fix_it(self, sleep, _exists):
        """
        没有频道的账号上传时只返回 401 Unauthorized，真正的原因藏在响应体的
        youtubeSignupRequired 里。任务状态必须带上它和处理建议，否则调用方
        会误以为是凭据失效而反复重新授权。
        """
        modules, state = _fake_modules(
            [
                FakeHttpError(
                    401,
                    "Unauthorized",
                    _api_error_body(401, "Unauthorized", "youtubeSignupRequired"),
                )
            ]
        )

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("youtubeSignupRequired", result["error"])
        self.assertIn("no YouTube channel", result["error"])
        self.assertEqual(state.request.calls, 1)
        sleep.assert_not_called()

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_error_without_a_parseable_body_still_reports_the_status(self, _exists):
        """响应体缺失或不是 JSON 时也要给出可读信息，不能吞掉整个失败。"""
        modules, _state = _fake_modules(
            [FakeHttpError(404, "Not Found", b"<html>gateway error</html>")]
        )

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("404", result["error"])
        self.assertIn("Not Found", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    @patch("app.services.youtube_upload.time.sleep")
    def test_client_errors_are_not_retried(self, sleep, _exists):
        """403 通常是配额耗尽或权限不足，重试只会更快耗尽当天的额度。"""
        modules, state = _fake_modules(
            [
                FakeHttpError(
                    403,
                    "Forbidden",
                    _api_error_body(403, "The request cannot be completed because "
                                    "you have exceeded your quota.", "quotaExceeded"),
                ),
                {"id": "vid123"},
            ]
        )

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("quotaExceeded", result["error"])
        self.assertEqual(state.request.calls, 1)
        sleep.assert_not_called()

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_expired_credentials_report_a_reauthorization_hint(self, _exists):
        modules, _state = _fake_modules(
            [{"id": "vid123"}],
            refresh_error=FakeGoogleAuthError("invalid_grant: Token has been expired"),
        )

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("refresh the YouTube OAuth credentials", result["error"])
        self.assertIn("invalid_grant", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_response_without_video_id_is_a_failure(self, _exists):
        modules, _state = _fake_modules([{"kind": "youtube#video"}])

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("video id", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_missing_client_library_reports_install_hint(self, _exists):
        with patch(
            "app.services.youtube_upload._load_google_modules",
            side_effect=youtube_upload.YouTubeUploadError(
                youtube_upload.MISSING_DEPENDENCY_ERROR
            ),
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("google-api-python-client", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_unexpected_errors_do_not_escape_to_the_caller(self, _exists):
        """发布失败只能变成可查询的结果，不能中断已完成的视频任务。"""
        modules, _state = _fake_modules([TimeoutError("socket timed out")])

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().upload_video("/fake/v.mp4", "Title")

        self.assertFalse(result["success"])
        self.assertIn("TimeoutError", result["error"])

    def test_privacy_status_reuses_legacy_upload_post_setting(self):
        """升级前的隐私设置保存在 Upload-Post 配置项里，必须继续生效。"""
        legacy = {
            key: value
            for key, value in _CONFIG_BASE.items()
            if key != "youtube_privacy_status"
        }
        legacy["upload_post_youtube_privacy_status"] = "private"

        with patch("app.services.youtube_upload.config.app", legacy):
            self.assertEqual(YouTubeUploadService().privacy_status, "private")

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_publish_video_helper_delegates_to_the_singleton(self, _exists):
        with patch.object(
            youtube_upload.youtube_upload_service, "upload_video"
        ) as upload_video:
            upload_video.return_value = {"success": True}
            youtube_upload.publish_video(
                "/fake/v.mp4", "Title", description="d", tags=["t"]
            )

        upload_video.assert_called_once_with(
            video_path="/fake/v.mp4",
            title="Title",
            description="d",
            tags=["t"],
            privacy_status=None,
            publish_at=None,
        )


class TestYouTubeDependencyLoading(unittest.TestCase):
    def test_import_failure_is_converted_to_a_domain_error(self):
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name.startswith("googleapiclient") or name.startswith("google."):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked_import):
            with self.assertRaises(youtube_upload.YouTubeUploadError) as ctx:
                youtube_upload._load_google_modules()

        self.assertIn("google-api-python-client", str(ctx.exception))

    def test_official_client_library_is_installed(self):
        """依赖已进入项目主依赖，缺失时应在 CI 立即暴露而不是发布时才失败。"""
        modules = youtube_upload._load_google_modules()

        self.assertTrue(callable(modules.build))
        self.assertTrue(callable(modules.MediaFileUpload))

    def test_real_client_accepts_the_upload_request(self):
        """
        用官方客户端真正构建一次 videos.insert 请求。

        本地假对象无法发现字段名或断点续传参数写错，但这些问题只会在真实
        发布时暴露。googleapiclient 自带 youtube v3 的发现文档，因此这段
        校验不需要联网，也不会产生任何请求。
        """
        modules = youtube_upload._load_google_modules()

        class OfflineCredentials(modules.Credentials):
            def refresh(self, request):
                self.token = "offline-access-token"

        offline_modules = SimpleNamespace(**vars(modules))
        offline_modules.Credentials = OfflineCredentials

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as video_file:
            video_file.write(b"\x00" * 1024)
            video_path = video_file.name

        try:
            with patch("app.services.youtube_upload.config.app", _CONFIG_BASE):
                service = YouTubeUploadService()
                client = service._build_client(offline_modules)
                media = offline_modules.MediaFileUpload(
                    video_path,
                    chunksize=youtube_upload.UPLOAD_CHUNK_SIZE,
                    resumable=True,
                    mimetype="video/*",
                )
                request = client.videos().insert(
                    part="snippet,status",
                    body={
                        "snippet": {
                            "title": "Morning Coffee",
                            "description": "A better morning.",
                            "tags": ["coffee"],
                            "categoryId": "27",
                        },
                        "status": {
                            "privacyStatus": "unlisted",
                            "selfDeclaredMadeForKids": False,
                            "containsSyntheticMedia": True,
                        },
                    },
                    media_body=media,
                )

                self.assertTrue(
                    request.uri.startswith(
                        "https://youtube.googleapis.com/upload/youtube/v3/videos"
                    ),
                    request.uri,
                )
                self.assertIsNotNone(request.resumable)
                media.stream().close()
        finally:
            os.unlink(video_path)


class TestFormatPublishAt(unittest.TestCase):
    def test_naive_datetime_is_interpreted_as_local_time_and_converted_to_utc(self):
        import datetime as dt

        # Simula um servidor em UTC-3 (ex.: America/Sao_Paulo): 09:00 local
        # tem que virar 12:00Z, nunca "09:00Z" literal.
        class _FixedOffsetLocal(dt.datetime):
            def astimezone(self, tz=None):
                if tz is None:
                    return dt.datetime(
                        self.year, self.month, self.day, self.hour, self.minute,
                        tzinfo=dt.timezone(dt.timedelta(hours=-3)),
                    )
                return super().astimezone(tz)

        fixed_local = _FixedOffsetLocal(2026, 3, 5, 9, 0)
        result = youtube_upload.format_publish_at(fixed_local)
        self.assertEqual(result, "2026-03-05T12:00:00Z")

    def test_string_value_passes_through_unchanged(self):
        self.assertEqual(
            youtube_upload.format_publish_at("2026-03-05T12:00:00Z"),
            "2026-03-05T12:00:00Z",
        )


class TestUploadVideoPublishAt(unittest.TestCase):
    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_publish_at_is_included_when_privacy_is_private(self, _exists):
        modules, state = _fake_modules([{"id": "vid123"}])

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            YouTubeUploadService().upload_video(
                "/fake/v.mp4",
                "Title",
                privacy_status="private",
                publish_at="2026-03-05T12:00:00Z",
            )

        self.assertEqual(
            state.insert_kwargs["body"]["status"]["publishAt"],
            "2026-03-05T12:00:00Z",
        )

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    @patch("app.services.youtube_upload.os.path.exists", return_value=True)
    def test_publish_at_is_ignored_when_privacy_is_not_private(self, _exists):
        """publishAt só é aceito pela API quando o vídeo continua private."""
        modules, state = _fake_modules([{"id": "vid123"}])

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            YouTubeUploadService().upload_video(
                "/fake/v.mp4",
                "Title",
                privacy_status="unlisted",
                publish_at="2026-03-05T12:00:00Z",
            )

        self.assertNotIn("publishAt", state.insert_kwargs["body"]["status"])


def _fake_update_modules(existing_item, refresh_error=None):
    """Fake client exposing videos().list() and videos().update()."""
    state = SimpleNamespace(
        list_kwargs=None, update_kwargs=None, refreshed=False
    )

    class FakeCredentials:
        def __init__(self, **kwargs):
            pass

        def refresh(self, request):
            if refresh_error is not None:
                raise refresh_error
            state.refreshed = True

    def fake_build(service, version, credentials=None, cache_discovery=None):
        def list_(**kwargs):
            state.list_kwargs = kwargs
            return SimpleNamespace(
                execute=lambda: {"items": [existing_item] if existing_item else []}
            )

        def update(**kwargs):
            state.update_kwargs = kwargs
            body = kwargs["body"]
            return SimpleNamespace(execute=lambda: body)

        return SimpleNamespace(videos=lambda: SimpleNamespace(list=list_, update=update))

    modules = SimpleNamespace(
        GoogleAuthError=FakeGoogleAuthError,
        Request=lambda: object(),
        Credentials=FakeCredentials,
        build=fake_build,
        HttpError=FakeHttpError,
    )
    return modules, state


class TestUpdateVideoMetadata(unittest.TestCase):
    @patch(
        "app.services.youtube_upload.config.app",
        {**_CONFIG_BASE, "youtube_enabled": False},
    )
    def test_not_configured_returns_error_without_calling_api(self):
        result = YouTubeUploadService().update_video_metadata(
            "vid123", title="New title"
        )
        self.assertFalse(result["success"])
        self.assertIn("not configured", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    def test_requires_at_least_one_field_to_update(self):
        result = YouTubeUploadService().update_video_metadata("vid123")
        self.assertFalse(result["success"])
        self.assertIn("nothing to update", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    def test_video_not_found_returns_error(self):
        modules, _state = _fake_update_modules(existing_item=None)
        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().update_video_metadata(
                "vid123", title="New title"
            )
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    def test_updates_only_requested_fields_and_preserves_the_rest(self):
        existing = {
            "snippet": {
                "title": "Old title",
                "description": "Old description",
                "tags": ["old"],
                "categoryId": "27",
            },
            "status": {"privacyStatus": "private"},
        }
        modules, state = _fake_update_modules(existing_item=existing)

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().update_video_metadata(
                "vid123", title="New title"
            )

        self.assertTrue(result["success"])
        body = state.update_kwargs["body"]
        self.assertEqual(body["snippet"]["title"], "New title")
        # categoryId e description preservados, mesmo sem serem passados.
        self.assertEqual(body["snippet"]["categoryId"], "27")
        self.assertEqual(body["snippet"]["description"], "Old description")
        self.assertEqual(body["status"]["privacyStatus"], "private")

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    def test_schedules_publish_at_while_keeping_video_private(self):
        existing = {
            "snippet": {"title": "T", "categoryId": "27"},
            "status": {"privacyStatus": "private"},
        }
        modules, state = _fake_update_modules(existing_item=existing)

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().update_video_metadata(
                "vid123", publish_at="2026-03-05T12:00:00Z"
            )

        self.assertTrue(result["success"])
        body = state.update_kwargs["body"]
        self.assertEqual(body["status"]["publishAt"], "2026-03-05T12:00:00Z")
        self.assertEqual(body["status"]["privacyStatus"], "private")

    @patch("app.services.youtube_upload.config.app", _CONFIG_BASE)
    def test_publishing_now_drops_any_stale_publish_at(self):
        existing = {
            "snippet": {"title": "T", "categoryId": "27"},
            "status": {"privacyStatus": "private", "publishAt": "2026-01-01T00:00:00Z"},
        }
        modules, state = _fake_update_modules(existing_item=existing)

        with patch(
            "app.services.youtube_upload._load_google_modules", return_value=modules
        ):
            result = YouTubeUploadService().update_video_metadata(
                "vid123", privacy_status="public"
            )

        self.assertTrue(result["success"])
        body = state.update_kwargs["body"]
        self.assertNotIn("publishAt", body["status"])
        self.assertEqual(body["status"]["privacyStatus"], "public")


if __name__ == "__main__":
    unittest.main()
