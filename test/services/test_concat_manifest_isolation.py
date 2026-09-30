import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import video


class TestConcatManifestIsolation(unittest.TestCase):
    def test_concurrent_concat_reads_only_its_own_inputs(self):
        barrier = threading.Barrier(2)
        observed = {}
        render = threading.local()
        manifests = []
        with tempfile.TemporaryDirectory() as directory:
            def run(command, output_file):
                manifest = Path(command[command.index("-i") + 1])
                manifests.append(manifest)
                barrier.wait(timeout=5)
                observed[render.name] = manifest.read_text(encoding="utf-8")
                Path(command[-1]).write_bytes(b"encoded-video")
                barrier.wait(timeout=5)
                return SimpleNamespace(returncode=0)

            def concat(name):
                render.name = name
                video.concat_video_clips_with_ffmpeg(
                    [str(Path(directory) / f"{name}-source.mp4")],
                    str(Path(directory) / f"{name}.mp4"), 1, directory,
                )

            with patch.object(video, "_run_concat_with_heartbeat", side_effect=run), patch.object(
                video, "_get_effective_video_codec", return_value="libx264"
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    list(executor.map(concat, ["first", "second"]))
            for name in ("first", "second"):
                self.assertIn(f"{name}-source.mp4", observed[name])
            self.assertEqual(len(set(manifests)), 2)
            self.assertTrue(all(not manifest.exists() for manifest in manifests))

    def test_encoder_failure_removes_only_its_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            unrelated = Path(directory) / "ffmpeg-concat-list.txt"
            unrelated.write_text("another operation's manifest", encoding="utf-8")
            with patch.object(video, "_run_concat_with_heartbeat", side_effect=RuntimeError("encoder failed")), patch.object(
                video, "_get_effective_video_codec", return_value="libx264"
            ):
                with self.assertRaisesRegex(RuntimeError, "encoder failed"):
                    video.concat_video_clips_with_ffmpeg(["source.mp4"], "result.mp4", 1, directory)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "another operation's manifest")
            self.assertEqual(list(Path(directory).iterdir()), [unrelated])
