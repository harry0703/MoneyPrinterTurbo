"""Audexum voice previews must not survive a key or endpoint change.

Regression for the preview-cache issue reported on PR #1700: the provider
signature had no Audexum branch, so a short or full preview generated under an
old key / base_url was reused (and could be carried into the final video).
"""

import ast
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams
from app.services import voice

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _load_main_functions(names, namespace):
    """Load selected WebUI helpers without running the Streamlit page."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == set(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(WEBUI_MAIN), "exec"), namespace)
    return namespace


@pytest.fixture
def audexum_config(monkeypatch):
    """Real config section (voice.get_audexum_* read it), restored afterwards."""
    monkeypatch.delenv("AUDEXUM_API_KEY", raising=False)
    section = {"api_key": "key-one"}
    with patch.object(config, "audexum", section):
        yield section


@pytest.fixture
def provider_signature():
    namespace = _load_main_functions(
        {"_credential_signature", "_get_voice_preview_provider_signature"},
        {"hashlib": hashlib, "config": config, "voice": voice, "st": SimpleNamespace(session_state={})},
    )
    return namespace["_get_voice_preview_provider_signature"]


def test_base_url_helper_matches_transport_rules(audexum_config):
    assert voice.get_audexum_base_url() == "https://audexum.com/v1"
    for blank in (None, "", "   "):
        audexum_config["base_url"] = blank
        assert voice.get_audexum_base_url() == "https://audexum.com/v1"
    audexum_config["base_url"] = " http://127.0.0.1:9000/v1/ "
    assert voice.get_audexum_base_url() == "http://127.0.0.1:9000/v1"


def test_signature_tracks_effective_key_and_endpoint(audexum_config, monkeypatch, provider_signature):
    configured = provider_signature("audexum")

    audexum_config["api_key"] = "key-two"
    changed_key = provider_signature("audexum")

    audexum_config["api_key"] = ""
    monkeypatch.setenv("AUDEXUM_API_KEY", "env-key-one")
    env_key = provider_signature("audexum")
    monkeypatch.setenv("AUDEXUM_API_KEY", "env-key-two")
    changed_env_key = provider_signature("audexum")

    monkeypatch.delenv("AUDEXUM_API_KEY")
    cleared_key = provider_signature("audexum")

    audexum_config["base_url"] = "http://127.0.0.1:9000/v1"
    changed_endpoint = provider_signature("audexum")
    audexum_config["base_url"] = "http://127.0.0.1:9000/v1/"
    trailing_slash = provider_signature("audexum")

    signatures = [configured, changed_key, env_key, changed_env_key, cleared_key, changed_endpoint]
    assert len({json.dumps(s, sort_keys=True) for s in signatures}) == len(signatures)
    assert trailing_slash == changed_endpoint
    assert cleared_key["credential"] == ""
    for secret in ("key-one", "key-two", "env-key-one", "env-key-two"):
        assert all(secret not in str(s) for s in signatures)


def test_full_preview_reuse_is_rejected_after_key_or_endpoint_change(audexum_config, monkeypatch):
    session_state = {}
    namespace = _load_main_functions(
        {
            "_credential_signature",
            "_get_voice_preview_provider_signature",
            "_voice_preview_fingerprint",
            "_get_reusable_full_voice_preview",
        },
        {
            "hashlib": hashlib,
            "json": json,
            "math": math,
            "config": config,
            "voice": voice,
            "st": SimpleNamespace(session_state=session_state),
            "VOICE_MODE_TTS": "tts",
        },
    )
    reusable = namespace["_get_reusable_full_voice_preview"]
    script = "One script for the preview and the final video."
    params = VideoParams(
        video_subject="audexum reuse",
        video_script=script,
        voice_name="audexum:Atlas",
        voice_rate=1.0,
        voice_volume=1.0,
    )

    def cache_preview():
        session_state["voice_preview_audio"] = {
            "fingerprint": namespace["_voice_preview_fingerprint"](
                preview_type="full",
                content=script,
                tts_server="audexum",
                voice_name=params.voice_name,
                voice_rate=params.voice_rate,
                voice_volume=params.voice_volume,
                provider_signature=namespace["_get_voice_preview_provider_signature"]("audexum"),
            ),
            "preview_type": "full",
            "audio_bytes": b"preview audio",
            "sub_maker": object(),
            "duration": 4.2,
        }

    with patch.object(config, "ui", dict(config.ui, tts_server="audexum")):
        cache_preview()
        assert reusable(params, "tts") is not None

        audexum_config["api_key"] = ""
        assert reusable(params, "tts") is None  # key cleared

        monkeypatch.setenv("AUDEXUM_API_KEY", "env-key")
        assert reusable(params, "tts") is None  # env fallback is a different key

        cache_preview()
        assert reusable(params, "tts") is not None
        audexum_config["base_url"] = "http://127.0.0.1:9000/v1"
        assert reusable(params, "tts") is None  # endpoint changed


def _button_by_key(app, key):
    return next(b for b in app.button if str(getattr(b, "key", "")).startswith(key))


@pytest.mark.parametrize(
    "button_key",
    ["play_voice_button", "generate_full_voiceover_preview_button"],
)
def test_preview_is_regenerated_after_key_or_endpoint_change(audexum_config, monkeypatch, button_key):
    test_ui = dict(config.ui, voice_mode="tts", tts_server="audexum", voice_name="audexum:Atlas")

    def fake_tts(**kwargs):
        Path(kwargs["voice_file"]).write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32)
        return object()

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "tts", side_effect=fake_tts) as synthesize,
        patch.object(voice, "get_audio_duration", return_value=3.0),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.session_state["video_script"] = "A script long enough for a full preview."
        app.run()

        _button_by_key(app, button_key).click().run()
        _button_by_key(app, button_key).click().run()
        assert synthesize.call_count == 1  # unchanged config: cached

        # Key changed through the WebUI field (the widget writes back to config).
        app.text_input(key="audexum_api_key_input").set_value("key-two").run()
        _button_by_key(app, button_key).click().run()
        assert synthesize.call_count == 2

        # Field cleared, key now only in the environment.
        monkeypatch.setenv("AUDEXUM_API_KEY", "env-key")
        app.text_input(key="audexum_api_key_input").set_value("").run()
        _button_by_key(app, button_key).click().run()
        assert synthesize.call_count == 3

        # Endpoint changed in config.toml.
        audexum_config["base_url"] = "http://127.0.0.1:9000/v1"
        _button_by_key(app, button_key).click().run()
        assert synthesize.call_count == 4

    assert [str(item.value) for item in app.exception] == []


def test_queued_duplicate_detection_sees_audexum_config(audexum_config):
    """A queued task must not be merged with one submitted under another key/endpoint."""
    from app.services import webui_task

    params = VideoParams(video_subject="queued", voice_name="audexum:Atlas")

    def signature():
        return webui_task._submission_signature(params, [], None, None, None)

    original = signature()
    audexum_config["api_key"] = "key-two"
    changed_key = signature()
    audexum_config["base_url"] = "http://127.0.0.1:9000/v1"
    changed_endpoint = signature()
    assert len({original, changed_key, changed_endpoint}) == 3


def test_transport_uses_the_configured_endpoint(audexum_config, tmp_path):
    captured = {}

    class _Response:
        status_code = 200
        content = b"\xff" * 200
        text = ""

    class _Clip:
        duration = 1.0

        def close(self):
            pass

    def fake_post(url, **kwargs):
        captured["url"] = url
        return _Response()

    audexum_config["base_url"] = " http://127.0.0.1:9000/v1/ "
    with (
        patch.object(voice.requests, "post", side_effect=fake_post),
        patch.object(voice, "AudioFileClip", return_value=_Clip()),
        patch.object(voice, "_validate_remote_tts_audio"),
    ):
        assert voice.audexum_tts("Hi.", "Atlas", str(tmp_path / "a.mp3")) is not None
    assert captured["url"] == "http://127.0.0.1:9000/v1/audio/speech"
