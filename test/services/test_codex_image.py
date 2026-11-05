import base64
from concurrent.futures import ThreadPoolExecutor
import json
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services import codex_image as image
from app.services import codex_oauth as oauth


def reply(status=200, event=None, chunks=None, payload=None):
    response = MagicMock()
    response.status_code = status
    response.__enter__.return_value = response
    response.json.return_value = payload or {}
    if chunks is None:
        chunks = [b"data: " + json.dumps(event or completed()).encode() + b"\n\n"]
    response.iter_content.return_value = iter(chunks)
    return response


def completed(result=b"image bytes", status="completed"):
    return {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {
                    "type": "image_generation_call",
                    "status": status,
                    "result": base64.b64encode(result).decode(),
                }
            ],
        },
    }


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    with patch.object(oauth, "_credential_path", return_value=tmp_path / "auth.bin"):
        oauth.disconnect()
        oauth._save(
            {
                "access_token": "old",
                "refresh_token": "refresh",
                "account_id": "test-account",
                "expires_at": time.time() + 3600,
            }
        )
        yield
        oauth.disconnect()


def context():
    return image.capture_context({"codex_image_model_name": "selected-model"})


def test_capture_uses_independent_settings_and_no_login_or_refresh():
    with patch.object(oauth, "_post") as post:
        captured = image.capture_context(
            {
                "codex_image_model_name": "images",
                "openai_codex_model_name": "text",
                "codex_image_timeout": "450",
            }
        )
    assert (captured.model, captured.timeout) == ("images", 450)
    post.assert_not_called()


@pytest.mark.parametrize(
    "settings,key",
    [
        ({}, "codex.image.model_required"),
        (
            {"codex_image_model_name": "m", "codex_image_timeout": "nan"},
            "codex.image.invalid_timeout",
        ),
        (
            {"codex_image_model_name": "m", "codex_image_timeout": 0},
            "codex.image.invalid_timeout",
        ),
    ],
)
def test_preflight_rejects_invalid_config_without_network(settings, key):
    with (
        patch.object(oauth, "_post") as post,
        pytest.raises(image.CodexImageError) as error,
    ):
        image.capture_context(settings)
    assert error.value.key == key
    post.assert_not_called()


def test_capture_requires_shared_login():
    oauth.disconnect()
    with pytest.raises(image.CodexImageError) as error:
        context()
    assert error.value.key == "codex.oauth.not_connected"


def test_request_uses_fixed_endpoint_and_image_tool():
    captured = context()
    with patch.object(oauth.requests, "post", return_value=reply()) as post:
        assert image.generate_image("Pirámides", captured) == b"image bytes"
    request = post.call_args.kwargs
    assert post.call_args.args == (oauth.RESPONSES_URL,)
    assert request["allow_redirects"] is False
    assert request["headers"]["Authorization"] == "Bearer old"
    assert request["json"]["model"] == "selected-model"
    assert request["json"]["tools"] == [
        {"type": "image_generation", "action": "generate", "output_format": "png"}
    ]
    assert request["json"]["tool_choice"] == {"type": "image_generation"}
    assert request["json"]["parallel_tool_calls"] is False
    assert request["json"]["store"] is False


def test_parser_handles_chunk_boundaries_and_ignores_partial_events():
    raw = (
        b'data: {"type":"response.image_generation_call.partial_image","partial_image_b64":"discard"}\r\n\r\n'
        + b"data: "
        + json.dumps(completed()).encode()
        + b"\r\n\r\n"
    )
    chunks = [raw[i : i + 7] for i in range(0, len(raw), 7)]
    assert (
        image._read_stream(reply(chunks=chunks), time.monotonic() + 10)
        == b"image bytes"
    )


@pytest.mark.parametrize(
    "event",
    [
        {"type": "response.failed", "error": {"message": "secret"}},
        {"type": "response.completed", "response": {"status": "incomplete"}},
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": []},
        },
        completed(status="in_progress"),
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": [None]},
        },
    ],
)
def test_invalid_results_never_retry_or_expose_bodies(event):
    with patch.object(oauth, "_post", return_value=reply(event=event)) as post:
        with pytest.raises(image.CodexImageError) as error:
            image.generate_image("p", context())
    assert "secret" not in str(error.value)
    assert post.call_count == 1


def test_multiple_images_and_bad_base64_rejected():
    payload = completed()["response"]
    payload["output"].append(dict(payload["output"][0]))
    with pytest.raises(image.CodexImageError):
        image._final_image(payload)
    payload["output"] = [dict(payload["output"][0], result="secret!!!")]
    with pytest.raises(image.CodexImageError) as error:
        image._final_image(payload)
    assert "secret" not in str(error.value)


def test_decoded_and_transport_limits_are_independent():
    with (
        patch.object(image, "MAX_IMAGE_BYTES", 4),
        pytest.raises(image.CodexImageError),
    ):
        image._final_image(completed(b"12345")["response"])
    with (
        patch.object(image, "MAX_RESPONSE_BYTES", 10),
        pytest.raises(image.CodexImageError),
    ):
        image._read_stream(reply(chunks=[b"x" * 11]), time.monotonic() + 10)


@pytest.mark.parametrize(
    "response",
    [
        reply(chunks=[]),
        reply(chunks=[b'data: {"type":"response.completed"}']),
    ],
)
def test_truncated_stream_does_not_retry(response):
    with patch.object(oauth, "_post", return_value=response) as post:
        with pytest.raises(image.CodexImageError) as error:
            image.generate_image("p", context())
    assert error.value.key == "codex.image.uncertain"
    assert post.call_count == 1


def test_network_failure_does_not_retry():
    with patch.object(
        oauth.requests, "post", side_effect=requests.Timeout("secret")
    ) as post:
        with pytest.raises(image.CodexImageError) as error:
            image.generate_image("p", context())
    assert error.value.key == "codex.image.uncertain"
    assert "secret" not in str(error.value)
    assert post.call_count == 1


def test_401_renews_once_then_uses_same_authorization_generation():
    captured = context()
    replies = [
        reply(401),
        reply(
            payload={
                "access_token": "new",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }
        ),
        reply(),
    ]
    with patch.object(oauth, "_post", side_effect=replies) as post:
        assert image.generate_image("p", captured) == b"image bytes"
    assert post.call_count == 3
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer new"
    image.assert_current(captured)


def test_second_401_stops_and_keeps_shared_login():
    replies = [
        reply(401),
        reply(payload={"access_token": "new", "expires_in": 3600}),
        reply(401),
    ]
    with patch.object(oauth, "_post", side_effect=replies) as post:
        with pytest.raises(image.CodexImageError):
            image.generate_image("p", context())
    assert post.call_count == 3
    assert oauth.account_status()


def test_stale_queued_context_makes_no_request():
    captured = context()
    oauth.disconnect()
    with patch.object(oauth, "_post") as post, pytest.raises(image.CodexImageError):
        image.generate_image("p", captured)
    post.assert_not_called()


def test_account_change_during_result_rejects_old_image():
    captured = context()

    def read_then_change(response, deadline):
        oauth.disconnect()
        return b"old account image"

    with (
        patch.object(oauth, "_post", return_value=reply()),
        patch.object(image, "_read_stream", read_then_change),
    ):
        with pytest.raises(image.CodexImageError) as error:
            image.generate_image("p", captured)
    assert error.value.key == "codex.oauth.changed"


def test_generation_rechecked_after_credentials_wait():
    captured = context()

    def credentials(**kwargs):
        oauth.disconnect()
        return {"access_token": "new-account", "account_id": "another"}

    with (
        patch.object(oauth, "_credentials", side_effect=credentials),
        patch.object(oauth, "_post") as post,
    ):
        with pytest.raises(image.CodexImageError):
            image.generate_image("p", captured)
    post.assert_not_called()


def test_concurrent_image_and_text_share_single_refresh():
    captured = context()
    bundle = oauth._load()
    bundle["expires_at"] = 0
    oauth._save(bundle)
    refreshes = []

    def post(url, **kwargs):
        if url == oauth.TOKEN_URL:
            refreshes.append(True)
            return reply(
                payload={
                    "access_token": "new",
                    "refresh_token": "rotated",
                    "expires_in": 3600,
                }
            )
        if "tools" in kwargs["json"]:
            return reply()
        response = reply()
        event = {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ],
            },
        }
        response.iter_lines.return_value = iter(["data: " + json.dumps(event), ""])
        return response

    with patch.object(oauth, "_post", side_effect=post), ThreadPoolExecutor(2) as pool:
        image_future = pool.submit(image.generate_image, "p", captured)
        text_future = pool.submit(oauth.generate_text, "p", "text-model")
        assert image_future.result() == b"image bytes"
        assert text_future.result() == "OK"
    assert len(refreshes) == 1
    assert captured.generation == oauth.authorization_generation()


def stream_events(*events):
    return reply(
        chunks=[b"data: " + json.dumps(event).encode() + b"\n\n" for event in events]
    )


def image_done(result=b"image bytes", item_id="image-one", status="completed"):
    item = dict(completed(result)["response"]["output"][0], id=item_id)
    if status is None:
        item.pop("status")
    else:
        item["status"] = status
    return {"type": "response.output_item.done", "item": item}


@pytest.mark.parametrize("status", [None, "completed"])
def test_completed_tool_item_is_published_only_after_completed_response(status):
    final = {
        "type": "response.completed",
        "response": {"status": "completed", "output": []},
    }
    response = stream_events(image_done(status=status), final)
    assert image._read_stream(response, time.monotonic() + 10) == b"image bytes"


def test_tool_item_followed_by_truncated_stream_is_not_published():
    with pytest.raises(image.CodexImageError) as error:
        image._read_stream(stream_events(image_done()), time.monotonic() + 10)
    assert error.value.key == "codex.image.uncertain"


def test_final_response_can_repeat_same_tool_item():
    done = image_done()
    final = {
        "type": "response.completed",
        "response": {"status": "completed", "output": [done["item"]]},
    }
    assert (
        image._read_stream(stream_events(done, final), time.monotonic() + 10)
        == b"image bytes"
    )


@pytest.mark.parametrize(
    "second",
    [
        image_done(result=b"different", item_id="image-one"),
        image_done(item_id="image-two"),
        image_done(status="in_progress"),
    ],
)
def test_multiple_or_conflicting_done_items_are_rejected(second):
    with pytest.raises(image.CodexImageError):
        image._read_stream(stream_events(image_done(), second), time.monotonic() + 10)


def test_conflicting_final_response_cannot_replace_completed_item():
    final = {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [image_done(b"different")["item"]],
        },
    }
    with pytest.raises(image.CodexImageError):
        image._read_stream(stream_events(image_done(), final), time.monotonic() + 10)


def test_failed_response_does_not_publish_completed_tool_item():
    final = {"type": "response.failed", "response": {"status": "failed"}}
    with pytest.raises(image.CodexImageError):
        image._read_stream(stream_events(image_done(), final), time.monotonic() + 10)


def test_final_payload_missing_tool_status_needs_prior_done_evidence():
    done = image_done(status=None)
    final = {
        "type": "response.completed",
        "response": {"status": "completed", "output": [done["item"]]},
    }
    with pytest.raises(image.CodexImageError):
        image._read_stream(stream_events(final), time.monotonic() + 10)
    assert (
        image._read_stream(stream_events(done, final), time.monotonic() + 10)
        == b"image bytes"
    )


@pytest.mark.parametrize("output_index", [None, 1])
def test_anonymous_done_items_do_not_deduplicate_by_equal_results(output_index):
    first = image_done(item_id=None)
    first["item"].pop("id")
    first["output_index"] = 0
    second = image_done(item_id=None)
    second["item"].pop("id")
    if output_index is not None:
        second["output_index"] = output_index
    with pytest.raises(image.CodexImageError):
        image._read_stream(stream_events(first, second), time.monotonic() + 10)


def test_missing_status_in_conflicting_final_payload_still_rejected():
    final = {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [image_done(b"other", status=None)["item"]],
        },
    }
    with pytest.raises(image.CodexImageError):
        image._read_stream(stream_events(image_done(), final), time.monotonic() + 10)


def test_opt_in_diagnostics_are_selected_metadata_not_credentials_or_content():
    event = completed()
    event["response"].update(id="resp_synthetic", model="selected-model")
    event["response"]["output"][0]["id"] = "ig_synthetic"
    response = reply(event=event)
    response.headers = {
        "x-request-id": "req_synthetic",
        "Authorization": "private-header",
    }
    with oauth.capture_image_diagnostics() as records:
        with patch.object(oauth, "_post", return_value=response):
            assert image.generate_image("private prompt", context()) == b"image bytes"
    assert records[0] == {
        "kind": "http",
        "attempt": 1,
        "status": 200,
        "requested_model": "selected-model",
        "request_id": "req_synthetic",
    }
    assert {
        "kind": "response",
        "event": "response.completed",
        "response_id": "resp_synthetic",
        "response_model": "selected-model",
        "status": "completed",
    } in records
    assert {
        "kind": "image_tool",
        "event": "response.completed",
        "tool_id": "ig_synthetic",
        "status": "completed",
        "result_bytes": 11,
    } in records
    serialized = json.dumps(records)
    for secret in (
        "private prompt",
        "private-header",
        "refresh",
        "test-account",
        "aW1hZ2UgYnl0ZXM=",
    ):
        assert secret not in serialized
    oauth._record_image_diagnostic(kind="http", status=200)
    assert len(records) == 3


def test_provider_diagnostic_classifies_maintainer_400_without_recording_body():
    response = reply(
        status=400,
        payload={
            "error": {
                "type": "invalid_request_error",
                "param": "tool_choice",
                "code": "unknown-private-code",
                "message": "Tool choice 'image_generation' must be specified with 'tools' parameter.",
                "secret": "do not retain",
            }
        },
    )
    response.iter_content.return_value = iter(
        [json.dumps(response.json.return_value).encode()]
    )
    response.headers = {}
    with oauth.capture_image_diagnostics() as records:
        with patch.object(oauth, "_post", return_value=response) as post:
            with pytest.raises(image.CodexImageError):
                image.generate_image("private prompt", context())
    assert post.call_count == 1
    assert records[-1] == {
        "kind": "provider_error",
        "error_type": "invalid_request_error",
        "error_code": "other",
        "error_param": "tool_choice",
        "reason": "tool_choice_missing_image_tool",
    }
    assert "do not retain" not in json.dumps(records)
    assert "unknown-private-code" not in json.dumps(records)


def test_legacy_credentials_migrate_without_refresh_or_new_login():
    original = oauth._load()
    original.pop("session_revision")
    oauth._credential_path().write_bytes(oauth._protect(json.dumps(original).encode()))
    with patch.object(oauth, "_post") as post:
        captured = context()
        assert captured.session == oauth.capture_session_binding()
        assert oauth._load()["access_token"] == original["access_token"]
    assert captured.session.account_id == "test-account"
    assert captured.session.revision
    assert "test-account" not in repr(captured)
    post.assert_not_called()


def test_refresh_cannot_silently_replace_bound_account():
    captured = context()
    prior = oauth._load()
    claims = {
        "https://api.openai.com/auth": {"chatgpt_account_id": "different-account"}
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    response = reply(
        payload={"access_token": "new", "id_token": "header." + encoded + ".sig"}
    )
    with patch.object(oauth, "_post", return_value=response):
        with pytest.raises(oauth.CodexError) as error:
            oauth._credentials(force=True, session=captured.session)
    assert error.value.key == "codex.oauth.changed"
    assert oauth._load() == prior


def test_unbound_image_transport_never_sends():
    with patch.object(oauth, "_post") as post:
        with pytest.raises(oauth.CodexError):
            oauth.request_image(
                {},
                generation=oauth.authorization_generation(),
                session=None,
                timeout=30,
                read_result=lambda *_: b"unused",
            )
    post.assert_not_called()


def test_binding_is_checked_on_loaded_credentials_before_dispatch():
    captured = context()
    wrong = dict(oauth._load(), account_id="different-account")
    with (
        patch.object(oauth, "_credentials", return_value=wrong),
        patch.object(oauth, "_post") as post,
    ):
        with pytest.raises(image.CodexImageError) as error:
            image.generate_image("private prompt", captured)
    assert error.value.key == "codex.oauth.changed"
    post.assert_not_called()


@pytest.mark.parametrize("failure", ["oversize", "deadline", "network"])
def test_error_diagnostics_body_is_bounded_and_never_changes_http_failure(failure):
    response = reply(status=400)
    response.headers = {}
    if failure == "oversize":
        response.iter_content.return_value = iter([b"x" * (64 * 1024 + 1)])
    elif failure == "network":
        response.iter_content.side_effect = requests.Timeout("private detail")
    else:
        response.iter_content.return_value = iter([b"{}"])
    with oauth.capture_image_diagnostics() as records:
        oauth._image_response_diagnostic(
            response,
            {"model": "selected-model"},
            0,
            time.monotonic() - 1 if failure == "deadline" else time.monotonic() + 30,
        )
    assert records == [
        {
            "kind": "http",
            "attempt": 1,
            "status": 400,
            "requested_model": "selected-model",
        }
    ]
    response.json.assert_not_called()
