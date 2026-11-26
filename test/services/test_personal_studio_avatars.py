# -*- coding: utf-8 -*-
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.services.personal_studio.avatars import AvatarStore, detect_face
from app.services.personal_studio.security import ConsentError, StudioError
from test.services._personal_studio_helpers import IMAGE_CONSENT


def portrait_bytes(width: int = 760, height: int = 980) -> bytes:
    image = Image.new("RGB", (width, height), (238, 236, 232))
    draw = ImageDraw.Draw(image)
    draw.ellipse((230, 180, 530, 620), fill=(224, 176, 140))
    draw.ellipse((330, 330, 370, 370), fill=(60, 45, 40))
    draw.ellipse((390, 330, 430, 370), fill=(60, 45, 40))
    if height > 640:
        draw.rectangle((180, 620, 580, height), fill=(40, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TestAvatarStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = AvatarStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_detects_face_box_inside_image(self):
        image = Image.open(io.BytesIO(portrait_bytes()))
        face = detect_face(image)
        self.assertIn(face["source"], {"skin-heuristic", "opencv"})
        self.assertIsNotNone(face["box"])
        x, y, w, h = face["box"]
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, image.width)
        self.assertLessEqual(y + h, image.height)

    def test_create_avatar_generates_derived_files(self):
        avatar = self.store.create(
            name="Avatar BYNEX",
            style="realista",
            consent=IMAGE_CONSENT,
            filename="foto.png",
            payload=portrait_bytes(),
        )
        self.assertEqual(avatar["engine"], "photo")
        self.assertTrue(self.store.image(avatar["id"], "portrait").is_file())
        self.assertTrue(self.store.image(avatar["id"], "thumb").is_file())
        self.assertIn("palette", avatar["cartoon"])
        self.assertGreater(avatar["image"]["score"], 0)

    def test_cartoon_style_marks_cartoon_engine(self):
        avatar = self.store.create(
            name="Caricatura",
            style="caricatura",
            consent=IMAGE_CONSENT,
            filename="foto.png",
            payload=portrait_bytes(),
        )
        self.assertEqual(avatar["engine"], "cartoon")

    def test_rejects_small_images_and_bad_payload(self):
        with self.assertRaises(StudioError):
            self.store.create(
                name="Pequeña",
                style="realista",
                consent=IMAGE_CONSENT,
                filename="foto.png",
                payload=portrait_bytes(300, 300),
            )
        with self.assertRaises(StudioError):
            self.store.create(
                name="Rota",
                style="realista",
                consent=IMAGE_CONSENT,
                filename="foto.png",
                payload=b"no es una imagen",
            )

    def test_requires_image_consent(self):
        with self.assertRaises(ConsentError):
            self.store.create(
                name="Sin permiso",
                style="realista",
                consent={"subject_name": "X", "granted": True, "age_confirmed": True, "scope": ["voz"]},
                filename="foto.png",
                payload=portrait_bytes(),
            )

    def test_preview_and_delete(self):
        avatar = self.store.create(
            name="Avatar",
            style="presentador",
            consent=IMAGE_CONSENT,
            filename="foto.png",
            payload=portrait_bytes(),
        )
        preview = self.store.preview(avatar["id"], self.root / "preview.png")
        self.assertTrue(preview.is_file())
        directory = self.store.avatar_dir(avatar["id"])
        self.store.remove(avatar["id"])
        self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
