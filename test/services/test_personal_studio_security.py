# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from app.services.personal_studio.security import (
    ConsentError,
    StudioError,
    atomic_json,
    build_consent,
    confined_path,
    delete_tree,
    read_json,
    require_consent,
)


class TestConsent(unittest.TestCase):
    def test_builds_and_verifies_signature(self):
        consent = build_consent(
            {
                "subject_name": "Nelson Julio",
                "granted": True,
                "age_confirmed": True,
                "scope": ["voz"],
            },
            scope=("voz",),
        )
        self.assertEqual(consent["scope"], ["voz"])
        self.assertEqual(len(consent["signature"]), 64)
        self.assertIs(require_consent(consent, ("voz",)), consent)

    def test_tampered_consent_is_rejected(self):
        consent = build_consent(
            {"subject_name": "Nelson Julio", "granted": True, "age_confirmed": True},
            scope=("imagen",),
        )
        consent["subject_name"] = "Otra persona"
        with self.assertRaises(ConsentError):
            require_consent(consent, ("imagen",))

    def test_scope_must_cover_request(self):
        consent = build_consent(
            {"subject_name": "Nelson Julio", "granted": True, "age_confirmed": True},
            scope=("voz",),
        )
        with self.assertRaises(ConsentError):
            require_consent(consent, ("imagen",))

    def test_minor_requires_guardian(self):
        with self.assertRaises(ConsentError):
            build_consent(
                {
                    "subject_name": "Menor Autorizado",
                    "granted": True,
                    "age_confirmed": True,
                    "is_minor": True,
                },
                scope=("voz",),
            )

    def test_requires_explicit_grant_and_age(self):
        with self.assertRaises(ConsentError):
            build_consent({"subject_name": "Nelson Julio", "age_confirmed": True}, scope=("voz",))
        with self.assertRaises(ConsentError):
            build_consent({"subject_name": "Nelson Julio", "granted": True}, scope=("voz",))


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "voices" / "v_test").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_confined_path_rejects_traversal(self):
        with self.assertRaises(StudioError):
            confined_path(self.root / "voices", "..", "secreto.txt")
        with self.assertRaises(StudioError):
            confined_path(self.root / "voices", "v_test", "..", "..", "x")

    def test_delete_tree_removes_only_the_profile(self):
        keep = self.root / "voices" / "v_keep"
        keep.mkdir()
        delete_tree(self.root / "voices", "v_test")
        self.assertFalse((self.root / "voices" / "v_test").exists())
        self.assertTrue(keep.exists())

    def test_atomic_json_roundtrip(self):
        path = self.root / "meta.json"
        atomic_json(path, {"a": 1, "texto": "ñ"})
        self.assertEqual(read_json(path)["texto"], "ñ")


if __name__ == "__main__":
    unittest.main()
