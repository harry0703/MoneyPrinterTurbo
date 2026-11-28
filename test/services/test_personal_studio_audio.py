# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from app.services.personal_studio import audio
from test.services._personal_studio_helpers import make_speechlike_wav


class TestAudioAnalysis(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_analyze_reports_levels_and_duration(self):
        source = make_speechlike_wav(self.root / "sample.wav", seconds=8)
        metrics = audio.analyze(source)
        self.assertAlmostEqual(metrics["duration"], 8.0, delta=0.2)
        self.assertGreaterEqual(metrics["score"], 50)
        self.assertIn(metrics["verdict"], {"buena", "aceptable"})
        self.assertLess(metrics["speech_dbfs"], 0)
        self.assertGreaterEqual(metrics["snr_db"], 12)
        self.assertIsInstance(metrics["issues"], list)

    def test_short_sample_is_flagged(self):
        source = make_speechlike_wav(self.root / "short.wav", seconds=2)
        metrics = audio.analyze(source)
        self.assertTrue(any("menos de 6" in issue for issue in metrics["issues"]))

    def test_process_sample_normalizes_and_creates_wav(self):
        source = make_speechlike_wav(self.root / "raw.wav", seconds=8)
        target = self.root / "clean.wav"
        audio.process_sample(source, target)
        self.assertTrue(target.is_file())
        metrics = audio.analyze(target)
        self.assertGreater(metrics["duration"], 4)
        self.assertLess(metrics["speech_dbfs"], -6)
        self.assertGreater(metrics["speech_dbfs"], -30)

    def test_concat_and_mp3_export(self):
        first = make_speechlike_wav(self.root / "a.wav", seconds=3)
        second = make_speechlike_wav(self.root / "b.wav", seconds=3)
        joined = self.root / "joined.wav"
        audio.concat_audio([first, second], joined)
        self.assertAlmostEqual(audio.ffprobe_duration(joined), 6.0, delta=0.3)
        mp3 = self.root / "joined.mp3"
        audio.to_mp3(joined, mp3)
        self.assertGreater(mp3.stat().st_size, 1000)

    def test_prepare_upload_rejects_wrong_type_and_empty(self):
        with self.assertRaises(audio.AudioError):
            audio.prepare_upload("nota.txt", b"texto")
        with self.assertRaises(audio.AudioError):
            audio.prepare_upload("voz.wav", b"")

    def test_missing_file_raises(self):
        with self.assertRaises(audio.AudioError):
            audio.decode_pcm(self.root / "missing.wav")


if __name__ == "__main__":
    unittest.main()
