import json
import time
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.services import chatgpt_oauth as chatgpt
from app.services import llm


def reply(status=200, payload=None, lines=None):
    response = MagicMock(status_code=status)
    response.json.return_value = payload or {}
    response.iter_lines.return_value = iter(lines or [])
    response.__enter__.return_value = response
    return response


@pytest.fixture(autouse=True)
def credentials():
    with (
        patch.object(
            chatgpt.auth,
            "credentials",
            return_value=({"access_token": "oauth-access"}, ("client", 1)),
        ) as auth,
        patch.object(chatgpt.auth, "assert_session") as check,
    ):
        yield auth, check


def completed_event(text="Narración de las pirámides"):
    return {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]},
            ],
        },
    }


def test_public_responses_uses_oauth_and_accepts_only_completed_text():
    lines = [
        'data: {"type":"response.output_text.delta","delta":"partial"}',
        "",
        "data: " + json.dumps(completed_event()),
        "",
    ]
    with patch.object(
        chatgpt.requests, "request", return_value=reply(lines=lines)
    ) as request:
        assert (
            chatgpt.generate_text("Historia\n\nEscenas", "account-model")
            == "Narración de las pirámides"
        )
    assert request.call_args.args == ("POST", "https://api.openai.com/v1/responses")
    sent = request.call_args.kwargs
    assert sent["headers"]["Authorization"] == "Bearer oauth-access"
    assert "chatgpt-account-id" not in sent["headers"]
    assert sent["allow_redirects"] is False
    assert sent["json"]["store"] is False
    assert sent["json"]["stream"] is True
    assert sent["json"]["model"] == "account-model"
    assert "tools" not in sent["json"]
    assert "temperature" not in sent["json"]


def test_models_use_same_authorized_account():
    data = {
        "models": [{"slug": "test-model", "display_name": "Test", "visibility": "list"}]
    }
    with patch.object(
        chatgpt.requests, "request", return_value=reply(payload=data)
    ) as request:
        assert chatgpt.get_models() == data
    assert request.call_args.args == ("GET", "https://api.openai.com/v1/models")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer oauth-access"


@pytest.mark.parametrize(
    "lines",
    [
        ['data: {"type":"response.output_text.delta","delta":"partial"}', ""],
        [
            'data: {"type":"response.failed","response":{"error":{"message":"secret"}}}',
            "",
        ],
        ['data: {"type":"response.completed","response":{"status":"incomplete"}}', ""],
        ["data: not-json", ""],
        ["data: [DONE]", ""],
    ],
)
def test_failure_does_not_return_partial_text_or_raw_errors(lines):
    with pytest.raises(chatgpt.ChatGPTError) as error:
        chatgpt._read_stream(reply(lines=lines), time.monotonic() + 30)
    assert "secret" not in str(error.value)


def test_usage_failure_inside_stream_retains_category():
    event = {
        "type": "response.failed",
        "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}},
    }
    with pytest.raises(chatgpt.ChatGPTError) as error:
        chatgpt._stream_event(json.dumps(event))
    assert error.value.key == "chatgpt.oauth.rate_limit"


def test_public_stream_can_complete_without_repeating_full_text():
    events = [
        {
            "type": "response.output_text.delta",
            "delta": "Hello ",
            "output_index": 0,
            "content_index": 0,
        },
        {
            "type": "response.output_text.delta",
            "delta": "world",
            "output_index": 0,
            "content_index": 0,
        },
        {
            "type": "response.output_text.done",
            "text": "Hello world",
            "output_index": 0,
            "content_index": 0,
        },
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": []},
        },
    ]
    lines = [line for event in events for line in ("data: " + json.dumps(event), "")]
    assert (
        chatgpt._read_stream(reply(lines=lines), time.monotonic() + 30) == "Hello world"
    )
    incomplete = lines[:-2]
    with pytest.raises(chatgpt.ChatGPTError, match="did not finish"):
        chatgpt._read_stream(reply(lines=incomplete), time.monotonic() + 30)


def test_unauthorized_refresh_retries_once(credentials):
    auth, _ = credentials
    auth.side_effect = [
        ({"access_token": "old"}, ("client", 1)),
        ({"access_token": "new"}, ("client", 1)),
    ]
    with patch.object(
        chatgpt.requests,
        "request",
        side_effect=[
            reply(401),
            reply(lines=["data: " + json.dumps(completed_event("OK")), ""]),
        ],
    ) as request:
        assert chatgpt.generate_text("hello", "test") == "OK"
    assert request.call_count == 2
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer new"
    assert auth.call_args.kwargs == {
        "force": True,
        "expected": "old",
        "session": ("client", 1),
        "deadline": ANY,
    }


def test_account_change_rejects_a_result(credentials):
    _, check = credentials
    check.side_effect = [None, chatgpt.ChatGPTError("changed")]
    with (
        patch.object(
            chatgpt.requests,
            "request",
            return_value=reply(
                lines=["data: " + json.dumps(completed_event("old account output")), ""]
            ),
        ),
        pytest.raises(chatgpt.ChatGPTError),
    ):
        chatgpt.generate_text("hello", "test")


def test_missing_grant_never_falls_back_to_api_key(credentials, monkeypatch):
    credentials[0].side_effect = chatgpt.ChatGPTError("plan_required")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-api-key")
    with (
        patch.object(chatgpt.requests, "request") as request,
        pytest.raises(chatgpt.ChatGPTError),
    ):
        chatgpt.generate_text("hello", "test")
    request.assert_not_called()


def test_existing_llm_dispatch_still_uses_provider_interface():
    settings = {
        "llm_provider": "openai_chatgpt",
        "openai_chatgpt_timeout": "300",
        "openai_chatgpt_model_name": "selected-account-model",
    }
    with patch.object(chatgpt, "generate_text", return_value="OK") as generate:
        assert (
            llm._generate_response("hello", app_config=settings, request_timeout=30)
            == "OK"
        )
    assert generate.call_args.args == ("hello", "selected-account-model", 30)
