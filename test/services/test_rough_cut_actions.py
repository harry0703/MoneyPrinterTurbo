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
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import rough_cut
from app.services import state as sm
from app.services import task as task_service
from app.services.providers.base import ProviderRegistry

TASK_ID = "task-456"

_COLORS = ((120, 60, 30), (40, 120, 160), (10, 200, 90))


class _FakeProvider:
    name = "fakegen"

    def is_available(self):
        return True

    def generate(self, shot, context):
        output_dir = context["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"regen_{shot.index:03d}.png")
        Image.new("RGB", (320, 180), (10, 200, 90)).save(path)
        return [path]


def _fake_segment(asset_path, clip_duration, motion="smooth"):
    segment_path = f"{asset_path}.smooth.mp4"
    if not os.path.isfile(segment_path):
        with open(segment_path, "wb") as handle:
            handle.write(b"fake")
    return segment_path


class RoughCutActionsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = os.path.join(self._tmp.name, "tasks", TASK_ID)
        os.makedirs(self.task_dir, exist_ok=True)
        self._patchers = [
            patch(
                "app.services.rough_cut.utils.task_dir",
                return_value=self.task_dir,
            ),
            patch.object(rough_cut, "_concatenate_segments", return_value=""),
            patch(
                "app.services.creative_segments.prepare_shot_segment",
                side_effect=_fake_segment,
            ),
        ]
        for patcher in self._patchers:
            patcher.start()
        self._creative_backup = dict(config.creative)
        self.images = [self._image(f"shot{i}.png", color) for i, color in enumerate(_COLORS, start=1)]

    def tearDown(self):
        for patcher in self._patchers:
            patcher.stop()
        sm.state.delete_task(TASK_ID)
        config.creative.clear()
        config.creative.update(self._creative_backup)
        self._tmp.cleanup()
        shutil.rmtree(self._tmp.name, ignore_errors=True)

    def _image(self, name, color):
        path = os.path.join(self.task_dir, name)
        Image.new("RGB", (320, 180), color).save(path)
        return path

    def _seed(self, durations=None):
        durations = durations or [1.0] * len(self.images)
        shots = []
        cursor = 0.0
        for image, duration in zip(self.images, durations):
            segment = _fake_segment(image, int(round(duration)))
            shots.append(
                {
                    "index": len(shots) + 1,
                    "source": "generated_image",
                    "asset_path": image,
                    "provider": "fakegen",
                    "prompt": f"prompt {len(shots) + 1}",
                    "query": "",
                    "duration": duration,
                    "segment_path": segment,
                    "in": cursor,
                    "out": cursor + duration,
                }
            )
            cursor += duration
        timeline = {
            "version": 1,
            "task_id": TASK_ID,
            "motion": "smooth",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "total_duration": cursor,
            "shots": shots,
        }
        with open(rough_cut.timeline_path(TASK_ID), "w", encoding="utf-8") as handle:
            json.dump(timeline, handle)
        sm.state.update_task(
            TASK_ID,
            state=const.TASK_STATE_WAITING_FOR_DIRECTOR,
            progress=60,
            params={"video_aspect": "16:9"},
        )
        return timeline


class TestReorderShots(RoughCutActionsTestCase):
    def test_reorder_permutes_and_recomputes_timing(self):
        self._seed()
        timeline = rough_cut.reorder_shots(TASK_ID, [2, 3, 1])
        self.assertEqual([shot["index"] for shot in timeline["shots"]], [1, 2, 3])
        self.assertEqual(timeline["shots"][0]["asset_path"], self.images[1])
        self.assertEqual(timeline["shots"][0]["in"], 0.0)
        self.assertEqual(timeline["shots"][0]["out"], 1.0)
        self.assertEqual(timeline["shots"][2]["asset_path"], self.images[0])
        self.assertEqual(timeline["shots"][2]["in"], 2.0)
        self.assertEqual(timeline["total_duration"], 3.0)
        on_disk = rough_cut.load_rough_cut(TASK_ID)
        self.assertEqual(
            [shot["asset_path"] for shot in on_disk["shots"]],
            [self.images[1], self.images[2], self.images[0]],
        )

    def test_reorder_rejects_non_permutation(self):
        self._seed()
        with self.assertRaises(rough_cut.RoughCutError) as raised:
            rough_cut.reorder_shots(TASK_ID, [1, 2])
        self.assertEqual(raised.exception.status_code, 400)


class TestSetShotDuration(RoughCutActionsTestCase):
    def test_duration_updates_timing_and_renders_segment(self):
        self._seed()
        os.remove(self.images[1] + ".smooth.mp4")
        timeline = rough_cut.set_shot_duration(TASK_ID, 2, 2.5)
        second = timeline["shots"][1]
        self.assertEqual(second["duration"], 2.5)
        self.assertEqual(second["in"], 1.0)
        self.assertEqual(second["out"], 3.5)
        self.assertEqual(timeline["total_duration"], 4.5)
        self.assertTrue(os.path.isfile(second["segment_path"]))

    def test_duration_out_of_range_rejected(self):
        self._seed()
        for bad in (0.1, 1000.0):
            with self.subTest(duration=bad):
                with self.assertRaises(rough_cut.RoughCutError):
                    rough_cut.set_shot_duration(TASK_ID, 1, bad)


class TestReplaceShotAsset(RoughCutActionsTestCase):
    def test_replace_swaps_asset_and_renders(self):
        self._seed()
        new_asset = self._image("replaced.png", (9, 90, 200))
        timeline = rough_cut.replace_shot_asset(TASK_ID, 1, new_asset)
        first = timeline["shots"][0]
        self.assertEqual(first["asset_path"], new_asset)
        self.assertTrue(os.path.isfile(new_asset + ".smooth.mp4"))

    def test_replace_rejects_missing_file(self):
        self._seed()
        with self.assertRaises(rough_cut.RoughCutError) as raised:
            rough_cut.replace_shot_asset(TASK_ID, 1, "nope.png")
        self.assertEqual(raised.exception.status_code, 400)


class TestDeleteShot(RoughCutActionsTestCase):
    def test_delete_removes_and_renumbers(self):
        self._seed()
        timeline = rough_cut.delete_shot(TASK_ID, 2)
        self.assertEqual(len(timeline["shots"]), 2)
        self.assertEqual(timeline["shots"][0]["asset_path"], self.images[0])
        self.assertEqual(timeline["shots"][1]["asset_path"], self.images[2])
        self.assertEqual(timeline["shots"][1]["in"], 1.0)
        self.assertEqual(timeline["total_duration"], 2.0)

    def test_delete_last_shot_rejected(self):
        self._seed([1.0, 1.0])
        rough_cut.delete_shot(TASK_ID, 1)
        with self.assertRaises(rough_cut.RoughCutError):
            rough_cut.delete_shot(TASK_ID, 1)


class TestRegenerateShot(RoughCutActionsTestCase):
    def test_regenerate_replaces_asset_with_provider_output(self):
        self._seed()
        registry = ProviderRegistry([_FakeProvider()])
        with patch.object(rough_cut, "build_registry", return_value=registry):
            timeline = rough_cut.regenerate_shot(TASK_ID, 2, prompt="a new prompt")
        second = timeline["shots"][1]
        self.assertEqual(second["prompt"], "a new prompt")
        self.assertIn("regen_002.png", second["asset_path"])
        self.assertTrue(os.path.isfile(second["asset_path"]))
        self.assertTrue(os.path.isfile(second["segment_path"]))

    def test_regenerate_non_generated_shot_requires_provider(self):
        self._seed()
        timeline = rough_cut.load_rough_cut(TASK_ID)
        timeline["shots"][0]["source"] = "stock"
        timeline["shots"][0]["provider"] = ""
        with open(rough_cut.timeline_path(TASK_ID), "w", encoding="utf-8") as handle:
            json.dump(timeline, handle)
        with self.assertRaises(rough_cut.RoughCutError):
            rough_cut.regenerate_shot(TASK_ID, 1)


class TestStateGating(RoughCutActionsTestCase):
    def test_action_rejects_task_not_waiting(self):
        self._seed()
        sm.state.update_task(
            TASK_ID, state=const.TASK_STATE_PROCESSING, progress=50,
            params={"video_aspect": "16:9"},
        )
        with self.assertRaises(rough_cut.RoughCutError) as raised:
            rough_cut.reorder_shots(TASK_ID, [2, 1, 3])
        self.assertEqual(raised.exception.status_code, 409)

    def test_action_rejects_missing_task(self):
        self._seed()
        sm.state.delete_task(TASK_ID)
        with self.assertRaises(rough_cut.RoughCutError) as raised:
            rough_cut.delete_shot(TASK_ID, 1)
        self.assertEqual(raised.exception.status_code, 404)


class TestResumeAfterDirector(RoughCutActionsTestCase):
    def test_resume_rebuilds_and_finalizes_video(self):
        self._seed()
        params = VideoParams(video_subject="test").model_dump(mode="json")
        sm.state.update_task(
            TASK_ID,
            state=const.TASK_STATE_WAITING_FOR_DIRECTOR,
            progress=60,
            params=params,
            script="script text",
            terms=["term"],
            audio_file="/fake/audio.mp3",
            audio_duration=3.0,
            subtitle_path="/fake/subtitles.srt",
            materials=list(self.images),
        )
        expected_segments = [image + ".smooth.mp4" for image in self.images]
        with patch.object(task_service, "generate_final_videos") as generate:
            generate.return_value = (
                ["/fake/final.mp4"],
                ["/fake/combined.mp4"],
                None,
            )
            result = task_service.resume_after_director(TASK_ID)

        self.assertEqual(result["videos"], ["/fake/final.mp4"])
        task = sm.state.get_task(TASK_ID)
        self.assertEqual(task["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(task["progress"], 100)
        self.assertEqual(task["videos"], ["/fake/final.mp4"])
        self.assertEqual(task["materials"], expected_segments)
        self.assertEqual(generate.call_args.args[2], expected_segments)
        self.assertEqual(generate.call_args.args[4], "/fake/subtitles.srt")
        called_params = generate.call_args.args[1]
        self.assertEqual(called_params.video_count, 1)
        self.assertEqual(called_params.video_concat_mode, VideoConcatMode.sequential)

    def test_resume_rejects_task_not_waiting(self):
        self._seed()
        sm.state.update_task(TASK_ID, state=const.TASK_STATE_COMPLETE, progress=100)
        task_service.resume_after_director(TASK_ID)
        task = sm.state.get_task(TASK_ID)
        self.assertEqual(task["state"], const.TASK_STATE_FAILED)
        self.assertIn("not waiting", task.get("error", ""))


if __name__ == "__main__":
    unittest.main()
