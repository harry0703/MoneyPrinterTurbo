"""An answer cut off at the provider's output token limit is not a script.

A provider that stops at the limit still returns the text written so far and
says so in the finish reason: "length" for Chat Completions and DashScope,
MAX_TOKENS for Gemini. That text was returned as the finished answer, so
/scripts answered 200 with a script that ends mid-sentence and a /videos task
narrated it. The Responses adapter already refuses an incomplete response.

The OpenAI and Gemini cases go through the real SDKs; only the HTTP transport
is replaced.
"""

import json
from unittest.mock import patch

import httpx
import pytest
from dashscope.api_entities.dashscope_response import (
    DashScopeAPIResponse,
    GenerationResponse,
)
from fastapi.testclient import TestClient
from google import genai
from google.genai import types as genai_types
from openai import OpenAI

from app import asgi
from app.config import config
from app.services import llm

CUT = "Coffee keeps the night shift awake. In the roastery the first batch goes in at"
WHOLE = "Coffee keeps the night shift awake."

OPENAI = {
    "llm_provider": "openai",
    "openai_api_key": "test-key",
    "openai_base_url": "https://llm.example/v1",
    "openai_model_name": "test-model",
}
MODELSCOPE = {
    "llm_provider": "modelscope",
    "modelscope_api_key": "test-key",
    "modelscope_model_name": "test-model",
}
GEMINI = {
    "llm_provider": "gemini",
    "gemini_api_key": "test-key",
    "gemini_model_name": "test-model",
}
QWEN = {
    "llm_provider": "qwen",
    "qwen_api_key": "test-key",
    "qwen_model_name": "test-model",
}


def _chat_completion(finish_reason, text):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": text},
            }
        ],
    }


def _chat_stream(finish_reason, text):
    def chunk(delta, finish=None):
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(body)}\n\n"

    half = len(text) // 2
    return (
        chunk({"role": "assistant", "content": text[:half]})
        + chunk({"content": text[half:]})
        + chunk({}, finish_reason)
        + "data: [DONE]\n\n"
    )


def _gemini_response(finish_reason, text):
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": finish_reason,
                "index": 0,
            }
        ]
    }


def _openai_sdk(respond):
    """Patch llm.OpenAI with the real client on a mock HTTP transport."""

    def create(**kwargs):
        # One transport per client: the service closes each client it opens.
        transport = httpx.Client(transport=httpx.MockTransport(respond))
        return OpenAI(**kwargs, http_client=transport)

    return patch.object(llm, "OpenAI", side_effect=create)


def _gemini_sdk(respond):
    """Patch google.genai.Client with the real client on a mock HTTP transport."""
    real_client = genai.Client

    def create(api_key, http_options=None):
        transport = httpx.Client(transport=httpx.MockTransport(respond))
        return real_client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(httpx_client=transport),
        )

    return patch("google.genai.Client", side_effect=create)


def _qwen_sdk(output):
    response = GenerationResponse.from_api_response(
        DashScopeAPIResponse(
            status_code=200,
            request_id="request-test",
            code="",
            message="",
            output=output,
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )
    )
    return patch("dashscope.Generation.call", return_value=response)


def _answer(sdk, settings):
    with sdk:
        return llm._generate_response("write the script", app_config=settings)


def _chat(finish_reason, text):
    return _openai_sdk(
        lambda request: httpx.Response(200, json=_chat_completion(finish_reason, text))
    )


def _stream(finish_reason, text):
    return _openai_sdk(
        lambda request: httpx.Response(
            200,
            content=_chat_stream(finish_reason, text).encode(),
            headers={"Content-Type": "text/event-stream"},
        )
    )


def _gemini(finish_reason, text):
    return _gemini_sdk(
        lambda request: httpx.Response(200, json=_gemini_response(finish_reason, text))
    )


def _qwen_choices(finish_reason, text):
    return _qwen_sdk(
        {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": text},
                }
            ]
        }
    )


def _qwen_text(finish_reason, text):
    return _qwen_sdk({"text": text, "finish_reason": finish_reason})


SHAPES = [
    pytest.param(_chat, OPENAI, "length", "stop", id="chat-completions"),
    pytest.param(_stream, MODELSCOPE, "length", "stop", id="chat-completions-stream"),
    pytest.param(_gemini, GEMINI, "MAX_TOKENS", "STOP", id="gemini"),
    pytest.param(_qwen_choices, QWEN, "length", "stop", id="dashscope-choices"),
    pytest.param(_qwen_text, QWEN, "length", "stop", id="dashscope-text"),
]


@pytest.mark.parametrize("sdk, settings, cut_off, finished", SHAPES)
def test_cut_off_answer_is_an_error(sdk, settings, cut_off, finished):
    result = _answer(sdk(cut_off, CUT), settings)

    assert result.startswith("Error: ")
    assert "cut off at the output token limit" in result
    assert f"finish_reason={cut_off}" in result
    assert CUT not in result


@pytest.mark.parametrize("sdk, settings, cut_off, finished", SHAPES)
def test_finished_answer_is_returned(sdk, settings, cut_off, finished):
    assert _answer(sdk(finished, WHOLE), settings) == WHOLE


def test_cut_off_answer_without_text_names_the_limit():
    # Reasoning can use the whole budget and leave no text at all.
    result = _answer(_chat("length", None), OPENAI)

    assert "cut off at the output token limit" in result


def test_answer_without_a_finish_reason_is_returned():
    # Some compatible gateways leave the field out or send null.
    payload = _chat_completion(None, WHOLE)
    del payload["choices"][0]["finish_reason"]
    sdk = _openai_sdk(lambda request: httpx.Response(200, json=payload))

    assert _answer(sdk, OPENAI) == WHOLE
    assert _answer(_chat(None, WHOLE), OPENAI) == WHOLE


def test_script_is_asked_for_again_after_a_cut_off_answer():
    answers = iter([_chat_completion("length", CUT), _chat_completion("stop", WHOLE)])
    sdk = _openai_sdk(lambda request: httpx.Response(200, json=next(answers)))

    with sdk:
        assert llm.generate_script("Coffee at night", app_config=OPENAI) == WHOLE
    assert next(answers, None) is None


def test_scripts_endpoint_does_not_return_a_cut_off_script():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=_chat_completion("length", CUT))

    with (
        patch.dict(config.app, {"api_key": "", **OPENAI}),
        _openai_sdk(respond),
        TestClient(asgi.app) as client,
    ):
        response = client.post(
            "/api/v1/scripts", json={"video_subject": "Coffee at night"}
        )

    assert response.status_code == 503
    assert response.json()["message"] == "script generation is unavailable"
    assert CUT not in response.text
    assert len(requests) == llm._max_retries
