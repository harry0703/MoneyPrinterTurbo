import unittest
from unittest.mock import patch

from app.services import export_profiles


class TestExportProfiles(unittest.TestCase):
    def test_profiles_encode_short_form_defaults_and_faststart(self):
        shorts = export_profiles.resolve_profile("shorts", codec="libx264")
        self.assertEqual(shorts["fps"], 30)
        self.assertEqual(shorts["video_bitrate"], "8M")
        self.assertEqual(shorts["audio_bitrate"], "192k")
        self.assertTrue(shorts["faststart"])
        self.assertEqual(shorts["encoder_preset"], "medium")

    def test_high_quality_raises_bitrate_without_requesting_a_resolution_upscale(self):
        profile = export_profiles.resolve_profile("high_quality", codec="libx264")
        self.assertEqual(profile["video_bitrate"], "14M")
        self.assertEqual(profile["encoder_preset"], "slow")
        self.assertNotIn("width", profile)
        self.assertNotIn("height", profile)

    def test_fast_profile_does_not_pass_x264_preset_to_hardware_encoder(self):
        profile = export_profiles.resolve_profile("fast", codec="h264_nvenc")
        self.assertEqual(profile["video_bitrate"], "5M")
        self.assertIsNone(profile["encoder_preset"])

    def test_invalid_profile_falls_back_to_legacy(self):
        self.assertEqual(
            export_profiles.resolve_profile("unknown", codec="libx264"),
            export_profiles.resolve_profile("legacy", codec="libx264"),
        )

    def test_user_config_can_override_allowed_profile_values(self):
        with patch("app.services.export_profiles.config.app", {
            "video_export_profiles": {"shorts": {"video_bitrate": "9M", "fps": 25}}
        }):
            profile = export_profiles.resolve_profile("shorts", codec="libx264")
        self.assertEqual(profile["video_bitrate"], "9M")
        self.assertEqual(profile["fps"], 25)


if __name__ == "__main__":
    unittest.main()
