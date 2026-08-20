import ast
import json
from pathlib import Path

import pytest

from app.models.schema import VideoParams


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
SETTINGS_TRANSFER_HELPERS = {
    "_is_credential_config_key",
    "_is_backup_config_key",
    "_credential_widget_state_key",
    "_normalize_backup_value",
    "_collect_key_backup",
    "_count_backup_keys",
    "_build_key_backup_payload",
    "_load_transfer_payload",
    "_parse_key_backup",
    "_build_settings_preset_payload",
    "_parse_settings_preset",
}
SETTINGS_TRANSFER_CONSTANTS = {
    "SETTINGS_PRESET_SCHEMA",
    "SETTINGS_PRESET_VERSION",
    "SETTINGS_PRESET_FILE_NAME",
    "KEY_BACKUP_SCHEMA",
    "KEY_BACKUP_VERSION",
    "KEY_BACKUP_FILE_NAME",
    "PRESET_EXCLUDED_PARAM_KEYS",
    "CREDENTIAL_KEY_SUFFIXES",
    "CREDENTIAL_COMPANION_KEYS",
    "KEY_BACKUP_EXCLUDED_SECTIONS",
}


def _load_settings_transfer_helpers():
    """
    从 WebUI 入口中隔离加载导出导入相关的纯函数。

    与任务历史测试相同，直接导入 Main.py 会执行整套页面渲染。这里只编译目标
    常量和函数，既验证真实实现，也不需要为测试拆出额外的生产模块。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in SETTINGS_TRANSFER_CONSTANTS
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif (
            isinstance(node, ast.FunctionDef) and node.name in SETTINGS_TRANSFER_HELPERS
        ):
            selected_nodes.append(node)

    namespace = {"json": json, "VideoParams": VideoParams}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


NAMESPACE = _load_settings_transfer_helpers()
build_settings_preset_payload = NAMESPACE["_build_settings_preset_payload"]
parse_settings_preset = NAMESPACE["_parse_settings_preset"]
build_key_backup_payload = NAMESPACE["_build_key_backup_payload"]
collect_key_backup = NAMESPACE["_collect_key_backup"]
count_backup_keys = NAMESPACE["_count_backup_keys"]
parse_key_backup = NAMESPACE["_parse_key_backup"]
credential_widget_state_key = NAMESPACE["_credential_widget_state_key"]
is_credential_config_key = NAMESPACE["_is_credential_config_key"]
SETTINGS_PRESET_SCHEMA = NAMESPACE["SETTINGS_PRESET_SCHEMA"]
SETTINGS_PRESET_VERSION = NAMESPACE["SETTINGS_PRESET_VERSION"]
KEY_BACKUP_SCHEMA = NAMESPACE["KEY_BACKUP_SCHEMA"]
KEY_BACKUP_VERSION = NAMESPACE["KEY_BACKUP_VERSION"]


def _encode(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _sample_config_sections():
    return {
        "app": {
            "pexels_api_keys": ["pexels-1", " ", "pexels-2"],
            "openai_api_key": " sk-openai ",
            "coverr_api_keys": [],
            "gemini_api_key": "",
            "video_language": "en-US",
        },
        "azure": {"speech_key": "azure-key", "speech_region": "westeurope"},
        "elevenlabs": {"api_key": "eleven-key", "model_id": "eleven_v3"},
        "ui": {"language": "en", "font_size": 60},
    }


def test_settings_preset_payload_drops_local_file_parameters():
    params = VideoParams(video_subject="a cat").model_dump(mode="json")
    params["video_materials"] = [{"provider": "local", "url": "/tmp/clip.mp4"}]
    params["custom_audio_file"] = "/tmp/voice.mp3"
    params["bgm_file"] = "/tmp/song.mp3"

    payload = build_settings_preset_payload(params, "1.3.4")

    assert payload["schema"] == SETTINGS_PRESET_SCHEMA
    assert payload["version"] == SETTINGS_PRESET_VERSION
    assert payload["app_version"] == "1.3.4"
    assert "video_materials" not in payload["params"]
    assert "custom_audio_file" not in payload["params"]
    assert "bgm_file" not in payload["params"]
    assert payload["params"]["video_subject"] == "a cat"


def test_settings_preset_round_trip_preserves_generation_settings():
    params = VideoParams(
        video_subject="a cat",
        video_aspect="9:16",
        font_size=48,
        stroke_width=2.5,
        voice_volume=0.8,
        paragraph_number=3,
    ).model_dump(mode="json")

    restored = parse_settings_preset(
        _encode(build_settings_preset_payload(params, "1"))
    )

    assert restored["video_subject"] == "a cat"
    assert restored["video_aspect"] == "9:16"
    assert restored["font_size"] == 48
    assert restored["stroke_width"] == 2.5
    assert restored["voice_volume"] == 0.8
    assert restored["paragraph_number"] == 3


def test_settings_preset_accepts_file_without_video_subject():
    payload = {
        "schema": SETTINGS_PRESET_SCHEMA,
        "version": SETTINGS_PRESET_VERSION,
        "params": {"font_size": 72},
    }

    restored = parse_settings_preset(_encode(payload))

    assert restored["video_subject"] == ""
    assert restored["font_size"] == 72


def test_settings_preset_rejects_foreign_or_outdated_files():
    with pytest.raises(ValueError):
        parse_settings_preset(_encode({"schema": "something-else", "version": 1}))
    with pytest.raises(ValueError):
        parse_settings_preset(
            _encode({"schema": SETTINGS_PRESET_SCHEMA, "version": 999})
        )
    with pytest.raises(ValueError):
        parse_settings_preset(
            _encode(
                {"schema": SETTINGS_PRESET_SCHEMA, "version": SETTINGS_PRESET_VERSION}
            )
        )
    with pytest.raises(json.JSONDecodeError):
        parse_settings_preset(b"not json at all")


def test_settings_preset_rejects_invalid_parameter_values():
    payload = {
        "schema": SETTINGS_PRESET_SCHEMA,
        "version": SETTINGS_PRESET_VERSION,
        "params": {"video_subject": "a cat", "paragraph_number": 99},
    }

    with pytest.raises(Exception):
        parse_settings_preset(_encode(payload))


def test_key_backup_collects_credentials_and_their_companion_settings():
    backup = collect_key_backup(_sample_config_sections())

    assert backup == {
        "app": {
            "pexels_api_keys": ["pexels-1", "pexels-2"],
            "openai_api_key": "sk-openai",
        },
        "azure": {"speech_key": "azure-key", "speech_region": "westeurope"},
        "elevenlabs": {"api_key": "eleven-key"},
    }
    assert count_backup_keys(backup) == 5


def test_key_backup_skips_interface_preferences_section():
    backup = collect_key_backup({"ui": {"language": "en", "openai_api_key": "leak"}})

    assert backup == {}


def test_key_backup_round_trip_restores_every_saved_key():
    sections = _sample_config_sections()
    payload = build_key_backup_payload(sections, "1.3.4")

    restored = parse_key_backup(_encode(payload), sections)

    assert restored == collect_key_backup(sections)


def test_key_backup_import_ignores_unknown_sections_and_non_key_settings():
    payload = {
        "schema": KEY_BACKUP_SCHEMA,
        "version": KEY_BACKUP_VERSION,
        "keys": {
            "app": {"openai_api_key": "sk-openai", "ffmpeg_path": "/usr/bin/ffmpeg"},
            "ui": {"openai_api_key": "leak"},
            "unknown_section": {"openai_api_key": "sk-other"},
        },
    }

    restored = parse_key_backup(_encode(payload), _sample_config_sections())

    assert restored == {"app": {"openai_api_key": "sk-openai"}}


def test_key_backup_import_rejects_files_without_any_key():
    payload = {
        "schema": KEY_BACKUP_SCHEMA,
        "version": KEY_BACKUP_VERSION,
        "keys": {"app": {"openai_api_key": ""}},
    }

    with pytest.raises(ValueError):
        parse_key_backup(_encode(payload), _sample_config_sections())


def test_key_backup_import_tolerates_utf8_bom_written_by_windows_editors():
    sections = _sample_config_sections()
    payload = build_key_backup_payload(sections, "1.3.4")
    raw = "﻿" + json.dumps(payload, ensure_ascii=False)

    restored = parse_key_backup(raw.encode("utf-8"), sections)

    assert restored["azure"]["speech_key"] == "azure-key"


def test_credential_widget_state_key_matches_settings_inputs():
    assert credential_widget_state_key("app", "pexels_api_keys") == (
        "pexels_api_keys_input"
    )
    assert credential_widget_state_key("app", "openai_api_key") == (
        "openai_api_key_input"
    )
    assert credential_widget_state_key("azure", "speech_key") == (
        "azure_speech_key_input"
    )
    assert credential_widget_state_key("minimax_tts", "api_key") == (
        "minimax_tts_api_key_input"
    )


def test_credential_config_key_detection_covers_project_naming():
    assert is_credential_config_key("openai_api_key")
    assert is_credential_config_key("pexels_api_keys")
    assert is_credential_config_key("loomloom_api_token")
    assert is_credential_config_key("speech_key")
    assert not is_credential_config_key("openai_base_url")
    assert not is_credential_config_key("ffmpeg_path")
