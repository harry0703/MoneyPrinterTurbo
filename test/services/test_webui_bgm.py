import io
import json
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from loguru import logger
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import bgm, sonilo


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
TEST_LOCALES = ("en", "zh")


def _valid_wav_bytes() -> bytes:
    """生成一个很短的标准 WAV，避免测试依赖仓库外部音频或系统录音文件。"""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 800)
    return output.getvalue()


class TestWebuiBackgroundMusic(unittest.TestCase):
    @staticmethod
    def _translation(locale, key):
        """按测试语言读取期望文案，避免断言反过来依赖某一种展示语言。"""
        locale_data = json.loads(
            (I18N_DIR / f"{locale}.json").read_text(encoding="utf-8")
        )
        return locale_data["Translation"][key]

    def _widget_by_key(self, elements, key_prefix):
        """通过稳定业务 key 查找控件，展示标签翻译后仍能命中同一控件。"""
        widget = next(
            (
                item
                for item in elements
                if str(getattr(item, "key", "")) == key_prefix
                or str(getattr(item, "key", "")).startswith(f"{key_prefix}_")
            ),
            None,
        )
        self.assertIsNotNone(widget, f"widget not found: {key_prefix}")
        return widget

    def _open_custom_bgm_panel(self, locale):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        # CI 没有本机 config.toml 中保存的语言。显式覆盖 session locale，既能
        # 复现 CI 的英文默认值，也能保护开发者常用的中文界面回归。
        app.session_state["ui_language"] = locale
        app.run()
        source_select = self._widget_by_key(app.selectbox, "bgm_type_select")
        # stable_selectbox 的真实选项是业务值，展示文案才会随 locale 变化。
        source_select.set_value("custom").run()
        return app

    def _open_sonilo_bgm_panel(self, locale):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = locale
        app.run()
        source_select = self._widget_by_key(app.selectbox, "bgm_type_select")
        source_select.set_value("sonilo").run()
        return app

    def _uploader(self, app):
        return self._widget_by_key(app.file_uploader, "custom_bgm_uploader")

    def _volume_select(self, app):
        return self._widget_by_key(app.selectbox, "bgm_volume_select")

    def test_invalid_audio_shows_error_without_ready_state_or_player(self):
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                app = self._open_custom_bgm_panel(locale)
                with patch.object(logger, "warning") as warning:
                    self._uploader(app).set_value(
                        (
                            "invalid.m4a",
                            b"not-a-decodable-audio-file",
                            "audio/mp4",
                        )
                    ).run()
                    # 非法文件留在上传控件时，音量调整会触发 Streamlit rerun。
                    # 缓存命中只能重绘错误，不能重复校验或重复记录 warning。
                    self._volume_select(app).set_value(0.4).run()

                rejection_logs = [
                    call
                    for call in warning.call_args_list
                    if "WebUI background music validation rejected" in str(call)
                ]
                self.assertEqual([str(item.value) for item in app.exception], [])
                self.assertEqual(
                    [item.value for item in app.error],
                    [self._translation(locale, "Invalid Background Music")],
                )
                self.assertFalse(
                    any("invalid.m4a" in item.value for item in app.info)
                )
                self.assertEqual(len(app.get("audio")), 0)
                self.assertEqual(len(rejection_logs), 1)

    def test_valid_audio_shows_ready_state_and_reuses_validation_cache(self):
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                app = self._open_custom_bgm_panel(locale)
                self._uploader(app).set_value(
                    ("valid.wav", _valid_wav_bytes(), "audio/wav")
                ).run()

                # 首次校验通过后，把服务函数改成显式失败；如果音量 rerun
                # 错误地再次调用 FFmpeg，AppTest 会收到 AssertionError。
                with patch.object(
                    bgm,
                    "validate_bgm_upload",
                    side_effect=AssertionError(
                        "validation repeated during rerun"
                    ),
                ):
                    self._volume_select(app).set_value(0.4).run()

                self.assertEqual([str(item.value) for item in app.exception], [])
                self.assertEqual([item.value for item in app.error], [])
                self.assertEqual(
                    [item.value for item in app.info if "valid.wav" in item.value],
                    [
                        f"{self._translation(locale, 'Background Music Ready')}: "
                        "valid.wav"
                    ],
                )
                self.assertEqual(len(app.get("audio")), 1)

    def test_zero_volume_defers_custom_upload_validation_until_enabled(self):
        """0 音量保留上传选择，但必须等重新启用 BGM 后才校验和预览。"""
        app = self._open_custom_bgm_panel("en")
        self._volume_select(app).set_value(0.0).run()

        with patch.object(bgm, "validate_bgm_upload") as validation:
            self._uploader(app).set_value(
                ("deferred.wav", _valid_wav_bytes(), "audio/wav")
            ).run()

        validation.assert_not_called()
        self.assertEqual([str(item.value) for item in app.exception], [])
        self.assertEqual([item.value for item in app.error], [])
        self.assertFalse(any("deferred.wav" in item.value for item in app.info))
        self.assertEqual(len(app.get("audio")), 0)

        # 文件仍保留在 Streamlit 会话中。用户调高音量后，同一次 rerun 应自动
        # 完成校验并显示播放器，不需要重新选择文件。
        with patch.object(bgm, "validate_bgm_upload") as validation:
            self._volume_select(app).set_value(0.2).run()

        validation.assert_called_once()
        self.assertEqual([str(item.value) for item in app.exception], [])
        self.assertEqual([item.value for item in app.error], [])
        self.assertTrue(any("deferred.wav" in item.value for item in app.info))
        self.assertEqual(len(app.get("audio")), 1)

    def test_service_failure_is_not_reported_as_invalid_user_audio(self):
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                app = self._open_custom_bgm_panel(locale)
                with patch.object(
                    bgm,
                    "validate_bgm_upload",
                    side_effect=bgm.BgmServiceError("FFmpeg unavailable"),
                ):
                    self._uploader(app).set_value(
                        ("valid.wav", _valid_wav_bytes(), "audio/wav")
                    ).run()

                self.assertEqual([str(item.value) for item in app.exception], [])
                self.assertEqual(
                    [item.value for item in app.error],
                    [
                        self._translation(
                            locale, "Background Music Validation Failed"
                        )
                    ],
                )
                self.assertEqual(len(app.get("audio")), 0)

    def test_sonilo_source_shows_masked_prefilled_key_and_optional_prompt(self):
        """选择 Sonilo 后应回填本机 Key，但控件必须保持密码显示模式。"""
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                test_config = dict(config.app, sonilo_api_key="saved-test-key")
                with (
                    patch.object(config, "app", test_config),
                    patch.object(config, "save_config"),
                ):
                    app = self._open_sonilo_bgm_panel(locale)

                api_key_input = self._widget_by_key(
                    app.text_input, "sonilo_api_key_input"
                )
                prompt_input = self._widget_by_key(
                    app.text_input, "sonilo_bgm_prompt_input"
                )
                self.assertEqual(api_key_input.value, "saved-test-key")
                self.assertEqual(
                    api_key_input.label,
                    self._translation(locale, "Sonilo API Key"),
                )
                self.assertIn(
                    "https://platform.sonilo.com/", api_key_input.label
                )
                # AppTest 的 element.type 表示控件种类（text_input）；密码模式
                # 保存在底层 protobuf 枚举中，必须检查该字段才能验证真实渲染。
                self.assertEqual(
                    api_key_input.proto.type, api_key_input.proto.PASSWORD
                )
                self.assertEqual(prompt_input.value, "")
                self.assertEqual([str(item.value) for item in app.exception], [])

    def test_sonilo_connection_button_reports_success(self):
        test_config = dict(config.app, sonilo_api_key="saved-test-key")
        with (
            patch.object(config, "app", test_config),
            patch.object(config, "save_config"),
            patch.object(sonilo, "test_connection", return_value={}) as connection,
        ):
            app = self._open_sonilo_bgm_panel("en")
            button = self._widget_by_key(
                app.button, "test_sonilo_connection_button"
            )
            button.click().run()

        connection.assert_called_once_with(
            required_service_ids=(sonilo.VIDEO_TO_MUSIC_SERVICE_ID,)
        )
        self.assertIn(
            self._translation("en", "Sonilo Connection Test Succeeded"),
            [item.value for item in app.success],
        )

    def test_zero_volume_does_not_require_sonilo_key(self):
        """Sonilo 音量为 0 时，WebUI 不应继续显示 API Key 必填警告。"""
        test_config = dict(config.app, sonilo_api_key="")
        required_warning = self._translation("en", "Sonilo API Key Required")
        with (
            patch.object(config, "app", test_config),
            patch.object(config, "save_config"),
            patch.object(sonilo, "is_enabled", return_value=False),
        ):
            app = self._open_sonilo_bgm_panel("en")
            self.assertIn(required_warning, [item.value for item in app.warning])
            self._volume_select(app).set_value(0.0).run()

        self.assertNotIn(required_warning, [item.value for item in app.warning])
        self.assertEqual([str(item.value) for item in app.exception], [])

    def _open_sfx_panel(self, locale):
        """默认背景音乐来源下开启音效开关，覆盖音效独立于配乐来源的场景。"""
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = locale
        app.run()
        self._widget_by_key(
            app.checkbox, "sonilo_sfx_enabled_checkbox"
        ).check().run()
        return app

    def test_sfx_toggle_shows_shared_key_volume_prompt_and_notice(self):
        """任意配乐来源下开启音效都应展示共享 Key、音量、描述与上传告知。"""
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                test_config = dict(config.app, sonilo_api_key="saved-test-key")
                with (
                    patch.object(config, "app", test_config),
                    patch.object(config, "save_config"),
                ):
                    app = self._open_sfx_panel(locale)

                api_key_input = self._widget_by_key(
                    app.text_input, "sonilo_api_key_input"
                )
                volume_select = self._widget_by_key(
                    app.selectbox, "sonilo_sfx_volume_select"
                )
                self._widget_by_key(app.text_input, "sonilo_sfx_prompt_input")
                self.assertEqual(api_key_input.value, "saved-test-key")
                self.assertEqual(
                    api_key_input.proto.type, api_key_input.proto.PASSWORD
                )
                self.assertEqual(volume_select.value, 0.3)
                self.assertIn(
                    self._translation(locale, "Sonilo Sound Effects Notice"),
                    [item.value for item in app.info],
                )
                self.assertEqual([str(item.value) for item in app.exception], [])

    def test_sfx_connection_button_requires_only_sfx_service(self):
        """仅开启音效时，连接测试不应要求账号同时开通配乐服务。"""
        test_config = dict(config.app, sonilo_api_key="saved-test-key")
        with (
            patch.object(config, "app", test_config),
            patch.object(config, "save_config"),
            patch.object(sonilo, "test_connection", return_value={}) as connection,
        ):
            app = self._open_sfx_panel("en")
            button = self._widget_by_key(
                app.button, "test_sonilo_connection_button"
            )
            button.click().run()

        connection.assert_called_once_with(
            required_service_ids=(sonilo.VIDEO_TO_SFX_SERVICE_ID,)
        )
        self.assertIn(
            self._translation("en", "Sonilo Connection Test Succeeded"),
            [item.value for item in app.success],
        )

    def test_sfx_zero_volume_does_not_require_sonilo_key(self):
        """音效音量为 0 时，WebUI 不应继续显示 API Key 必填警告。"""
        test_config = dict(config.app, sonilo_api_key="")
        required_warning = self._translation("en", "Sonilo API Key Required")
        with (
            patch.object(config, "app", test_config),
            patch.object(config, "save_config"),
            patch.object(sonilo, "is_enabled", return_value=False),
        ):
            app = self._open_sfx_panel("en")
            self.assertIn(required_warning, [item.value for item in app.warning])
            self._widget_by_key(
                app.selectbox, "sonilo_sfx_volume_select"
            ).set_value(0.0).run()

        self.assertNotIn(required_warning, [item.value for item in app.warning])
        self.assertEqual([str(item.value) for item in app.exception], [])


if __name__ == "__main__":
    unittest.main()
