import importlib.util
import tomllib
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("mpt_multiline_fixture", Path(__file__).parents[2] / "docs" / "skill" / "mpt_agent.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_environment_key_update_replaces_complete_multiline_array(tmp_path):
    destination = tmp_path / "config.toml"
    destination.write_text('[app]\nllm_provider = "ollama"\npexels_api_keys = [\n  "old-fixture",\n]\n# Retained settings\nvideo_source = "pexels"\n', encoding="utf-8")
    with patch.dict(helper.os.environ, {"MPT_PEXELS_API_KEY": "new-fixture"}, clear=True):
        helper.apply_environment_config(destination)
    text = destination.read_text(encoding="utf-8")
    document = tomllib.loads(text)
    assert document["app"]["pexels_api_keys"] == ["new-fixture"]
    assert document["app"]["video_source"] == "pexels"
    assert "# Retained settings" in text
