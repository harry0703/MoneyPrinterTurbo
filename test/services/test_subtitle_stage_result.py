"""Standalone subtitle completion requires a generated subtitle artifact."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edge_tts import SubMaker

from app.config import config
from app.models import const
from app.models.schema import SubtitleRequest
from app.services import state as sm
from app.services import task as tm
from app.services import voice


class TestSubtitleStageResult(unittest.TestCase):
    def _run(self, maker, directory, state):
        params = SubtitleRequest(video_script="Hello world.")
        with (
            patch.dict(config.app, {"subtitle_provider": "edge"}),
            patch.object(sm, "state", state),
            patch.object(tm.utils, "task_dir", return_value=directory),
            # External TTS has produced audio but no word-boundary events. Keep
            # script persistence, subtitle construction and task state real.
            patch.object(tm, "generate_audio", return_value=(
                str(Path(directory, "audio.mp3")), 2.0, maker
            )),
        ):
            return tm.start("subtitle-stage", params, stop_at="subtitle")

    def test_missing_timeline_fails_instead_of_completing_without_subtitles(self):
        state = sm.MemoryState()
        maker = voice.ensure_legacy_submaker_fields(SubMaker())
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(maker, directory, state)
            self.assertFalse(Path(directory, "subtitle.srt").exists())
            self.assertEqual(result["state"], const.TASK_STATE_FAILED)
            self.assertEqual(result["failed_stage"], "subtitle")
            self.assertIn("subtitle", result["error"])
            self.assertEqual(state.get_task("subtitle-stage")["state"], const.TASK_STATE_FAILED)

    def test_real_generated_subtitle_still_completes_successfully(self):
        state = sm.MemoryState()
        maker = SubMaker()
        maker.feed({
            "type": "WordBoundary", "offset": 0, "duration": 20_000_000,
            "text": "Hello world.",
        })
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(maker, directory, state)
            subtitle_file = Path(result["subtitle_path"])
            self.assertEqual(subtitle_file, Path(directory, "subtitle.srt"))
            self.assertIn("Hello world", subtitle_file.read_text(encoding="utf-8"))
            self.assertEqual(state.get_task("subtitle-stage")["state"], const.TASK_STATE_COMPLETE)
