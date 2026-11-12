"""APIXO Responses 回归：真实 SDK 编解码，HTTP 层不访问外网。"""

import json
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from app.config import config
from app.services import llm


def _response(*, status="completed", text="你好，世界！"):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.4-mini",
        "status": status,
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
    }


def _generate(respond, **settings):
    transport = httpx.Client(transport=httpx.MockTransport(respond))

    def create(**kwargs):
        return OpenAI(**kwargs, http_client=transport)

    snapshot = dict(config.app)
    with patch.object(llm, "OpenAI", side_effect=create):
        result = llm._generate_response(
            "生成中文文案",
            app_config={
                "llm_provider": "apixo",
                "apixo_api_key": "test-key",
                **settings,
            },
            request_timeout=3,
            max_retries=0,
        )
    assert transport.is_closed
    assert config.app == snapshot
    return result


@pytest.mark.parametrize(
    "base_url,model,expected_url,expected_model",
    [
        ("", "", "https://llm.apixo.ai/v1/responses", "gpt-5.4-mini"),
        ("  ", "  ", "https://llm.apixo.ai/v1/responses", "gpt-5.4-mini"),
        (
            "https://gateway.example/v1/",
            "gpt-5.5",
            "https://gateway.example/v1/responses",
            "gpt-5.5",
        ),
    ],
)
def test_responses_defaults_and_overrides(
    base_url, model, expected_url, expected_model
):
    """验证 Responses 路径、鉴权及请求体，避免退回 Chat Completions。"""
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == expected_url
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": expected_model,
            "input": "生成中文文案",
        }
        return httpx.Response(200, json=_response())

    assert (
        _generate(respond, apixo_base_url=base_url, apixo_model_name=model)
        == "你好，世界！"
    )
    assert len(requests) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_close_transport(status):
    result = _generate(
        lambda request: httpx.Response(
            status,
            json={"error": {"message": "upstream failure"}},
        )
    )
    assert result.startswith("Error:")
    assert str(status) in result


@pytest.mark.parametrize(
    "payload",
    [
        _response(status="incomplete"),
        _response(status="failed"),
        _response(status="in_progress"),
        _response(text=""),
        _response(text="<think>仅有推理</think>"),
        {**_response(), "output": []},
        {
            **_response(),
            "output": [
                {
                    "type": "message",
                    "id": "msg_test",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "refused"}],
                }
            ],
        },
    ],
)
def test_unfinished_empty_and_refused_responses_are_errors(payload):
    """部分正文、拒答和空内容都不能进入配音链路。"""
    result = _generate(lambda request: httpx.Response(200, json=payload))
    assert result.startswith("Error:")


def test_missing_key_fails_before_network():
    with patch.object(llm, "OpenAI") as factory:
        result = llm._generate_response("test", app_config={"llm_provider": "apixo"})
    assert "apixo: api_key is not set" in result
    factory.assert_not_called()
