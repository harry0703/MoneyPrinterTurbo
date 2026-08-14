import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PIL import Image

from app.services import photo_library


def _write_photos(root: str, relative_names: list[str]) -> None:
    for name in relative_names:
        file_path = os.path.join(root, name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        Image.new("RGB", (32, 20), (10, 200, 10)).save(file_path)


class TestPhotoFileListing(unittest.TestCase):
    def test_missing_dir_returns_empty_list(self):
        self.assertEqual(photo_library.list_photo_files("/does/not/exist"), [])
        self.assertEqual(photo_library.list_photo_files(""), [])

    def test_subdirectories_are_included_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(tmp_dir, ["b.jpg", os.path.join("sub", "a.png")])
            with open(os.path.join(tmp_dir, "notes.txt"), "w") as handle:
                handle.write("not a photo")

            files = photo_library.list_photo_files(tmp_dir)

        self.assertEqual([os.path.basename(f) for f in files], ["b.jpg", "a.png"])


class TestThemeDiscovery(unittest.TestCase):
    def test_numeric_prefixes_are_not_the_theme(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(
                tmp_dir, ["10-film-00.jpg", "10-film-01.jpg", "20-spider.jpg"]
            )
            themes = photo_library.discover_photo_themes(tmp_dir)

        self.assertEqual([theme.name for theme in themes], ["film", "spider"])
        self.assertEqual(len(themes[0].files), 2)

    def test_subdirectories_win_over_file_names(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(
                tmp_dir,
                [
                    os.path.join("spiderman", "20-spider-00.jpg"),
                    os.path.join("faces", "30-harlamov.jpg"),
                ],
            )
            themes = photo_library.discover_photo_themes(tmp_dir)

        self.assertEqual(sorted(theme.name for theme in themes), ["faces", "spiderman"])

    def test_manifest_supplies_descriptions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(tmp_dir, ["10-film-00.jpg"])
            with open(
                os.path.join(tmp_dir, photo_library.THEMES_MANIFEST),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"Film": "movie stills"}, handle)

            themes = photo_library.discover_photo_themes(tmp_dir)

        self.assertEqual(themes[0].description, "movie stills")

    def test_broken_manifest_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(tmp_dir, ["10-film-00.jpg"])
            with open(
                os.path.join(tmp_dir, photo_library.THEMES_MANIFEST),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("{not json")

            themes = photo_library.discover_photo_themes(tmp_dir)

        self.assertEqual(themes[0].description, "")

    def test_digits_only_names_land_in_one_theme(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(tmp_dir, ["01.jpg", "02.jpg"])
            themes = photo_library.discover_photo_themes(tmp_dir)

        self.assertEqual([theme.name for theme in themes], ["misc"])
        self.assertEqual(len(themes[0].files), 2)

    def test_empty_dir_has_no_themes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertEqual(photo_library.discover_photo_themes(tmp_dir), [])

    def test_samples_are_basenames(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_photos(tmp_dir, [f"10-film-{i:02d}.jpg" for i in range(5)])
            themes = photo_library.discover_photo_themes(tmp_dir)

        self.assertEqual(themes[0].samples(2), ["10-film-00.jpg", "10-film-01.jpg"])


class TestThemedPhotoPicker(unittest.TestCase):
    def setUp(self):
        self.themes = [
            photo_library.PhotoTheme(name="film", files=["a.jpg", "b.jpg"]),
            photo_library.PhotoTheme(name="actor", files=["c.jpg"]),
        ]
        self.picker = photo_library.ThemedPhotoPicker(self.themes)

    def test_photos_are_handed_out_in_order(self):
        self.assertEqual(self.picker.take("film"), "a.jpg")
        self.assertEqual(self.picker.take("film"), "b.jpg")

    def test_exhausted_pool_wraps_around(self):
        self.assertEqual(self.picker.take("actor"), "c.jpg")
        self.assertEqual(self.picker.take("actor"), "c.jpg")

    def test_themes_do_not_share_a_cursor(self):
        self.picker.take("film")
        self.assertEqual(self.picker.take("actor"), "c.jpg")
        self.assertEqual(self.picker.take("film"), "b.jpg")

    def test_unknown_theme_returns_nothing(self):
        self.assertIsNone(self.picker.take("nothing"))

    def test_theme_lookup_is_case_insensitive(self):
        self.assertEqual(self.picker.take(" FILM "), "a.jpg")


if __name__ == "__main__":
    unittest.main()
