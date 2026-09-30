import io
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.services import video


class TestVideoReaderStdout(unittest.TestCase):
    def test_overlapping_reader_opens_restore_the_original_stdout(self):
        first_started = threading.Event()
        second_started = threading.Event()
        first_returned = threading.Event()
        release_first = threading.Event()
        captured = io.StringIO()
        readers = {"first.mp4": object(), "second.mp4": object()}

        def open_reader(path, audio=False):
            if path == "first.mp4":
                first_started.set()
                if not release_first.wait(timeout=2):
                    raise TimeoutError("first reader was not released")
            else:
                second_started.set()
                if not first_returned.wait(timeout=2):
                    raise TimeoutError("first caller did not finish")
            print(f"metadata: {path}")
            return readers[path]

        def first_call():
            try:
                return video._open_video_clip_quietly("first.mp4")
            finally:
                first_returned.set()

        with patch.object(video, "VideoFileClip", side_effect=open_reader), patch.object(sys, "stdout", captured):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(first_call)
                self.assertTrue(first_started.wait(timeout=1))
                second = executor.submit(video._open_video_clip_quietly, "second.mp4")
                # Old code permits both redirections to overlap; corrected code
                # serializes just reader construction, not later encoding.
                second_started.wait(timeout=0.1)
                release_first.set()
                self.assertIs(first.result(timeout=2), readers["first.mp4"])
                self.assertIs(second.result(timeout=2), readers["second.mp4"])
            self.assertIs(sys.stdout, captured)
            print("CLI result after both readers")
            self.assertEqual(captured.getvalue(), "CLI result after both readers\n")

    def test_failed_reader_restores_stdout_and_releases_open_lock(self):
        captured = io.StringIO()
        reader = object()
        with patch.object(video, "VideoFileClip", side_effect=[RuntimeError("bad media"), reader]), patch.object(sys, "stdout", captured):
            with self.assertRaisesRegex(RuntimeError, "bad media"):
                video._open_video_clip_quietly("bad.mp4")
            self.assertIs(sys.stdout, captured)
            self.assertIs(video._open_video_clip_quietly("good.mp4"), reader)
            self.assertIs(sys.stdout, captured)
