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
            video_concat_mode="random",
        )

        self.assertEqual(result, [])

    def test_download_videos_can_round_robin_terms_in_script_order(self):
        """
        开启按文案顺序匹配素材后，不能让第一个关键词的多个候选先把
        音频时长填满。这里模拟两个关键词各有多个候选，验证下载顺序是
        term1-第1个、term2-第1个、term1-第2个，贴近脚本叙事顺序。
        """
        search_results = {
            "opening city": [
                material.MaterialInfo(provider="pexels", url="https://v.example/a1.mp4", duration=3),
                material.MaterialInfo(provider="pexels", url="https://v.example/a2.mp4", duration=3),
            ],
            "middle office": [
                material.MaterialInfo(provider="pexels", url="https://v.example/b1.mp4", duration=3),
                material.MaterialInfo(provider="pexels", url="https://v.example/b2.mp4", duration=3),
            ],
        }
        downloaded_urls = []

        def fake_search(search_term, minimum_duration, video_aspect):
            return search_results[search_term]

        def fake_save_video(video_url, save_dir=""):
            downloaded_urls.append(video_url)
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(config.app, {"material_directory": ""}),
            patch.object(material, "search_videos_pexels", side_effect=fake_search),
            patch.object(material, "save_video", side_effect=fake_save_video),
        ):
            result = material.download_videos(
                task_id="ordered-materials",
                search_terms=["opening city", "middle office"],
                source="pexels",
                audio_duration=7,
                max_clip_duration=3,
                match_script_order=True,
            )

        self.assertEqual(
            downloaded_urls,
            [
                "https://v.example/a1.mp4",
                "https://v.example/b1.mp4",
                "https://v.example/a2.mp4",
            ],
        )
        self.assertEqual(result, ["/tmp/a1.mp4", "/tmp/b1.mp4", "/tmp/a2.mp4"])


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

    def test_search_coverr_uses_mp4_download_url(self):
        """
        search_videos_coverr 应把每个 hit 转成 MaterialInfo，并把 urls.mp4_download
        直接作为 MaterialInfo.url。
        按 Coverr 官方文档 (api.coverr.co/docs/videos/#download-a-video),
        GET mp4_download 本身就被 Coverr 计入下载统计,无需额外 PATCH ping。
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
        # url 字段就是 mp4_download URL,不再做 coverr://id|url 编码
        self.assertEqual(
            item.url, "https://storage.coverr.co/videos/abc/download?token=xyz"
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
                        "urls": {"mp4_download": "https://example.com/a.mp4"},
                    },
                    {
                        "id": "stringdur",
                        "duration": "10.500000",  # string accepted
                        "urls": {"mp4_download": "https://example.com/b.mp4"},
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
        self.assertEqual(results[0].url, "https://example.com/b.mp4")

    def test_search_coverr_skips_invalid_items(self):
        """缺 id 或缺 urls.mp4_download 的条目应被跳过,不应抛异常。"""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {  # missing urls.mp4_download
                        "id": "no-download",
                        "duration": 10,
                        "urls": {"mp4_preview": "https://example.com/preview.mp4"},
                    },
                    {  # missing id
                        "duration": 10,
                        "urls": {"mp4_download": "https://example.com/x.mp4"},
                    },
                    {  # valid baseline
                        "id": "good",
                        "duration": 10,
                        "urls": {"mp4_download": "https://example.com/good.mp4"},
                    },
                ]
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ):
            results = material.search_videos_coverr("x", minimum_duration=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/good.mp4")

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

    # ---------------- Tests for download_videos coverr branch ----------------

    def test_download_videos_passes_mp4_download_url_to_save_video(self):
        """
        在 source="coverr" 时:
          1. dispatch 到 search_videos_coverr
          2. coverr item 走通用下载路径:save_video 收到的就是 mp4_download URL
             (不再有 coverr://id|url 编码,也不再调用 PATCH ping)
          3. 返回保存路径
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.app.pop("material_directory", None)
        config.proxy.clear()

        fake_item = material.MaterialInfo()
        fake_item.provider = "coverr"
        fake_item.url = "https://storage.coverr.co/videos/abc/download?token=xyz"
        fake_item.duration = 10

        with patch(
            "app.services.material.search_videos_coverr",
            return_value=[fake_item],
        ) as search, patch(
            "app.services.material.save_video",
            return_value="/tmp/coverr-saved.mp4",
        ) as save:
            result = material.download_videos(
                task_id="t-coverr",
                search_terms=["nature"],
                source="coverr",
                audio_duration=5,
                max_clip_duration=5,
            )

        # 1. dispatch
        self.assertEqual(search.call_count, 1)

        # 2. save_video 收到的就是 mp4_download URL,原样传入
        save_url = save.call_args.kwargs.get("video_url") or save.call_args.args[0]
        self.assertEqual(
            save_url, "https://storage.coverr.co/videos/abc/download?token=xyz"
        )

        # 3. 返回值正确
        self.assertEqual(result, ["/tmp/coverr-saved.mp4"])


class TestDiscordProvider(unittest.TestCase):
    """
    Discord 视频素材源：用 bot token 拉取所选频道里最近的视频附件。
    全部用 unittest.mock 替换 requests，不依赖真实网络和真实 token。
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def _ok(self, payload):
        return SimpleNamespace(status_code=200, json=lambda: payload, text="")

    def _mixed_messages(self):
        return [
            {
                "id": "3",
                "attachments": [
                    {"url": "https://cdn.discord/a.mp4", "content_type": "video/mp4", "filename": "a.mp4"},
                    {"url": "https://cdn.discord/pic.png", "content_type": "image/png", "filename": "pic.png"},
                ],
            },
            {
                "id": "2",
                "attachments": [
                    # content_type 缺失，靠文件名扩展名识别
                    {"url": "https://cdn.discord/b.mov", "filename": "b.mov"},
                    {"url": "https://cdn.discord/doc.pdf", "filename": "doc.pdf"},
                ],
            },
            {"id": "1", "attachments": []},
        ]

    def test_fetch_video_only_filters_images(self):
        """media_type='video' 只保留视频附件，图片 / 其它附件应被过滤。"""
        config.proxy.clear()
        with patch(
            "app.services.material.requests.get",
            return_value=self._ok(self._mixed_messages()),
        ) as get:
            items = material.fetch_discord_attachments("tok", "chan", count=10, media_type="video")

        self.assertEqual([i.url for i in items], [
            "https://cdn.discord/a.mp4",
            "https://cdn.discord/b.mov",
        ])
        self.assertTrue(all(i.provider == "discord" and i.kind == "video" and i.duration == 0 for i in items))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bot tok")

    def test_fetch_image_only(self):
        """media_type='image' 只保留图片附件。"""
        config.proxy.clear()
        with patch(
            "app.services.material.requests.get",
            return_value=self._ok(self._mixed_messages()),
        ):
            items = material.fetch_discord_attachments("tok", "chan", count=10, media_type="image")
        self.assertEqual([i.url for i in items], ["https://cdn.discord/pic.png"])
        self.assertEqual(items[0].kind, "image")

    def test_fetch_both_keeps_videos_and_images(self):
        """media_type='both' 同时保留视频和图片，其它附件仍被过滤。"""
        config.proxy.clear()
        with patch(
            "app.services.material.requests.get",
            return_value=self._ok(self._mixed_messages()),
        ):
            items = material.fetch_discord_attachments("tok", "chan", count=10, media_type="both")
        self.assertEqual([i.url for i in items], [
            "https://cdn.discord/a.mp4",
            "https://cdn.discord/pic.png",
            "https://cdn.discord/b.mov",
        ])

    def test_legacy_fetch_video_wrapper(self):
        """旧名 fetch_discord_video_attachments 仍只返回视频。"""
        config.proxy.clear()
        with patch(
            "app.services.material.requests.get",
            return_value=self._ok(self._mixed_messages()),
        ):
            items = material.fetch_discord_video_attachments("tok", "chan", count=10)
        self.assertEqual([i.kind for i in items], ["video", "video"])

    def test_fetch_stops_at_count(self):
        """收集够 count 个视频后立即返回，不再继续翻页。"""
        config.proxy.clear()
        messages = [
            {"id": str(i), "attachments": [
                {"url": f"https://cdn.discord/{i}.mp4", "content_type": "video/mp4", "filename": f"{i}.mp4"}
            ]}
            for i in range(5)
        ]
        with patch(
            "app.services.material.requests.get", return_value=self._ok(messages)
        ):
            items = material.fetch_discord_video_attachments("tok", "chan", count=2)
        self.assertEqual(len(items), 2)

    def test_download_videos_dispatches_to_discord(self):
        """
        source="discord" 时短路搜索逻辑：从 config.app 读取 token，把每个附件
        URL 交给 save_video，返回保存路径。
        """
        config.app["discord_bot_token"] = "tok"
        config.app.pop("material_directory", None)
        config.proxy.clear()

        fake_item = material.MaterialInfo()
        fake_item.provider = "discord"
        fake_item.kind = "video"
        fake_item.url = "https://cdn.discord/a.mp4"
        fake_item.duration = 0

        with patch(
            "app.services.material.fetch_discord_attachments",
            return_value=[fake_item],
        ) as fetch, patch(
            "app.services.material.save_video",
            return_value="/tmp/discord-a.mp4",
        ) as save:
            result = material.download_videos(
                task_id="t-discord",
                search_terms=[],
                source="discord",
                discord_channel_id="chan",
                discord_count=3,
                discord_media_type="video",
            )

        fetch.assert_called_once_with("tok", "chan", 3, "video")
        save_url = save.call_args.kwargs.get("video_url") or save.call_args.args[0]
        self.assertEqual(save_url, "https://cdn.discord/a.mp4")
        self.assertEqual(result, ["/tmp/discord-a.mp4"])

    def test_download_videos_dispatches_images_through_preprocess(self):
        """
        media_type='image' 时，图片附件下载后必须经过 video.preprocess_video
        转成短视频片段，返回的才是可被 combine_videos 直接拼接的 mp4 路径。
        """
        config.app["discord_bot_token"] = "tok"
        config.app.pop("material_directory", None)
        config.proxy.clear()

        img_item = material.MaterialInfo()
        img_item.provider = "discord"
        img_item.kind = "image"
        img_item.url = "https://cdn.discord/pic.png?ex=abc"

        processed = material.MaterialInfo()
        processed.url = "/tmp/local_videos/img-hash.png.mp4"

        with patch(
            "app.services.material.fetch_discord_attachments",
            return_value=[img_item],
        ), patch(
            "app.services.material.save_discord_image",
            return_value="/tmp/local_videos/img-hash.png",
        ), patch(
            "app.services.video.preprocess_video",
            return_value=[processed],
        ) as preprocess:
            result = material.download_videos(
                task_id="t-discord-img",
                search_terms=[],
                source="discord",
                discord_channel_id="chan",
                discord_count=2,
                discord_media_type="image",
            )

        # 传给 preprocess_video 的素材 url 应是文件名（供 local_videos_dir 解析）
        passed_materials = preprocess.call_args.kwargs["materials"]
        self.assertEqual(passed_materials[0].url, "img-hash.png")
        self.assertEqual(result, ["/tmp/local_videos/img-hash.png.mp4"])

    def test_download_discord_returns_empty_without_token_or_channel(self):
        config.proxy.clear()
        self.assertEqual(
            material.download_discord_videos("t", token="", channel_id="c", count=1), []
        )
        self.assertEqual(
            material.download_discord_videos("t", token="tok", channel_id="", count=1), []
        )


if __name__ == "__main__":
    unittest.main()
