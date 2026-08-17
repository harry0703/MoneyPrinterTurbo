import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PIL import Image

from app.config import config
from app.services import asset_vision

GOOD_RESPONSE = {
    "caption": "Красная плашка с надписью на тёмном фоне.",
    "tags": [
        {"name": "распродажа", "weight": 0.9},
        {"name": "  ", "weight": 0.5},
        {"name": "графика", "weight": 1.7},
    ],
    "has_text": True,
    "min_display": 3.0,
}


def _client_returning(text):
    """Fake genai.Client: context manager returning itself, like the real one."""
    response = MagicMock()
    response.text = text
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.generate_content.return_value = response
    return client


class TestAssetVision(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.tmp = tempfile.TemporaryDirectory()
        self.image_path = str(Path(self.tmp.name) / "asset.png")
        Image.new("RGB", (64, 40), (200, 30, 30)).save(self.image_path)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self.tmp.cleanup()

    def _enable(self):
        config.app["photo_library_enabled"] = True
        config.app["gemini_api_key"] = "test-key"

    # ---------------- disabled / no-op behavior ----------------

    def test_disabled_when_feature_off(self):
        config.app["photo_library_enabled"] = False
        config.app["gemini_api_key"] = "test-key"
        self.assertFalse(asset_vision.is_enabled())
        with patch.object(asset_vision, "_client") as client:
            self.assertIsNone(asset_vision.annotate_image(self.image_path))
        client.assert_not_called()

    def test_disabled_when_no_api_key(self):
        config.app["photo_library_enabled"] = True
        config.app.pop("gemini_api_key", None)
        self.assertFalse(asset_vision.is_enabled())
        with patch.object(asset_vision, "_client") as client:
            self.assertIsNone(asset_vision.annotate_image(self.image_path))
        client.assert_not_called()

    # ---------------- happy path ----------------

    def test_parses_model_response(self):
        self._enable()
        config.app["photo_library_vision_model"] = "gemini-test"
        client = _client_returning(json.dumps(GOOD_RESPONSE))

        with patch.object(asset_vision, "_client", return_value=client):
            result = asset_vision.annotate_image(self.image_path)

        self.assertIsNotNone(result)
        self.assertEqual(result.caption, "Красная плашка с надписью на тёмном фоне.")
        self.assertTrue(result.has_text)
        self.assertEqual(result.min_display, 3.0)
        self.assertEqual(result.model, "gemini-test")
        # blank tag names dropped, weights clamped into 0..1
        self.assertEqual(result.tags, {"распродажа": 0.9, "графика": 1.0})
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["model"], "gemini-test"
        )

    def test_min_display_is_clamped(self):
        self._enable()
        payload = dict(GOOD_RESPONSE, min_display=99.0)
        client = _client_returning(json.dumps(payload))
        with patch.object(asset_vision, "_client", return_value=client):
            result = asset_vision.annotate_image(self.image_path)
        self.assertEqual(result.min_display, asset_vision.MIN_DISPLAY_CEIL)

        payload = dict(GOOD_RESPONSE, min_display=0.0)
        client = _client_returning(json.dumps(payload))
        with patch.object(asset_vision, "_client", return_value=client):
            result = asset_vision.annotate_image(self.image_path)
        self.assertEqual(result.min_display, asset_vision.MIN_DISPLAY_FLOOR)

    def test_sends_image_bytes_with_guessed_mime_type(self):
        self._enable()
        client = _client_returning(json.dumps(GOOD_RESPONSE))
        with patch.object(asset_vision, "_client", return_value=client):
            asset_vision.annotate_image(self.image_path)
        part = client.models.generate_content.call_args.kwargs["contents"][0]
        self.assertEqual(part.inline_data.mime_type, "image/png")
        self.assertEqual(part.inline_data.data, Path(self.image_path).read_bytes())

    # ---------------- degradation ----------------

    def test_returns_none_on_garbage_response(self):
        self._enable()
        client = _client_returning("not json at all")
        with patch.object(asset_vision, "_client", return_value=client):
            self.assertIsNone(asset_vision.annotate_image(self.image_path))

    def test_returns_none_on_missing_fields(self):
        self._enable()
        client = _client_returning(json.dumps({"caption": "только капшен"}))
        with patch.object(asset_vision, "_client", return_value=client):
            self.assertIsNone(asset_vision.annotate_image(self.image_path))

    def test_returns_none_on_empty_caption(self):
        self._enable()
        client = _client_returning(json.dumps(dict(GOOD_RESPONSE, caption="   ")))
        with patch.object(asset_vision, "_client", return_value=client):
            self.assertIsNone(asset_vision.annotate_image(self.image_path))

    def test_provider_error_does_not_raise(self):
        self._enable()
        client = MagicMock()
        client.__enter__.return_value = client
        client.models.generate_content.side_effect = RuntimeError("api down")
        with patch.object(asset_vision, "_client", return_value=client):
            self.assertIsNone(asset_vision.annotate_image(self.image_path))

    def test_missing_file_does_not_raise(self):
        self._enable()
        missing = str(Path(self.tmp.name) / "nope.png")
        with patch.object(asset_vision, "_client", return_value=MagicMock()):
            self.assertIsNone(asset_vision.annotate_image(missing))

    def test_non_image_file_is_skipped_before_the_api_call(self):
        self._enable()
        text_file = Path(self.tmp.name) / "notes.txt"
        text_file.write_text("not a photo", encoding="utf-8")
        with patch.object(asset_vision, "_client") as client:
            self.assertIsNone(asset_vision.annotate_image(str(text_file)))
        client.assert_not_called()

    # ---------------- lazy SDK import ----------------

    def test_module_does_not_import_genai_at_module_level(self):
        source = Path(asset_vision.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            if line.startswith(("import ", "from ")):
                self.assertNotIn("google", line)


if __name__ == "__main__":
    unittest.main()
