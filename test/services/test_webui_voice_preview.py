import ast
import hashlib
import re
import shutil
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams
from app.services import task as tm
from app.services import voice
from app.services import webui_task
from app.utils import utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _load_duration_estimator():
    """Load only the pure estimation functions so unit tests do not import and execute the full Streamlit page."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_estimate_voiceover_duration_range"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"re": re}
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace["_estimate_voiceover_duration_range"]


def _load_provider_signature(test_config):
    """Load the credential digest and provider fingerprint functions to verify cache invalidation in isolation."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_credential_signature",
            "_get_voice_preview_provider_signature",
        }
    ]
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {"hashlib": hashlib, "config": test_config}
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace["_get_voice_preview_provider_signature"]


def _button_by_key(app, key):
    return next(
        button
        for button in app.button
        if str(getattr(button, "key", "")).startswith(key)
    )


def test_duration_estimator_is_local_and_respects_voice_rate():
    """Local estimation should cover Chinese and English and shorten sensibly with the user's chosen rate."""
    estimate = _load_duration_estimator()
    script = "人工智能正在改变日常生活。它可以帮助我们整理信息，也能提高效率。"

    normal_range = estimate(script, 1.0)
    fast_range = estimate(script, 2.0)

    assert normal_range is not None
    assert fast_range is not None
    assert normal_range[0] < normal_range[1]
    assert fast_range[0] < normal_range[0]
    assert estimate("", 1.0) is None
    assert estimate("AI tools can simplify repetitive work.", 1.0) is not None


def test_provider_signature_changes_when_api_key_changes():
    """Changing only the API key must still invalidate the preview cache; never fake a success with stale credentials."""
    test_config = SimpleNamespace(
        app={"gemini_api_key": "old-gemini", "mimo_api_key": "old-mimo"},
        azure={"speech_region": "eastasia", "speech_key": "old-azure"},
        siliconflow={"api_key": "old-siliconflow"},
        elevenlabs={"api_key": "old-elevenlabs", "model_id": "eleven_v3"},
        chatterbox={
            "api_key": "old-chatterbox",
            "base_url": "http://127.0.0.1:4123/v1",
            "model_id": "chatterbox",
        },
    )
    provider_signature = _load_provider_signature(test_config)

    old_signature = provider_signature("elevenlabs")
    test_config.elevenlabs["api_key"] = "new-elevenlabs"
    new_signature = provider_signature("elevenlabs")

    assert old_signature != new_signature
    assert "old-elevenlabs" not in str(old_signature)
    assert "new-elevenlabs" not in str(new_signature)


def test_full_voiceover_preview_is_disabled_until_script_exists():
    """A full preview must be user-triggered; an empty script must never trigger a commercial TTS call."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )
    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.run()

    full_preview = _button_by_key(
        app,
        "generate_full_voiceover_preview_button",
    )
    assert full_preview.disabled
    assert any("填写视频文案后" in item.value for item in app.caption)


def test_script_shows_estimate_and_enables_full_voiceover_preview():
    """Show the free estimate once a script is entered and state clearly that a full preview may incur API cost."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )
    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.session_state["video_script"] = (
            "人工智能正在改变日常生活。合理使用工具，可以帮助我们提高工作效率。"
        )
        app.run()

    full_preview = _button_by_key(
        app,
        "generate_full_voiceover_preview_button",
    )
    assert not full_preview.disabled
    assert any("本地估算，不调用 API" in item.value for item in app.caption)
    assert "可能消耗 API 额度" in full_preview.help
    assert [str(item.value) for item in app.exception] == []


def test_short_preview_autoplays_only_after_explicit_click_and_reuses_cache():
    """Short previews should play immediately; ordinary reruns must not replay, and repeated clicks must not re-call TTS."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )

    def fake_tts(**kwargs):
        Path(kwargs["voice_file"]).write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
        )
        return object()

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "tts", side_effect=fake_tts) as synthesize,
        patch.object(voice, "get_audio_duration", return_value=3.0),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.run()

        _button_by_key(app, "play_voice_button").click().run()
        assert len(app.get("audio")) == 1
        assert app.get("audio")[0].proto.autoplay

        app.run()
        assert len(app.get("audio")) == 1
        assert not app.get("audio")[0].proto.autoplay

        _button_by_key(app, "play_voice_button").click().run()

    synthesize.assert_called_once()
    assert app.get("audio")[0].proto.autoplay
    assert [str(item.value) for item in app.exception] == []


def test_full_preview_uses_script_and_reuses_identical_cached_audio():
    """A full preview uses the current script; repeated clicks with identical parameters must not call TTS again."""
    script = "这是一段用于验证完整配音预览缓存的测试文案。"
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )

    def fake_tts(**kwargs):
        # The extension is mp3 but the real TTS may return WAV; this minimal header also
        # verifies the WebUI picks the player MIME from content instead of blindly trusting the extension.
        Path(kwargs["voice_file"]).write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
        )
        return object()

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "tts", side_effect=fake_tts) as synthesize,
        patch.object(voice, "get_audio_duration", return_value=12.3),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.session_state["video_script"] = script
        app.run()

        _button_by_key(
            app,
            "generate_full_voiceover_preview_button",
        ).click().run()
        _button_by_key(
            app,
            "generate_full_voiceover_preview_button",
        ).click().run()

    synthesize.assert_called_once()
    assert synthesize.call_args.kwargs["text"] == script
    assert len(app.get("audio")) == 1
    assert not app.get("audio")[0].proto.autoplay
    assert any("实际配音时长：12.3 秒" in item.value for item in app.caption)
    assert [str(item.value) for item in app.exception] == []


def test_full_preview_reports_when_tts_returns_no_audio():
    """When TTS returns empty, give an actionable hint — the button click must never end without feedback."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )
    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "tts", return_value=None),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.session_state["video_script"] = "验证配音服务空响应。"
        app.run()
        _button_by_key(
            app,
            "generate_full_voiceover_preview_button",
        ).click().run()

    assert [item.value for item in app.error] == [
        "配音服务未返回试听音频，请检查相关设置和应用日志。"
    ]
    assert [str(item.value) for item in app.exception] == []


def test_full_preview_returns_immediately_when_runtime_config_is_busy():
    """While a background task holds the config lock, preview should prompt a retry instead of blocking the page."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )
    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(
            config,
            "try_runtime_config_lock",
            return_value=nullcontext(False),
        ),
        patch.object(voice, "tts") as synthesize,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.session_state["video_script"] = "验证忙碌状态不会阻塞页面。"
        app.run()
        _button_by_key(
            app,
            "generate_full_voiceover_preview_button",
        ).click().run()

    synthesize.assert_not_called()
    warning_messages = [item.value for item in app.warning]
    assert "当前有视频任务正在使用配音配置，请稍后重试。" in warning_messages


def test_full_preview_warns_when_audio_duration_is_unavailable():
    """When audio is playable but the duration cannot be decoded, do not present 0.0 seconds as a real result."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )

    def fake_tts(**kwargs):
        Path(kwargs["voice_file"]).write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
        )
        return object()

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "tts", side_effect=fake_tts),
        patch.object(voice, "get_audio_duration", return_value=0),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.session_state["video_script"] = "验证无法读取试听音频时长的提示。"
        app.run()
        _button_by_key(
            app,
            "generate_full_voiceover_preview_button",
        ).click().run()

    assert len(app.get("audio")) == 1
    warning_messages = [item.value for item in app.warning]
    assert "试听音频已生成，但无法读取准确时长，请检查应用日志。" in warning_messages


def test_task_reuses_matching_full_preview_without_calling_tts():
    """With fully identical parameters, the real task should reuse the preview audio and subtitle timeline."""
    task_id = "reuse-full-voice-preview"
    task_dir = Path(utils.task_dir(task_id))
    audio_file = task_dir / "audio.mp3"
    audio_file.write_bytes(b"preview audio")
    sub_maker = object()
    script = "完整试听和正式任务使用同一段文案。"
    params = VideoParams(
        video_subject="preview reuse",
        video_script=script,
        voice_name="zh-CN-XiaoxiaoNeural-Female",
        voice_rate=1.2,
        voice_volume=1.0,
    )
    preview = {
        "audio_file": str(audio_file),
        "duration": 8.2,
        "sub_maker": sub_maker,
        "script": script,
        "voice_name": params.voice_name,
        "voice_rate": params.voice_rate,
        "voice_volume": params.voice_volume,
    }

    try:
        with patch.object(tm.voice, "tts") as synthesize:
            result = tm.generate_audio(
                task_id,
                params,
                script,
                voice_preview=preview,
            )
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)

    assert result == (str(audio_file.resolve()), 9, sub_maker)
    synthesize.assert_not_called()


def test_task_regenerates_audio_when_preview_parameters_changed():
    """After the script or any voice parameter changes, fall back to TTS; never reuse a stale full preview."""
    task_id = "stale-full-voice-preview"
    task_dir = Path(utils.task_dir(task_id))
    audio_file = task_dir / "audio.mp3"
    audio_file.write_bytes(b"stale preview audio")
    script = "正式任务需要使用新的语速重新生成配音。"
    params = VideoParams(
        video_subject="stale preview",
        video_script=script,
        voice_name="zh-CN-XiaoxiaoNeural-Female",
        voice_rate=1.5,
        voice_volume=1.0,
    )
    preview = {
        "audio_file": str(audio_file),
        "duration": 8.2,
        "sub_maker": object(),
        "script": script,
        "voice_name": params.voice_name,
        "voice_rate": 1.0,
        "voice_volume": params.voice_volume,
    }
    regenerated_sub_maker = object()

    try:
        with (
            patch.object(
                tm.voice,
                "tts",
                return_value=regenerated_sub_maker,
            ) as synthesize,
            patch.object(tm.voice, "get_audio_duration", return_value=6),
        ):
            result = tm.generate_audio(
                task_id,
                params,
                script,
                voice_preview=preview,
            )
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)

    assert result[1:] == (6, regenerated_sub_maker)
    synthesize.assert_called_once()
    assert synthesize.call_args.kwargs["voice_rate"] == 1.5


def test_non_default_volume_regenerates_audio_without_double_gain():
    """Non-default volume must fall back to the original flow to avoid gain being applied twice by TTS and composition."""
    task_id = "voice-volume-forwarding"
    task_dir = Path(utils.task_dir(task_id))
    audio_file = task_dir / "audio.mp3"
    audio_file.write_bytes(b"preview with provider-side volume")
    script = "非默认音量需要按原流程生成配音。"
    params = VideoParams(
        video_subject="voice volume",
        video_script=script,
        voice_name="zh-CN-XiaoxiaoNeural-Female",
        voice_rate=1.2,
        voice_volume=1.5,
    )
    sub_maker = object()
    preview = {
        "audio_file": str(audio_file),
        "duration": 5.0,
        "sub_maker": object(),
        "script": script,
        "voice_name": params.voice_name,
        "voice_rate": params.voice_rate,
        "voice_volume": params.voice_volume,
    }

    try:
        with (
            patch.object(tm.voice, "tts", return_value=sub_maker) as synthesize,
            patch.object(tm.voice, "get_audio_duration", return_value=5),
        ):
            result = tm.generate_audio(
                task_id,
                params,
                script,
                voice_preview=preview,
            )
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)

    assert result[1:] == (5, sub_maker)
    synthesize.assert_called_once()
    assert "voice_volume" not in synthesize.call_args.kwargs


def test_webui_worker_forwards_voice_preview_to_pipeline():
    """The background task wrapper must not lose the preview cache validated at submission time."""
    preview = {"audio_file": "audio.mp3", "duration": 5.0}
    with (
        patch.object(webui_task.tm, "start", return_value={"videos": []}) as start,
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        webui_task._run_generation(
            "preview-forwarding",
            VideoParams(video_subject="preview forwarding"),
            capture_logs=False,
            voice_preview=preview,
        )

    assert start.call_args.kwargs["voice_preview"] == preview
