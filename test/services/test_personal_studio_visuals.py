# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.services.personal_studio import compose, visuals
from test.services._personal_studio_helpers import make_speechlike_wav


def make_portrait(path: Path) -> Path:
    image = Image.new("RGB", (600, 800), (230, 228, 224))
    draw = ImageDraw.Draw(image)
    draw.ellipse((180, 120, 420, 480), fill=(222, 174, 140))
    draw.ellipse((250, 250, 280, 282), fill=(50, 40, 36))
    draw.ellipse((320, 250, 350, 282), fill=(50, 40, 36))
    draw.arc((250, 340, 350, 420), 0, 180, fill=(120, 60, 50), width=5)
    image.save(path, format="PNG")
    return path


class TestFrames(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.portrait = make_portrait(self.root / "portrait.png")

    def tearDown(self):
        self.temp.cleanup()

    def test_presenter_frame_has_requested_size(self):
        renderer = visuals.PresenterFrames(
            self.portrait, size=(180, 320), fps=10, scene="estudio",
            face_normalized=[0.28, 0.15, 0.4, 0.45],
        )
        closed = renderer.frame(1.0, 0.0)
        open_mouth = renderer.frame(1.0, 0.9)
        self.assertEqual(closed.size, (180, 320))
        self.assertEqual(open_mouth.size, (180, 320))
        self.assertNotEqual(closed.tobytes(), open_mouth.tobytes())

    def test_cartoon_frame_uses_existing_engine(self):
        renderer = visuals.CartoonFrames(
            size=(180, 320), palette={"blue": "#4A90D9", "yellow": "#FFD24A"},
            scene="jardin",
        )
        frame = renderer.frame(0.5, 0.7)
        self.assertEqual(frame.size, (180, 320))

    def test_hybrid_places_presenter_beside_slides(self):
        slide = Image.new("RGB", (400, 300), (10, 120, 80))
        slide_path = self.root / "slide.png"
        slide.save(slide_path)
        renderer = visuals.PresenterFrames(
            self.portrait, size=(200, 320), fps=10, scene="estudio",
            face_normalized=[0.28, 0.15, 0.4, 0.45], side_slides=[slide_path],
        )
        renderer.duration = 5.0
        frame = renderer.frame(1.0, 0.4)
        self.assertEqual(frame.size, (200, 320))
        # La mitad izquierda pertenece a la diapositiva verde.
        pixel = frame.getpixel((10, 160))
        self.assertGreater(pixel[1], pixel[0])


class TestSubtitles(unittest.TestCase):
    def test_ass_document_escapes_and_times(self):
        document = compose.ass_document(
            [("Hola {mundo}", 1.0), ("Segunda línea", 2.0)], width=720, height=1280
        )
        self.assertIn("[Events]", document)
        self.assertIn("Hola (mundo)", document)
        self.assertIn("0:00:00.00,0:00:01.00", document)

    def test_srt_document_formats_milliseconds(self):
        document = compose.srt_document([("Primera", 1.5), ("Segunda", 0.5)])
        self.assertIn("00:00:00,000 --> 00:00:01,500", document)
        self.assertIn("2\n00:00:01,500", document)


class TestRenderAndCompose(unittest.TestCase):
    def test_render_and_finalize_small_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portrait = make_portrait(root / "portrait.png")
            audio = make_speechlike_wav(root / "audio.wav", seconds=1.2)
            silent = root / "silent.mp4"
            visuals.render_presenter(
                portrait_path=portrait,
                audio_path=audio,
                destination=silent,
                size=(120, 160),
                output_size=(120, 160),
                fps=10,
                scene="estudio",
                face_normalized=[0.28, 0.15, 0.4, 0.45],
                crf=28,
                preset="veryfast",
            )
            self.assertTrue(silent.is_file())
            final = root / "final.mp4"
            compose.finalize(
                silent,
                audio,
                final,
                events=[("Hola BYNEX", 1.2)],
                width=120,
                height=160,
                crf=28,
            )
            self.assertTrue(final.is_file())
            self.assertGreater(final.stat().st_size, 1000)
            srt = compose.write_subtitles(
                [("Hola BYNEX", 1.2)], root / "subs.srt", width=120, height=160
            )
            self.assertIn("Hola BYNEX", srt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
