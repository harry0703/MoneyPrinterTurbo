import math
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import asset_embed


def _client_returning(values):
    """Fake genai.Client: context manager returning itself, like the real one."""
    embedding = MagicMock()
    embedding.values = values
    response = MagicMock()
    response.embeddings = [embedding]
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.embed_content.return_value = response
    return client


class TestAssetEmbed(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _enable(self):
        config.app["photo_library_enabled"] = True
        config.app["gemini_api_key"] = "test-key"

    # ---------------- disabled / no-op behavior ----------------

    def test_disabled_when_feature_off(self):
        config.app["photo_library_enabled"] = False
        config.app["gemini_api_key"] = "test-key"
        self.assertFalse(asset_embed.is_enabled())
        with patch.object(asset_embed, "_client") as client:
            self.assertIsNone(asset_embed.embed_text("кот на окне"))
        client.assert_not_called()

    def test_disabled_when_no_api_key(self):
        config.app["photo_library_enabled"] = True
        config.app.pop("gemini_api_key", None)
        self.assertFalse(asset_embed.is_enabled())
        with patch.object(asset_embed, "_client") as client:
            self.assertIsNone(asset_embed.embed_text("кот на окне"))
        client.assert_not_called()

    def test_blank_text_is_a_noop(self):
        self._enable()
        with patch.object(asset_embed, "_client") as client:
            self.assertIsNone(asset_embed.embed_text("   "))
        client.assert_not_called()

    # ---------------- happy path ----------------

    def test_returns_unit_vector_of_expected_dim(self):
        self._enable()
        config.app["photo_library_embed_model"] = "embed-test"
        # provider returns an unnormalized vector, as gemini-embedding-001 does
        # below 3072 dims
        raw = [0.02] * asset_embed.EMBEDDING_DIM
        client = _client_returning(raw)

        with patch.object(asset_embed, "_client", return_value=client):
            result = asset_embed.embed_text("  кот на окне  ")

        self.assertIsNotNone(result)
        self.assertEqual(len(result.vector), asset_embed.EMBEDDING_DIM)
        norm = math.sqrt(sum(v * v for v in result.vector))
        self.assertAlmostEqual(norm, 1.0, places=6)
        self.assertEqual(result.model, "embed-test")
        kwargs = client.models.embed_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "embed-test")
        self.assertEqual(kwargs["contents"], "кот на окне")
        self.assertEqual(
            kwargs["config"].output_dimensionality, asset_embed.EMBEDDING_DIM
        )

    def test_normalization_preserves_direction(self):
        self._enable()
        raw = [0.0] * asset_embed.EMBEDDING_DIM
        raw[0], raw[1] = 3.0, 4.0
        client = _client_returning(raw)
        with patch.object(asset_embed, "_client", return_value=client):
            result = asset_embed.embed_text("текст")
        self.assertAlmostEqual(result.vector[0], 0.6, places=6)
        self.assertAlmostEqual(result.vector[1], 0.8, places=6)

    # ---------------- degradation ----------------

    def test_wrong_dimension_returns_none(self):
        self._enable()
        client = _client_returning([0.1] * 512)
        with patch.object(asset_embed, "_client", return_value=client):
            self.assertIsNone(asset_embed.embed_text("текст"))

    def test_zero_vector_returns_none(self):
        self._enable()
        client = _client_returning([0.0] * asset_embed.EMBEDDING_DIM)
        with patch.object(asset_embed, "_client", return_value=client):
            self.assertIsNone(asset_embed.embed_text("текст"))

    def test_provider_error_does_not_raise(self):
        self._enable()
        client = MagicMock()
        client.__enter__.return_value = client
        client.models.embed_content.side_effect = RuntimeError("api down")
        with patch.object(asset_embed, "_client", return_value=client):
            self.assertIsNone(asset_embed.embed_text("текст"))

    def test_empty_embeddings_list_does_not_raise(self):
        self._enable()
        response = MagicMock()
        response.embeddings = []
        client = MagicMock()
        client.__enter__.return_value = client
        client.models.embed_content.return_value = response
        with patch.object(asset_embed, "_client", return_value=client):
            self.assertIsNone(asset_embed.embed_text("текст"))

    # ---------------- lazy SDK import ----------------

    def test_module_does_not_import_genai_at_module_level(self):
        source = Path(asset_embed.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            if line.startswith(("import ", "from ")):
                self.assertNotIn("google", line)


if __name__ == "__main__":
    unittest.main()
