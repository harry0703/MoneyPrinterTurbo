import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_SCRIPT = (
    Path(__file__).parent.parent.parent / "docs" / "skill" / "mpt_agent.py"
)
SKILL_DOCUMENT = SKILL_SCRIPT.with_name("SKILL.md")
SPEC = importlib.util.spec_from_file_location("mpt_agent_skill", SKILL_SCRIPT)
mpt_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mpt_agent)


MINIMAL_CONFIG = """\
llm_provider = "moonshot"
moonshot_api_key = ""
deepseek_api_key = ""
pexels_api_keys = []
pixabay_api_keys = []
coverr_api_keys = []
oneapi_api_key = ""
oneapi_base_url = ""
oneapi_model_name = ""
"""


class TestMptAgentSkill(unittest.TestCase):
    def create_project(self, root: Path) -> None:
        """创建足够完成安装和配置检查的最小项目结构。"""
        root.mkdir()
        (root / "cli.py").write_text("", encoding="utf-8")
        (root / "config.example.toml").write_text(
            MINIMAL_CONFIG, encoding="utf-8"
        )

    class FakeHttpResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def test_skill_runs_helper_from_its_working_directory(self):
        """确保 Windows Agent 不会在命令中嵌入易被破坏的绝对路径。"""
        text = SKILL_DOCUMENT.read_text(encoding="utf-8")

        self.assertIn(
            'uv run --no-project --python 3.11 python mpt_agent.py --subject',
            text,
        )
        self.assertIn("workdir=SKILL_DIR", text)
        self.assertNotIn('python "<SKILL_DIR>/mpt_agent.py"', text)

    def test_first_run_only_requests_missing_api_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MoneyPrinterTurbo"
            self.create_project(root)
            output = io.StringIO()

            with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
                code = mpt_agent.main(
                    ["--subject", "人工智能如何改变生活", "--root", str(root)]
                )

            self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
            text = output.getvalue()
            self.assertIn("MPT_NEEDS_INPUT", text)
            self.assertIn("MISSING=moonshot_api_key", text)
            self.assertIn("MISSING=pexels_api_keys", text)
            self.assertIn("LLM_PROVIDER_OPTION=deepseek|DeepSeek|", text)
            self.assertIn(
                "LLM_PROVIDER_OPTION=oneapi|Other OpenAI-compatible provider|",
                text,
            )
            self.assertNotIn("Alibaba Cloud Qwen", text)
            self.assertNotIn("Microsoft Azure OpenAI", text)
            self.assertNotIn("xAI Grok", text)
            self.assertIn(
                f"PEXELS_API_KEY_URL={mpt_agent.PEXELS_API_KEY_URL}", text
            )

    def test_environment_keys_are_written_without_being_logged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
            output = io.StringIO()
            llm_key = "secret-llm-key"
            pexels_key = "secret-pexels-key"

            with patch.dict(
                os.environ,
                {
                    "MPT_LLM_PROVIDER": "deepseek",
                    "MPT_LLM_API_KEY": llm_key,
                    "MPT_PEXELS_API_KEY": pexels_key,
                },
                clear=True,
            ), redirect_stdout(output):
                mpt_agent.apply_environment_config(config_path)

            config = config_path.read_text(encoding="utf-8")
            self.assertIn('llm_provider = "deepseek"', config)
            self.assertIn(f'deepseek_api_key = "{llm_key}"', config)
            self.assertIn(f'pexels_api_keys = ["{pexels_key}"]', config)
            self.assertNotIn(llm_key, output.getvalue())
            self.assertNotIn(pexels_key, output.getvalue())

    def test_material_key_check_matches_selected_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ).replace("pixabay_api_keys = []", 'pixabay_api_keys = ["key"]'),
                encoding="utf-8",
            )

            _, default_missing = mpt_agent.missing_config(config_path, [])
            _, pixabay_missing = mpt_agent.missing_config(
                config_path, ["--video-source", "pixabay"]
            )

            self.assertEqual(default_missing, ["pexels_api_keys"])
            self.assertEqual(pixabay_missing, [])

    def test_existing_provider_key_is_reused_without_asking_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            secret = "already-configured-deepseek-key"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'deepseek_api_key = ""', f'deepseek_api_key = "{secret}"'
                ).replace("pexels_api_keys = []", 'pexels_api_keys = ["key"]'),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                provider = mpt_agent.reuse_existing_llm_provider(config_path)
            _, missing = mpt_agent.missing_config(config_path, [])

            self.assertEqual(provider, "deepseek")
            self.assertEqual(missing, [])
            self.assertIn(
                'llm_provider = "deepseek"',
                config_path.read_text(encoding="utf-8"),
            )
            self.assertNotIn(secret, output.getvalue())

    def test_only_missing_pexels_key_does_not_ask_for_llm_again(self):
        output = io.StringIO()

        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "deepseek", ["pexels_api_keys"]
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(f"PEXELS_API_KEY_URL={mpt_agent.PEXELS_API_KEY_URL}", text)
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_custom_openai_compatible_provider_requires_connection_details(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'llm_provider = "moonshot"', 'llm_provider = "oneapi"'
                ).replace('oneapi_api_key = ""', 'oneapi_api_key = "key"'),
                encoding="utf-8",
            )

            provider, missing = mpt_agent.missing_config(config_path, [])
            output = io.StringIO()
            with redirect_stdout(output):
                mpt_agent.report_missing_config(provider, missing)

            self.assertEqual(provider, "oneapi")
            self.assertEqual(
                missing,
                ["oneapi_base_url", "oneapi_model_name", "pexels_api_keys"],
            )
            self.assertIn("OPENAI_COMPATIBLE_REQUIRED=", output.getvalue())

    def test_custom_openai_compatible_environment_is_mapped_to_oneapi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "MPT_LLM_PROVIDER": "openai_compatible",
                    "MPT_LLM_API_KEY": "custom-key",
                    "MPT_LLM_BASE_URL": "https://llm.example.com/v1",
                    "MPT_LLM_MODEL_NAME": "example-model",
                },
                clear=True,
            ):
                mpt_agent.apply_environment_config(config_path)

            config = config_path.read_text(encoding="utf-8")
            self.assertIn('llm_provider = "oneapi"', config)
            self.assertIn('oneapi_api_key = "custom-key"', config)
            self.assertIn(
                'oneapi_base_url = "https://llm.example.com/v1"', config
            )
            self.assertIn('oneapi_model_name = "example-model"', config)

    def test_zip_extraction_rejects_parent_directory_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "unsafe.zip"
            destination = Path(temp_dir) / "extract"
            destination.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")

            with zipfile.ZipFile(archive_path) as archive, self.assertRaises(
                mpt_agent.SkillError
            ):
                mpt_agent._safe_extract(archive, destination)

    def test_pexels_validation_filters_rejected_keys_without_logging_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            bad_key = "rejected-secret-key"
            good_key = "valid-secret-key"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    "pexels_api_keys = []",
                    f'pexels_api_keys = ["{bad_key}", "{good_key}"]',
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            def validate(request, timeout):
                self.assertEqual(
                    request.full_url, mpt_agent.PEXELS_VALIDATION_URL
                )
                if request.get_header("Authorization") == bad_key:
                    raise mpt_agent.urllib.error.HTTPError(
                        request.full_url, 401, "Unauthorized", None, None
                    )
                return self.FakeHttpResponse()

            with patch.object(
                mpt_agent.urllib.request, "urlopen", side_effect=validate
            ), redirect_stdout(output):
                valid = mpt_agent.validate_pexels_config(config_path, [])

            config = config_path.read_text(encoding="utf-8")
            self.assertTrue(valid)
            self.assertNotIn(bad_key, config)
            self.assertIn(good_key, config)
            self.assertNotIn(bad_key, output.getvalue())
            self.assertNotIn(good_key, output.getvalue())

    def test_pexels_validation_requests_new_key_when_all_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    "pexels_api_keys = []", 'pexels_api_keys = ["bad-key"]'
                ),
                encoding="utf-8",
            )
            error = mpt_agent.urllib.error.HTTPError(
                mpt_agent.PEXELS_VALIDATION_URL,
                403,
                "Forbidden",
                None,
                None,
            )

            with patch.object(
                mpt_agent.urllib.request, "urlopen", side_effect=error
            ):
                valid = mpt_agent.validate_pexels_config(config_path, [])

            self.assertFalse(valid)

    def test_generation_returns_only_non_empty_final_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_id = "12345678-1234-1234-1234-123456789abc"

            def finish_cli(command, **kwargs):
                task_dir = root / "storage" / "tasks" / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "final-1.mp4").write_bytes(b"video")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(mpt_agent.shutil, "which", return_value="uv"),
                patch.object(mpt_agent, "run_checked"),
                patch.object(mpt_agent.uuid, "uuid4", return_value=task_id),
                patch.object(
                    mpt_agent.subprocess, "run", side_effect=finish_cli
                ) as run_mock,
            ):
                videos, task_dir, log_path, result_path = mpt_agent.generate_video(
                    root,
                    "测试主题",
                    ["--video-aspect", "16:9", "--stop-at", "script"],
                )

            self.assertEqual(videos, [(task_dir / "final-1.mp4").resolve()])
            self.assertTrue(log_path.name.startswith("run-"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["video_files"], [str(videos[0])])
            command = run_mock.call_args.args[0]
            voice_index = command.index("--voice-name")
            self.assertEqual(
                command[voice_index + 1], mpt_agent.DEFAULT_VOICE_NAME
            )
            self.assertEqual(command[-2:], ["--stop-at", "video"])

    def test_generation_failure_prints_original_model_error(self):
        """生成失败时保留模型原始错误，避免 Skill 层猜测供应商语义。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_id = "12345678-1234-1234-1234-123456789abc"
            model_error = "provider error: model is unavailable for this account"
            stderr = io.StringIO()

            def reject_model(command, **kwargs):
                kwargs["stdout"].write(model_error + "\n")
                return SimpleNamespace(returncode=1)

            with (
                patch.object(mpt_agent.shutil, "which", return_value="uv"),
                patch.object(mpt_agent, "run_checked"),
                patch.object(mpt_agent.uuid, "uuid4", return_value=task_id),
                patch.object(mpt_agent.subprocess, "run", side_effect=reject_model),
                redirect_stderr(stderr),
                self.assertRaises(mpt_agent.SkillError),
            ):
                mpt_agent.generate_video(root, "测试主题", [])

            self.assertIn(model_error, stderr.getvalue())
            result = json.loads(
                mpt_agent.result_manifest_path(root).read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "failed")

    def test_successful_dependency_sync_does_not_print_package_list(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = SimpleNamespace(
            returncode=0,
            stdout="Installed package-a\nInstalled package-b\n",
        )

        with patch.object(
            mpt_agent.subprocess, "run", return_value=result
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())

        self.assertNotIn("package-a", stdout.getvalue())
        self.assertNotIn("package-a", stderr.getvalue())

    def test_explicit_voice_is_not_overridden(self):
        self.assertTrue(
            mpt_agent.has_cli_option(
                ["--voice-name", "en-US-JennyNeural-Female"], "--voice-name"
            )
        )
        self.assertTrue(
            mpt_agent.has_cli_option(
                ["--voice-name=en-US-JennyNeural-Female"], "--voice-name"
            )
        )


if __name__ == "__main__":
    unittest.main()
