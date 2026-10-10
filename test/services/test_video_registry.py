import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services.providers.base import (
    GeneratedVideoProvider,
    ProviderError,
    VideoProviderRegistry,
    build_video_registry,
)


class _FakeVideoProvider(GeneratedVideoProvider):
    name = "fakevid"

    def is_available(self) -> bool:
        return True

    def generate_video(self, shot, context) -> str:
        return "x"


class _DownVideoProvider(GeneratedVideoProvider):
    name = "downvid"

    def is_available(self) -> bool:
        return False

    def generate_video(self, shot, context) -> str:
        raise AssertionError("must not be called when unavailable")


class TestVideoProviderRegistry(unittest.TestCase):
    def test_register_get_and_names(self):
        provider = _FakeVideoProvider()
        registry = VideoProviderRegistry([provider, _DownVideoProvider()])
        self.assertEqual(registry.names(), ["downvid", "fakevid"])
        self.assertIs(registry.get("fakevid"), provider)
        self.assertTrue(registry.is_available("fakevid"))
        self.assertFalse(registry.is_available("downvid"))

    def test_empty_registry(self):
        registry = VideoProviderRegistry()
        self.assertEqual(registry.names(), [])

    def test_unknown_provider_raises(self):
        registry = VideoProviderRegistry()
        with self.assertRaises(ProviderError):
            registry.get("nope")


class TestBuildVideoRegistry(unittest.TestCase):
    def setUp(self):
        self._saved = dict(config.kling)
        config.kling.clear()

    def tearDown(self):
        config.kling.clear()
        config.kling.update(self._saved)

    def test_kling_registered_when_enabled_with_keys(self):
        config.kling.update(
            {"enabled": True, "access_key": "ak", "secret_key": "sk"}
        )
        registry = build_video_registry()
        self.assertEqual(registry.names(), ["kling"])
        self.assertTrue(registry.is_available("kling"))

    def test_kling_skipped_when_disabled(self):
        config.kling.update(
            {"enabled": False, "access_key": "ak", "secret_key": "sk"}
        )
        self.assertEqual(build_video_registry().names(), [])

    def test_kling_skipped_without_keys(self):
        config.kling.update(
            {"enabled": True, "access_key": "", "secret_key": ""}
        )
        self.assertEqual(build_video_registry().names(), [])


if __name__ == "__main__":
    unittest.main()
