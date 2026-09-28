"""胜算云吸收优化的回归：隔离状态、准确试听时长和既有文案路由。"""

import ast
import hashlib
import json
import math
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import llm, loomloom

MAIN = Path(__file__).parents[2] / "webui" / "Main.py"


def helpers(state):
    """只执行待测 helper，避免为了验证缓存语义启动整页或访问外部服务。"""
    names = {
        "_loomloom_video_account_signature",
        "_load_loomloom_video_capability",
        "_matching_full_voice_preview_duration",
    }
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    module = ast.fix_missing_locations(
        ast.Module(
            body=[
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name in names
            ],
            type_ignores=[],
        )
    )
    env = {
        "st": SimpleNamespace(session_state=state),
        "config": config,
        "loomloom": loomloom,
        "hashlib": hashlib,
        "json": json,
        "math": math,
        "localized_widget_key": lambda key: key,
        "logger": SimpleNamespace(warning=lambda message: None),
    }
    exec(compile(module, str(MAIN), "exec"), env)
    return env


def test_capability_cache_isolated_by_endpoint_and_key_and_recovers():
    state = {}
    env = helpers(state)
    capability = loomloom.LoomLoomVideoCapability(
        (loomloom.LoomLoomVideoModel("m", "Model"),), "m", ("9:16",)
    )
    from unittest.mock import Mock

    backend = Mock()
    backend.resolve_video_capability.return_value = capability
    env["_create_loomloom_video_backend"] = lambda: backend
    values = {"loomloom_base_url": "https://example.test/v1"}
    with patch.object(config, "snapshot_config_with_pending", return_value=values):
        load = env["_load_loomloom_video_capability"]
        assert load("key-a") == capability
        assert load("key-a") == capability
        assert backend.resolve_video_capability.call_count == 1
        backend.resolve_video_capability.side_effect = loomloom.LoomLoomAPIError(
            "offline"
        )
        assert load("key-a", force=True) == capability
        assert state["loomloom_video_capability_error"] == "offline"
        # 换 Key/端点后失败必须清空旧目录，不能把其他账户的目录误认为有效。
        assert load("key-b") is None
        backend.resolve_video_capability.side_effect = None
        assert load("key-b", force=True) == capability
        assert not state["loomloom_video_capability_error"]
        values["loomloom_base_url"] = "https://second.test/v1"
        backend.resolve_video_capability.side_effect = loomloom.LoomLoomAPIError(
            "offline"
        )
        assert load("key-b") is None
        assert load("") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("preview_type", "sample"),
        ("content_digest", "old"),
        ("tts_server", "other"),
        ("voice_name", "other"),
        ("voice_rate", 1.2),
        ("voice_rate", "invalid"),
        ("duration", 0),
        ("duration", float("nan")),
        ("duration", float("inf")),
    ],
)
def test_old_or_invalid_preview_never_changes_recommendation(field, value):
    preview = {
        "preview_type": "full",
        "content_digest": hashlib.sha256(b"script").hexdigest(),
        "tts_server": "kokoro",
        "voice_name": "kokoro:af_heart",
        "voice_rate": 1.0,
        "duration": 12.0,
    }
    state = {
        "voice_preview_audio": preview,
        "tts_server_select": "kokoro",
        "speech_synthesis_select_kokoro": "kokoro:af_heart",
    }
    match = helpers(state)["_matching_full_voice_preview_duration"]
    assert match("script", 1.0) == 12.0
    preview[field] = value
    assert match("script", 1.0) is None


def test_batch_script_and_video_use_settings_key_without_local_llm():
    values = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="loomloom",
        video_source="loomloom",
        loomloom_api_token="",
    )
    capability = loomloom.LoomLoomVideoCapability(
        (loomloom.LoomLoomVideoModel("m", "Model"),), "m", ("9:16",)
    )
    quote = loomloom.LoomLoomQuote("q", "v", "CNY", 1, 1, "0.1", ())
    with (
        patch.object(config, "app", values),
        patch.object(config, "ui", {}),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "resolve_video_capability",
            return_value=capability,
        ),
        patch.object(loomloom.LoomLoomVideoBackend, "quote", return_value=quote),
        patch.object(llm, "generate_script") as generate,
    ):
        app = AppTest.from_file(str(MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()
        fields = [x for x in app.text_input if x.key == "loomloom_user_api_token"]
        assert len(fields) == 0
        # 设置是唯一凭据入口；配置更新后两个功能都读取最新快照。
        values["loomloom_api_token"] = "test-key"
        app.run()
        assert not app.exception
        assert app.session_state["loomloom_video_capability"] == capability
        assert any(x.key == "loomloom_quote_scripts" for x in app.button)
        assert not any(x.key == "auto_generate_script" for x in app.button)
        generate.assert_not_called()


def widget(items, key):
    return next(item for item in items if item.key == key)


@pytest.fixture
def quote_page():
    """用真实 Streamlit 控件运行失败路径，模拟网络且禁止写配置和提交任务。"""
    values = dict(
        config.app,
        video_source="loomloom",
        script_generation_backend="local",
        loomloom_api_token="test-key",
        loomloom_base_url="https://example.test/v1",
    )
    capability = loomloom.LoomLoomVideoCapability(
        (
            loomloom.LoomLoomVideoModel("a", "Model A"),
            loomloom.LoomLoomVideoModel("b", "Model B"),
        ),
        "a",
        ("16:9", "9:16"),
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(config, "app", values))
        stack.enter_context(patch.object(config, "ui", {}))
        stack.enter_context(patch.object(config, "try_save_config", return_value=True))
        stack.enter_context(
            patch.object(
                loomloom.LoomLoomVideoBackend,
                "resolve_video_capability",
                return_value=capability,
            )
        )
        quote = stack.enter_context(
            patch.object(loomloom.LoomLoomVideoBackend, "quote")
        )
        submit = stack.enter_context(patch("app.services.webui_task.submit_generation"))
        app = AppTest.from_file(str(MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.session_state["video_subject"] = "AI daily life"
        app.session_state["video_script"] = "AI helps people every day."
        app.session_state["video_terms"] = "robot, office"
        yield app, values, quote, submit
        assert not app.exception
        submit.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        loomloom.LoomLoomAPIError("timeout", retryable=True),
        loomloom.LoomLoomAPIError("unauthorized", status_code=401),
        loomloom.LoomLoomAPIError("rate limited", status_code=429, retryable=True),
        ValueError("invalid quote"),
        ValueError(""),
    ],
)
def test_failed_quote_pauses_until_manual_retry_and_recovers(quote_page, error):
    app, _, quote, _ = quote_page
    quote.side_effect = error
    app.run()
    assert quote.call_count == 1
    for _ in range(3):
        app.run()
    assert quote.call_count == 1
    assert app.session_state["loomloom_video_quote_error"]
    widget(app.button, "loomloom_retry_video_quote").click().run()
    assert quote.call_count == 2
    app.run()
    assert quote.call_count == 2
    quote.side_effect = None
    quote.return_value = loomloom.LoomLoomQuote("q", "v", "CNY", 1, 0, "0", ())
    widget(app.button, "loomloom_retry_video_quote").click().run()
    assert quote.call_count == 3
    assert not app.session_state["loomloom_video_quote_error"]
    assert not app.session_state["loomloom_video_confirm_charge"]
    request_id = app.session_state["loomloom_video_client_request_id"]
    app.run()
    assert quote.call_count == 3
    assert app.session_state["loomloom_video_client_request_id"] == request_id
    assert not any(item.key == "loomloom_retry_video_quote" for item in app.button)


@pytest.mark.parametrize(
    "field", ["subject", "terms", "model", "ratio", "count", "key", "endpoint"]
)
def test_changed_billable_inputs_allow_one_new_quote_attempt(quote_page, field):
    app, values, quote, _ = quote_page
    quote.side_effect = loomloom.LoomLoomAPIError("offline", retryable=True)
    app.run()
    signature = app.session_state["loomloom_video_quote_error_signature"]
    if field == "subject":
        widget(app.text_area, "video_subject").set_value("New topic")
    elif field == "terms":
        widget(app.text_area, "video_terms").set_value("new scene")
    elif field == "model":
        widget(app.selectbox, "loomloom_video_model_select_en").select("b")
    elif field == "ratio":
        widget(app.selectbox, "video_aspect_for_loomloom_en").select("9:16")
    elif field == "count":
        widget(app.number_input, "loomloom_video_scene_count").set_value(2)
    elif field == "key":
        values["loomloom_api_token"] = "second-key"
    else:
        values["loomloom_base_url"] = "https://second.test/v1"
    app.run()
    assert quote.call_count == 2
    assert app.session_state["loomloom_video_quote_error_signature"] != signature
    app.run()
    assert quote.call_count == 2


def test_missing_key_clears_error_and_never_retries(quote_page):
    app, values, quote, _ = quote_page
    quote.side_effect = loomloom.LoomLoomAPIError("offline")
    app.run()
    values["loomloom_api_token"] = ""
    app.run()
    app.run()
    assert quote.call_count == 1
    assert not app.session_state["loomloom_video_quote_error"]
    assert not any(item.key == "loomloom_retry_video_quote" for item in app.button)


@pytest.mark.parametrize("change", ["script", "source"])
def test_unrelated_edits_do_not_retry_failed_quote(quote_page, change):
    """文案正文不改变已有主题/关键词报价；切到其它来源也不能触发胜算云请求。"""
    app, _, quote, _ = quote_page
    quote.side_effect = loomloom.LoomLoomAPIError("offline")
    app.run()
    if change == "script":
        widget(app.text_area, "video_script").set_value("A different narration.").run()
    else:
        # 来源使用自定义分组控件，AppTest 无 selectbox 适配器；模拟其回传状态。
        app.session_state["video_source_select_en"] = "pexels"
        app.run()
        app.run()
        assert not any(item.key == "loomloom_retry_video_quote" for item in app.button)
        app.session_state["video_source_select_en"] = "loomloom"
        app.run()
    assert quote.call_count == 1


def test_incomplete_input_clears_failed_quote_without_network(quote_page):
    app, _, quote, _ = quote_page
    quote.side_effect = loomloom.LoomLoomAPIError("offline")
    app.run()
    widget(app.text_area, "video_subject").set_value("")
    widget(app.text_area, "video_script").set_value("")
    widget(app.text_area, "video_terms").set_value("")
    app.run()
    assert quote.call_count == 1
    assert not app.session_state["loomloom_video_quote_error"]
    assert not any(item.key == "loomloom_retry_video_quote" for item in app.button)


def test_new_quote_failure_disables_old_confirmation(quote_page):
    app, _, quote, _ = quote_page
    quote.return_value = loomloom.LoomLoomQuote("q", "v", "CNY", 1, 1, "0.1", ())
    app.run()
    widget(app.checkbox, "loomloom_video_confirm_charge").check().run()
    old_id = app.session_state["loomloom_video_client_request_id"]
    quote.side_effect = loomloom.LoomLoomAPIError("offline")
    widget(app.selectbox, "loomloom_video_model_select_en").select("b").run()
    assert not app.session_state["loomloom_video_confirm_charge"]
    assert widget(app.checkbox, "loomloom_video_confirm_charge").disabled
    widget(app.button, "generate_video_button").click().run()
    assert quote.call_count == 2
    quote.side_effect = None
    widget(app.button, "loomloom_retry_video_quote").click().run()
    assert app.session_state["loomloom_video_client_request_id"] != old_id
    assert not widget(app.checkbox, "loomloom_video_confirm_charge").value


@pytest.mark.parametrize(
    "script",
    [
        "AI helps us.",
        "人工智能帮助人们改善生活。" * 40,
        "  " + "AI improves daily life. " * 50 + "\n",
    ],
)
def test_batch_candidate_autofill_once_preserves_manual_count(script):
    values = dict(
        config.app,
        video_source="loomloom",
        script_generation_backend="loomloom",
        loomloom_api_token="",
        llm_provider="openai",
    )
    candidate = SimpleNamespace(
        row_index=0, script=script, video_terms=("robot", "home")
    )
    with (
        patch.object(config, "app", values),
        patch.object(config, "ui", {"video_clip_duration": 3}),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.session_state["loomloom_script_candidates"] = (candidate,)
        app.run()
        widget(app.button, "loomloom_apply_candidate").click().run()
        assert not app.exception
        expected = 1 if script == "AI helps us." else loomloom.MAX_VIDEO_SCENES
        assert widget(app.number_input, "loomloom_video_scene_count").value == expected
        assert app.session_state["loomloom_video_scene_autofill_digest"] == ""
        widget(app.number_input, "loomloom_video_scene_count").set_value(3).run()
        app.run()
        assert widget(app.number_input, "loomloom_video_scene_count").value == 3


def test_reference_price_copy_does_not_promise_quote_is_final():
    for locale in ("zh", "en"):
        messages = json.loads((MAIN.parent / "i18n" / f"{locale}.json").read_text())
        # 价格仅作选择参考，避免与“不完整估算仍可能扣费”的警告矛盾。
        text = messages["Translation"]["AI Video Model Reference Price"]
        assert ("实际模型调用" if locale == "zh" else "actual model usage") in text
