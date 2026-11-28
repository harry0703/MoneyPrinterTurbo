# -*- coding: utf-8 -*-
import tempfile
import time
import unittest
from pathlib import Path

from app.services.personal_studio import jobs, social, studio
from app.services.personal_studio.security import StudioError


def project_payload(**overrides):
    payload = {
        "name": "Presentador BYNEX",
        "description": "Prueba",
        "topic": "Soporte técnico",
        "script": "Bienvenidos a BYNEX. Hoy hablamos de soporte técnico.",
        "keywords": ["soporte", "tecnología"],
        "mode": "presentador",
        "platform": "instagram_reels",
        "quality": "economico",
        "aspect": "9:16",
        "fps": 20,
        "subtitles": True,
    }
    payload.update(overrides)
    return payload


class TestProjectValidation(unittest.TestCase):
    def test_output_size_respects_quality_and_aspect(self):
        size = studio.output_size(
            {"quality": "economico", "aspect": "9:16", "platform": "tiktok"}
        )
        self.assertEqual(size, (270, 480))
        square = studio.output_size(
            {"quality": "equilibrado", "aspect": "1:1", "platform": "whatsapp"}
        )
        self.assertEqual(square[0], square[1])

    def test_rejects_unknown_fields_and_bad_values(self):
        with self.assertRaises(StudioError):
            studio.normalize_project(project_payload(api_key="secreto"))
        with self.assertRaises(StudioError):
            studio.normalize_project(project_payload(fps=99))
        with self.assertRaises(StudioError):
            studio.normalize_project(project_payload(name=""))
        with self.assertRaises(StudioError):
            studio.normalize_project(project_payload(mode="inexistente"))

    def test_keywords_accept_comma_text(self):
        data = studio.normalize_project(project_payload(keywords="uno, dos, uno"))
        self.assertEqual(data["keywords"], ["uno", "dos"])

    def test_partial_update_only_changes_given_fields(self):
        data = studio.normalize_project({"name": "Solo nombre"}, partial=True)
        self.assertEqual(data, {"name": "Solo nombre"})


class TestProjectStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = studio.ProjectStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_update_delete(self):
        project = self.store.create(project_payload())
        self.assertEqual(project["state"], "draft")
        self.assertTrue((self.store.project_dir(project["id"]) / "assets").is_dir())
        updated = self.store.update(project["id"], {"script": "Nuevo guion."})
        self.assertEqual(updated["script"], "Nuevo guion.")
        self.assertEqual(len(self.store.list()), 1)
        self.store.delete(project["id"])
        self.assertEqual(self.store.list(), [])

    def test_update_keeps_assets_reference(self):
        project = self.store.create(project_payload())
        self.store.add_asset(project["id"], "music", "tema.mp3", b"ID3fake")
        self.assertIn("music", self.store.get(project["id"]))
        assets = sorted(p.name for p in (self.store.project_dir(project["id"]) / "assets").iterdir())
        self.assertEqual(len(assets), 1)
        path = self.store.asset_path(project["id"], assets[0])
        self.assertTrue(path.is_file())

    def test_asset_type_and_traversal_are_rejected(self):
        project = self.store.create(project_payload())
        with self.assertRaises(StudioError):
            self.store.add_asset(project["id"], "image", "script.exe", b"MZ")
        with self.assertRaises(StudioError):
            self.store.asset_path(project["id"], "../project.json")

    def test_fingerprint_changes_with_content(self):
        project = self.store.create(project_payload())
        before = studio.fingerprint(project)
        changed = {**project, "script": "Otro guion completamente distinto."}
        self.assertNotEqual(before, studio.fingerprint(changed))

    def test_approval_requires_render_and_export_requires_approval(self):
        project = self.store.create(project_payload())
        with self.assertRaises(StudioError):
            studio.approve(
                project["id"], reviewer="Nelson", decision="approve", store=self.store
            )
        with self.assertRaises(StudioError):
            studio.export(project["id"], store=self.store)

    def test_approval_state_is_stale_after_change(self):
        project = self.store.create(project_payload())
        project["state"] = "rendered"
        project["narration"] = {"sha256": "a" * 64}
        project["render"] = {"sha256": "b" * 64}
        self.store._save(project)
        studio.approve(project["id"], reviewer="Nelson", decision="approve", store=self.store)
        self.assertTrue(studio.approval_state(self.store.get(project["id"]))["approved"])
        self.store.update(project["id"], {"script": "Guion nuevo."})
        state = studio.approval_state(self.store.get(project["id"]))
        self.assertFalse(state["approved"])


class TestSocialMetadata(unittest.TestCase):
    def test_title_and_hashtag_limits(self):
        metadata = social.build_metadata(
            project={
                "name": "Un título muy largo " * 10,
                "description": "Resumen",
                "keywords": ["IA", "#Soporte", "con espacios", "inválido!"],
            },
            platform="tiktok",
            duration=30,
        )
        self.assertLessEqual(len(metadata["title"]), PLATFORM_TITLE_LIMIT)
        self.assertTrue(metadata["hashtags"])
        self.assertTrue(all(tag.startswith("#") for tag in metadata["hashtags"]))
        self.assertEqual(metadata["auto_publish"], False)
        self.assertIn("inteligencia artificial", metadata["ai_disclosure"])

    def test_long_duration_warns(self):
        metadata = social.build_metadata(
            project={"name": "Largo"},
            platform="instagram_stories",
            duration=120,
        )
        self.assertTrue(metadata["warnings"])
        self.assertTrue(metadata["synthetic_media"])


PLATFORM_TITLE_LIMIT = 100


class TestJobQueue(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = studio.ProjectStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_job_completes_and_persists(self):
        project = self.store.create(project_payload())

        def fake_build(project_id, *, store, progress, cancel):
            progress("narracion", 0.5)
            time.sleep(0.05)
            return {"warnings": ["aviso de prueba"]}

        manager = jobs.StudioJobManager(self.root, build=fake_build)
        try:
            job = manager.submit(project["id"])
            done = manager.wait(job["id"], timeout=10)
            self.assertEqual(done["state"], jobs.COMPLETED)
            self.assertEqual(done["warnings"], ["aviso de prueba"])
            self.assertTrue((self.root / "jobs.json").is_file())
        finally:
            manager.shutdown()

    def test_cancel_marks_job_cancelled(self):
        project = self.store.create(project_payload())

        def slow_build(project_id, *, store, progress, cancel):
            for _ in range(200):
                if cancel():
                    raise StudioError("cancelado")
                time.sleep(0.02)
            return {}

        manager = jobs.StudioJobManager(self.root, build=slow_build)
        try:
            job = manager.submit(project["id"])
            time.sleep(0.1)
            manager.cancel(job["id"])
            done = manager.wait(job["id"], timeout=10)
            self.assertEqual(done["state"], jobs.CANCELLED)
        finally:
            manager.shutdown()

    def test_duplicate_submit_returns_active_job(self):
        project = self.store.create(project_payload())

        def slow_build(project_id, *, store, progress, cancel):
            time.sleep(0.4)
            return {}

        manager = jobs.StudioJobManager(self.root, build=slow_build)
        try:
            first = manager.submit(project["id"])
            second = manager.submit(project["id"])
            self.assertEqual(first["id"], second["id"])
        finally:
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
