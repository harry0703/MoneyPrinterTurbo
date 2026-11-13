import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import metaso_minimax, muapi, ofox, volcengine_seedance


spec = importlib.util.spec_from_file_location("mpt_whitespace_keys_fixture", Path(__file__).parents[2] / "docs" / "skill" / "mpt_agent.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.mark.parametrize("source,key,environment,service,confirmation", [
    ("ofox", "ofox_api_key", "OFOX_API_KEY", ofox, "--confirm-ofox-charge"),
    ("muapi", "muapi_api_key", "MUAPI_API_KEY", muapi, "--confirm-muapi-charge"),
    ("metaso_minimax", "metaso_minimax_api_key", "METASO_MINIMAX_API_KEY", metaso_minimax, "--confirm-metaso-minimax-charge"),
    ("volcengine_seedance", "volcengine_seedance_api_key", "VOLCENGINE_ARK_API_KEY", volcengine_seedance, "--confirm-seedance-charge"),
])
def test_helper_matches_runtime_environment_fallback_after_blank_config(tmp_path, source, key, environment, service, confirmation):
    destination = tmp_path / "config.toml"
    destination.write_text(f'[app]\nllm_provider = "ollama"\n{key} = "   "\n', encoding="utf-8")
    with patch.dict(helper.os.environ, {environment: "fixture-environment-key"}, clear=True):
        assert service.get_api_key({key: "   "}) == "fixture-environment-key"
        assert helper.missing_config(destination, ["--video-source", source, confirmation]) == ("ollama", [])
