import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import llm, loomloom


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _video_capability(default_model_id="model-a", models=None):
    return loomloom.LoomLoomVideoCapability(
        models=(
            (
                loomloom.LoomLoomVideoModel("model-a", "Model A"),
                loomloom.LoomLoomVideoModel("model-b", "Model B"),
            )
            if models is None
            else tuple(models)
        ),
        default_model_id=default_model_id,
        aspect_ratios=("16:9", "9:16"),
    )


def _function(tree, name):
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _widget_by_key(elements, key):
    return next(item for item in elements if str(getattr(item, "key", "")) == key)


def test_loomloom_execution_requires_confirmation_and_quoted_version():
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = _function(tree, "_render_loomloom_script_generation")
    execute_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]

    assert len(execute_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in execute_calls[0].keywords}
    assert isinstance(keywords["confirm"], ast.Constant)
    assert keywords["confirm"].value is True
    assert "client_request_id" in keywords
    assert "listing_version_id" in keywords
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "checkbox"
        for node in ast.walk(function)
    )


def test_loomloom_path_does_not_fall_back_to_local_llm_calls():
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    loomloom_function = _function(tree, "_render_loomloom_script_generation")
    local_function = _function(tree, "_render_local_script_generation")

    def llm_calls(function):
        return {
            node.func.attr
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "llm"
        }

    assert llm_calls(loomloom_function) == set()
    assert {"generate_script", "generate_terms"} <= llm_calls(local_function)


def test_loomloom_quote_signature_changes_with_billable_inputs():
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    signature_function = _function(tree, "_loomloom_script_signature")
    module = ast.fix_missing_locations(
        ast.Module(body=[signature_function], type_ignores=[])
    )
    namespace = {"hashlib": hashlib, "json": json}
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    signature = namespace["_loomloom_script_signature"]

    original = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=3,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-a",
    )
    repeated = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=3,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-a",
    )
    changed = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=4,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-a",
    )
    changed_credential = signature(
        subject="主题",
        language="zh-CN",
        candidate_count=3,
        duration_seconds=60,
        style="轻松",
        credential_fingerprint="account-b",
    )

    assert original == repeated
    assert original != changed
    assert original != changed_credential


def test_loomloom_model_reference_prices_match_known_models_and_ignore_new_ones():
    """价格仅是本地展示增强，未知后端模型不能因此变成不可选。"""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    price_table = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "LOOMLOOM_VIDEO_MODEL_PRICES"
            for target in node.targets
        )
    )
    module = ast.fix_missing_locations(
        ast.Module(
            body=[
                price_table,
                _function(tree, "_normalize_loomloom_model_identifier"),
                _function(tree, "_loomloom_video_model_price"),
                _function(tree, "_format_loomloom_video_model_option"),
            ],
            type_ignores=[],
        )
    )
    namespace = {"re": __import__("re")}
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)

    known_models = (
        ("google/veo3.1-fast-preview", "Veo3.1-fast", "￥0.700/秒"),
        ("", "通义万相2.2-文生视频-Fast-Lora", "￥0.350–0.770/条"),
        ("", "即梦3.0-文生视频-720P", "￥0.230/秒"),
        ("", "即梦3.0Pro-视频", "￥1.000/秒"),
        ("", "Veo3", "￥1.400/秒"),
        ("", "Veo3.1", "￥1.400/秒"),
        ("", "KlingV2", "￥10.00–20.00/条"),
        ("", "Kling V2.1 Master", "￥10.00–20.00/条"),
        ("", "ViduQ3-Pro", "￥0.440–1.000/秒"),
    )
    unknown = SimpleNamespace(model_id="future/model", display_name="Future Model")

    for model_id, display_name, compact_price in known_models:
        model = SimpleNamespace(model_id=model_id, display_name=display_name)
        assert namespace["_format_loomloom_video_model_option"](model) == (
            f"{display_name} · {compact_price}"
        )
    assert namespace["_loomloom_video_model_price"](unknown) == ("", "")
    assert namespace["_format_loomloom_video_model_option"](unknown) == "Future Model"


def test_loomloom_webui_quotes_then_requires_confirmation_before_execute():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="loomloom",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="user-token-1",
        loomloom_market_listing_id="listing-1",
    )
    quote_result = loomloom.LoomLoomQuote(
        quote_id="quote-1",
        listing_version_id="listing-version-1",
        currency="CNY",
        task_count=3,
        estimated_buyer_payable_t=12345,
        estimated_buyer_payable_amount="0.0012345",
        input_rows=(),
    )
    execution = loomloom.LoomLoomExecution(
        run_id="run-1",
        transaction_id="transaction-1",
        transaction_status="running",
        listing_version_id="listing-version-1",
    )
    running = loomloom.LoomLoomRun("run-1", "running", 3, 0, 0, 0, "")

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomScriptBackend,
            "quote",
            return_value=quote_result,
        ) as quote_call,
        patch.object(
            loomloom.LoomLoomScriptBackend,
            "execute",
            return_value=execution,
        ) as execute_call,
        patch.object(
            loomloom.LoomLoomScriptBackend,
            "get_run",
            return_value=running,
        ),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        assert quote_call.call_count == 0
        assert execute_call.call_count == 0

        _widget_by_key(app.text_area, "video_subject").set_value("AI daily life").run()
        assert all(item.key != "loomloom_user_api_token" for item in app.text_input)
        _widget_by_key(app.button, "loomloom_quote_scripts").click().run()

        assert quote_call.call_count == 1
        execute_button = _widget_by_key(app.button, "loomloom_execute_scripts")
        assert execute_button.disabled
        assert execute_call.call_count == 0

        test_config["loomloom_api_token"] = "user-token-2"
        app.run()
        assert _widget_by_key(app.button, "loomloom_execute_scripts").disabled

        test_config["loomloom_api_token"] = "user-token-1"
        app.run()
        _widget_by_key(app.checkbox, "loomloom_confirm_charge").check().run()
        execute_button = _widget_by_key(app.button, "loomloom_execute_scripts")
        assert not execute_button.disabled
        execute_button.click().run()

        assert execute_call.call_count == 1
        assert execute_call.call_args.kwargs["confirm"] is True
        assert (
            execute_call.call_args.kwargs["listing_version_id"] == "listing-version-1"
        )
        assert execute_call.call_args.kwargs["client_request_id"].startswith("mpt-")
        assert app.session_state["loomloom_script_quote"] is None
        assert app.session_state["loomloom_script_batch"] is None
        assert [str(item.value) for item in app.exception] == []


def test_generated_long_script_autofills_video_count_once_and_shows_shortfall():
    """推荐数受五段上限约束，且用户手动调整后不能被下一次 rerun 覆盖。"""
    long_script = " ".join(
        [
            "Robots cross the ruined city while alarms echo through every street"
        ]
        * 8
    )
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
        video_source="loomloom",
        loomloom_api_token="",
    )
    test_ui_config = dict(config.ui, video_clip_duration=3)

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(llm, "generate_script", return_value=long_script),
        patch.object(llm, "generate_terms", return_value=["robot city"]),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        _widget_by_key(app.text_area, "video_subject").set_value("Robot city").run()
        _widget_by_key(app.button, "auto_generate_script").click().run()

        scene_count = _widget_by_key(
            app.number_input, "loomloom_video_scene_count"
        )
        assert scene_count.value == loomloom.MAX_VIDEO_SCENES
        warning_text = " ".join(str(item.value) for item in app.warning).lower()
        assert "shortfall" in warning_text
        assert "black screen" not in warning_text
        assert "cover approximately 15.0 sec" in warning_text
        assert app.session_state["loomloom_video_scene_autofill_digest"] == ""

        scene_count.set_value(3).run()
        assert _widget_by_key(
            app.number_input, "loomloom_video_scene_count"
        ).value == 3
        # 任意普通 rerun 也应保留用户的手动选择，而不是再次跳回推荐值 5。
        _widget_by_key(app.text_area, "video_subject").set_value(
            "Robot city updated"
        ).run()
        assert _widget_by_key(
            app.number_input, "loomloom_video_scene_count"
        ).value == 3
        assert [str(item.value) for item in app.exception] == []


def test_loomloom_video_source_quotes_then_passes_secret_in_confirmed_request():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
        video_source="pexels",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="session-user-token",
    )
    quote_result = loomloom.LoomLoomQuote(
        quote_id="video-quote-1",
        listing_version_id="video-version-1",
        currency="CNY",
        task_count=1,
        estimated_buyer_payable_t=1230000,
        estimated_buyer_payable_amount="0.123",
        input_rows=(),
    )

    with (
        patch.object(config, "app", test_config),
        # 显式从两段切到一段，不能依赖开发者 config.toml 中的历史值。
        patch.object(config, "ui", dict(config.ui, loomloom_video_scene_count=2)),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "quote",
            return_value=quote_result,
        ) as quote_call,
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "resolve_video_capability",
            return_value=_video_capability(),
        ) as resolve_call,
        patch("app.services.webui_task.submit_generation") as submit_generation,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        _widget_by_key(app.text_area, "video_subject").set_value("AI office").run()
        _widget_by_key(app.text_area, "video_script").set_value(
            "AI helps people work faster."
        ).run()
        _widget_by_key(app.text_area, "video_terms").set_value(
            "office worker, AI assistant, productive team"
        ).run()
        app.session_state["video_source_select_en"] = "loomloom"
        app.run()
        _widget_by_key(app.number_input, "loomloom_video_scene_count").set_value(
            1
        ).run()
        model_select = _widget_by_key(app.selectbox, "loomloom_video_model_select_en")
        assert model_select.value == "model-a"
        assert model_select.options == ["Model A", "Model B"]
        assert resolve_call.call_count == 1
        assert all(item.key != "loomloom_user_api_token" for item in app.text_input)
        # 切换来源后取得初始报价；场景数归一为 1 后再刷新一次。
        assert quote_call.call_count == 2
        assert all(item.key != "loomloom_quote_videos" for item in app.button)
        quoted_batch = quote_call.call_args.args[0]
        assert quoted_batch.input_rows[0]["modelChoice"] == "model-a"

        model_select = _widget_by_key(app.selectbox, "loomloom_video_model_select_en")
        model_select.select("model-b").run()
        assert quote_call.call_count == 3
        assert not _widget_by_key(
            app.checkbox, "loomloom_video_confirm_charge"
        ).value

        _widget_by_key(app.selectbox, "loomloom_video_model_select_en").select(
            "model-a"
        ).run()
        assert quote_call.call_count == 4
        _widget_by_key(app.checkbox, "loomloom_video_confirm_charge").check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()

        assert submit_generation.call_count == 1
        submitted_params = submit_generation.call_args.kwargs["params"]
        video_request = submit_generation.call_args.kwargs["loomloom_video_request"]
        assert "session-user-token" not in submitted_params.model_dump_json()
        assert video_request.settings.api_token == "session-user-token"
        assert "session-user-token" not in repr(video_request)
        assert video_request.listing_version_id == "video-version-1"
        assert video_request.client_request_id.startswith("mpt-video-")
        assert app.session_state["loomloom_video_quote"] is None
        assert [str(item.value) for item in app.exception] == []


def test_loomloom_refresh_keeps_unavailable_selection_until_user_changes_it():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
        video_source="pexels",
        loomloom_api_token="session-user-token",
    )
    refreshed_capability = _video_capability(
        models=(loomloom.LoomLoomVideoModel("model-a", "Model A"),)
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "resolve_video_capability",
            side_effect=[_video_capability(), refreshed_capability],
        ),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        app.session_state["video_source_select_en"] = "loomloom"
        app.run()
        _widget_by_key(app.selectbox, "loomloom_video_model_select_en").select(
            "model-b"
        ).run()
        _widget_by_key(app.button, "loomloom_refresh_video_models").click().run()

        selected = _widget_by_key(app.selectbox, "loomloom_video_model_select_en")
        assert selected.value == "model-b"
        assert selected.options[0] == "Unavailable: model-b"
        assert any(
            "no longer available" in str(item.value).lower() for item in app.error
        )
        assert all(item.key != "loomloom_quote_videos" for item in app.button)
        assert [str(item.value) for item in app.exception] == []


def test_loomloom_zero_video_quote_warns_about_actual_charges():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
        video_source="pexels",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="",
    )
    quote_result = loomloom.LoomLoomQuote(
        quote_id="video-quote-zero",
        listing_version_id="video-version-1",
        currency="CNY",
        task_count=1,
        estimated_buyer_payable_t=0,
        estimated_buyer_payable_amount="0",
        input_rows=(),
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "resolve_video_capability",
            return_value=_video_capability(),
        ),
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "quote",
            return_value=quote_result,
        ),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        _widget_by_key(app.text_area, "video_subject").set_value("AI office").run()
        _widget_by_key(app.text_area, "video_script").set_value("AI at work").run()
        _widget_by_key(app.text_area, "video_terms").set_value("office").run()
        app.session_state["video_source_select_en"] = "loomloom"
        app.run()
        test_config["loomloom_api_token"] = "session-user-token"
        app.run()

        warnings = " ".join(str(item.value) for item in app.warning).lower()
        assert all(item.key != "loomloom_quote_videos" for item in app.button)
        assert "complete cost estimate" in warnings
        assert "final billing" in warnings
        assert "free" not in warnings
        assert not _widget_by_key(
            app.checkbox, "loomloom_video_confirm_charge"
        ).disabled
        assert [str(item.value) for item in app.exception] == []


def test_selected_shengsuanyun_provider_hides_duplicate_loomloom_key_input():
    test_config = dict(
        config.app,
        llm_provider="shengsuanyun",
        shengsuanyun_api_key="provider-key",
        script_generation_backend="local",
        loomloom_api_token="standalone-key",
        video_source="pexels",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.run()

        assert all(item.key != "loomloom_user_api_token" for item in app.text_input)
        generation_method = _widget_by_key(
            app.selectbox, "script_generation_backend_select_zh"
        )
        assert generation_method.value == "local"
        assert "使用“设置”中当前选择的大模型 Provider 生成文案" in generation_method.help
        assert "LoomLoom" not in generation_method.help
        assert "https://console.shengsuanyun.com/user/keys" not in generation_method.help

        generation_method.select("loomloom").run()
        generation_method = _widget_by_key(
            app.selectbox, "script_generation_backend_select_zh"
        )
        assert generation_method.value == "loomloom"
        assert "LoomLoom 会批量生成多个独立文案候选" in generation_method.help
        assert "已复用“设置 → 大模型提供商”中的胜算云 API Key" in generation_method.help
        assert (
            "https://console.shengsuanyun.com/user/keys" in generation_method.help
        )
        assert _widget_by_key(app.button, "loomloom_quote_scripts")
        assert all(item.key != "auto_generate_script" for item in app.button)
        assert all(item.key != "loomloom_user_api_token" for item in app.text_input)
        assert all(
            "https://console.shengsuanyun.com/user/keys" not in str(item.value)
            for item in app.markdown
        )
        assert [str(item.value) for item in app.exception] == []


def test_paused_script_run_keeps_remote_id_until_user_stops_tracking():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="loomloom",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="configured-token",
        loomloom_market_listing_id="script-listing",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.session_state["loomloom_run_id"] = "paid-run-1"
        app.session_state["loomloom_run_error"] = "temporary network failure"
        app.session_state["loomloom_poll_paused"] = True
        app.run()

        assert _widget_by_key(app.button, "loomloom_quote_scripts").disabled
        assert _widget_by_key(app.button, "loomloom_resume_status_check")
        _widget_by_key(app.button, "loomloom_stop_tracking_run").click().run()

        assert app.session_state["loomloom_run_id"] == ""
        assert not app.session_state["loomloom_poll_paused"]
        assert [str(item.value) for item in app.exception] == []
