import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import material


class TestMaterialTlsVerification(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_search_pexels_uses_tls_verification_by_default(self):
        """
        默认路径必须开启 TLS 校验，避免素材 API key 和返回的素材 URL
        在公共网络或不可信代理环境中被中间人攻击截获或篡改。
        """
        config.app["pexels_api_keys"] = ["pexels-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "videos": [
                    {
                        "duration": 8,
                        "video_files": [
                            {
                                "width": 1080,
                                "height": 1920,
                                "link": "https://example.com/video.mp4",
                            }
                        ],
                    }
                ]
            }
        )

        with patch("app.services.material.requests.get", return_value=fake_response) as get:
            results = material.search_videos_pexels("cat", minimum_duration=1)

        self.assertEqual(len(results), 1)
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_pixabay_allows_explicit_tls_disable_for_proxy(self):
        """
        少数企业代理会使用自签证书。该场景必须显式配置关闭 TLS 校验，
        不能再由代码硬编码默认关闭。
        """
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.app["tls_verify"] = False
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": 1920,
                                "url": "https://example.com/video.mp4",
                            }
                        },
                    }
                ]
            }
        )

        with patch("app.services.material.requests.get", return_value=fake_response) as get:
            results = material.search_videos_pixabay("cat", minimum_duration=1)

        self.assertEqual(len(results), 1)
        self.assertFalse(get.call_args.kwargs["verify"])

    def test_save_video_uses_tls_verification_by_default(self):
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(content=b"fake-video")

        class FakeVideoFileClip:
            duration = 1
            fps = 24

            def __init__(self, path):
                self.path = path

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.material.requests.get", return_value=fake_response
            ) as get, patch("app.services.material.VideoFileClip", FakeVideoFileClip):
                video_path = material.save_video(
                    "https://example.com/video.mp4?token=abc", save_dir=temp_dir
                )

            self.assertTrue(os.path.exists(video_path))
            self.assertTrue(get.call_args.kwargs["verify"])

    def test_download_videos_accepts_plain_string_concat_mode(self):
        """
        download_videos 可能被服务层或测试直接传入字符串模式，而不是
        VideoConcatMode 枚举。这里用空搜索词避免真实网络请求，只验证
        字符串 "random" 不会再因为访问 `.value` 抛 AttributeError。
        """
        result = material.download_videos(
            task_id="string-concat-mode",
            search_terms=[],
            video_contact_mode="random",
        )

        self.assertEqual(result, [])


class TestCoverrProvider(unittest.TestCase):
    """
    Coverr 视频素材源(spec: 2026-06-09-coverr-video-provider-design.md)。
    全部用 unittest.mock 替换 requests，确保 CI 不依赖真实网络和真实 API key。
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    # ---------------- Tests for search_videos_coverr ----------------

    def test_search_coverr_parses_hits_and_encodes_url(self):
        """
        search_videos_coverr 应把每个 hit 转成 MaterialInfo，并把
        (id, mp4_url) 编码进 url 字段供下载时拆解。
        同时验证 Authorization header 使用 Bearer scheme。
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "page": 0,
                "pages": 50,
                "page_size": 20,
                "total": 1,
                "hits": [
                    {
                        "id": "S1YbPl1NfI",
                        "duration": 11.625,
                        "aspect_ratio": "16:9",
                        "urls": {
                            "mp4": "https://storage.coverr.co/videos/abc?token=xyz",
                            "mp4_preview": "https://storage.coverr.co/videos/abc/preview?token=xyz",
                            "mp4_download": "https://storage.coverr.co/videos/abc/download?token=xyz",
                        },
                    }
                ],
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ) as get:
            results = material.search_videos_coverr("nature", minimum_duration=5)

        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item.provider, "coverr")
        self.assertEqual(item.duration, 11)
        self.assertTrue(item.url.startswith("coverr://"))
        self.assertIn("S1YbPl1NfI", item.url)
        self.assertIn(
            "https://storage.coverr.co/videos/abc?token=xyz", item.url
        )
        # Bearer auth + TLS verify on by default
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], "Bearer coverr-key"
        )
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_coverr_uses_tls_verification_by_default(self):
        """与 pexels/pixabay 一致:未显式配置时 TLS 校验默认开启。"""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(json=lambda: {"hits": []})

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ) as get:
            material.search_videos_coverr("nature", minimum_duration=1)

        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_coverr_allows_explicit_tls_disable_for_proxy(self):
        """企业自签证书代理场景必须能显式关闭 TLS 校验。"""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app["tls_verify"] = False
        config.proxy.clear()

        fake_response = SimpleNamespace(json=lambda: {"hits": []})

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ) as get:
            material.search_videos_coverr("nature", minimum_duration=1)

        self.assertFalse(get.call_args.kwargs["verify"])

    def test_search_coverr_filters_by_min_duration_and_accepts_string(self):
        """
        Coverr duration 字段在不同响应里可能是 number 或 string,
        两种格式都要接受;低于 minimum_duration 的应被过滤。
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {
                        "id": "shortvid",
                        "duration": 3,  # below minimum
                        "urls": {"mp4": "https://example.com/a.mp4"},
                    },
                    {
                        "id": "stringdur",
                        "duration": "10.500000",  # string accepted
                        "urls": {"mp4": "https://example.com/b.mp4"},
                    },
                ]
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ):
            results = material.search_videos_coverr("x", minimum_duration=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].duration, 10)
        self.assertIn("stringdur", results[0].url)

    def test_search_coverr_skips_invalid_items(self):
        """缺 id 或缺 urls.mp4 的条目应被跳过,不应抛异常。"""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {  # missing urls.mp4
                        "id": "no-mp4",
                        "duration": 10,
                        "urls": {"mp4_preview": "https://example.com/preview.mp4"},
                    },
                    {  # missing id
                        "duration": 10,
                        "urls": {"mp4": "https://example.com/x.mp4"},
                    },
                    {  # valid baseline
                        "id": "good",
                        "duration": 10,
                        "urls": {"mp4": "https://example.com/good.mp4"},
                    },
                ]
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ):
            results = material.search_videos_coverr("x", minimum_duration=1)

        self.assertEqual(len(results), 1)
        self.assertIn("good", results[0].url)

    def test_search_coverr_returns_empty_on_failure(self):
        """
        响应结构异常 / 网络异常时,函数必须返回 [] 而不是抛异常,
        与 pexels/pixabay 行为保持一致。
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        # Subtest A: malformed response (no "hits" key)
        with self.subTest("malformed response"):
            fake_response = SimpleNamespace(
                json=lambda: {"error": "rate limited"}
            )
            with patch(
                "app.services.material.requests.get", return_value=fake_response
            ):
                results = material.search_videos_coverr("x", minimum_duration=1)
            self.assertEqual(results, [])

        # Subtest B: network exception bubbles up from requests.get
        with self.subTest("network exception"):
            with patch(
                "app.services.material.requests.get",
                side_effect=requests.ConnectionError("boom"),
            ):
                results = material.search_videos_coverr("x", minimum_duration=1)
            self.assertEqual(results, [])

    # ---------------- Tests for _ping_coverr_download ----------------

    def test_ping_coverr_download_sends_patch_with_bearer_auth(self):
        """
        合规性 ping 必须使用 PATCH + Bearer auth,落到正确的 stats endpoint。
        """
        config.proxy.clear()
        config.app.pop("tls_verify", None)

        fake_response = SimpleNamespace(status_code=204)
        with patch(
            "app.services.material.requests.patch", return_value=fake_response
        ) as patch_call:
            material._ping_coverr_download("vid-abc", "coverr-key")

        call = patch_call.call_args
        # URL 必须是 stats/downloads endpoint
        self.assertIn("/videos/vid-abc/stats/downloads", call.args[0])
        # Bearer auth
        self.assertEqual(
            call.kwargs["headers"]["Authorization"], "Bearer coverr-key"
        )

    def test_ping_coverr_download_swallows_failures(self):
        """
        ping 失败不能阻断下载流程 —— 视频已经在硬盘上,
        失败只能记 warning,绝不能 raise。
        """
        config.proxy.clear()
        config.app.pop("tls_verify", None)

        # Subtest A: HTTP non-204 status -> warning, no raise
        with self.subTest("non-204 status"):
            fake_response = SimpleNamespace(status_code=500)
            with patch(
                "app.services.material.requests.patch",
                return_value=fake_response,
            ):
                # 不应抛任何异常
                material._ping_coverr_download("vid-x", "coverr-key")

        # Subtest B: network exception -> swallowed
        with self.subTest("network exception"):
            with patch(
                "app.services.material.requests.patch",
                side_effect=requests.ConnectionError("boom"),
            ):
                material._ping_coverr_download("vid-y", "coverr-key")

    # ---------------- Tests for download_videos coverr branch ----------------

    def test_download_videos_decodes_coverr_url_and_pings(self):
        """
        download_videos 在 source="coverr" 时:
          1. dispatch 到 search_videos_coverr
          2. 把 item.url 的 coverr://<id>|<mp4_url> 拆开,只把 mp4_url 传给 save_video
          3. 下载成功后才 ping,且 ping 携带正确的 video_id
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.app.pop("material_directory", None)
        config.proxy.clear()

        fake_item = material.MaterialInfo()
        fake_item.provider = "coverr"
        fake_item.url = (
            f"{material.COVERR_URL_PREFIX}vid-XYZ|"
            "https://storage.coverr.co/videos/abc?token=xyz"
        )
        fake_item.duration = 10

        with patch(
            "app.services.material.search_videos_coverr",
            return_value=[fake_item],
        ) as search, patch(
            "app.services.material.save_video",
            return_value="/tmp/coverr-saved.mp4",
        ) as save, patch(
            "app.services.material._ping_coverr_download"
        ) as ping:
            result = material.download_videos(
                task_id="t-coverr",
                search_terms=["nature"],
                source="coverr",
                audio_duration=5,
                max_clip_duration=5,
            )

        # 1. dispatch
        self.assertEqual(search.call_count, 1)

        # 2. save_video 收到的是 mp4 直链,不带 coverr:// 前缀也不带 |id 段
        save_url = save.call_args.kwargs.get("video_url") or save.call_args.args[0]
        self.assertEqual(
            save_url, "https://storage.coverr.co/videos/abc?token=xyz"
        )
        self.assertNotIn("coverr://", save_url)
        self.assertNotIn("|", save_url)

        # 3. 下载成功后 ping,且 video_id 正确
        self.assertEqual(ping.call_count, 1)
        ping_kwargs = ping.call_args.kwargs
        self.assertEqual(ping_kwargs.get("video_id"), "vid-XYZ")
        self.assertEqual(ping_kwargs.get("api_key"), "coverr-key")

        # 4. 整体返回值正确
        self.assertEqual(result, ["/tmp/coverr-saved.mp4"])

    def test_download_videos_skips_ping_on_failure_or_malformed_url(self):
        """
        合规性保护:
          - save_video 返回 "" (下载失败) → 不能 ping
          - item.url 缺 | 分隔符 → 跳过该 item,不能 ping 也不能下载
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.app.pop("material_directory", None)
        config.proxy.clear()

        # Subtest A: save_video failed
        with self.subTest("save_video fails -> no ping"):
            fake_item = material.MaterialInfo()
            fake_item.provider = "coverr"
            fake_item.url = (
                f"{material.COVERR_URL_PREFIX}vid-A|https://example.com/a.mp4"
            )
            fake_item.duration = 10

            with patch(
                "app.services.material.search_videos_coverr",
                return_value=[fake_item],
            ), patch(
                "app.services.material.save_video", return_value=""
            ), patch(
                "app.services.material._ping_coverr_download"
            ) as ping:
                material.download_videos(
                    task_id="t-fail",
                    search_terms=["x"],
                    source="coverr",
                    audio_duration=5,
                    max_clip_duration=5,
                )
            self.assertEqual(ping.call_count, 0)

        # Subtest B: malformed url (missing |)
        with self.subTest("malformed url -> skip item entirely"):
            fake_item = material.MaterialInfo()
            fake_item.provider = "coverr"
            fake_item.url = f"{material.COVERR_URL_PREFIX}only-an-id"  # no |
            fake_item.duration = 10

            with patch(
                "app.services.material.search_videos_coverr",
                return_value=[fake_item],
            ), patch(
                "app.services.material.save_video", return_value="/tmp/x.mp4"
            ) as save, patch(
                "app.services.material._ping_coverr_download"
            ) as ping:
                result = material.download_videos(
                    task_id="t-bad",
                    search_terms=["x"],
                    source="coverr",
                    audio_duration=5,
                    max_clip_duration=5,
                )
            self.assertEqual(save.call_count, 0)
            self.assertEqual(ping.call_count, 0)
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
