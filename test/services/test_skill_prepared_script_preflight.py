import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("mpt_prepared_script_fixture", Path(__file__).parents[2] / "docs" / "skill" / "mpt_agent.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.mark.parametrize("forwarded", [
    ["--video-script", "Prepared narration", "--video-source", "local", "--video-materials", "./owned.mp4"],
    ["--video-script=Prepared narration", "--video-source=local", "--video-materials=./owned.mp4"],
    ["--video-script", "Prepared narration", "--video-terms", "ocean waves", "--video-source", "pexels"],
])
def test_prepared_script_and_visuals_need_no_llm_credentials(tmp_path, forwarded):
    config = tmp_path / "config.toml"
    config.write_text('[app]\nllm_provider = "moonshot"\nmoonshot_api_key = ""\npexels_api_keys = ["fixture"]\n', encoding="utf-8")
    assert helper.missing_config(config, forwarded) == ("moonshot", [])


def test_stock_materials_without_terms_still_need_llm(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[app]\nllm_provider = "moonshot"\nmoonshot_api_key = ""\npexels_api_keys = ["fixture"]\n', encoding="utf-8")
    assert helper.missing_config(config, ["--video-script", "Prepared narration"])[1] == ["moonshot_api_key"]


def test_last_empty_script_option_requires_generation_again(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[app]\nllm_provider = "moonshot"\nmoonshot_api_key = ""\n', encoding="utf-8")
    forwarded = ["--video-script", "Prepared narration", "--video-script=", "--video-source=local", "--video-materials=./owned.mp4"]
    assert helper.missing_config(config, forwarded)[1] == ["moonshot_api_key"]
