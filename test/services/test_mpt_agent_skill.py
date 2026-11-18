import ast
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models.llm_provider import LLM_PROVIDER_REGISTRY


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
volcengine_seedance_api_key = ""
ofox_api_key = ""
metaso_minimax_api_key = ""
muapi_api_key = ""
useapi_api_token = ""
infistar_video_api_key = ""
jalapeno_api_key = ""
jalapeno_video_api_key = ""
openai_image_base_url = ""
openai_image_model = ""
openai_image_api_keys = []
oneapi_api_key = ""
oneapi_base_url = ""
oneapi_model_name = ""
"""


class TestMptAgentSkill(unittest.TestCase):
    def test_repeated_source_options_follow_the_actual_cli_last_value(self):
        import cli

        for last_source in ("local", "pexels"):
            first_source = "pexels" if last_source == "local" else "local"
            for first_equals in (False, True):
                for last_equals in (False, True):
                    with self.subTest(last_source=last_source, first_equals=first_equals, last_equals=last_equals):
                        forwarded = ([f"--video-source={first_source}"] if first_equals
                                     else ["--video-source", first_source])
                        forwarded += ([f"--video-source={last_source}"] if last_equals
                                      else ["--video-source", last_source])
                        if last_source == "local":
                            forwarded += ["--video-materials", "./owned.mp4"]
                        actual = cli.parse_args(["--video-subject", "owned topic", *forwarded])
                        parsed = mpt_agent.parse_args(["--subject", "owned topic", "--", *forwarded])
                        self.assertEqual(parsed.cli_args, forwarded)
                        self.assertEqual(mpt_agent.selected_video_source(parsed.cli_args), actual.video_source)
                        with tempfile.TemporaryDirectory() as temp_dir:
                            config = Path(temp_dir) / "config.toml"
                            text = '[app]\nllm_provider = "ollama"\n'
                            if last_source == "pexels":
                                text += 'pexels_api_keys = ["owned-fixture-key"]\n'
                            config.write_text(text, encoding="utf-8")
                            provider, missing = mpt_agent.missing_config(config, parsed.cli_args)
                            self.assertEqual((provider, missing), ("ollama", []))

    def test_helper_main_accepts_keyless_local_override_after_source_defaults(self):
        for forwarded in (
            ["--video-source", "pexels", "--video-source=local", "--video-materials", "./owned.mp4"],
            ["--video-source=pexels", "--video-source", "local", "--video-materials", "./owned.mp4"],
        ):
            with self.subTest(forwarded=forwarded), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "project"
                self.create_project(root)
                (root / "config.toml").write_text('[app]\nllm_provider = "ollama"\n', encoding="utf-8")
                video, task, log = root / "owned.mp4", root / "task", root / "log"
                video.write_bytes(b"owned output boundary fixture")
                manifest = root / "result.json"
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch.object(mpt_agent, "validate_pexels_config", wraps=mpt_agent.validate_pexels_config) as validation,
                    patch.object(mpt_agent, "generate_video", return_value=([video], task, log, manifest)) as generate,
                    patch.object(mpt_agent.urllib.request, "urlopen", side_effect=AssertionError("local source must not probe Pexels")),
                    redirect_stdout(io.StringIO()),
                ):
                    status = mpt_agent.main(["--subject", "owned topic", "--root", str(root), "--", *forwarded])
                self.assertEqual(status, 0)
                validation.assert_called_once()
                generate.assert_called_once_with(root.resolve(), "owned topic", forwarded)

    def test_source_option_default_and_single_value_controls(self):
        import cli

        for forwarded in ([], ["--video-source", "pexels"], ["--video-source=pexels"],
                          ["--video-source", "local", "--video-materials", "./owned.mp4"]):
            with self.subTest(forwarded=forwarded):
                actual = cli.parse_args(["--video-subject", "owned topic", *forwarded])
                self.assertEqual(mpt_agent.selected_video_source(forwarded), actual.video_source)

    def create_project(self, root: Path) -> None:
        """Create the minimal project structure needed to finish install and config checks."""
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

    def test_toml_literal_provider_and_multiline_key_arrays(self):
        # These are valid TOML configurations understood by the backend loader.
        for text in (
            "[app]\nllm_provider = 'ollama'\npexels_api_keys = [\n 'fixture#key', # comment\n]\n",
            '[app]\n"llm_provider" = "ollama"\npexels_api_keys = ["fixture#key"]\n',
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / "config.toml"
                config_path.write_text(text, encoding="utf-8")
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(mpt_agent.reuse_existing_llm_provider(config_path), "ollama")
                    self.assertEqual(mpt_agent.missing_config(config_path, ["--video-source", "local", "--video-materials", directory]), ("ollama", []))
                    with patch.object(mpt_agent, "_validate_pexels_key", return_value="valid") as validate:
                        self.assertTrue(mpt_agent.validate_pexels_config(config_path, []))
                    validate.assert_called_once_with("fixture#key")
                self.assertEqual(config_path.read_text(encoding="utf-8"), text)

    def test_config_reader_uses_app_table_not_unrelated_provider_fields(self):
        text = "[other]\nllm_provider = 'moonshot'\n[app]\nllm_provider = 'ollama'\n"
        self.assertEqual(mpt_agent._plain_config_value(text, "llm_provider"), "ollama")

    def test_config_reader_reports_invalid_toml_without_echoing_contents(self):
        with self.assertRaises(mpt_agent.SkillError) as error:
            mpt_agent._plain_config_value("[app]\nllm_provider = 'fixture\n", "llm_provider")
        self.assertNotIn("fixture", str(error.exception))
        self.assertIn("TOML", str(error.exception))

    def test_skill_runs_helper_from_its_working_directory(self):
        """Make sure the Windows Agent doesn't embed fragile absolute paths in commands."""
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
            seedance_key = "secret-ark-key"
            metaso_key = "secret-metaso-key"
            muapi_key = "secret-muapi-key"
            useapi_token = "secret-useapi-token"

            with patch.dict(
                os.environ,
                {
                    "MPT_LLM_PROVIDER": "deepseek",
                    "MPT_LLM_API_KEY": llm_key,
                    "MPT_PEXELS_API_KEY": pexels_key,
                    "MPT_VOLCENGINE_ARK_API_KEY": seedance_key,
                    "MPT_METASO_MINIMAX_API_KEY": metaso_key,
                    "MPT_MUAPI_API_KEY": muapi_key,
                    "MPT_USEAPI_TOKEN": useapi_token,
                },
                clear=True,
            ), redirect_stdout(output):
                mpt_agent.apply_environment_config(config_path)

            config = config_path.read_text(encoding="utf-8")
            self.assertIn('llm_provider = "deepseek"', config)
            self.assertIn(f'deepseek_api_key = "{llm_key}"', config)
            self.assertIn(f'pexels_api_keys = ["{pexels_key}"]', config)
            self.assertIn(
                f'volcengine_seedance_api_key = "{seedance_key}"', config
            )
            self.assertIn(f'metaso_minimax_api_key = "{metaso_key}"', config)
            self.assertIn(f'muapi_api_key = "{muapi_key}"', config)
            self.assertIn(f'useapi_api_token = "{useapi_token}"', config)
            self.assertNotIn(useapi_token, output.getvalue())
            self.assertNotIn(llm_key, output.getvalue())
            self.assertNotIn(pexels_key, output.getvalue())
            self.assertNotIn(seedance_key, output.getvalue())
            self.assertNotIn(metaso_key, output.getvalue())
            self.assertNotIn(muapi_key, output.getvalue())

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

    def test_local_video_source_requires_video_materials(self):
        """The local material source must provide --video-materials, otherwise it should fail early."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                mpt_agent.SkillError, "--video-materials"
            ):
                mpt_agent.missing_config(config_path, ["--video-source", "local"])

            _, missing = mpt_agent.missing_config(
                config_path,
                ["--video-source", "local", "--video-materials", "./clips"],
            )
            _, missing_eq = mpt_agent.missing_config(
                config_path,
                ["--video-source=local", "--video-materials=./clips"],
            )
            self.assertEqual(missing, [])
            self.assertEqual(missing_eq, [])

    def test_openai_image_source_accepts_keyless_local_gateway(self):
        """The text-to-image material source only needs the endpoint and model name; local gateways may have no API Key configured."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                )
                .replace(
                    'openai_image_base_url = ""',
                    'openai_image_base_url = "http://127.0.0.1:7860/v1"',
                )
                .replace(
                    'openai_image_model = ""', 'openai_image_model = "local-sd"'
                ),
                encoding="utf-8",
            )

            _, missing = mpt_agent.missing_config(
                config_path, ["--video-source", "openai_image"]
            )

            self.assertEqual(missing, [])

    def test_missing_openai_image_inputs_report_endpoint_and_model(self):
        """When the endpoint or model name is missing, the field name must be reported, and the optional Key must not be treated as missing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            _, missing = mpt_agent.missing_config(
                config_path, ["--video-source", "openai_image"]
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = mpt_agent.report_missing_config("moonshot", missing)

            self.assertEqual(
                missing, ["openai_image_base_url", "openai_image_model"]
            )
            self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
            self.assertIn("OPENAI_IMAGE_REQUIRED=", output.getvalue())
            self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", output.getvalue())

    def test_ofox_source_requires_key_and_explicit_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "ofox"]
                )
            self.assertEqual(missing, ["ofox_api_key", "confirm_ofox_charge"])

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'ofox_api_key = ""', 'ofox_api_key = "configured"'
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _, confirmed_missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "ofox", "--confirm-ofox-charge"],
                )
            self.assertEqual(confirmed_missing, [])

    def test_ofox_source_accepts_the_provider_specific_environment_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"OFOX_API_KEY": "environment-ofox-key"},
                clear=True,
            ):
                _, missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "ofox", "--confirm-ofox-charge"],
                )

            self.assertEqual(missing, [])

    def test_ofox_environment_key_is_written_without_leaking_to_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
            ofox_key = "secret-ofox-key"
            output = io.StringIO()

            with patch.dict(
                os.environ,
                {"MPT_OFOX_API_KEY": ofox_key},
                clear=True,
            ), redirect_stdout(output):
                mpt_agent.apply_environment_config(config_path)

            config = config_path.read_text(encoding="utf-8")
            self.assertIn(f'ofox_api_key = "{ofox_key}"', config)
            self.assertNotIn(ofox_key, output.getvalue())

    def test_missing_ofox_inputs_report_signup_and_charge_flag(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "deepseek",
                ["ofox_api_key", "confirm_ofox_charge"],
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(f"OFOX_API_KEY_URL={mpt_agent.OFOX_API_KEY_URL}", text)
        self.assertIn(
            "OFOX_CHARGE_CONFIRMATION_REQUIRED=--confirm-ofox-charge", text
        )
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_wavespeed_source_requires_its_own_key_and_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_text = MINIMAL_CONFIG.replace(
                'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
            ).replace(
                "pexels_api_keys = []",
                "pexels_api_keys = []\nwavespeed_api_keys = []",
            )
            config_path.write_text(config_text, encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "wavespeed"]
                )
            self.assertEqual(
                missing, ["wavespeed_api_keys", "confirm_wavespeed_charge"]
            )

            config_path.write_text(
                config_text.replace(
                    "wavespeed_api_keys = []", 'wavespeed_api_keys = ["configured"]'
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _, confirmed_missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "wavespeed", "--confirm-wavespeed-charge"],
                )
            self.assertEqual(confirmed_missing, [])

    def test_missing_wavespeed_inputs_report_the_charge_flag(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "moonshot",
                ["wavespeed_api_keys", "confirm_wavespeed_charge"],
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(
            "WAVESPEED_CHARGE_CONFIRMATION_REQUIRED=--confirm-wavespeed-charge",
            text,
        )
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_supported_sources_match_the_cli_video_source_list(self):
        """The helper's source allowlist must be the same set as _CLI_VIDEO_SOURCES in cli.py.

        The list hand-copied into the script once missed wavespeed: the CLI accepted the source while the helper reported
        "unsupported video source". The expected value is derived from the authoritative constant, so it fails first when a source is added.
        """
        tree = ast.parse(
            (SKILL_SCRIPT.parents[2] / "cli.py").read_text(encoding="utf-8")
        )
        cli_sources = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name)
                and target.id == "_CLI_VIDEO_SOURCES"
                for target in node.targets
            ):
                cli_sources = set(ast.literal_eval(node.value))
                break

        self.assertIsNotNone(cli_sources)
        self.assertEqual(set(mpt_agent.SUPPORTED_SOURCES), cli_sources)

    def test_seedance_source_requires_key_and_explicit_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            _, missing = mpt_agent.missing_config(
                config_path, ["--video-source", "volcengine_seedance"]
            )
            self.assertEqual(
                missing,
                ["volcengine_seedance_api_key", "confirm_seedance_charge"],
            )

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'volcengine_seedance_api_key = ""',
                    'volcengine_seedance_api_key = "configured"',
                ),
                encoding="utf-8",
            )
            _, confirmed_missing = mpt_agent.missing_config(
                config_path,
                [
                    "--video-source",
                    "volcengine_seedance",
                    "--confirm-seedance-charge",
                ],
            )
            self.assertEqual(confirmed_missing, [])

    def test_seedance_source_accepts_the_official_specific_environment_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"VOLCENGINE_ARK_API_KEY": "environment-ark-key"},
                clear=True,
            ):
                _, missing = mpt_agent.missing_config(
                    config_path,
                    [
                        "--video-source",
                        "volcengine_seedance",
                        "--confirm-seedance-charge",
                    ],
                )

            self.assertEqual(missing, [])

    def test_metaso_source_requires_its_own_key_and_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            _, missing = mpt_agent.missing_config(
                config_path, ["--video-source", "metaso_minimax"]
            )
            self.assertEqual(
                missing,
                ["metaso_minimax_api_key", "confirm_metaso_minimax_charge"],
            )

            with patch.dict(
                os.environ,
                {"METASO_MINIMAX_API_KEY": "environment-metaso-key"},
                clear=True,
            ):
                _, confirmed_missing = mpt_agent.missing_config(
                    config_path,
                    [
                        "--video-source",
                        "metaso_minimax",
                        "--confirm-metaso-minimax-charge",
                    ],
                )
            self.assertEqual(confirmed_missing, [])

    def test_muapi_source_requires_its_own_key_and_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "muapi"]
                )
            self.assertEqual(missing, ["muapi_api_key", "confirm_muapi_charge"])

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'muapi_api_key = ""', 'muapi_api_key = "configured"'
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _, confirmed_missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "muapi", "--confirm-muapi-charge"],
                )
            self.assertEqual(confirmed_missing, [])

    def test_muapi_source_accepts_provider_environment_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"MUAPI_API_KEY": "environment-muapi-key"},
                clear=True,
            ):
                _, missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "muapi", "--confirm-muapi-charge"],
                )
            self.assertEqual(missing, [])

    def test_useapi_source_requires_its_own_token_and_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "useapi"]
                )
            self.assertEqual(missing, ["useapi_api_token", "confirm_useapi_charge"])

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'useapi_api_token = ""', 'useapi_api_token = "configured"'
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _, confirmed_missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "useapi", "--confirm-useapi-charge"],
                )
            self.assertEqual(confirmed_missing, [])

    def test_useapi_image_source_requires_the_shared_token_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "useapi_image"]
                )
            self.assertEqual(missing, ["useapi_api_token"])
            with patch.dict(os.environ, {"USEAPI_TOKEN": "env-token"}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "useapi_image"]
                )
            self.assertEqual(missing, [])

    def test_useapi_kling_image_model_requires_charge_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ).replace(
                    'useapi_api_token = ""',
                    'useapi_api_token = "configured"\n'
                    'useapi_image_model = "kling-omni-image-v3"',
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _, missing = mpt_agent.missing_config(
                    config_path, ["--video-source", "useapi_image"]
                )
                self.assertEqual(missing, ["confirm_useapi_charge"])
                _, missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "useapi_image", "--confirm-useapi-charge"],
                )
                self.assertEqual(missing, [])

    def test_useapi_source_accepts_provider_environment_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'moonshot_api_key = ""', 'moonshot_api_key = "configured"'
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"USEAPI_TOKEN": "environment-useapi-token"},
                clear=True,
            ):
                _, missing = mpt_agent.missing_config(
                    config_path,
                    ["--video-source", "useapi", "--confirm-useapi-charge"],
                )
            self.assertEqual(missing, [])

    def test_infistar_source_uses_video_credentials_and_charge_confirmation(self):
        """Preflight and the actual video service use the same credentials and must not misuse the Infistar LLM Key."""
        from app.services import infistar_video

        cases = (
            ("", "", False, ["infistar_video_api_key", "confirm_infistar_charge"]),
            ("", "", True, ["infistar_video_api_key"]),
            ("video-key", "", False, ["confirm_infistar_charge"]),
            ("video-key", "", True, []),
            ("", "environment-video-key", True, []),
            ("  ", "environment-video-key", True, []),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            for key, environment_key, confirmed, expected in cases:
                settings = {
                    "llm_provider": "ollama",
                    "infistar_api_key": "llm-only-key",
                    "infistar_video_api_key": key,
                }
                config_path.write_text(
                    "[app]\n" + "\n".join(
                        f"{field} = {json.dumps(value)}"
                        for field, value in settings.items()
                    ),
                    encoding="utf-8",
                )
                args = ["--video-source", "infistar"]
                if confirmed:
                    args.append("--confirm-infistar-charge")
                with (
                    self.subTest(key=key, environment_key=environment_key, confirmed=confirmed),
                    patch.dict(os.environ, {"INFISTAR_VIDEO_API_KEY": environment_key}, clear=True),
                ):
                    provider, missing = mpt_agent.missing_config(config_path, args)
                    self.assertEqual(provider, "ollama")
                    self.assertEqual(missing, expected)
                    self.assertEqual(
                        "infistar_video_api_key" not in missing,
                        infistar_video.is_enabled(settings),
                    )

    def test_infistar_environment_key_is_written_without_leaking_to_output(self):
        """Agent-specific environment variables should be written into the separate video config, and logs must not contain keys."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
            secret = "secret-infistar-video-key"
            output = io.StringIO()
            with (
                patch.dict(os.environ, {"MPT_INFISTAR_VIDEO_API_KEY": secret}, clear=True),
                redirect_stdout(output),
            ):
                mpt_agent.apply_environment_config(config_path)
            self.assertEqual(
                mpt_agent._plain_config_value(config_path.read_text(), "infistar_video_api_key"),
                secret,
            )
            self.assertNotIn(secret, output.getvalue())
            self.assertIn("infistar_video_api_key", output.getvalue())

    def test_missing_infistar_inputs_report_video_key_and_charge_flag(self):
        """When only the video access info is missing, it shouldn't wrongly suggest switching the LLM Provider."""
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "ollama", ["infistar_video_api_key", "confirm_infistar_charge"]
            )
        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn("INFISTAR_VIDEO_API_KEY_URL=https://infistar.cc/keys", text)
        self.assertIn("INFISTAR_VIDEO_API_KEY_ENV=MPT_INFISTAR_VIDEO_API_KEY", text)
        self.assertIn(
            "INFISTAR_CHARGE_CONFIRMATION_REQUIRED=--confirm-infistar-charge", text
        )
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_jalapeno_source_uses_same_shared_or_independent_key_as_runtime(self):
        from app.services import jalapeno_video

        cases = (
            ("ollama", "", "", "", False, ["jalapeno_video_api_key", "confirm_jalapeno_charge"]),
            ("openai", "video", "", "", True, []),
            ("openai", "", "environment", "", True, []),
            ("openai", "", "", "shared", True, []),
            ("jalapeno", "", "", "", True, ["jalapeno_api_key"]),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for provider, dedicated, environment, shared, confirmed, expected in cases:
                settings = {
                    "llm_provider": provider,
                    "openai_api_key": "unrelated",
                    "jalapeno_api_key": shared,
                    "jalapeno_video_api_key": dedicated,
                }
                path.write_text("[app]\n" + "\n".join(
                    f"{name} = {json.dumps(value)}" for name, value in settings.items()
                ), encoding="utf-8")
                args = ["--video-source", "jalapeno"]
                if confirmed:
                    args.append("--confirm-jalapeno-charge")
                with (
                    self.subTest(provider=provider, dedicated=dedicated, environment=environment, shared=shared),
                    patch.dict(os.environ, {"JALAPENO_VIDEO_API_KEY": environment}, clear=True),
                ):
                    self.assertEqual(mpt_agent.missing_config(path, args), (provider, expected))
                    self.assertEqual(jalapeno_video.is_enabled(settings), bool(dedicated or environment or shared))

    def test_jalapeno_environment_key_and_missing_input_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(MINIMAL_CONFIG, encoding="utf-8")
            output = io.StringIO()
            secret = "secret-jalapeno-test-key"
            with (
                patch.dict(os.environ, {"MPT_JALAPENO_VIDEO_API_KEY": secret}, clear=True),
                redirect_stdout(output),
            ):
                mpt_agent.apply_environment_config(path)
                code = mpt_agent.report_missing_config(
                    "ollama", ["jalapeno_video_api_key", "confirm_jalapeno_charge"]
                )
            self.assertEqual(mpt_agent._plain_config_value(path.read_text(), "jalapeno_video_api_key"), secret)
            self.assertNotIn(secret, output.getvalue())
            self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
            self.assertIn("JALAPENO_API_KEY_URL=https://www.jalapeno-cloud.ai/MoneyPrinterTurbo", output.getvalue())
            self.assertIn("JALAPENO_VIDEO_API_KEY_ENV=MPT_JALAPENO_VIDEO_API_KEY", output.getvalue())
            self.assertIn("JALAPENO_CHARGE_CONFIRMATION_REQUIRED=--confirm-jalapeno-charge", output.getvalue())
            self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", output.getvalue())

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

    def test_keyless_providers_stay_aligned_with_the_provider_registry(self):
        """The helper script's no-Key set must stay consistent with the Provider registry."""
        registry_keyless = {
            provider.provider_id
            for provider in LLM_PROVIDER_REGISTRY
            if not provider.requires_api_key
        }

        self.assertEqual(mpt_agent.KEYLESS_LLM_PROVIDERS, registry_keyless)

    def test_claude_code_subscription_provider_needs_no_api_key(self):
        """
        Claude Code uses the local subscription, so the helper script must no longer require an API Key that doesn't exist.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'llm_provider = "moonshot"', 'llm_provider = "claude_code"'
                ).replace(
                    'deepseek_api_key = ""',
                    'deepseek_api_key = "already-configured-key"',
                ).replace("pexels_api_keys = []", 'pexels_api_keys = ["pexels-key"]'),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                provider = mpt_agent.reuse_existing_llm_provider(config_path)
            active_provider, missing = mpt_agent.missing_config(config_path, [])

            # Even if another Provider already has a Key configured, subscription users must not be quietly switched away.
            self.assertEqual(provider, "claude_code")
            self.assertEqual(active_provider, "claude_code")
            self.assertEqual(missing, [])
            self.assertIn(
                'llm_provider = "claude_code"',
                config_path.read_text(encoding="utf-8"),
            )

    def test_codex_subscription_provider_needs_no_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'llm_provider = "moonshot"', 'llm_provider = "openai_codex"'
                ).replace(
                    'deepseek_api_key = ""', 'deepseek_api_key = "other-provider-key"'
                ).replace("pexels_api_keys = []", 'pexels_api_keys = ["pexels-key"]')
                + 'openai_codex_model_name = "selected-model"\n',
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                provider = mpt_agent.reuse_existing_llm_provider(config_path)
            active, missing = mpt_agent.missing_config(config_path, [])
            self.assertEqual(provider, "openai_codex")
            self.assertEqual(active, "openai_codex")
            self.assertEqual(missing, [])

    def test_kimi_code_signed_in_provider_needs_no_api_key(self):
        """
        Kimi Code uses OAuth subscription credentials, so when logged in the helper script must not require an API Key,
        nor switch subscription users to another Provider.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'llm_provider = "moonshot"', 'llm_provider = "kimi_code"'
                ).replace(
                    'deepseek_api_key = ""',
                    'deepseek_api_key = "already-configured-key"',
                ).replace(
                    "pexels_api_keys = []", 'pexels_api_keys = ["pexels-key"]'
                )
                + 'kimi_code_refresh_token = "rt-1"\n',
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                provider = mpt_agent.reuse_existing_llm_provider(config_path)
            active_provider, missing = mpt_agent.missing_config(config_path, [])

            self.assertEqual(provider, "kimi_code")
            self.assertEqual(active_provider, "kimi_code")
            self.assertEqual(missing, [])

    def test_kimi_code_without_sign_in_reports_sign_in_not_api_key(self):
        """For an unauthenticated Kimi Code, what's missing is the login action; the script should report sign-in rather than an API Key."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    'llm_provider = "moonshot"', 'llm_provider = "kimi_code"'
                ).replace(
                    'deepseek_api_key = ""',
                    'deepseek_api_key = "already-configured-key"',
                ).replace(
                    "pexels_api_keys = []", 'pexels_api_keys = ["pexels-key"]'
                ),
                encoding="utf-8",
            )

            active_provider, missing = mpt_agent.missing_config(config_path, [])
            output = io.StringIO()
            with redirect_stdout(output):
                mpt_agent.report_missing_config(active_provider, missing)

            self.assertEqual(active_provider, "kimi_code")
            self.assertEqual(missing, ["kimi_code_sign_in"])
            self.assertNotIn("kimi_code_api_key", output.getvalue())
            self.assertIn("KIMI_CODE_SIGN_IN_REQUIRED", output.getvalue())

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

    def test_missing_seedance_inputs_report_ark_signup_and_charge_flag(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "deepseek",
                ["volcengine_seedance_api_key", "confirm_seedance_charge"],
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(
            f"VOLCENGINE_ARK_API_KEY_URL={mpt_agent.VOLCENGINE_ARK_API_KEY_URL}",
            text,
        )
        self.assertIn(
            "SEEDANCE_CHARGE_CONFIRMATION_REQUIRED=--confirm-seedance-charge",
            text,
        )
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_missing_metaso_inputs_report_key_environment_and_charge_flag(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "deepseek",
                ["metaso_minimax_api_key", "confirm_metaso_minimax_charge"],
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(
            "METASO_MINIMAX_API_KEY_ENV=MPT_METASO_MINIMAX_API_KEY", text
        )
        self.assertIn(
            "METASO_MINIMAX_CHARGE_CONFIRMATION_REQUIRED="
            "--confirm-metaso-minimax-charge",
            text,
        )
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_missing_muapi_inputs_report_key_environment_and_charge_flag(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "deepseek", ["muapi_api_key", "confirm_muapi_charge"]
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(f"MUAPI_API_KEY_URL={mpt_agent.MUAPI_API_KEY_URL}", text)
        self.assertIn("MUAPI_API_KEY_ENV=MPT_MUAPI_API_KEY", text)
        self.assertIn(
            "MUAPI_CHARGE_CONFIRMATION_REQUIRED=--confirm-muapi-charge", text
        )
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_missing_useapi_inputs_report_token_environment_and_charge_flag(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = mpt_agent.report_missing_config(
                "deepseek", ["useapi_api_token", "confirm_useapi_charge"]
            )

        text = output.getvalue()
        self.assertEqual(code, mpt_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(f"USEAPI_TOKEN_URL={mpt_agent.USEAPI_TOKEN_URL}", text)
        self.assertIn("utm_source=moneyprinterturbo", mpt_agent.USEAPI_TOKEN_URL)
        self.assertIn("USEAPI_TOKEN_ENV=MPT_USEAPI_TOKEN", text)
        self.assertIn(
            "USEAPI_CHARGE_CONFIRMATION_REQUIRED=--confirm-useapi-charge", text
        )
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

    def test_runtime_home_config_uses_cli_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config.example.toml").write_text('[app]\nllm_provider = "ollama"\n', encoding="utf-8")
            with patch.dict(os.environ, {"MPT_HOME": "relative-runtime"}):
                config_path = mpt_agent.ensure_config(root)
                self.assertEqual(config_path, root / "relative-runtime" / "config.toml")
                config_path.write_text('[app]\nllm_provider = "existing"\n', encoding="utf-8")
                self.assertEqual(mpt_agent.ensure_config(root).read_text(encoding="utf-8"), '[app]\nllm_provider = "existing"\n')
            self.assertFalse((root / "config.toml").exists())

    def test_generation_uses_runtime_home_for_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_id = "12345678-1234-1234-1234-123456789abc"
            def finish_cli(command, **kwargs):
                task_dir = root / "relative-runtime" / "storage" / "tasks" / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "final-1.mp4").write_bytes(b"video")
                return SimpleNamespace(returncode=0)
            with (
                patch.dict(os.environ, {"MPT_HOME": "relative-runtime"}),
                patch.object(mpt_agent.shutil, "which", return_value="uv"),
                patch.object(mpt_agent, "run_checked"),
                patch.object(mpt_agent.uuid, "uuid4", return_value=task_id),
                patch.object(mpt_agent.subprocess, "run", side_effect=finish_cli),
            ):
                result = mpt_agent.generate_video(root, "topic", [])
                videos, task_dir, _, manifest = result[:4]
            self.assertEqual(task_dir, (root / "relative-runtime" / "storage" / "tasks" / task_id).resolve())
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["video_files"], [str(videos[0])])

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
        """On generation failure keep the model's original error, so the Skill layer doesn't guess provider semantics."""
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

    def test_run_checked_decodes_piped_output_as_utf8(self):
        # run_checked pipes uv's output and re-decodes it with text=True. Without
        # an explicit encoding, that decode follows the host locale (cp936/cp1252),
        # so non-ASCII dependency errors reach the tail as mojibake. PR #1365 pinned
        # every other PIPE-decoding subprocess.run to UTF-8; derive the requirement
        # from the call so a future regression fails here instead of in the field.
        with patch.object(
            mpt_agent.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=""),
        ) as run_mock:
            mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())

        kwargs = run_mock.call_args.kwargs
        self.assertEqual(kwargs.get("stdout"), mpt_agent.subprocess.PIPE)
        self.assertTrue(kwargs.get("text"))
        self.assertEqual(
            kwargs.get("encoding"),
            "utf-8",
            "piped output must be decoded as UTF-8, not the host locale",
        )

    def test_dependency_sync_sets_default_lock_timeout_without_mutating_environment(self):
        """The default only applies to the install subprocess; other environment variables stay unchanged."""
        environment = {"UV_CACHE_DIR": "cache-fixture", "TOKEN": "private-fixture"}
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(
                mpt_agent.subprocess, "run",
                return_value=SimpleNamespace(returncode=0, stdout=""),
            ) as run_mock,
            redirect_stdout(io.StringIO()),
        ):
            mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())
            child_env = run_mock.call_args.kwargs["env"]
            self.assertEqual(child_env["UV_LOCK_TIMEOUT"], "1200")
            self.assertEqual(child_env["UV_CACHE_DIR"], "cache-fixture")
            self.assertEqual(child_env["TOKEN"], "private-fixture")
            self.assertEqual(dict(os.environ), environment)
            self.assertEqual(run_mock.call_args.args[0], ["uv", "sync", "--frozen"])

    def test_dependency_sync_preserves_explicit_lock_timeout(self):
        """User-defined values, including empty or invalid ones, are all left to uv to validate."""
        for value in ("600", "2400", "0", "", "invalid"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"UV_LOCK_TIMEOUT": value}, clear=True),
                patch.object(
                    mpt_agent.subprocess, "run",
                    return_value=SimpleNamespace(returncode=0, stdout=""),
                ) as run_mock,
                redirect_stdout(io.StringIO()),
            ):
                mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())
                self.assertEqual(run_mock.call_args.kwargs["env"]["UV_LOCK_TIMEOUT"], value)
                self.assertEqual(os.environ["UV_LOCK_TIMEOUT"], value)

    def test_dependency_sync_passes_timeout_to_real_child_process(self):
        """Without mocking subprocess, really verify the default and user overrides can be passed to the subprocess."""
        for configured, expected in ((None, "1200"), ("2400", "2400")):
            with self.subTest(configured=configured), patch.dict(os.environ), redirect_stdout(io.StringIO()):
                os.environ.pop("UV_LOCK_TIMEOUT", None)
                if configured is not None:
                    os.environ["UV_LOCK_TIMEOUT"] = configured
                mpt_agent.run_checked(
                    [sys.executable, "-c", "import os,sys; assert os.environ['UV_LOCK_TIMEOUT'] == sys.argv[1]", expected],
                    cwd=Path.cwd(),
                )
                self.assertEqual(os.environ.get("UV_LOCK_TIMEOUT"), configured)

    def test_dependency_lock_timeout_has_actionable_hint_and_bounded_log_tail(self):
        """Reuse the user's actual error; match the full output but still only print the last 30 lines."""
        output = "Timeout (300s) when waiting for lock on pyarrow.lock\n"
        output += "\n".join(f"line-{index}" for index in range(35))
        stderr = io.StringIO()
        with (
            patch.object(
                mpt_agent.subprocess, "run",
                return_value=SimpleNamespace(returncode=1, stdout=output),
            ),
            redirect_stdout(io.StringIO()), redirect_stderr(stderr),
            self.assertRaisesRegex(mpt_agent.SkillError, "exit code 1"),
        ):
            mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())
        text = stderr.getvalue()
        self.assertNotIn("line-0\n", text)
        self.assertNotIn("line-4\n", text)
        self.assertIn("line-5\n", text)
        self.assertIn("line-34\n", text)
        self.assertIn("Wait for other uv installs", text)
        self.assertIn("UV_LOCK_TIMEOUT", text)
        self.assertIn("uv 0.9.4", text)

    def test_dependency_errors_do_not_misreport_cache_lock_timeout(self):
        """Network timeouts, ordinary cache errors and empty output must not be misdiagnosed as lock timeouts."""
        for output in ("HTTP request timeout", "Could not acquire lock: permission denied", "", None):
            with (
                self.subTest(output=output),
                patch.object(
                    mpt_agent.subprocess, "run",
                    return_value=SimpleNamespace(returncode=2, stdout=output),
                ),
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr,
                self.assertRaisesRegex(mpt_agent.SkillError, "exit code 2"),
            ):
                mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())
            self.assertNotIn("UV_LOCK_TIMEOUT", stderr.getvalue())

    def test_dependency_lock_wait_alternative_wording_has_hint(self):
        """Support the timed out wording used by different uv versions."""
        stderr = io.StringIO()
        with (
            patch.object(
                mpt_agent.subprocess, "run",
                return_value=SimpleNamespace(returncode=1, stdout="Timed out waiting for cache lock"),
            ),
            redirect_stdout(io.StringIO()), redirect_stderr(stderr),
            self.assertRaises(mpt_agent.SkillError),
        ):
            mpt_agent.run_checked(["uv", "sync", "--frozen"], cwd=Path.cwd())
        self.assertIn("UV_LOCK_TIMEOUT", stderr.getvalue())

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
