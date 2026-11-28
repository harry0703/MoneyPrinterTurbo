# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from app.services.personal_studio.security import ConsentError, StudioError
from app.services.personal_studio.voice_profiles import VoiceStore
from test.services._personal_studio_helpers import VOICE_CONSENT, make_speechlike_wav


class TestVoiceStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = VoiceStore(self.root)
        self.profile = self.store.create(name="Voz BYNEX", consent=VOICE_CONSENT)
        self.audio_file = make_speechlike_wav(self.root / "muestra.wav", seconds=9)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_requires_consent_and_valid_name(self):
        with self.assertRaises(ConsentError):
            self.store.create(name="Sin permiso", consent={"subject_name": "X"})
        with self.assertRaises(StudioError):
            self.store.create(name="A", consent=VOICE_CONSENT)
        self.assertEqual(self.store.get(self.profile["id"])["status"], "draft")

    def test_add_sample_analyzes_and_cleans(self):
        sample = self.store.add_sample(
            self.profile["id"], "mi voz.wav", self.audio_file.read_bytes()
        )
        self.assertGreater(sample["raw"]["duration"], 6)
        self.assertTrue(sample["raw"]["issues"] == [] or isinstance(sample["raw"]["issues"], list))
        clean = self.store.profile_dir(self.profile["id"]) / sample["clean_file"]
        self.assertTrue(clean.is_file())
        self.assertGreaterEqual(sample["clean"]["score"], 35)

    def test_process_builds_reference_and_approve(self):
        self.store.add_sample(self.profile["id"], "voz.wav", self.audio_file.read_bytes())
        processed = self.store.process(self.profile["id"])
        self.assertTrue(self.store.reference(self.profile["id"]).is_file())
        self.assertGreater(processed["duration"], 3)
        self.assertEqual(self.store.get(self.profile["id"])["status"], "ready")
        approved = self.store.approve(self.profile["id"])
        self.assertTrue(approved["approved"])

    def test_process_without_samples_fails(self):
        with self.assertRaises(StudioError):
            self.store.process(self.profile["id"])

    def test_adding_sample_after_approval_resets_it(self):
        self.store.add_sample(self.profile["id"], "voz.wav", self.audio_file.read_bytes())
        self.store.process(self.profile["id"])
        self.store.approve(self.profile["id"])
        second = make_speechlike_wav(self.root / "segunda.wav", seconds=7)
        self.store.add_sample(self.profile["id"], "segunda.wav", second.read_bytes())
        profile = self.store.get(self.profile["id"])
        self.assertFalse(profile["approved"])
        self.assertIsNone(profile["processed"])

    def test_remove_deletes_every_file(self):
        self.store.add_sample(self.profile["id"], "voz.wav", self.audio_file.read_bytes())
        directory = self.store.profile_dir(self.profile["id"])
        self.store.remove(self.profile["id"])
        self.assertFalse(directory.exists())
        self.assertEqual(self.store.list(), [])

    def test_list_sorted_and_update(self):
        second = self.store.create(name="Otra voz", consent=VOICE_CONSENT)
        updated = self.store.update(second["id"], name="Voz editada")
        self.assertEqual(updated["name"], "Voz editada")
        self.assertEqual(len(self.store.list()), 2)


if __name__ == "__main__":
    unittest.main()
