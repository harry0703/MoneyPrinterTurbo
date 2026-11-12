"""验证 APINEBULA 的真实 SDK 编解码、独立凭据和失败路径，不消耗远端额度。"""

import json
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from app.config import config
from app.services import llm


@pytest.mark.parametrize(
    "base_url,model,expected_url,expected_model",
    [
        ("", "", "https://apinebula.ai/v1/chat/completions", "gpt-6.1-sol"),
        ("  ", "  ", "https://apinebula.ai/v1/chat/completions", "gpt-6.1-sol"),
        (
            " https://gateway.example/v1/ ",
            " custom-model ",
            "https://gateway.example/v1/chat/completions",
            "custom-model",
        ),
    ],
)
def test_request_defaults_overrides_and_client_cleanup(
    base_url, model, expected_url, expected_model
):
    """从服务入口调用真实 SDK，检查请求契约、配置隔离和连接释放。"""
    received = []
    clients = []
    snapshot = dict(config.app)

    def respond(request):
        received.append(request)
        assert str(request.url) == expected_url
        assert request.headers["Authorization"] == "Bearer test-apinebula-key"
        assert json.loads(request.content) == {
            "model": expected_model,
            "messages": [{"role": "user", "content": "生成中文文案"}],
        }
        return httpx.Response(
            200,
            json={
                "id": "apinebula-test",
                "object": "chat.completion",
                "created": 0,
                "model": expected_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "测试成功"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def make_client(**kwargs):
        client = OpenAI(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        clients.append(client)
        return client

    values = {
        "llm_provider": "apinebula",
        "apinebula_api_key": "test-apinebula-key",
        "apinebula_base_url": base_url,
        "apinebula_model_name": model,
        "openai_api_key": "unrelated-key",
    }
    with patch.object(llm, "OpenAI", make_client):
        assert llm._generate_response("生成中文文案", app_config=values) == "测试成功"
    assert len(received) == 1
    assert all(client.is_closed() for client in clients)
    assert config.app == snapshot


def test_missing_key_does_not_reuse_other_provider_credentials():
    """缺少专属密钥必须在网络调用前失败，不能泄露其他平台的凭据。"""
    with patch.object(llm, "OpenAI") as factory:
        result = llm._generate_response(
            "test",
            app_config={"llm_provider": "apinebula", "openai_api_key": "other-key"},
        )
    assert "apinebula: api_key is not set" in result
    factory.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_are_not_successful_text(status):
    """鉴权、权限、限流和服务端异常均需沿统一错误路径返回并释放连接。"""
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, json={"error": {"message": "test upstream failure"}}
            )
        )
    )

    def make_client(**kwargs):
        return OpenAI(**kwargs, http_client=http_client)

    with patch.object(llm, "OpenAI", make_client):
        result = llm._generate_response(
            "test",
            app_config={
                "llm_provider": "apinebula",
                "apinebula_api_key": "test-key",
            },
            max_retries=0,
        )
    assert result.startswith("Error:")
    assert str(status) in result
    assert http_client.is_closed
