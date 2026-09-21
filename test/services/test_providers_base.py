import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.providers.base import (
    MaterialProvider,
    ProviderError,
    ProviderRegistry,
    build_registry,
)


class _FakeProvider(MaterialProvider):
    def __init__(self, name: str = "fake", available: bool = True, raises: bool = False):
        self.name = name
        self._available = available
        self._raises = raises

    def is_available(self) -> bool:
        if self._raises:
            raise RuntimeError("probe exploded")
        return self._available


class TestProviderRegistry(unittest.TestCase):
    def test_register_and_get(self):
        provider = _FakeProvider("alpha")
        registry = ProviderRegistry([provider])
        self.assertIs(registry.get("alpha"), provider)

    def test_get_unknown_provider_raises(self):
        registry = ProviderRegistry()
        with self.assertRaises(ProviderError):
            registry.get("missing")

    def test_names_sorted(self):
        registry = ProviderRegistry([_FakeProvider("zeta"), _FakeProvider("alpha")])
        self.assertEqual(registry.names(), ["alpha", "zeta"])

    def test_is_available_true(self):
        registry = ProviderRegistry([_FakeProvider("ok", available=True)])
        self.assertTrue(registry.is_available("ok"))

    def test_is_available_false(self):
        registry = ProviderRegistry([_FakeProvider("off", available=False)])
        self.assertFalse(registry.is_available("off"))

    def test_is_available_swallows_probe_exceptions(self):
        registry = ProviderRegistry([_FakeProvider("bad", raises=True)])
        self.assertFalse(registry.is_available("bad"))

    def test_register_replaces_same_name(self):
        first = _FakeProvider("x")
        second = _FakeProvider("x")
        registry = ProviderRegistry([first])
        registry.register(second)
        self.assertIs(registry.get("x"), second)

    def test_build_registry_empty_by_default(self):
        registry = build_registry()
        self.assertIsInstance(registry, ProviderRegistry)
        self.assertEqual(registry.names(), [])


if __name__ == "__main__":
    unittest.main()
