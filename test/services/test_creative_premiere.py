import io
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.creative import premiere as creative_premiere

TASK_ID = "task-prem"


def _write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


class CreativePremiereTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = os.path.join(self._tmp.name, "tasks", TASK_ID)
        self.shot1_dir = os.path.join(self.task_dir, "assets", "shot_001")
        self.shot2_dir = os.path.join(self.task_dir, "assets", "shot_002")
        os.makedirs(self.shot1_dir, exist_ok=True)
        os.makedirs(self.shot2_dir, exist_ok=True)
        self._patcher = patch(
            "app.services.creative.premiere.utils.task_dir",
            return_value=self.task_dir,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    # -- fixtures ---------------------------------------------------------

    def _make_media(self):
        seg1 = os.path.join(self.shot1_dir, "vid-a.mp4")
        seg2 = os.path.join(self.shot2_dir, "generated_001.png.smooth.mp4")
        _write_bytes(seg1, b"segment-one")
        _write_bytes(seg2, b"segment-two")
        _write_bytes(os.path.join(self.task_dir, "audio.mp3"), b"voice")
        _write_bytes(os.path.join(self.task_dir, "subtitle.srt"), b"1\n00:00:00,000")
        return seg1, seg2

    def _write_artifacts(self, container_root=False):
        if container_root:
            root = f"/MoneyPrinterTurbo/storage/tasks/{TASK_ID}"
        else:
            root = self.task_dir
        timeline = {
            "version": 1,
            "task_id": TASK_ID,
            "motion": "smooth",
            "created_at": "t0",
            "updated_at": "t1",
            "total_duration": 9.0,
            "shots": [
                {
                    "index": 1,
                    "source": "stock",
                    "asset_path": os.path.join(root, "assets", "shot_001", "vid-a.mp4"),
                    "provider": "stock",
                    "prompt": "",
                    "query": "harbor dawn",
                    "duration": 5.0,
                    "segment_path": os.path.join(
                        root, "assets", "shot_001", "vid-a.mp4"
                    ),
                    "in": 0.0,
                    "out": 5.0,
                },
                {
                    "index": 2,
                    "source": "generated_image",
                    "asset_path": os.path.join(
                        root, "assets", "shot_002", "generated_001.png"
                    ),
                    "provider": "comfyui",
                    "prompt": "cinematic harbor at dawn",
                    "query": "",
                    "duration": 4.0,
                    "segment_path": os.path.join(
                        root, "assets", "shot_002", "generated_001.png.smooth.mp4"
                    ),
                    "in": 5.0,
                    "out": 9.0,
                },
            ],
        }
        plan = {
            "version": 1,
            "task_id": TASK_ID,
            "shots": [
                {
                    "index": 1,
                    "script_segment": "The harbor wakes slowly.",
                    "duration": 5.0,
                    "source_type": "stock",
                    "query": "harbor dawn",
                    "prompt": None,
                    "provider": "stock",
                    "camera": "Wide shot",
                    "framing": "Full harbor",
                    "motion": "Slow pan",
                    "asset_path": "vid-a.mp4",
                    "status": "resolved",
                    "error": None,
                },
                {
                    "index": 2,
                    "script_segment": "Light spills over the water.",
                    "duration": 4.0,
                    "source_type": "generated_image",
                    "query": None,
                    "prompt": "cinematic harbor at dawn",
                    "provider": "comfyui",
                    "camera": "Close-up",
                    "framing": "Water surface",
                    "motion": "Static",
                    "asset_path": "generated_001.png",
                    "status": "resolved",
                    "error": None,
                },
            ],
        }
        for name, payload in (
            ("rough_cut.json", timeline),
            ("shot_plan.json", plan),
            ("script.json", {"script": "The harbor wakes slowly."}),
        ):
            with open(os.path.join(self.task_dir, name), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

    # -- tests ------------------------------------------------------------

    def test_build_package_structure(self):
        self._make_media()
        self._write_artifacts()
        package = creative_premiere.build_premiere_package(TASK_ID)

        root = ET.fromstring(package["xml"])
        self.assertEqual(root.tag, "Sequence")
        self.assertEqual(root.get("formatVersion"), "1|8")
        self.assertEqual(root.get("videoRate"), "30.000")
        self.assertEqual(root.get("audioRate"), "48000.000")
        # 9 s * 30 fps * TimeScale 24 = 6480
        self.assertEqual(root.get("out"), "6480")
        self.assertEqual(root.get("duration"), "6480")
        self.assertEqual(
            root.find("DOVidRes").attrib,
            {
                "frameRate": "30.000",
                "displayFrameRate": "30.000",
                "width": "1920",
                "height": "1080",
                "pixelAspectRatio": "1.000",
            },
        )
        self.assertEqual(root.find("TimeFormat").get("timeScale"), "24")
        track_defs = {track.get("id"): track for track in root.find("TrackStructure/Tracks")}
        self.assertEqual(sorted(track_defs), ["a1", "v1"])
        self.assertEqual(track_defs["v1"].get("clipHasMedia"), "1")

        track_list = root.find("TrackList")
        tracks = {track.get("targetTrack"): track for track in track_list}
        video_seqs = tracks["v1"].findall("SeqItem")
        self.assertEqual(len(video_seqs), 2)
        self.assertEqual(video_seqs[0].get("in"), "0")
        self.assertEqual(video_seqs[0].get("out"), "3600")
        self.assertEqual(video_seqs[1].get("in"), "3600")
        self.assertEqual(video_seqs[1].get("out"), "6480")
        video_clips = [seq.find("ClipItem") for seq in video_seqs]
        first, second = video_clips
        self.assertEqual(first.get("in"), "0")
        self.assertEqual(first.get("out"), "3600")
        self.assertEqual(first.get("duration"), "3600")
        self.assertEqual(second.get("in"), "0")
        self.assertEqual(second.get("out"), "2880")
        self.assertEqual(second.get("duration"), "2880")

        urls = [
            clip.find("MediaPath/MediaPathURL").get("URL") for clip in video_clips
        ]
        self.assertEqual(
            urls,
            [
                "media/assets/shot_001/vid-a.mp4",
                "media/assets/shot_002/generated_001.png.smooth.mp4",
            ],
        )
        audio_clip = tracks["a1"].find("SeqItem/ClipItem")
        self.assertEqual(audio_clip.get("name"), "audio.mp3")
        self.assertEqual(audio_clip.get("in"), "0")
        self.assertEqual(audio_clip.get("out"), "6480")
        self.assertEqual(
            audio_clip.find("MediaPath/MediaPathURL").get("URL"), "media/audio.mp3"
        )

        comment = first.find("Comment").text
        self.assertIn("shot 1", comment)
        self.assertIn("stock", comment)
        self.assertIn("The harbor wakes slowly.", comment)

        self.assertEqual(
            sorted(package["files"]),
            [
                "media/assets/shot_001/vid-a.mp4",
                "media/assets/shot_002/generated_001.png.smooth.mp4",
                "media/audio.mp3",
                "media/subtitle.srt",
            ],
        )

    def test_manifest_metadata(self):
        self._make_media()
        self._write_artifacts()
        manifest = creative_premiere.build_premiere_package(TASK_ID)["manifest"]

        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["total_duration"], 9.0)
        self.assertEqual(manifest["video"], {"width": 1920, "height": 1080, "fps": 30})
        self.assertEqual(manifest["audio"]["file"], "media/audio.mp3")
        self.assertEqual(manifest["subtitles"]["file"], "media/subtitle.srt")
        self.assertEqual(manifest["script"], "The harbor wakes slowly.")
        first, second = manifest["shots"]
        self.assertEqual(first["source_type"], "stock")
        self.assertEqual(first["query"], "harbor dawn")
        self.assertEqual(first["camera"], "Wide shot")
        self.assertEqual((first["timeline_in"], first["timeline_out"]), (0.0, 5.0))
        self.assertFalse(first["missing"])
        self.assertEqual(second["source_type"], "generated_image")
        self.assertEqual(second["provider"], "comfyui")
        self.assertEqual(second["script_segment"], "Light spills over the water.")

    def test_zip_contents(self):
        self._make_media()
        self._write_artifacts()
        payload, filename = creative_premiere.build_premiere_zip(TASK_ID)
        self.assertEqual(filename, f"premiere-{TASK_ID[:8]}.zip")

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
        self.assertTrue(
            {
                "timeline.xml",
                "manifest.json",
                "media/audio.mp3",
                "media/subtitle.srt",
                "media/assets/shot_001/vid-a.mp4",
                "media/assets/shot_002/generated_001.png.smooth.mp4",
            }
            <= names
        )

    def test_container_root_paths_reanchored(self):
        self._make_media()
        self._write_artifacts(container_root=True)
        package = creative_premiere.build_premiere_package(TASK_ID)
        manifest = package["manifest"]
        self.assertFalse(manifest["shots"][0]["missing"])
        self.assertFalse(manifest["shots"][1]["missing"])
        self.assertEqual(len(package["files"]), 4)

    def test_missing_segment_marked_but_exported(self):
        seg1, _ = self._make_media()
        self._write_artifacts()
        # remove the second segment file so resolution fails
        os.remove(
            os.path.join(self.shot2_dir, "generated_001.png.smooth.mp4")
        )
        package = creative_premiere.build_premiere_package(TASK_ID)
        manifest = package["manifest"]
        self.assertTrue(manifest["shots"][1]["missing"])
        self.assertNotIn(
            "media/assets/shot_002/generated_001.png.smooth.mp4", package["files"]
        )
        root = ET.fromstring(package["xml"])
        clips = root.find("TrackList").findall("Track")[0].findall("SeqItem/ClipItem")
        self.assertEqual(len(clips), 2)
        payload, _ = creative_premiere.build_premiere_zip(TASK_ID)
        self.assertTrue(len(payload) > 0)

    def test_missing_timeline_raises(self):
        os.makedirs(self.task_dir, exist_ok=True)
        with self.assertRaises(creative_premiere.PremiereExportError):
            creative_premiere.build_premiere_package(TASK_ID)

    def test_missing_task_dir_raises(self):
        with patch(
            "app.services.creative.premiere.utils.task_dir",
            return_value=os.path.join(self._tmp.name, "nope"),
        ):
            with self.assertRaises(creative_premiere.PremiereExportError):
                creative_premiere.build_premiere_package(TASK_ID)


if __name__ == "__main__":
    unittest.main()
