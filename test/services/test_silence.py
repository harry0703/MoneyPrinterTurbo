import sys
import unittest
from pathlib import Path

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import silence as silence_service

SRT = """1
00:00:00,100 --> 00:00:00,938
Nvidia

2
00:00:01,125 --> 00:00:04,650
a blockbuster deal

3
00:00:05,812 --> 00:00:06,575
chip giant
"""


class TestSilencePlanning(unittest.TestCase):
    def _write_srt(self, tmp_path, content=SRT):
        p = tmp_path / "subtitle.srt"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_timestamp_roundtrip(self):
        self.assertAlmostEqual(silence_service._srt_to_seconds("00:00:04,650"), 4.65)
        self.assertEqual(silence_service._seconds_to_srt(4.65), "00:00:04,650")

    def test_plan_cuts_finds_long_gap(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_srt(Path(tmp))
            cuts = silence_service.plan_cuts(path)
            # cue2 end 4.650 -> cue3 start 5.812 = 1.162s gap > 0.6
            self.assertEqual(len(cuts), 1)
            self.assertAlmostEqual(cuts[0][0], 4.65 + 0.3, places=2)
            self.assertAlmostEqual(cuts[0][1], 5.812, places=2)

    def test_plan_cuts_empty_for_tight_subs(self):
        import tempfile

        tight = (
            "1\n00:00:00,000 --> 00:00:01,000\nA\n\n"
            "2\n00:00:01,200 --> 00:00:02,000\nB\n\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_srt(Path(tmp), tight)
            self.assertEqual(silence_service.plan_cuts(path), [])

    def test_shift_cues_moves_later_cues(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_srt(Path(tmp))
            cuts = silence_service.plan_cuts(path)
            shifted = silence_service.shift_cues(path, cuts)
            # cue1-2 unchanged, cue3 shifts back
            self.assertTrue(shifted[0][1].startswith("00:00:00,100"))
            self.assertTrue(shifted[1][1].startswith("00:00:01,125"))
            saved = cuts[0][1] - cuts[0][0]
            self.assertIn("00:00:05,812", SRT)  # original
            new_start = shifted[2][1].split(" --> ")[0]
            self.assertAlmostEqual(
                silence_service._srt_to_seconds(new_start),
                5.812 - saved,
                places=2,
            )

    def test_trim_missing_files_returns_none(self):
        self.assertEqual(
            silence_service.trim_silences("/nonexistent/audio.mp3", "/nonexistent/sub.srt"),
            (None, None),
        )


if __name__ == "__main__":
    unittest.main()
