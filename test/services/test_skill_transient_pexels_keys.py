import importlib.util
import io
import tomllib
import urllib.error
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("mpt_transient_keys_fixture", Path(__file__).parents[2] / "docs" / "skill" / "mpt_agent.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_rate_limited_key_is_not_classified_as_invalid_credentials():
    response = urllib.error.HTTPError("https://fixture.invalid", 429, "Too Many Requests", {}, io.BytesIO())
    with patch.object(helper.urllib.request, "urlopen", side_effect=response):
        assert helper._validate_pexels_key("fixture") == "unknown"


def test_transient_unknown_key_survives_a_successful_peer_validation(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[app]\npexels_api_keys = ["unknown-fixture", "valid-fixture", "rejected-fixture"]\n', encoding="utf-8")
    with patch.object(helper, "_validate_pexels_key", side_effect=["unknown", "valid", "rejected"]):
        assert helper.validate_pexels_config(config, []) is True
    assert tomllib.loads(config.read_text(encoding="utf-8"))["app"]["pexels_api_keys"] == ["unknown-fixture", "valid-fixture"]
