import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cli


class TestCli(unittest.TestCase):
    def test_build_video_params_with_local_materials(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "测试主题",
                "--video-source",
                "local",
                "--video-materials",
                "a.mp4,b.jpg",
                "--video-terms",
                "foo, bar",
            ]
        )

        params = cli.build_video_params(args)

        self.assertEqual(params.video_subject, "测试主题")
        self.assertEqual(params.video_source, "local")
        self.assertEqual([m.url for m in params.video_materials], ["a.mp4", "b.jpg"])
        self.assertEqual(params.video_terms, ["foo", "bar"])

    def test_run_cli_dispatches_task_start(self):
        with patch.object(cli.tm, "start", return_value={"script": "ok"}) as start, patch.object(
            cli.utils, "get_uuid", return_value="task-123"
        ), patch("builtins.print") as print_mock:
            code = cli.run_cli(["--video-subject", "命令行测试", "--stop-at", "script"])

        self.assertEqual(code, 0)
        self.assertTrue(start.called)
        kwargs = start.call_args.kwargs
        self.assertEqual(kwargs["task_id"], "task-123")
        self.assertEqual(kwargs["stop_at"], "script")
        self.assertEqual(kwargs["params"].video_subject, "命令行测试")
        print_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
