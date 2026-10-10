import importlib.util
import tomllib
from pathlib import Path
from unittest.mock import patch

from app.models.llm_provider import get_llm_provider


spec = importlib.util.spec_from_file_location("mpt_provider_case_fixture", Path(__file__).parents[2] / "docs" / "skill" / "mpt_agent.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_uppercase_keyless_provider_matches_runtime_registry(tmp_path):
    assert get_llm_provider("OLLAMA").requires_api_key is False
    config = tmp_path / "config.toml"
    config.write_text('[app]\nllm_provider = "OLLAMA"\n', encoding="utf-8")
    assert helper.missing_config(config, ["--video-source=local", "--video-materials=owned.mp4"]) == ("ollama", [])


def test_uppercase_current_provider_is_retained_before_other_configured_provider(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[app]\nllm_provider = "DEEPSEEK"\ndeepseek_api_key = "chosen-fixture"\nmoonshot_api_key = "other-fixture"\n', encoding="utf-8")
    assert helper.reuse_existing_llm_provider(config) == "deepseek"
    assert tomllib.loads(config.read_text(encoding="utf-8"))["app"]["llm_provider"] == "DEEPSEEK"


def test_environment_key_uses_existing_lowercase_provider_field(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[app]\nllm_provider = "OPENAI"\nopenai_api_key = ""\n', encoding="utf-8")
    with patch.dict(helper.os.environ, {"MPT_LLM_API_KEY": "new-fixture"}, clear=True):
        helper.apply_environment_config(config)
    assert tomllib.loads(config.read_text(encoding="utf-8"))["app"]["openai_api_key"] == "new-fixture"
