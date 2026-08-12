import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import claude_cli


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["claude"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _payload(result="generated text", is_error=False):
    return json.dumps({"is_error": is_error, "result": result})


class TestClaudeCliInvocation(unittest.TestCase):
    def test_prompt_is_passed_on_stdin_with_tools_disabled(self):
        """
        提示词可能超过 8000 字符，必须走 stdin 而不是命令行参数；同时禁用工具，
        保证订阅制 CLI 只做一次纯文本生成。
        """
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess, "run", return_value=_completed(_payload())
            ) as run,
        ):
            result = claude_cli.generate("write a script", model="opus", effort="high")

        self.assertEqual(result, "generated text")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/claude")
        self.assertIn("-p", command)
        self.assertNotIn("write a script", command)
        self.assertEqual(run.call_args.kwargs["input"], "write a script")
        self.assertEqual(command[command.index("--model") + 1], "opus")
        self.assertEqual(command[command.index("--effort") + 1], "high")
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(
            command[command.index("--system-prompt") + 1],
            claude_cli.SYSTEM_PROMPT,
        )

    def test_defaults_are_applied_for_empty_settings(self):
        """配置留空时应使用 Registry 之外的模块默认值，而不是发出无效参数。"""
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess, "run", return_value=_completed(_payload())
            ) as run,
        ):
            claude_cli.generate("prompt", model="", effort="", binary="", timeout=0)

        command = run.call_args.args[0]
        self.assertEqual(
            command[command.index("--model") + 1], claude_cli.DEFAULT_MODEL
        )
        self.assertEqual(
            command[command.index("--effort") + 1], claude_cli.DEFAULT_EFFORT
        )
        self.assertEqual(run.call_args.kwargs["timeout"], claude_cli.DEFAULT_TIMEOUT)

    def test_unsupported_effort_falls_back_to_default(self):
        """错误的 effort 不应让整条流水线失败，回退到默认值即可。"""
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess, "run", return_value=_completed(_payload())
            ) as run,
        ):
            claude_cli.generate("prompt", effort="turbo")

        command = run.call_args.args[0]
        self.assertEqual(
            command[command.index("--effort") + 1], claude_cli.DEFAULT_EFFORT
        )

    def test_session_environment_is_not_inherited(self):
        """
        从 Claude Code 会话内部启动时，父进程的会话变量会让子进程按嵌套 Agent
        运行；只有 OAuth Token 需要继承。
        """
        env = {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "abc",
            "CLAUDE_CODE_OAUTH_TOKEN": "token",
            "PATH": "/usr/bin",
        }
        with (
            patch.dict(claude_cli.os.environ, env, clear=True),
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess, "run", return_value=_completed(_payload())
            ) as run,
        ):
            claude_cli.generate("prompt")

        child_env = run.call_args.kwargs["env"]
        self.assertNotIn("CLAUDECODE", child_env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", child_env)
        self.assertEqual(child_env["CLAUDE_CODE_OAUTH_TOKEN"], "token")
        self.assertEqual(child_env["PATH"], "/usr/bin")

    def test_generation_runs_outside_the_project_directory(self):
        """临时工作目录可以避免请求带上项目的 CLAUDE.md、hooks 和 git 状态。"""
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess, "run", return_value=_completed(_payload())
            ) as run,
        ):
            claude_cli.generate("prompt")

        cwd = run.call_args.kwargs["cwd"]
        self.assertTrue(cwd)
        self.assertNotEqual(Path(cwd), Path.cwd())


class TestClaudeCliFailures(unittest.TestCase):
    def test_missing_binary_reports_install_hint(self):
        """CLI 未安装是最常见的配置错误，报错必须给出可执行的下一步。"""
        with (
            patch.object(claude_cli.shutil, "which", return_value=None),
            patch.object(claude_cli.os.path, "isfile", return_value=False),
            patch.object(claude_cli.subprocess, "run") as run,
        ):
            with self.assertRaises(claude_cli.ClaudeCliError) as ctx:
                claude_cli.generate("prompt")

        run.assert_not_called()
        self.assertIn("claude.ai/install.sh", str(ctx.exception))

    def test_non_zero_exit_code_includes_stderr(self):
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess,
                "run",
                return_value=_completed(stderr="usage limit reached", returncode=1),
            ),
        ):
            with self.assertRaises(claude_cli.ClaudeCliError) as ctx:
                claude_cli.generate("prompt")

        self.assertIn("usage limit reached", str(ctx.exception))

    def test_timeout_is_reported_as_provider_error(self):
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300),
            ),
        ):
            with self.assertRaises(claude_cli.ClaudeCliError) as ctx:
                claude_cli.generate("prompt", timeout=300)

        self.assertIn("timed out", str(ctx.exception))

    def test_error_payload_is_rejected(self):
        """CLI 以 0 退出但 is_error 为真时，内容不能当作脚本继续使用。"""
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess,
                "run",
                return_value=_completed(_payload("rate limited", is_error=True)),
            ),
        ):
            with self.assertRaises(claude_cli.ClaudeCliError) as ctx:
                claude_cli.generate("prompt")

        self.assertIn("rate limited", str(ctx.exception))

    def test_invalid_json_is_rejected(self):
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess,
                "run",
                return_value=_completed("not json at all"),
            ),
        ):
            with self.assertRaises(claude_cli.ClaudeCliError):
                claude_cli.generate("prompt")

    def test_blank_result_is_rejected(self):
        with (
            patch.object(claude_cli.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                claude_cli.subprocess,
                "run",
                return_value=_completed(_payload("   ")),
            ),
        ):
            with self.assertRaises(claude_cli.ClaudeCliError):
                claude_cli.generate("prompt")


if __name__ == "__main__":
    unittest.main()
