import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock

from PIL import Image
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import VideoAspect, VideoParams
from app.services.character_image import CharacterImageService
from app.services.character_lipsync import CharacterLipSyncService
from app.services.character_lipsync import LipSyncFrame
from app.services import video as video_service
from app.services.character_overlay import CharacterOverlayLayout, CharacterOverlayResult, CharacterOverlayService


class FakeClip:
    def __init__(self, duration: float = 3.0, width: int = 240, height: int = 160, name: str = "clip"):
        self.duration = duration
        self.w = width
        self.h = height
        self.size = (width, height)
        self.name = name
        self.mask = None
        self.audio = None
        self.written = False

    def with_effects(self, _effects):
        return self

    def with_start(self, _start):
        return self

    def with_end(self, _end):
        return self

    def with_duration(self, duration):
        self.duration = duration
        return self

    def with_position(self, _position):
        return self

    def with_audio(self, audio):
        self.audio = audio
        return self

    def write_videofile(self, *_args, **_kwargs):
        self.written = True

    def close(self):
        return None


class FakeSubtitlesClip:
    def __init__(self, *_args, **_kwargs):
        self.subtitles = [((0.0, 1.0), "Hola overlay")]


class TestCharacterOverlaySchema(unittest.TestCase):
    def test_videoparams_accepts_character_overlay_fields(self):
        params = VideoParams(
            video_subject="demo",
            video_aspect=VideoAspect.portrait.value,
            character_overlay_enabled=True,
            character_image_file="/tmp/avatar.png",
            character_position="custom",
            character_custom_x=50.0,
            character_custom_y=80.0,
            character_scale=0.32,
            character_margin_x=24,
            character_margin_y=48,
            character_lipsync_enabled=True,
            character_idle_motion_enabled=True,
            character_layer_order="behind_subtitles",
        )

        self.assertTrue(params.character_overlay_enabled)
        self.assertEqual(params.character_image_file, "/tmp/avatar.png")
        self.assertEqual(params.character_position, "custom")
        self.assertEqual(params.character_custom_x, 50.0)
        self.assertEqual(params.character_custom_y, 80.0)
        self.assertEqual(params.character_layer_order, "behind_subtitles")

    def test_videoparams_character_overlay_defaults_are_safe(self):
        params = VideoParams(video_subject="demo")

        self.assertFalse(params.character_overlay_enabled)
        self.assertIsNone(params.character_image_file)
        self.assertEqual(params.character_position, "bottom_right")
        self.assertTrue(params.character_remove_background)
        self.assertTrue(params.character_lipsync_enabled)
        self.assertTrue(params.character_idle_motion_enabled)

    def test_prepare_character_image_crops_transparent_padding(self):
        service = CharacterImageService()
        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "character.png"
            image = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
            image.paste(Image.new("RGBA", (40, 50), (255, 255, 255, 255)), (20, 15))
            image.save(image_path)

            prepared = service.prepare(str(image_path), remove_background=False)

        self.assertEqual(prepared.original_size, (80, 80))
        self.assertEqual(prepared.content_size, (40, 50))

    def test_character_overlay_layout_stays_inside_canvas(self):
        overlay_service = CharacterOverlayService()
        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "character.png"
            image = Image.new("RGBA", (320, 480), (0, 0, 0, 0))
            image.paste(Image.new("RGBA", (200, 320), (255, 255, 255, 255)), (60, 80))
            image.save(image_path)

            params = VideoParams(
                video_subject="demo",
                video_aspect=VideoAspect.portrait.value,
                character_overlay_enabled=True,
                character_image_file=str(image_path),
                character_position="bottom_right",
                character_margin_x=36,
                character_margin_y=36,
                character_scale=0.28,
            )
            result = overlay_service.create_overlay(
                params=params,
                canvas_size=(1080, 1920),
                duration=3.0,
                audio_path=None,
            )

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.layout.x, 0)
        self.assertGreaterEqual(result.layout.y, 0)
        self.assertLessEqual(result.layout.x + result.layout.width, 1080)
        self.assertLessEqual(result.layout.y + result.layout.height, 1920)
        self.assertTrue(result.layout.avoid_subtitles)
        if result is not None:
            if getattr(result.clip, "mask", None) is not None:
                result.clip.mask.close()
            result.clip.close()

    def test_character_overlay_requires_existing_image_file(self):
        overlay_service = CharacterOverlayService()
        params = VideoParams(
            video_subject="demo",
            character_overlay_enabled=True,
            character_image_file="/tmp/does-not-exist.png",
        )

        with self.assertRaises(FileNotFoundError):
            overlay_service.create_overlay(
                params=params,
                canvas_size=(1080, 1920),
                duration=2.0,
                audio_path=None,
            )

    def test_lipsync_service_returns_neutral_timeline_without_audio(self):
        timeline = CharacterLipSyncService().analyze(audio_path=None, duration=2.5)

        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0].start, 0.0)
        self.assertEqual(timeline[0].end, 2.5)
        self.assertEqual(timeline[0].openness, 0.0)

    def test_mouth_deformation_preserves_alpha_shape(self):
        overlay_service = CharacterOverlayService()
        image = Image.new("RGBA", (240, 320), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (140, 220), (255, 255, 255, 255)), (50, 50))

        deformed = overlay_service._apply_mouth_deformation(image, openness=0.9)

        original_alpha = image.split()[-1]
        deformed_alpha = deformed.split()[-1]
        self.assertEqual(original_alpha.getbbox(), deformed_alpha.getbbox())

    def test_render_character_frame_applies_mouth_before_idle_scale(self):
        overlay_service = CharacterOverlayService()
        base_frame = np.zeros((24, 24, 4), dtype=np.uint8)
        call_order = []

        def fake_mouth(image, openness, mouth_region):
            call_order.append("mouth")
            return image

        def fake_scale(image, idle_scale):
            call_order.append("scale")
            return image

        with patch.object(overlay_service, "_apply_mouth_deformation", side_effect=fake_mouth), patch.object(
            overlay_service,
            "_apply_idle_scale",
            side_effect=fake_scale,
        ):
            overlay_service._render_character_frame(
                base_frame=base_frame,
                openness=0.9,
                idle_scale=1.03,
                mouth_region=(6, 10, 18, 16),
            )

        self.assertEqual(call_order, ["mouth", "scale"])

    def test_create_overlay_preserves_original_canvas_in_manual_mapping(self):
        image_service = MagicMock()
        lipsync_service = MagicMock()
        image_service.prepare.return_value = type(
            "Prepared", (), {"image": Image.new("RGBA", (200, 300), (255, 255, 255, 255))}
        )()
        image_service.scale_for_canvas.return_value = type(
            "Scaled", (), {"image": Image.new("RGBA", (120, 180), (255, 255, 255, 255)), "width": 120, "height": 180}
        )()
        lipsync_service.analyze.return_value = []
        lipsync_service.openness_at.return_value = 0.0

        overlay_service = CharacterOverlayService(
            image_service=image_service,
            lipsync_service=lipsync_service,
        )
        params = VideoParams(
            video_subject="demo",
            character_overlay_enabled=True,
            character_image_file="/tmp/avatar.png",
            character_manual_mapping_enabled=True,
            character_lipsync_enabled=False,
        )

        with patch.object(overlay_service, "_resolve_mouth_region", return_value=(20, 40, 60, 80)):
            result = overlay_service.create_overlay(
                params=params,
                canvas_size=(1080, 1920),
                duration=1.0,
                audio_path=None,
            )

        self.assertIsNotNone(result)
        image_service.prepare.assert_called_once()
        self.assertFalse(image_service.prepare.call_args.kwargs.get("crop_transparent_edges", True))

    def test_mouth_region_uses_face_bbox_when_available(self):
        overlay_service = CharacterOverlayService()
        image = Image.new("RGBA", (300, 400), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (200, 320), (255, 255, 255, 255)), (60, 40))
        rgba = np.array(image, dtype=np.uint8)

        with patch.object(
            CharacterOverlayService,
            "_resolve_face_bbox",
            return_value=(120, 110, 210, 220),
        ):
            mouth_region = overlay_service._resolve_mouth_region(rgba)

        self.assertIsNotNone(mouth_region)
        if mouth_region is not None:
            x1, y1, x2, y2 = mouth_region
            self.assertGreaterEqual(x1, 120)
            self.assertLessEqual(x2, 210)
            self.assertGreaterEqual(y1, 150)
            self.assertLessEqual(y2, 220)

    def test_mouth_region_fallback_without_face_detection(self):
        overlay_service = CharacterOverlayService()
        image = Image.new("RGBA", (220, 260), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (140, 180), (255, 255, 255, 255)), (30, 40))
        rgba = np.array(image, dtype=np.uint8)

        with patch.object(CharacterOverlayService, "_resolve_face_bbox", return_value=None):
            mouth_region = overlay_service._resolve_mouth_region(rgba)

        self.assertIsNotNone(mouth_region)
        if mouth_region is not None:
            x1, y1, x2, y2 = mouth_region
            self.assertGreater(x2, x1)
            self.assertGreater(y2, y1)

    def test_mouth_region_uses_manual_mapping_when_enabled(self):
        overlay_service = CharacterOverlayService()
        image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (140, 220), (255, 255, 255, 255)), (30, 40))
        rgba = np.array(image, dtype=np.uint8)
        params = VideoParams(
            video_subject="demo",
            character_manual_mapping_enabled=True,
            character_face_x=10.0,
            character_face_y=10.0,
            character_face_w=80.0,
            character_face_h=80.0,
            character_mouth_x=40.0,
            character_mouth_y=60.0,
            character_mouth_w=20.0,
            character_mouth_h=10.0,
        )

        mouth_region = overlay_service._resolve_mouth_region(rgba, params)

        self.assertEqual(mouth_region, (80, 180, 120, 210))

    def test_mouth_region_manual_mapping_is_clamped_to_face(self):
        overlay_service = CharacterOverlayService()
        image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (140, 220), (255, 255, 255, 255)), (30, 40))
        rgba = np.array(image, dtype=np.uint8)
        params = VideoParams(
            video_subject="demo",
            character_manual_mapping_enabled=True,
            character_face_x=20.0,
            character_face_y=20.0,
            character_face_w=30.0,
            character_face_h=30.0,
            character_mouth_x=90.0,
            character_mouth_y=90.0,
            character_mouth_w=30.0,
            character_mouth_h=30.0,
        )

        mouth_region = overlay_service._resolve_mouth_region(rgba, params)

        self.assertIsNotNone(mouth_region)
        if mouth_region is not None:
            x1, y1, x2, y2 = mouth_region
            self.assertGreaterEqual(x1, 40)
            self.assertGreaterEqual(y1, 60)
            self.assertLessEqual(x2, 100)
            self.assertLessEqual(y2, 150)

    def test_lipsync_openness_interpolates_smoothly(self):
        service = CharacterLipSyncService()
        timeline = [
            LipSyncFrame(start=0.0, end=0.1, openness=0.0),
            LipSyncFrame(start=0.1, end=0.2, openness=1.0),
        ]

        # Service applies a small visual lead for better perceived sync.
        mid = service.openness_at(timeline, 0.09)
        self.assertGreater(mid, 0.45)
        self.assertLess(mid, 0.55)

    def test_lipsync_handles_corrupted_audio_with_neutral_timeline(self):
        service = CharacterLipSyncService()
        with TemporaryDirectory() as temp_dir:
            broken_audio_path = Path(temp_dir) / "broken.mp3"
            broken_audio_path.write_bytes(b"not-audio")
            timeline = service.analyze(audio_path=str(broken_audio_path), duration=2.0)

        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0].start, 0.0)
        self.assertEqual(timeline[0].end, 2.0)
        self.assertEqual(timeline[0].openness, 0.0)

    def test_generate_video_includes_character_overlay_layer(self):
        composite_calls = []
        overlay_clip = FakeClip(duration=3.0, width=180, height=280, name="overlay")
        overlay_clip.mask = FakeClip(duration=3.0, width=180, height=280, name="overlay-mask")

        def fake_composite(clips, size=None):
            composite_calls.append((clips, size))
            return FakeClip(duration=3.0, width=(size or (1080, 1920))[0], height=(size or (1080, 1920))[1], name="composite")

        with TemporaryDirectory() as temp_dir:
            subtitle_path = Path(temp_dir) / "subtitle.srt"
            subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHola overlay\n", encoding="utf-8")

            params = VideoParams(
                video_subject="demo",
                video_aspect=VideoAspect.portrait.value,
                subtitle_enabled=True,
                character_overlay_enabled=True,
                character_image_file="/tmp/avatar.png",
                character_layer_order="behind_subtitles",
            )

            with patch.object(video_service, "_open_video_clip_quietly", return_value=FakeClip(duration=3.0, width=1080, height=1920, name="video")), patch.object(
                video_service,
                "AudioFileClip",
                side_effect=lambda *_args, **_kwargs: FakeClip(duration=3.0, width=0, height=0, name="audio"),
            ), patch.object(video_service, "CompositeAudioClip", side_effect=lambda clips: clips[0]), patch.object(
                video_service,
                "TextClip",
                side_effect=lambda *args, **kwargs: FakeClip(duration=1.0, width=800, height=120, name="subtitle"),
            ), patch.object(video_service, "SubtitlesClip", FakeSubtitlesClip), patch.object(
                video_service,
                "CompositeVideoClip",
                side_effect=fake_composite,
            ), patch.object(video_service, "get_bgm_file", return_value=""), patch.object(
                video_service.CharacterOverlayService,
                "create_overlay",
                return_value=CharacterOverlayResult(
                    clip=overlay_clip,
                    layout=CharacterOverlayLayout(x=780, y=1320, width=180, height=280, avoid_subtitles=True),
                ),
            ) as create_overlay_mock:
                video_service.generate_video(
                    video_path="/tmp/base.mp4",
                    audio_path="/tmp/audio.mp3",
                    subtitle_path=str(subtitle_path),
                    output_file=str(Path(temp_dir) / "final.mp4"),
                    params=params,
                )

        self.assertTrue(create_overlay_mock.called)
        self.assertTrue(composite_calls)
        visual_layers, size = composite_calls[0]
        self.assertEqual(size, (1080, 1920))
        self.assertEqual(len(visual_layers), 3)
        self.assertEqual(getattr(visual_layers[1], "name", ""), "overlay")

    def test_get_bgm_file_prefers_copyright_free_catalog(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            curated_dir = root / "copyright_free"
            legacy_dir = root / "legacy"
            curated_dir.mkdir(parents=True, exist_ok=True)
            legacy_dir.mkdir(parents=True, exist_ok=True)

            curated_track = curated_dir / "safe-track.mp3"
            legacy_track = legacy_dir / "legacy-track.mp3"
            curated_track.write_bytes(b"safe")
            legacy_track.write_bytes(b"legacy")

            with patch.object(
                video_service.utils,
                "song_dir",
                side_effect=lambda sub_dir="": str(curated_dir) if sub_dir == "copyright_free" else str(legacy_dir),
            ):
                selected = video_service.get_bgm_file(bgm_type="random", bgm_file="")

        self.assertEqual(selected, str(curated_track))

    def test_get_bgm_file_catalog_falls_back_to_legacy_directory(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            curated_dir = root / "copyright_free"
            legacy_dir = root / "legacy"
            curated_dir.mkdir(parents=True, exist_ok=True)
            legacy_dir.mkdir(parents=True, exist_ok=True)

            legacy_track = legacy_dir / "legacy-track.ogg"
            legacy_track.write_bytes(b"legacy")

            with patch.object(
                video_service.utils,
                "song_dir",
                side_effect=lambda sub_dir="": str(curated_dir) if sub_dir == "copyright_free" else str(legacy_dir),
            ):
                selected = video_service.get_bgm_file(bgm_type="catalog", bgm_file="")

        self.assertEqual(selected, str(legacy_track))


if __name__ == "__main__":
    unittest.main()