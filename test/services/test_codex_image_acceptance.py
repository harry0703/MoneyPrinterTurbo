"""Acceptance reports require remote completion, not merely a local PNG."""

from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from app.services import codex_oauth, material
from scripts import accept_codex_image as acceptance


@pytest.fixture
def fake_route(tmp_path, monkeypatch):
    trace = [
        {
            "kind": "http",
            "status": 200,
            "request_id": "req_synthetic",
            "authorization": "SECRET_TOKEN",
        },
        {
            "kind": "response",
            "event": "response.completed",
            "status": "completed",
            "response_id": "resp_synthetic",
            "response_model": "chosen-model",
            "prompt": "SECRET_PROMPT",
        },
        {
            "kind": "image_tool",
            "event": "response.output_item.done",
            "tool_id": "ig_synthetic",
            "status": "completed",
            "result_bytes": 1024,
            "result": "SECRET_BASE64",
        },
    ]

    @contextmanager
    def capture():
        yield trace

    monkeypatch.setattr(
        codex_oauth, "capture_image_diagnostics", capture, raising=False
    )
    monkeypatch.setattr(
        acceptance, "_revision", lambda: {"commit": "synthetic", "dirty": False}
    )
    context = SimpleNamespace(timeout=300)
    capture_context = Mock(return_value=context)
    monkeypatch.setattr(acceptance.codex_image, "capture_context", capture_context)
    monkeypatch.setattr(acceptance.codex_image, "assert_current", lambda ctx: None)
    png = tmp_path / "synthetic.png"
    Image.new("RGB", (32, 18), "gold").save(png)
    generate = Mock(return_value=[SimpleNamespace(url=str(png))])
    monkeypatch.setattr(material, "generate_images_codex", generate)
    render = Mock(
        side_effect=lambda path, motion: {
            "file": motion + ".mp4",
            "duration_seconds": 2,
            "first_frame_decoded": True,
        }
    )
    monkeypatch.setattr(acceptance, "_render_and_probe", render)
    return SimpleNamespace(
        trace=trace,
        generate=generate,
        capture_context=capture_context,
        render=render,
        context=context,
    )


def run(tmp_path, **kwargs):
    return acceptance.run_acceptance(
        model="chosen-model",
        output_dir=tmp_path / "assets",
        confirm_image_generation=True,
        **kwargs,
    )


def test_success_requires_remote_evidence_and_uses_one_normal_material_request(
    tmp_path, fake_route
):
    report = run(tmp_path, plan="pro")
    assert report["status"] == "passed"
    assert report["requested_model"] == "chosen-model"
    assert report["self_reported_plan"] == "pro"
    assert report["account_access_verified"] is True
    assert report["image"]["decoded"] is True
    assert len(report["image"]["sha256"]) == 64
    assert set(report["renders"]) == {"static", "zoom"}
    fake_route.capture_context.assert_called_once_with(
        {"codex_image_model_name": "chosen-model", "codex_image_timeout": 300}
    )
    fake_route.generate.assert_called_once_with(
        acceptance.PROMPT,
        2,
        "16:9",
        str(tmp_path / "assets"),
        context=fake_route.context,
    )
    assert fake_route.render.call_count == 2
    payload = json.dumps(report)
    for private in (
        "SECRET_TOKEN",
        "SECRET_PROMPT",
        "SECRET_BASE64",
        "authorization",
        '"result"',
    ):
        assert private not in payload


@pytest.mark.parametrize("missing_kind", ["response", "image_tool"])
def test_local_png_does_not_prove_live_generation(tmp_path, fake_route, missing_kind):
    fake_route.trace[:] = [
        record for record in fake_route.trace if record["kind"] != missing_kind
    ]
    report = run(tmp_path)
    assert report["status"] == "failed"
    assert report["error"]["code"] == "completed_image_evidence_missing"
    fake_route.render.assert_not_called()


def test_http_failure_keeps_safe_diagnostics_without_retry_or_raw_message(
    tmp_path, fake_route
):
    fake_route.trace[:] = [
        {"kind": "http", "status": 400, "request_id": None},
        {
            "kind": "provider_error",
            "error_type": "invalid_request_error",
            "error_code": None,
            "error_param": "tool_choice",
            "reason": "tool_choice_missing_image_tool",
            "message": "SECRET_REMOTE_BODY",
        },
    ]
    fake_route.generate.side_effect = material.CodexImageMaterialError(
        codex_oauth.CodexError("codex.oauth.http_error", status=400)
    )
    report = run(tmp_path)
    assert report["status"] == "failed"
    assert report["error"] == {"code": "codex.oauth.http_error", "http_status": 400}
    assert report["trace"][-1]["reason"] == "tool_choice_missing_image_tool"
    assert "SECRET_REMOTE_BODY" not in json.dumps(report)
    fake_route.generate.assert_called_once()
    fake_route.render.assert_not_called()


def test_no_generation_without_explicit_confirmation(tmp_path, fake_route):
    report = acceptance.run_acceptance(model="chosen-model", output_dir=tmp_path)
    assert report["error"]["code"] == "explicit_generation_confirmation_required"
    fake_route.capture_context.assert_not_called()
    fake_route.generate.assert_not_called()


def test_unexpected_errors_never_expose_exception_text(tmp_path, fake_route):
    fake_route.generate.side_effect = RuntimeError(
        "Bearer SECRET_TOKEN account SECRET_ACCOUNT"
    )
    report = run(tmp_path)
    assert report["error"] == {"code": "unexpected_error", "type": "RuntimeError"}
    assert "SECRET_" not in json.dumps(report)


def test_render_failure_does_not_regenerate(tmp_path, fake_route):
    fake_route.render.side_effect = acceptance.AcceptanceFailure("render_failed")
    report = run(tmp_path)
    assert report["error"]["code"] == "render_failed"
    assert report["account_access_verified"] is True
    fake_route.generate.assert_called_once()
    fake_route.render.assert_called_once()


def test_cli_requires_confirmation_before_entering_acceptance(tmp_path, monkeypatch):
    acceptance_run = Mock()
    monkeypatch.setattr(acceptance, "run_acceptance", acceptance_run)
    with pytest.raises(SystemExit) as exit_info:
        acceptance.main(
            ["--model", "chosen-model", "--output", str(tmp_path / "report.json")]
        )
    assert exit_info.value.code == 2
    acceptance_run.assert_not_called()


def test_cli_writes_failed_report_with_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        acceptance,
        "run_acceptance",
        lambda **kwargs: {"status": "failed", "error": {"code": "rejected"}},
    )
    monkeypatch.setattr(acceptance.logger, "remove", lambda: None)
    monkeypatch.setattr(acceptance, "set_logging_options", lambda *args: None)
    destination = tmp_path / "report.json"
    result = acceptance.main(
        [
            "--model",
            "chosen-model",
            "--output",
            str(destination),
            "--confirm-image-generation",
        ]
    )
    assert result == 1
    assert json.loads(destination.read_text(encoding="utf-8"))["status"] == "failed"


@pytest.mark.parametrize(
    "model", ["SECRET arbitrary text", "sk-SECRET-token", "eyJSECRET.jwt.token"]
)
def test_invalid_model_is_not_copied_into_report(tmp_path, fake_route, model):
    report = acceptance.run_acceptance(
        model=model, output_dir=tmp_path, confirm_image_generation=True
    )
    assert report["requested_model"] is None
    assert "SECRET" not in json.dumps(report)
    fake_route.generate.assert_not_called()


def test_render_subprocess_has_timeout_and_does_not_expose_stderr(monkeypatch):
    import subprocess

    process = Mock(
        side_effect=subprocess.TimeoutExpired(
            ["private-path"], 120, stderr="SECRET_STDERR"
        )
    )
    monkeypatch.setattr(acceptance.subprocess, "run", process)
    with pytest.raises(acceptance.AcceptanceFailure, match="^render_timeout$"):
        acceptance._render_and_probe("image.png", "static")
    assert process.call_args.kwargs["timeout"] == 120


@pytest.mark.parametrize("http_status", [200, 400])
def test_report_integrates_actual_transport_diagnostics_and_material_path(
    tmp_path, monkeypatch, http_status
):
    import base64
    import io
    import time

    monkeypatch.setattr(codex_oauth, "_credential_path", lambda: tmp_path / "auth.bin")
    codex_oauth._save(
        {
            "access_token": "SECRET_ACCESS_TOKEN",
            "refresh_token": "SECRET_REFRESH_TOKEN",
            "account_id": "SECRET_ACCOUNT_ID",
            "expires_at": time.time() + 3600,
        }
    )
    png = io.BytesIO()
    Image.new("RGB", (32, 18), "gold").save(png, format="PNG")
    events = [
        {
            "type": "response.output_item.done",
            "item": {
                "type": "image_generation_call",
                "id": "ig_synthetic",
                "status": "completed",
                "result": base64.b64encode(png.getvalue()).decode(),
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp_synthetic",
                "model": "chosen-model",
                "status": "completed",
                "output": [],
            },
        },
    ]

    class Response:
        status_code = http_status
        headers = {"x-request-id": "req_synthetic", "Set-Cookie": "SECRET_COOKIE"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, **kwargs):
            if self.status_code == 400:
                return iter([json.dumps(self.json()).encode()])
            return iter(
                [("data: " + json.dumps(event) + "\n\n").encode() for event in events]
            )

        def json(self):
            return {
                "error": {
                    "type": "invalid_request_error",
                    "param": "tool_choice",
                    "message": "Tool choice 'image_generation' must be specified with 'tools' parameter.",
                    "private": "SECRET_ERROR_FIELD",
                }
            }

    post = Mock(return_value=Response())
    monkeypatch.setattr(codex_oauth.requests, "post", post)
    monkeypatch.setattr(
        acceptance,
        "_render_and_probe",
        lambda path, motion: {
            "file": motion + ".mp4",
            "first_frame_decoded": True,
            "duration_seconds": 2,
        },
    )
    report = run(tmp_path)
    assert report["trace"][0] == {
        "kind": "http",
        "attempt": 1,
        "status": http_status,
        "requested_model": "chosen-model",
        "request_id": "req_synthetic",
    }
    assert "SECRET_" not in json.dumps(report)
    post.assert_called_once()
    if http_status == 200:
        assert report["status"] == "passed"
        assert report["image"]["width"] == 32
        assert report["image"]["height"] == 18
        assert any(
            record.get("response_id") == "resp_synthetic" for record in report["trace"]
        )
        assert any(
            record.get("result_bytes") == len(png.getvalue())
            for record in report["trace"]
        )
    else:
        assert report["status"] == "failed"
        assert report["trace"][-1]["reason"] == "tool_choice_missing_image_tool"
