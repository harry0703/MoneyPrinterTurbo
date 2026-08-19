import ast
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import loomloom


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


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


def test_loomloom_webui_quotes_then_requires_confirmation_before_execute():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="loomloom",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="test-token",
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
        _widget_by_key(app.text_input, "loomloom_user_api_token").set_value(
            "user-token-1"
        ).run()
        _widget_by_key(app.button, "loomloom_quote_scripts").click().run()

        assert quote_call.call_count == 1
        execute_button = _widget_by_key(app.button, "loomloom_execute_scripts")
        assert execute_button.disabled
        assert execute_call.call_count == 0

        _widget_by_key(app.text_input, "loomloom_user_api_token").set_value(
            "user-token-2"
        ).run()
        assert _widget_by_key(app.button, "loomloom_execute_scripts").disabled

        _widget_by_key(app.text_input, "loomloom_user_api_token").set_value(
            "user-token-1"
        ).run()
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


def test_loomloom_video_source_quotes_then_passes_secret_in_confirmed_request():
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
        video_source="pexels",
        loomloom_base_url="https://example.test/loom/v1",
        loomloom_api_token="",
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
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            loomloom.LoomLoomVideoBackend,
            "quote",
            return_value=quote_result,
        ) as quote_call,
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
        _widget_by_key(app.selectbox, "video_source_select_en").select("loomloom").run()
        _widget_by_key(app.text_input, "loomloom_user_api_token").set_value(
            "session-user-token"
        ).run()
        assert _widget_by_key(app.number_input, "loomloom_video_scene_count").value == 1
        _widget_by_key(app.button, "loomloom_quote_videos").click().run()
        assert quote_call.call_count == 1
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


def test_selected_shengsuanyun_provider_hides_duplicate_loomloom_key_input():
    test_config = dict(
        config.app,
        llm_provider="shengsuanyun",
        shengsuanyun_api_key="provider-key",
        script_generation_backend="loomloom",
        loomloom_api_token="standalone-key",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        assert all(item.key != "loomloom_user_api_token" for item in app.text_input)
        assert any("reused" in str(item.value).lower() for item in app.caption)
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
