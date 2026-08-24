import ast
import json
from pathlib import Path

import pytest

from app.models.llm_provider import LLM_PROVIDER_REGISTRY, get_llm_provider
from app.models.schema import VideoParams


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
SETTINGS_TRANSFER_HELPERS = {
    "_is_credential_config_key",
    "_is_backup_config_key",
    "_credential_widget_state_keys",
    "_apply_key_backup",
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
    "CREDENTIAL_WIDGET_STATE_ALIASES",
    "NON_LLM_COMPANION_KEYS",
    "KEY_BACKUP_EXCLUDED_SECTIONS",
}


class _FakeStreamlit:
    """只提供 _apply_key_backup 需要的 session_state 字典。"""

    def __init__(self):
        self.session_state = {}


RUNTIME_CONFIG_UPDATES = []


def _record_runtime_config(section_name, key, value):
    RUNTIME_CONFIG_UPDATES.append((section_name, key, value))


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

    namespace = {
        "json": json,
        "VideoParams": VideoParams,
        "LLM_PROVIDER_REGISTRY": LLM_PROVIDER_REGISTRY,
        # _apply_key_backup 写配置并清理控件状态，两者都由测试替身记录，
        # 这样可以验证真实实现而不需要启动 Streamlit 会话。
        "st": _FakeStreamlit(),
        "_set_runtime_config": _record_runtime_config,
    }
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
credential_widget_state_keys = NAMESPACE["_credential_widget_state_keys"]
apply_key_backup = NAMESPACE["_apply_key_backup"]
FAKE_STREAMLIT = NAMESPACE["st"]
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
            "cloudflare_api_key": "cf-key",
            "cloudflare_account_id": "cf-account",
            "cloudflare_gateway_id": "cf-gateway",
            "video_language": "en-US",
            "upload_post_api_key": "api-key-123",
            "upload_post_username": "my-username",
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
            "cloudflare_api_key": "cf-key",
            "cloudflare_account_id": "cf-account",
            "cloudflare_gateway_id": "cf-gateway",
            "upload_post_api_key": "api-key-123",
            "upload_post_username": "my-username",
        },
        "azure": {"speech_key": "azure-key", "speech_region": "westeurope"},
        "elevenlabs": {"api_key": "eleven-key"},
    }
    assert count_backup_keys(backup) == 10


def test_key_backup_carries_llm_provider_extra_fields_with_the_key():
    """
    Cloudflare AI Gateway 的 Key 单独恢复没有意义，必须带上网关标识。

    额外字段从 Provider Registry 读取，因此以后新增的 Provider 字段也会
    自动进入备份。
    """
    cloudflare = get_llm_provider("cloudflare")
    extra_config_keys = [
        cloudflare.config_key(field.config_suffix) for field in cloudflare.extra_fields
    ]
    assert extra_config_keys == ["cloudflare_account_id", "cloudflare_gateway_id"]

    sections = _sample_config_sections()
    restored = parse_key_backup(
        _encode(build_key_backup_payload(sections, "1.3.4")), sections
    )

    assert restored["app"]["cloudflare_api_key"] == "cf-key"
    assert restored["app"]["cloudflare_account_id"] == "cf-account"
    assert restored["app"]["cloudflare_gateway_id"] == "cf-gateway"


def test_key_backup_companion_keys_stay_in_sync_with_the_provider_registry():
    companion_app_keys = set(NAMESPACE["CREDENTIAL_COMPANION_KEYS"]["app"])
    registry_extra_keys = {
        provider.config_key(field.config_suffix)
        for provider in LLM_PROVIDER_REGISTRY
        for field in provider.extra_fields
    }

    assert companion_app_keys == registry_extra_keys
    assert registry_extra_keys


def test_key_backup_skips_interface_preferences_section():
    backup = collect_key_backup({"ui": {"language": "en", "openai_api_key": "leak"}})

    assert backup == {}


def test_key_backup_round_trip_restores_every_saved_key():
    sections = _sample_config_sections()
    payload = build_key_backup_payload(sections, "1.3.4")

    restored = parse_key_backup(_encode(payload), sections)

    assert restored == collect_key_backup(sections)
    # Explicit assertion for upload_post credentials restoration requested by reviewer
    assert restored["app"]["upload_post_api_key"] == "api-key-123"
    assert restored["app"]["upload_post_username"] == "my-username"


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


def test_credential_widget_state_keys_match_settings_inputs():
    assert credential_widget_state_keys("app", "pexels_api_keys") == (
        "pexels_api_keys_input",
    )
    assert credential_widget_state_keys("app", "openai_api_key") == (
        "openai_api_key_input",
    )
    assert credential_widget_state_keys("azure", "speech_key") == (
        "azure_speech_key_input",
    )
    assert credential_widget_state_keys("minimax_tts", "api_key") == (
        "minimax_tts_api_key_input",
    )


def test_credential_widget_state_keys_cover_shared_input_aliases():
    """音频面板为同一份密钥提供了第二个输入框，别名必须一起返回。"""
    assert credential_widget_state_keys("app", "gemini_api_key") == (
        "gemini_api_key_input",
        "gemini_tts_api_key_input",
    )
    assert credential_widget_state_keys("app", "mimo_api_key") == (
        "mimo_api_key_input",
        "mimo_tts_api_key_input",
    )
    assert credential_widget_state_keys("app", "loomloom_api_token") == (
        "loomloom_api_token_input",
        "loomloom_user_api_token",
    )


def test_apply_key_backup_writes_config_and_clears_every_widget_alias():
    RUNTIME_CONFIG_UPDATES.clear()
    FAKE_STREAMLIT.session_state.clear()
    FAKE_STREAMLIT.session_state.update(
        {
            "gemini_api_key_input": "stale-gemini",
            "gemini_tts_api_key_input": "stale-gemini",
            "loomloom_user_api_token": "stale-loomloom",
            "azure_speech_key_input": "stale-azure",
            "elevenlabs_voices_stale-key": ["old voice"],
            "video_subject": "untouched",
        }
    )

    restored_count = apply_key_backup(
        {
            "app": {
                "gemini_api_key": "new-gemini",
                "loomloom_api_token": "new-loomloom",
            },
            "azure": {"speech_key": "new-azure", "speech_region": "westeurope"},
        }
    )

    assert restored_count == 4
    assert sorted(RUNTIME_CONFIG_UPDATES) == [
        ("app", "gemini_api_key", "new-gemini"),
        ("app", "loomloom_api_token", "new-loomloom"),
        ("azure", "speech_key", "new-azure"),
        ("azure", "speech_region", "westeurope"),
    ]
    # 每一个别名控件状态都必须消失，否则旧密钥会在下一次 rerun 写回配置。
    assert FAKE_STREAMLIT.session_state == {"video_subject": "untouched"}


def test_credential_config_key_detection_covers_project_naming():
    assert is_credential_config_key("openai_api_key")
    assert is_credential_config_key("pexels_api_keys")
    assert is_credential_config_key("loomloom_api_token")
    assert is_credential_config_key("speech_key")
    assert not is_credential_config_key("openai_base_url")
    assert not is_credential_config_key("ffmpeg_path")
