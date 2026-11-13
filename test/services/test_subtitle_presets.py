import unittest
from unittest.mock import patch

from app.models.schema import VideoAspect, VideoParams
from app.services import subtitle_presets


class TestSubtitlePresets(unittest.TestCase):
    def test_all_professional_presets_are_available(self):
        self.assertEqual(
            subtitle_presets.available_presets(),
            ("classic", "cinematic", "modern", "documentary", "viral", "minimalist"),
        )
        self.assertEqual(subtitle_presets.resolve_preset("modern")["background"], "#111827")

    def test_preset_config_can_override_appearance_without_code_changes(self):
        with patch("app.services.subtitle_presets.config.ui", {
            "subtitle_presets": {
                "modern": {"font_size": 72, "highlight_color": "#00FFAA"},
                "classic": {"font_size": 52},
            }
        }):
            settings = subtitle_presets.resolve_preset("modern")
            classic = subtitle_presets.resolve_preset("classic")
        self.assertEqual(settings["font_size"], 72)
        self.assertEqual(settings["highlight_color"], "#00FFAA")
        self.assertEqual(classic["font_size"], 52)

    def test_dynamic_presets_request_word_timing_when_mode_is_not_explicit(self):
        params = VideoParams(video_subject="test", subtitle_preset="modern")
        self.assertEqual(subtitle_presets.display_mode(params), "word_by_word")
        self.assertTrue(subtitle_presets.highlight_word_cue(params, "precise"))
        self.assertFalse(subtitle_presets.highlight_word_cue(params, "two words"))

    def test_explicit_sentence_mode_does_not_claim_word_synchronization(self):
        params = VideoParams(
            video_subject="test", subtitle_preset="viral", subtitle_display_mode="sentence"
        )
        self.assertEqual(subtitle_presets.display_mode(params), "sentence")
        self.assertFalse(subtitle_presets.highlight_word_cue(params, "word"))

    def test_vertical_safe_area_stays_above_common_bottom_controls(self):
        self.assertEqual(subtitle_presets.safe_bottom_ratio(VideoAspect.portrait), 0.80)
        self.assertEqual(subtitle_presets.safe_bottom_ratio(VideoAspect.landscape), 0.88)

    def test_classic_is_backward_compatible(self):
        params = VideoParams(video_subject="test")
        self.assertEqual(params.subtitle_preset, "classic")
        self.assertEqual(subtitle_presets.resolve_preset("classic"), {})
        self.assertEqual(subtitle_presets.display_mode(params), "sentence")


if __name__ == "__main__":
    unittest.main()
