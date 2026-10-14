import importlib.util
import tomllib
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("mpt_app_section_fixture", Path(__file__).parents[2] / "docs" / "skill" / "mpt_agent.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_environment_updates_app_field_instead_of_same_named_other_table(tmp_path):
    destination = tmp_path / "config.toml"
    destination.write_text('[ui]\npexels_api_keys = ["ui-fixture"]\n[app]\nllm_provider = "ollama"\npexels_api_keys = ["old-fixture"]\n[other]\npexels_api_keys = ["other-fixture"]\n', encoding="utf-8")
    with patch.dict(helper.os.environ, {"MPT_PEXELS_API_KEY": "new-fixture"}, clear=True):
        helper.apply_environment_config(destination)
    document = tomllib.loads(destination.read_text(encoding="utf-8"))
    assert document["app"]["pexels_api_keys"] == ["new-fixture"]
    assert document["ui"]["pexels_api_keys"] == ["ui-fixture"]
    assert document["other"]["pexels_api_keys"] == ["other-fixture"]


def test_app_field_missing_does_not_update_another_tables_field():
    text = '[ui]\npexels_api_keys = ["ui-fixture"]\n[app]\nllm_provider = "ollama"\n'
    try:
        helper._replace_config_value(text, "pexels_api_keys", ["new-fixture"])
    except helper.SkillError:
        return
    raise AssertionError("missing app field must be reported")


def test_table_like_text_inside_multiline_value_is_not_a_settings_header():
    text = '[ui]\ndescription = """\n[app]\nAn example only\n"""\n["app"] # Settings\npexels_api_keys = ["old-fixture"]\n'
    updated = helper._replace_config_value(text, "pexels_api_keys", ["new-fixture"])
    document = tomllib.loads(updated)
    assert document["app"]["pexels_api_keys"] == ["new-fixture"]
    assert document["ui"]["description"] == tomllib.loads(text)["ui"]["description"]
