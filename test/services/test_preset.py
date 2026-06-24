import unittest

from app.utils import preset


class TestPresetUtils(unittest.TestCase):
    def test_build_preset_filters_sensitive_fields_and_keeps_generation_settings(self):
        built = preset.build_preset(
            app_config={
                "llm_provider": "openai",
                "openai_model_name": "gpt-4o-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "openai_api_key": "should-not-export",
                "video_source": "pexels",
            },
            ui_config={
                "video_language": "en-US",
                "video_aspect": "16:9",
                "voice_rate": 1.2,
            },
            azure_config={"speech_region": "eastasia", "speech_key": "secret"},
            siliconflow_config={"api_key": "secret"},
            session_state={"video_subject": "demo", "video_script": "hello"},
            name="My Preset #1",
        )

        self.assertEqual(built["name"], "My-Preset-1")
        self.assertEqual(built["app"]["openai_model_name"], "gpt-4o-mini")
        self.assertEqual(built["app"]["openai_base_url"], "https://api.openai.com/v1")
        self.assertNotIn("openai_api_key", built["app"])
        self.assertNotIn("speech_key", built["azure"])
        self.assertEqual(built["ui"]["video_language"], "en-US")
        self.assertEqual(built["session"]["video_subject"], "demo")

    def test_apply_preset_ignores_sensitive_fields(self):
        app_config = {}
        ui_config = {}
        azure_config = {}
        siliconflow_config = {}
        session_state = {}

        preset.apply_preset(
            preset={
                "app": {
                    "llm_provider": "openai",
                    "openai_model_name": "gpt-4o",
                    "openai_api_key": "secret",
                },
                "ui": {"video_aspect": "9:16", "voice_volume": 1.2},
                "azure": {"speech_region": "westus", "speech_key": "secret"},
                "session": {"video_subject": "topic"},
            },
            app_config=app_config,
            ui_config=ui_config,
            azure_config=azure_config,
            siliconflow_config=siliconflow_config,
            session_state=session_state,
        )

        self.assertEqual(app_config["llm_provider"], "openai")
        self.assertEqual(app_config["openai_model_name"], "gpt-4o")
        self.assertNotIn("openai_api_key", app_config)
        self.assertEqual(ui_config["video_aspect"], "9:16")
        self.assertEqual(azure_config["speech_region"], "westus")
        self.assertNotIn("speech_key", azure_config)
        self.assertEqual(session_state["video_subject"], "topic")

    def test_sanitize_preset_name(self):
        self.assertEqual(
            preset.sanitize_preset_name("  YouTube Shorts / Preset  "),
            "YouTube-Shorts-Preset",
        )
        self.assertEqual(preset.sanitize_preset_name("***"), "moneyprinterturbo-preset")


if __name__ == "__main__":
    unittest.main()
