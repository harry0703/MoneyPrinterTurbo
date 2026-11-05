"""Codex image snapshots must survive queues and reject account changes."""

from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import codex_image, codex_oauth, task, webui_task


def context(generation=1, model="test-responses"):
    return codex_image.CodexImageContext(model, 300, generation)


def test_queue_snapshots_context_and_deduplicates_by_account():
    params = VideoParams(video_subject="Pyramids", video_source="codex_image")
    with (
        patch.dict(webui_task._active_submissions, {}, clear=True),
        patch.object(webui_task, "_enqueue_generation") as enqueue,
        patch.object(codex_image, "capture_context", return_value=context()) as capture,
    ):
        assert webui_task.submit_generation("first", params) == "first"
        assert webui_task.submit_generation("duplicate", params) == "first"
        assert enqueue.call_count == 1
        assert enqueue.call_args.args[-1] == context()
        capture.return_value = context(2)
        assert webui_task.submit_generation("new-account", params) == "new-account"
        capture.return_value = context(2, "other-model")
        assert webui_task.submit_generation("new-model", params) == "new-model"
        assert enqueue.call_count == 3


def test_queue_dedup_distinguishes_persistent_sessions_with_same_generation():
    from dataclasses import replace

    params = VideoParams(video_subject="Pyramids", video_source="codex_image")
    first = replace(
        context(0), session=codex_oauth.CodexSessionBinding("account-a", "login-a")
    )
    other_account = replace(
        first, session=codex_oauth.CodexSessionBinding("account-b", "login-b")
    )
    same_account_reconnected = replace(
        first, session=codex_oauth.CodexSessionBinding("account-a", "new-login-a")
    )
    with (
        patch.dict(webui_task._active_submissions, {}, clear=True),
        patch.object(webui_task, "_enqueue_generation") as enqueue,
        patch.object(codex_image, "capture_context", return_value=first) as capture,
    ):
        assert webui_task.submit_generation("first", params) == "first"
        assert webui_task.submit_generation("duplicate", params) == "first"
        capture.return_value = other_account
        assert webui_task.submit_generation("different-account", params) == "different-account"
        capture.return_value = same_account_reconnected
        assert webui_task.submit_generation("reconnected", params) == "reconnected"
        assert enqueue.call_count == 3


def test_queued_account_change_fails_before_script_or_voice():
    params = VideoParams(
        video_subject="Pyramids", video_source="codex_image", subtitle_enabled=False
    )
    with (
        patch.object(codex_oauth, "authorization_generation", return_value=2),
        patch.object(task, "generate_script") as script,
        patch.object(task, "_mark_task_failed", return_value={"failed": True}) as fail,
    ):
        result = task.start("stale", params, codex_image_context=context())
    assert result == {"failed": True}
    assert fail.call_args.args[1] == "preflight"
    script.assert_not_called()


def test_api_captures_context_before_any_consuming_service():
    params = VideoParams(
        video_subject="Pyramids", video_source="codex_image", subtitle_enabled=False
    )
    with (
        patch.object(
            codex_image,
            "capture_context",
            side_effect=codex_image.CodexImageError("codex.image.model_required"),
        ),
        patch.object(task, "generate_script") as script,
        patch.object(task, "_mark_task_failed", return_value=None) as fail,
    ):
        task.start("missing-model", params)
    assert fail.call_args.args[1] == "preflight"
    assert fail.call_args.kwargs["details"]["error_key"] == "codex.image.model_required"
    script.assert_not_called()


def test_worker_forwards_frozen_context():
    from contextlib import nullcontext

    snapshot = context()
    with (
        patch.object(
            webui_task.config, "runtime_config_lock", return_value=nullcontext()
        ),
        patch.object(task, "start", return_value={}) as start,
    ):
        webui_task._run_generation(
            "frozen",
            VideoParams(video_subject="Pyramids", video_source="codex_image"),
            False,
            codex_image_context=snapshot,
        )
    assert start.call_args.kwargs["codex_image_context"] is snapshot


def test_material_phase_forwards_context_and_retains_translatable_error():
    from app.services import material

    snapshot = context()
    params = VideoParams(video_subject="Pyramids", video_source="codex_image")
    error = material.CodexImageMaterialError(
        codex_image.CodexImageError("codex.image.invalid_result")
    )
    with (
        patch.object(material, "download_videos", side_effect=error) as download,
        patch.object(task, "_mark_task_failed") as fail,
    ):
        assert (
            task.get_video_materials(
                "image-error", params, ["pyramid"], 3, codex_image_context=snapshot
            )
            is None
        )
    assert download.call_args.kwargs["codex_image_context"] is snapshot
    assert fail.call_args.kwargs["details"] == {
        "error_key": "codex.image.invalid_result",
        "error_params": {},
    }


def test_cli_and_bootstrap_accept_codex_without_an_api_key(tmp_path, monkeypatch):
    import importlib.util
    import cli
    args = cli.parse_args(["--video-subject", "Pyramids", "--video-source", "codex_image", "--image-motion", "static"])
    assert cli.build_video_params(args).video_source == "codex_image"
    spec = importlib.util.spec_from_file_location("image_bootstrap", Path(__file__).resolve().parents[2] / "docs/skill/mpt_agent.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    config_file = tmp_path / "config.toml"
    config_file.write_text('llm_provider="ollama"\ncodex_image_model_name="responses-model"\n', encoding="utf-8")
    monkeypatch.setenv("MPT_HOME", str(tmp_path))
    provider, missing = helper.missing_config(config_file, ["--video-source", "codex_image"])
    assert missing == ["codex_sign_in"]
    auth = tmp_path / "storage/auth/openai_codex.bin"
    auth.parent.mkdir(parents=True)
    auth.write_bytes(b"presence only; helper never decrypts")
    assert helper.missing_config(config_file, ["--video-source", "codex_image"])[1] == []


def test_translatable_failure_is_persisted_and_returned_consistently(tmp_path):
    from app.services.state import MemoryState
    state = MemoryState()
    with patch.object(task.sm, "state", state):
        state.update_task("translated", state=task.const.TASK_STATE_PROCESSING, error_key=None, error_params=None)
        result = task._mark_task_failed("translated", "materials", "sanitized", details={"error_key": "codex.oauth.http_error", "error_params": {"status": 403}})
        assert result == state.get_task("translated")
        assert result["error_key"] == "codex.oauth.http_error"
        assert result["error_params"] == {"status": 403}
