import importlib.util
from pathlib import Path
import tomllib


spec = importlib.util.spec_from_file_location("mpt_agent_string_lookalikes", Path(__file__).resolve().parents[2] / "docs/skill/mpt_agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def test_config_update_skips_key_looking_text_inside_multiline_string():
    text = '[app]\nnotes = """Example settings:\nllm_provider = "moonshot"\n"""\nllm_provider = "ollama"\n'
    updated = agent._replace_config_value(text, "llm_provider", "openai")
    before = tomllib.loads(text)["app"]
    after = tomllib.loads(updated)["app"]
    assert after["llm_provider"] == "openai"
    assert after["notes"] == before["notes"]
