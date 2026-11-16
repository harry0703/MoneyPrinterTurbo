"""Opt-in request tracing must cover the newest sign-in and catalog calls.

Issue #1669 asks for an opt-in way to inspect the JSON payloads that go to
external APIs. The shared tracer covers the material, TTS and LLM providers,
but the ChatGPT and Codex sign-in flows were added later and still talked to
the network directly. Enabling "Trace API Requests" therefore showed nothing
at all for the two newest providers, which is exactly the situation a user
turns the switch on for.

These tests are behavioural: with the switch off no trace is emitted, and
with the switch on every request produces a request/response pair whose
credentials are redacted.
"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from app.services import chatgpt_auth, codex_models, codex_oauth
from app.utils import logging_utils as logs


@pytest.fixture(autouse=True)
def restore_logging_options():
    previous = logs.get_logging_options()
    yield
    logs.set_logging_options(*previous)


@pytest.fixture
def trace_output():
    sink = io.StringIO()
    handler = logger.add(
        sink, level=0, filter=logs.runtime_log_filter, format="{message}"
    )
    try:
        yield sink
    finally:
        logger.remove(handler)


def trace_events(sink):
    return [
        json.loads(line.removeprefix("request_trace "))
        for line in sink.getvalue().splitlines()
        if line.startswith("request_trace ")
    ]


def response(status=200, payload=None):
    reply = MagicMock()
    reply.status_code = status
    reply.json.return_value = payload if payload is not None else {}
    reply.__enter__.return_value = reply
    return reply

def test_codex_token_exchange_is_traced_and_redacted(trace_output):
    logs.set_logging_options("DEBUG", True)

    with patch.object(
        codex_oauth.requests, "post", return_value=response()
    ) as post:
        codex_oauth._post(
            "https://auth.openai.com/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "client-one",
                "refresh_token": "private-refresh-token",
            },
        )

    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"]
    parameters = events[0]["parameters"]["data"]
    assert parameters["grant_type"] == "refresh_token"
    assert parameters["refresh_token"] == "[REDACTED]"
    assert "private-refresh-token" not in trace_output.getvalue()
    # The original request must still carry the real credential.
    assert post.call_args.kwargs["data"]["refresh_token"] == "private-refresh-token"


def test_codex_device_flow_identifiers_are_redacted(trace_output):
    logs.set_logging_options("DEBUG", True)

    with patch.object(codex_oauth.requests, "post", return_value=response()):
        codex_oauth._post(
            "https://auth.openai.com/api/accounts/deviceauth/token",
            json={
                "device_auth_id": "private-device-id",
                "user_code": "private-user-code",
            },
        )

    parameters = trace_events(trace_output)[0]["parameters"]["json"]
    assert parameters["device_auth_id"] == "[REDACTED]"
    assert parameters["user_code"] == "[REDACTED]"
    assert "private-device-id" not in trace_output.getvalue()
    assert "private-user-code" not in trace_output.getvalue()


def test_codex_responses_transport_is_traced_without_the_bearer_token(trace_output):
    logs.set_logging_options("DEBUG", True)

    with patch.object(codex_oauth.requests, "post", return_value=response()):
        codex_oauth._post(
            "https://chatgpt.com/backend-api/codex/responses",
            headers={"Authorization": "Bearer private-access-token"},
            json={
                "model": "gpt-5.4",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "visible prompt"}],
                    }
                ],
            },
        )

    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"]
    assert events[0]["parameters"]["json"]["model"] == "gpt-5.4"
    assert "visible prompt" in trace_output.getvalue()
    assert "private-access-token" not in trace_output.getvalue()


def test_chatgpt_sign_in_exchange_is_traced_and_redacted(trace_output):
    logs.set_logging_options("DEBUG", True)

    with patch.object(
        chatgpt_auth.requests,
        "request",
        return_value=response(payload={"access_token": "x"}),
    ) as request:
        chatgpt_auth._request_json(
            "POST",
            chatgpt_auth.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": "client-one",
                "code": "private-authorization-code",
                "code_verifier": "private-code-verifier",
            },
        )

    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"]
    parameters = events[0]["parameters"]["data"]
    assert parameters["grant_type"] == "authorization_code"
    assert parameters["code"] == "[REDACTED]"
    assert parameters["code_verifier"] == "[REDACTED]"
    assert "private-authorization-code" not in trace_output.getvalue()
    assert "private-code-verifier" not in trace_output.getvalue()
    # The request itself is unchanged.
    assert request.call_args.args[0] == "POST"
    assert request.call_args.args[1] == chatgpt_auth.TOKEN_URL


def test_codex_model_catalog_download_is_traced(trace_output):
    logs.set_logging_options("DEBUG", True)

    catalog = json.dumps(
        {"openai": {"models": {"gpt-5.4": {"id": "gpt-5.4", "name": "GPT-5.4"}}}}
    ).encode()
    reply = response()
    reply.iter_content.return_value = iter([catalog])

    with patch.object(codex_models.requests, "get", return_value=reply):
        models = codex_models._download()

    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"]
    assert models[0].id == "gpt-5.4"


def test_sign_in_requests_stay_untraced_while_the_switch_is_off(trace_output):
    logs.set_logging_options("DEBUG", False)

    with patch.object(codex_oauth.requests, "post", return_value=response()):
        codex_oauth._post(
            "https://auth.openai.com/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": "private-refresh"},
        )

    assert trace_events(trace_output) == []
    assert "private-refresh" not in trace_output.getvalue()
