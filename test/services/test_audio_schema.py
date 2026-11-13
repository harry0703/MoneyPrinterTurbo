import unittest

from pydantic import ValidationError

from app.models.schema import SoundEffectCue, VideoParams


class TestAudioSchema(unittest.TestCase):
    def test_audio_processing_and_export_options_keep_legacy_defaults(self):
        params = VideoParams(video_subject="test")
        self.assertEqual(params.video_pipeline, "legacy")
        self.assertEqual(params.scene_plan_fallback, "legacy")
        self.assertFalse(params.scene_media_visual_validation)
        self.assertEqual(params.video_export_profile, "legacy")
        self.assertFalse(params.audio_ducking_enabled)
        self.assertFalse(params.audio_normalization_enabled)
        self.assertFalse(params.audio_peak_guard_enabled)
        self.assertEqual(params.sound_effects, [])

    def test_sound_effect_is_scene_scoped_and_validated(self):
        cue = SoundEffectCue(
            file_name="soft-whoosh.wav", scene_id="scene-001",
            start_seconds=0.4, duration_seconds=1.2, volume=0.25,
        )
        self.assertEqual(cue.scene_id, "scene-001")
        self.assertEqual(cue.volume, 0.25)
        for unsafe in ("../escape.wav", "folder\\effect.mp3", "effect.exe"):
            with self.subTest(file_name=unsafe), self.assertRaises(ValidationError):
                SoundEffectCue(file_name=unsafe)

    def test_sound_effect_count_is_bounded(self):
        with self.assertRaises(ValidationError):
            VideoParams(
                video_subject="test",
                sound_effects=[{"file_name": f"fx-{index}.wav"} for index in range(25)],
            )


if __name__ == "__main__":
    unittest.main()
