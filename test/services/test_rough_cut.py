import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.creative import ShotPlan, ShotPlanItem
from app.services import creative_segments
from app.services import rough_cut
from app.services.providers.base import ProviderRegistry


class _FakeImageProvider:
    name = "fakegen"

    def is_available(self):
        return True

    def generate(self, shot, context):
        output_dir = context["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"gen_{shot.index:03d}.png")
        Image.new("RGB", (320, 180), (20, 120, 40)).save(path)
        return [path]


class _FailingImageProvider:
    name = "fakefail"

    def is_available(self):
        return True

    def generate(self, shot, context):
        return []


class RoughCutTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = os.path.join(self._tmp.name, "tasks", "task-1")
        os.makedirs(self.task_dir, exist_ok=True)
        self._patcher = patch(
            "app.services.rough_cut.utils.task_dir",
            return_value=self.task_dir,
        )
        self._patcher.start()
        self._creative_backup = dict(config.creative)

    def tearDown(self):
        self._patcher.stop()
        config.creative.clear()
        config.creative.update(self._creative_backup)
        self._tmp.cleanup()
        shutil.rmtree(self._tmp.name, ignore_errors=True)

    def _image(self, name, color=(120, 60, 30), size=(320, 180)):
        path = os.path.join(self.task_dir, name)
        Image.new("RGB", size, color).save(path)
        return path

    def _shots(self):
        return [
            {
                "index": 1,
                "source": "generated_image",
                "asset_path": self._image("shot1.png"),
                "provider": "fakegen",
                "prompt": "p1",
                "query": "",
                "duration": 1.0,
            },
            {
                "index": 2,
                "source": "generated_image",
                "asset_path": self._image("shot2.png", (40, 120, 160)),
                "provider": "fakegen",
                "prompt": "p2",
                "query": "",
                "duration": 1.0,
            },
        ]


class TestBuildRoughCut(RoughCutTestCase):
    def test_build_writes_video_and_timeline(self):
        timeline = rough_cut.build_rough_cut(
            "task-1", self._shots(), params={"video_aspect": "16:9"}
        )
        self.assertTrue(os.path.isfile(rough_cut.video_path("task-1")))
        self.assertTrue(os.path.isfile(rough_cut.timeline_path("task-1")))
        self.assertEqual(len(timeline["shots"]), 2)
        self.assertEqual(timeline["total_duration"], 2.0)
        first, second = timeline["shots"]
        self.assertEqual(first["in"], 0.0)
        self.assertEqual(first["out"], 1.0)
        self.assertEqual(second["in"], 1.0)
        self.assertEqual(second["out"], 2.0)
        self.assertTrue(first["segment_path"].endswith(".mp4"))
        self.assertTrue(os.path.isfile(first["segment_path"]))

    def test_build_missing_asset_raises(self):
        shots = [
            {
                "index": 1,
                "source": "local",
                "asset_path": os.path.join(self.task_dir, "nope.png"),
                "duration": 1.0,
            }
        ]
        with self.assertRaises(rough_cut.RoughCutError):
            rough_cut.build_rough_cut(
                "task-1", shots, params={"video_aspect": "16:9"}
            )
        self.assertFalse(os.path.isfile(rough_cut.video_path("task-1")))

    def test_load_missing_returns_none(self):
        self.assertIsNone(rough_cut.load_rough_cut("task-1"))


class TestRebuildRoughCut(RoughCutTestCase):
    def test_rebuild_recomputes_timing_and_renders_deleted_segment(self):
        rough_cut.build_rough_cut(
            "task-1", self._shots(), params={"video_aspect": "16:9"}
        )
        path = rough_cut.timeline_path("task-1")
        with open(path, "r", encoding="utf-8") as handle:
            timeline = json.load(handle)
        stale_segment = timeline["shots"][1]["segment_path"]
        timeline["shots"][1]["duration"] = 2.0
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(timeline, handle)
        os.remove(stale_segment)

        rebuilt = rough_cut.rebuild_rough_cut(
            "task-1", params={"video_aspect": "16:9"}
        )
        self.assertEqual(rebuilt["total_duration"], 3.0)
        second = rebuilt["shots"][1]
        self.assertEqual(second["in"], 1.0)
        self.assertEqual(second["out"], 3.0)
        self.assertEqual(second["segment_path"], stale_segment)
        self.assertTrue(os.path.isfile(second["segment_path"]))
        self.assertTrue(os.path.isfile(rough_cut.video_path("task-1")))

    def test_rebuild_missing_timeline_returns_none(self):
        self.assertIsNone(rough_cut.rebuild_rough_cut("task-1"))


class TestDefaults(RoughCutTestCase):
    def test_default_motion_follows_config(self):
        config.creative["motion"] = "standard"
        self.assertEqual(rough_cut.default_motion(), "standard")
        config.creative["motion"] = "bogus"
        self.assertEqual(rough_cut.default_motion(), creative_segments.DEFAULT_MOTION)
        config.creative.pop("motion", None)
        self.assertEqual(rough_cut.default_motion(), creative_segments.DEFAULT_MOTION)

    def test_default_fallback_follows_config(self):
        config.creative["material_fallback"] = "none"
        self.assertEqual(rough_cut.default_fallback(), "none")
        config.creative["material_fallback"] = "bogus"
        self.assertEqual(
            rough_cut.default_fallback(), "stock"
        )


class TestResolveShotMaterials(RoughCutTestCase):
    def test_resolves_generated_shots(self):
        registry = ProviderRegistry([_FakeImageProvider()])
        with patch(
            "app.services.material_router.build_registry",
            return_value=registry,
        ):
            plan = ShotPlan(
                task_id="task-1",
                shots=[
                    ShotPlanItem(
                        index=1,
                        source_type="generated_image",
                        prompt="a red van",
                        provider="fakegen",
                        duration=1.0,
                    )
                ],
            )
            shots = rough_cut.resolve_shot_materials(
                "task-1", {"video_aspect": "16:9"}, plan
            )
        self.assertIsNotNone(shots)
        self.assertEqual(len(shots), 1)
        shot = shots[0]
        self.assertEqual(shot["source"], "generated_image")
        self.assertEqual(shot["provider"], "fakegen")
        self.assertEqual(shot["duration"], 1.0)
        self.assertTrue(os.path.isfile(shot["asset_path"]))
        self.assertTrue(
            os.path.isfile(os.path.join(self.task_dir, "shot_plan.json"))
        )

    def test_returns_none_when_shot_fails_and_fallback_is_none(self):
        config.creative["material_fallback"] = "none"
        registry = ProviderRegistry([_FailingImageProvider()])
        with patch(
            "app.services.material_router.build_registry",
            return_value=registry,
        ):
            plan = ShotPlan(
                task_id="task-1",
                shots=[
                    ShotPlanItem(
                        index=1,
                        source_type="generated_image",
                        prompt="a red van",
                        provider="fakefail",
                        duration=1.0,
                    )
                ],
            )
            self.assertIsNone(
                rough_cut.resolve_shot_materials(
                    "task-1", {"video_aspect": "16:9"}, plan
                )
            )

    def test_returns_none_without_plan(self):
        self.assertIsNone(
            rough_cut.resolve_shot_materials("task-1", {"video_aspect": "16:9"}, None)
        )


if __name__ == "__main__":
    unittest.main()
