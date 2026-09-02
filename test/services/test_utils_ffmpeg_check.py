import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils import utils


class TestCheckFfmpegReady(unittest.TestCase):
    """覆盖 utils.check_ffmpeg_ready() 的四种探测结果。"""

    def test_returns_true_when_ffmpeg_probe_succeeds(self):
        completed = subprocess.CompletedProcess(args=["ffmpeg", "-version"], returncode=0)
        with (
            patch.object(utils, "get_ffmpeg_binary", return_value="/usr/bin/ffmpeg"),
            patch.object(utils.subprocess, "run", return_value=completed) as run,
        ):
            self.assertTrue(utils.check_ffmpeg_ready())

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/ffmpeg", "-version"])

    def test_returns_false_when_executable_is_missing(self):
        with (
            patch.object(utils, "get_ffmpeg_binary", return_value="ffmpeg"),
            patch.object(utils.subprocess, "run", side_effect=FileNotFoundError()),
            patch.object(utils.logger, "warning") as warning,
        ):
            self.assertFalse(utils.check_ffmpeg_ready())

        warning.assert_called_once()
        self.assertIn("no usable ffmpeg executable found", warning.call_args.args[0])

    def test_returns_false_on_non_zero_exit_code(self):
        completed = subprocess.CompletedProcess(args=["ffmpeg", "-version"], returncode=1)
        with (
            patch.object(utils, "get_ffmpeg_binary", return_value="/usr/bin/ffmpeg"),
            patch.object(utils.subprocess, "run", return_value=completed),
            patch.object(utils.logger, "warning") as warning,
        ):
            self.assertFalse(utils.check_ffmpeg_ready())

        warning.assert_called_once()
        self.assertIn("exited with status 1", warning.call_args.args[0])

    def test_returns_false_on_timeout(self):
        with (
            patch.object(utils, "get_ffmpeg_binary", return_value="/usr/bin/ffmpeg"),
            patch.object(
                utils.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10),
            ),
            patch.object(utils.logger, "warning") as warning,
        ):
            self.assertFalse(utils.check_ffmpeg_ready(timeout=10))

        warning.assert_called_once()
        self.assertIn("failed to probe ffmpeg", warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
