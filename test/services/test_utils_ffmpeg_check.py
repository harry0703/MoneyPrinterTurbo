import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
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



class TestGetFfmpegBinaryEnvExpansion(unittest.TestCase):
    """Verify get_ffmpeg_binary() expands the IMAGEIO_FFMPEG_EXE value."""

    def test_expands_user_home(self):
        with patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": "~/bin/ffmpeg"}):
            self.assertEqual(
                utils.get_ffmpeg_binary(),
                os.path.expanduser("~/bin/ffmpeg"),
            )

    def test_expands_environment_variable(self):
        with patch.dict(
            os.environ,
            {"IMAGEIO_FFMPEG_EXE": "${FFMPEG_BIN}/ffmpeg", "FFMPEG_BIN": "/opt/ffmpeg"},
        ):
            self.assertEqual(
                utils.get_ffmpeg_binary(),
                "/opt/ffmpeg/ffmpeg",
            )

    def test_absolute_path_is_unchanged(self):
        with patch.dict(
            os.environ, {"IMAGEIO_FFMPEG_EXE": "/usr/local/bin/ffmpeg"}
        ):
            self.assertEqual(
                utils.get_ffmpeg_binary(),
                "/usr/local/bin/ffmpeg",
            )

    def test_normalizes_home_path_in_os_environ(self):
        """get_ffmpeg_binary() 必须把展开后的路径写回环境变量。

        MoviePy/imageio 直接读取 os.environ["IMAGEIO_FFMPEG_EXE"]，
        只展开返回值会让预检通过而 MoviePy 编码仍然失败（issue #1662）。
        """
        home = tempfile.mkdtemp(prefix="ffmpeg-home-")
        try:
            with patch.dict(
                os.environ, {"HOME": home, "IMAGEIO_FFMPEG_EXE": "~/bin/ffmpeg"}
            ):
                expanded = utils.get_ffmpeg_binary()
                self.assertEqual(expanded, os.path.join(home, "bin", "ffmpeg"))
                self.assertEqual(os.environ["IMAGEIO_FFMPEG_EXE"], expanded)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_normalizes_env_var_references_in_os_environ(self):
        with patch.dict(
            os.environ,
            {"IMAGEIO_FFMPEG_EXE": "${FFMPEG_BIN}/ffmpeg", "FFMPEG_BIN": "/opt/ffmpeg"},
        ):
            utils.get_ffmpeg_binary()
            self.assertEqual(os.environ["IMAGEIO_FFMPEG_EXE"], "/opt/ffmpeg/ffmpeg")

    def test_absolute_path_leaves_os_environ_unchanged(self):
        with patch.dict(
            os.environ, {"IMAGEIO_FFMPEG_EXE": "/usr/local/bin/ffmpeg"}
        ):
            utils.get_ffmpeg_binary()
            self.assertEqual(
                os.environ["IMAGEIO_FFMPEG_EXE"], "/usr/local/bin/ffmpeg"
            )


@unittest.skipUnless(
    shutil.which("ffmpeg"), "需要系统里存在真实 ffmpeg 才能做编码回归"
)
class TestMoviePyEncodeWithExpandedEnv(unittest.TestCase):
    """issue #1662 回归：MoviePy 实际编码链路。

    MoviePy 2.x 在 import 时通过 imageio 一次性解析 ffmpeg 路径并缓存为
    moviepy.config.FFMPEG_BINARY，测试进程里早已导入 moviepy，因此直接
    在本进程写视频无法复现问题。这里用子进程按真实启动顺序执行：先加载
    app.config（负责规范化 IMAGEIO_FFMPEG_EXE），再导入 moviepy 编码。
    "~"、环境变量、绝对路径三种写法都必须产出真实视频文件。
    """

    PROJECT_ROOT = str(Path(__file__).parent.parent.parent)

    def setUp(self):
        self.bin_dir = tempfile.mkdtemp(prefix="ffmpeg-regression-")
        self.linked_ffmpeg = os.path.join(self.bin_dir, "ffmpeg")
        try:
            os.symlink(shutil.which("ffmpeg"), self.linked_ffmpeg)
        except OSError:
            shutil.rmtree(self.bin_dir, ignore_errors=True)
            self.skipTest("当前环境无法创建符号链接")

    def tearDown(self):
        shutil.rmtree(self.bin_dir, ignore_errors=True)

    def _encode_with_imageio_env(self, imageio_value, extra_env):
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {self.PROJECT_ROOT!r})
            import app.config.config  # noqa: F401  规范化必须先于 moviepy 初始化
            from moviepy import ColorClip

            clip = ColorClip(size=(8, 8), color=(0, 128, 255), duration=0.2)
            try:
                clip.write_videofile(
                    sys.argv[1], codec="mpeg4", fps=8, audio=False, logger=None
                )
            finally:
                clip.close()
            """
        )
        env = dict(os.environ)
        env["IMAGEIO_FFMPEG_EXE"] = imageio_value
        env.update(extra_env)
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = os.path.join(tmp_dir, "regression.mp4")
            proc = subprocess.run(
                [sys.executable, "-c", script, output],
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(proc.returncode, 0, f"stderr:\n{proc.stderr[-2000:]}")
            self.assertTrue(os.path.isfile(output))
            self.assertGreater(os.path.getsize(output), 0)

    def test_encode_with_tilde_path(self):
        self._encode_with_imageio_env("~/ffmpeg", {"HOME": self.bin_dir})

    def test_encode_with_env_var_path(self):
        self._encode_with_imageio_env(
            "${FFMPEG_REGRESSION_BIN}/ffmpeg",
            {"FFMPEG_REGRESSION_BIN": self.bin_dir},
        )

    def test_encode_with_absolute_path(self):
        self._encode_with_imageio_env(self.linked_ffmpeg, {})

if __name__ == "__main__":
    unittest.main()
