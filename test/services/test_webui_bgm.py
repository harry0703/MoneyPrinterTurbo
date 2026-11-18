import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from loguru import logger
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import bgm, elevenlabs_music, sonilo, voice


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
TEST_LOCALES = ("en", "zh")


def _valid_wav_bytes() -> bytes:
    """Generate a very short standard WAV, so tests don't depend on audio outside the repo or system recordings."""
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
        """Read the expected text for the test language, so assertions don't in turn depend on one particular display language."""
        locale_data = json.loads(
            (I18N_DIR / f"{locale}.json").read_text(encoding="utf-8")
        )
        return locale_data["Translation"][key]

    def _widget_by_key(self, elements, key_prefix):
        """Find widgets by stable business key, so the same widget is still found after the display label is translated."""
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
        # CI doesn't have the language saved in a local config.toml. Explicitly overriding the session locale both
        # reproduces CI's English default and protects against regressions in the Chinese UI developers often use.
        app.session_state["ui_language"] = locale
        app.run()
        source_select = self._widget_by_key(app.selectbox, "bgm_type_select")
        # The real options of stable_selectbox are business values; only the display text changes with the locale.
        source_select.set_value("custom").run()
        return app

    def _open_sonilo_bgm_panel(self, locale):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = locale
        app.run()
        source_select = self._widget_by_key(app.selectbox, "bgm_type_select")
        source_select.set_value("sonilo").run()
        return app

    def _open_elevenlabs_bgm_panel(self, locale):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = locale
        app.run()
        source_select = self._widget_by_key(app.selectbox, "bgm_type_select")
        source_select.set_value("elevenlabs").run()
        return app

    def _open_preset_bgm_panel(self, locale):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = locale
        app.run()
        source_select = self._widget_by_key(app.selectbox, "bgm_type_select")
        source_select.set_value("preset").run()
        return app

    def _uploader(self, app):
        return self._widget_by_key(app.file_uploader, "custom_bgm_uploader")

    def _volume_select(self, app):
        return self._widget_by_key(app.selectbox, "bgm_volume_select")

    def test_preset_song_selection_is_previewed_and_persisted(self):
        """After switching the preset song, the player should update immediately and keep the stable filename config."""
        with tempfile.TemporaryDirectory() as temp_dir:
            first_song = Path(temp_dir) / "first.wav"
            second_song = Path(temp_dir) / "second.wav"
            first_song.write_bytes(_valid_wav_bytes())
            second_song.write_bytes(_valid_wav_bytes())
            test_ui = dict(
                config.ui,
                language="en",
                bgm_type="random",
                preset_song=first_song.name,
            )

            with (
                patch.object(config, "ui", test_ui),
                patch.object(config, "try_save_config", return_value=True),
                patch.object(
                    bgm,
                    "list_builtin_bgm_files",
                    return_value=[str(first_song), str(second_song)],
                ),
            ):
                app = self._open_preset_bgm_panel("en")
                preset_select = self._widget_by_key(
                    app.selectbox, "preset_song_select"
                )
                self.assertEqual(preset_select.value, first_song.name)
                self.assertEqual(len(app.get("audio")), 1)

                preset_select.set_value(second_song.name).run()

            updated_select = self._widget_by_key(
                app.selectbox, "preset_song_select"
            )
            self.assertEqual(updated_select.value, second_song.name)
            self.assertEqual(test_ui["preset_song"], second_song.name)
            self.assertEqual(len(app.get("audio")), 1)
            self.assertEqual([str(item.value) for item in app.exception], [])

    def test_empty_preset_song_list_shows_localized_warning(self):
        """When no songs are available, a hint in the current language should be shown rather than rendering an invalid select box."""
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                test_ui = dict(config.ui, language=locale, bgm_type="random")
                with (
                    patch.object(config, "ui", test_ui),
                    patch.object(config, "try_save_config", return_value=True),
                    patch.object(bgm, "list_builtin_bgm_files", return_value=[]),
                ):
                    app = self._open_preset_bgm_panel(locale)

                self.assertTrue(
                    any(
                        item.value
                        == self._translation(locale, "No Background Music Available")
                        for item in app.warning
                    )
                )
                self.assertFalse(
                    any(
                        str(getattr(item, "key", "")).startswith(
                            "preset_song_select"
                        )
                        for item in app.selectbox
                    )
                )
                self.assertEqual([str(item.value) for item in app.exception], [])

    def test_task_restore_selects_the_original_preset_song(self):
        """When restoring a history task, it must not be overridden by the globally saved preset song."""
        with tempfile.TemporaryDirectory() as temp_dir:
            saved_song = Path(temp_dir) / "saved.wav"
            restored_song = Path(temp_dir) / "restored.wav"
            saved_song.write_bytes(_valid_wav_bytes())
            restored_song.write_bytes(_valid_wav_bytes())
            test_ui = dict(
                config.ui,
                language="en",
                bgm_type="random",
                preset_song=saved_song.name,
            )

            with (
                patch.object(config, "ui", test_ui),
                patch.object(config, "try_save_config", return_value=True),
                patch.object(
                    bgm,
                    "list_builtin_bgm_files",
                    return_value=[str(saved_song), str(restored_song)],
                ),
            ):
                app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
                app.session_state["ui_language"] = "en"
                app.session_state["task_restore_payload"] = {
                    "task_id": "preset-bgm-restore-test",
                    "params": {
                        "bgm_type": "preset",
                        "bgm_file": str(restored_song),
                    },
                }
                app.run()

            preset_select = self._widget_by_key(
                app.selectbox, "preset_song_select"
            )
            self.assertEqual(preset_select.value, restored_song.name)
            self.assertEqual(test_ui["preset_song"], restored_song.name)
            self.assertEqual(len(app.get("audio")), 1)
            self.assertEqual([str(item.value) for item in app.exception], [])

    def test_missing_preset_song_does_not_interrupt_the_page(self):
        """When a file becomes invalid after enumeration, a hint should be shown and no broken player created."""
        missing_song = Path(tempfile.gettempdir()) / "mpt-missing-preset.wav"
        missing_song.unlink(missing_ok=True)
        test_ui = dict(config.ui, language="en", bgm_type="random")

        with (
            patch.object(config, "ui", test_ui),
            patch.object(config, "try_save_config", return_value=True),
            patch.object(
                bgm,
                "list_builtin_bgm_files",
                return_value=[str(missing_song)],
            ),
        ):
            app = self._open_preset_bgm_panel("en")

        self.assertIn(
            self._translation("en", "Background Music Preview Failed"),
            [item.value for item in app.warning],
        )
        self.assertEqual(len(app.get("audio")), 0)
        self.assertEqual([str(item.value) for item in app.exception], [])

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
                    # While an invalid file stays in the upload widget, a volume change triggers a Streamlit rerun.
                    # A cache hit may only redraw the error and must not revalidate or log the warning again.
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

                # After the first validation passes, change the service function to fail explicitly; if the volume rerun
                # wrongly called FFmpeg again, AppTest would receive an AssertionError.
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
        """0 volume keeps the upload selection, but validation and preview must wait until BGM is re-enabled."""
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

        # The file stays in the Streamlit session. After the user raises the volume, the same rerun should automatically
        # finish validation and show the player, without reselecting the file.
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
        """After choosing Sonilo the local Key should be backfilled, keeping password display mode."""
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
                self.assertIn("platform.sonilo.com", api_key_input.label)
                # AppTest's element.type is the widget kind (text_input); password mode
                # is stored in the underlying protobuf enum, and that field must be checked to verify the real rendering.
                self.assertEqual(
                    api_key_input.proto.type, api_key_input.proto.PASSWORD
                )
                self.assertFalse(getattr(api_key_input.proto, "help", ""))
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

        connection.assert_called_once_with()
        self.assertIn(
            self._translation("en", "Sonilo Connection Test Succeeded"),
            [item.value for item in app.success],
        )

    def test_zero_volume_does_not_require_sonilo_key(self):
        """When the Sonilo volume is 0, the WebUI shouldn't keep showing the API Key required warning."""
        test_config = dict(config.app, sonilo_api_key="")
        # BGM volume is now a persistable user preference. Explicitly set this test's
        # non-zero initial condition, so defaults saved by other AppTest sessions don't affect the precondition assertions.
        test_ui = dict(config.ui, bgm_volume=0.2)
        required_warning = self._translation("en", "Sonilo API Key Required")
        with (
            patch.object(config, "app", test_config),
            patch.object(config, "ui", test_ui),
            patch.object(config, "save_config"),
            patch.object(sonilo, "is_enabled", return_value=False),
        ):
            app = self._open_sonilo_bgm_panel("en")
            self.assertIn(required_warning, [item.value for item in app.warning])
            self._volume_select(app).set_value(0.0).run()

        self.assertNotIn(required_warning, [item.value for item in app.warning])
        self.assertEqual([str(item.value) for item in app.exception], [])

    def test_elevenlabs_source_reuses_masked_tts_key_and_shows_prompt(self):
        """Music and TTS should share the Key, keeping password input and the separate music model config."""
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                test_config = dict(
                    config.elevenlabs,
                    api_key="saved-elevenlabs-key",
                    model_id="eleven_multilingual_v2",
                    music_model_id="music_v2",
                )
                with (
                    patch.object(config, "elevenlabs", test_config),
                    patch.object(config, "save_config"),
                ):
                    app = self._open_elevenlabs_bgm_panel(locale)

                api_key_input = self._widget_by_key(
                    app.text_input, "elevenlabs_api_key_input"
                )
                prompt_input = self._widget_by_key(
                    app.text_input, "elevenlabs_music_prompt_input"
                )
                self.assertEqual(api_key_input.value, "saved-elevenlabs-key")
                self.assertEqual(
                    api_key_input.label,
                    self._translation(locale, "ElevenLabs Music API Key"),
                )
                self.assertIn(
                    "elevenlabs.io/app/settings/api-keys",
                    api_key_input.label,
                )
                self.assertEqual(
                    api_key_input.proto.type, api_key_input.proto.PASSWORD
                )
                self.assertFalse(getattr(api_key_input.proto, "help", ""))
                self.assertEqual(prompt_input.value, "")
                self.assertEqual(
                    test_config["model_id"], "eleven_multilingual_v2"
                )
                self.assertEqual([str(item.value) for item in app.exception], [])

    def test_elevenlabs_tts_and_music_share_one_api_key_widget(self):
        """With both voice-over and music enabled there may be only one Key state, and changes must not be overwritten by old values."""
        test_config = dict(config.elevenlabs, api_key="key-A")
        test_ui = dict(config.ui, voice_mode="tts")
        with (
            patch.object(config, "elevenlabs", test_config),
            patch.object(config, "ui", test_ui),
            patch.object(config, "save_config"),
            patch.object(voice, "get_elevenlabs_voices", return_value=[]),
        ):
            app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
            app.session_state["ui_language"] = "en"
            app.run()
            self._widget_by_key(
                app.selectbox, "tts_server_select"
            ).set_value("elevenlabs").run()
            self._widget_by_key(
                app.selectbox, "bgm_type_select"
            ).set_value("elevenlabs").run()

            shared_inputs = [
                item
                for item in app.text_input
                if str(getattr(item, "key", "")).startswith(
                    "elevenlabs_api_key_input"
                )
            ]
            self.assertEqual(len(shared_inputs), 1)
            self.assertEqual(shared_inputs[0].value, "key-A")
            self.assertFalse(
                any(
                    str(getattr(item, "key", "")).startswith(
                        "elevenlabs_music_api_key_input"
                    )
                    for item in app.text_input
                )
            )

            shared_inputs[0].set_value("key-B").run()
            updated_input = self._widget_by_key(
                app.text_input, "elevenlabs_api_key_input"
            )
            self.assertEqual(updated_input.value, "key-B")
            self.assertEqual(test_config["api_key"], "key-B")

        self.assertEqual([str(item.value) for item in app.exception], [])

    def test_elevenlabs_connection_button_reports_success(self):
        test_config = dict(config.elevenlabs, api_key="saved-test-key")
        with (
            patch.object(config, "elevenlabs", test_config),
            patch.object(config, "save_config"),
            patch.object(
                elevenlabs_music, "test_connection", return_value={}
            ) as connection,
        ):
            app = self._open_elevenlabs_bgm_panel("en")
            button = self._widget_by_key(
                app.button, "test_elevenlabs_music_connection_button"
            )
            button.click().run()

        connection.assert_called_once_with()
        self.assertIn(
            self._translation(
                "en", "ElevenLabs Connection Test Succeeded"
            ),
            [item.value for item in app.success],
        )

    def test_elevenlabs_connection_reports_paid_plan_requirement(self):
        """The free plan error should use the current UI's natural language rather than show the English exception directly."""
        for locale in TEST_LOCALES:
            with self.subTest(locale=locale):
                test_config = dict(
                    config.elevenlabs, api_key="saved-test-key"
                )
                with (
                    patch.object(config, "elevenlabs", test_config),
                    patch.object(config, "save_config"),
                    patch.object(
                        elevenlabs_music,
                        "test_connection",
                        side_effect=(
                            elevenlabs_music.ElevenLabsPaidPlanRequiredError(
                                "paid plan required"
                            )
                        ),
                    ),
                ):
                    app = self._open_elevenlabs_bgm_panel(locale)
                    button = self._widget_by_key(
                        app.button,
                        "test_elevenlabs_music_connection_button",
                    )
                    button.click().run()

                self.assertIn(
                    self._translation(
                        locale, "ElevenLabs Paid Plan Required"
                    ),
                    [item.value for item in app.error],
                )

    def test_zero_volume_does_not_require_elevenlabs_key(self):
        """When the ElevenLabs volume is 0, it likewise shouldn't require a Key or call the paid service."""
        test_config = dict(config.elevenlabs, api_key="")
        required_warning = self._translation(
            "en", "ElevenLabs API Key Required"
        )
        with (
            patch.object(config, "elevenlabs", test_config),
            patch.object(config, "save_config"),
            patch.object(
                elevenlabs_music, "is_enabled", return_value=False
            ),
        ):
            app = self._open_elevenlabs_bgm_panel("en")
            self.assertIn(required_warning, [item.value for item in app.warning])
            self._volume_select(app).set_value(0.0).run()

        self.assertNotIn(required_warning, [item.value for item in app.warning])
        self.assertEqual([str(item.value) for item in app.exception], [])


if __name__ == "__main__":
    unittest.main()
