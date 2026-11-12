"""The agent skill and config template know the useapi.net audio token."""

import importlib.util
import io
import os
import tempfile
import tomllib
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
SKILL_SCRIPT = ROOT_DIR / "docs" / "skill" / "mpt_agent.py"
SPEC = importlib.util.spec_from_file_location("mpt_agent_skill_useapi_audio", SKILL_SCRIPT)
mpt_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mpt_agent)

CONFIG = """\
llm_provider = "moonshot"
moonshot_api_key = "configured"
pexels_api_keys = ["configured"]
useapi_api_token = ""
"""


def _missing(cli_args, environment=None, config_text=CONFIG):
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.toml"
        config_path.write_text(config_text, encoding="utf-8")
        with patch.dict(os.environ, environment or {}, clear=True):
            return mpt_agent.missing_config(config_path, cli_args)[1]


def test_useapi_voices_and_flow_music_require_the_token():
    for cli_args in (
        ["--voice-name", "useapi-kling:voice_1"],
        ["--voice-name=useapi-vids:Holt"],
        ["--bgm-type", "flowmusic"],
        ["--voice-name", "useapi-vids:Holt", "--bgm-type", "flowmusic"],
    ):
        assert _missing(cli_args) == ["useapi_api_token"], cli_args


def test_other_voices_and_music_do_not_ask_for_the_token():
    assert _missing(["--voice-name", "zh-CN-XiaoxiaoNeural-Female"]) == []
    assert _missing(["--bgm-type", "elevenlabs"]) == []


def test_configured_or_environment_token_satisfies_the_check():
    configured = CONFIG.replace('useapi_api_token = ""', 'useapi_api_token = "tok"')
    assert _missing(["--bgm-type", "flowmusic"], config_text=configured) == []
    assert _missing(["--bgm-type", "flowmusic"], {"USEAPI_TOKEN": "env-token"}) == []


def test_missing_token_report_points_to_setup_and_environment_variable():
    output = io.StringIO()
    with redirect_stdout(output):
        code = mpt_agent.report_missing_config("moonshot", ["useapi_api_token"])
    text = output.getvalue()
    assert code == mpt_agent.NEEDS_INPUT_EXIT_CODE
    assert "USEAPI_TOKEN_URL=https://useapi.net/docs/start-here/setup-useapi" in text
    assert "utm_source=moneyprinterturbo" in text
    assert "USEAPI_TOKEN_ENV=MPT_USEAPI_TOKEN" in text
    assert "LLM_PROVIDER_OPTIONS_BEGIN" not in text


def test_environment_token_is_written_without_being_printed():
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"MPT_USEAPI_TOKEN": "secret-token"}, clear=True),
            redirect_stdout(output),
        ):
            mpt_agent.apply_environment_config(config_path)
        assert 'useapi_api_token = "secret-token"' in config_path.read_text("utf-8")
        assert "secret-token" not in output.getvalue()


def test_skill_document_lists_the_token_variable():
    document = (ROOT_DIR / "docs" / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "MPT_USEAPI_TOKEN" in document
    assert "--bgm-type flowmusic" in document


def test_config_template_declares_the_useapi_audio_settings():
    app = tomllib.loads((ROOT_DIR / "config.example.toml").read_text("utf-8"))["app"]
    assert app["useapi_api_token"] == ""
    assert app["useapi_kling_tts_emotion"] == ""
    assert app["useapi_flowmusic_model"] == "lyria-3.5"
