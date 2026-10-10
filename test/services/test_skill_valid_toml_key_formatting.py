import importlib.util
from pathlib import Path
import tomllib

import pytest


spec = importlib.util.spec_from_file_location("mpt_agent_valid_keys", Path(__file__).resolve().parents[2] / "docs/skill/mpt_agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


@pytest.mark.parametrize("assignment", [
    '  llm_provider = "ollama"',
    '"llm_provider" = "ollama"',
    "'llm_provider' = \"ollama\"",
])
def test_valid_toml_assignment_formatting_can_update_provider(assignment):
    text = f"[app]\n{assignment}\n"
    assert agent._plain_config_value(text, "llm_provider") == "ollama"
    updated = agent._replace_config_value(text, "llm_provider", "openai")
    assert tomllib.loads(updated)["app"]["llm_provider"] == "openai"
