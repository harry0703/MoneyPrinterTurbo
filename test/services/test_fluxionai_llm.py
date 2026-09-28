"""Fluxion AI 接入回归：使用真实 SDK 编解码，HTTP 层不访问外网或消耗额度。"""

import json
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from app.config import config
from app.models.llm_provider import get_llm_provider
from app.services import llm


@pytest.mark.parametrize(
    "base_url,model,expected_url,expected_model",
    [
        ("", "", "https://fluxionai.space/v1/chat/completions", "gpt-5.5"),
        ("  ", "  ", "https://fluxionai.space/v1/chat/completions", "gpt-5.5"),
        (
            "https://gateway.example.com/custom/v1/",
            "custom-group-model",
            "https://gateway.example.com/custom/v1/chat/completions",
            "custom-group-model",
        ),
    ],
)
def test_fluxionai_defaults_and_group_overrides(
    base_url, model, expected_url, expected_model
):
    """空配置使用默认值，分组自定义值不被覆盖；其他 Provider 的配置保持原样。"""
    snapshot = dict(config.app)
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == expected_url
        assert request.headers["Authorization"] == "Bearer test-fluxion-key"
        assert json.loads(request.content) == {
            "model": expected_model,
            "messages": [{"role": "user", "content": "生成中文文案"}],
        }
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 0,
                "model": expected_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "你好，世界！"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    # 保留真实 SDK 的 URL 拼接和响应解析，只替换 HTTP 传输层，避免 mock 掩盖协议问题。
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        with OpenAI(
            api_key="test-fluxion-key",
            base_url=base_url.strip() or "https://fluxionai.space/v1",
            http_client=http_client,
            max_retries=0,
        ) as client:
            with patch.object(llm, "OpenAI", return_value=client) as factory:
                result = llm._generate_response(
                    "生成中文文案",
                    app_config={
                        "llm_provider": "fluxionai",
                        "fluxionai_api_key": "test-fluxion-key",
                        "fluxionai_base_url": base_url,
                        "fluxionai_model_name": model,
                    },
                )
                factory.assert_called_once_with(
                    api_key="test-fluxion-key",
                    base_url=base_url.strip() or "https://fluxionai.space/v1",
                )
    assert result == "你好，世界！"
    assert len(requests) == 1
    assert config.app == snapshot


def test_fluxionai_missing_key_fails_before_network():
    """缺少密钥时沿用统一错误提示，不创建客户端或发起付费请求。"""
    with patch.object(llm, "OpenAI") as factory:
        result = llm._generate_response(
            "test", app_config={"llm_provider": "fluxionai"}
        )
    assert result.startswith("Error:")
    assert "fluxionai: api_key is not set" in result
    factory.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_fluxionai_http_errors_are_not_successful_text(status):
    """鉴权、分组权限、限流和服务端错误必须走错误路径，不能被当成正常文案。"""

    def respond(request):
        return httpx.Response(
            status,
            json={"error": {"message": "test upstream failure", "type": "api_error"}},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        with OpenAI(
            api_key="test-key",
            base_url="https://fluxionai.space/v1",
            http_client=http_client,
            max_retries=0,
        ) as client:
            with patch.object(llm, "OpenAI", return_value=client):
                result = llm._generate_response(
                    "test",
                    app_config={
                        "llm_provider": "fluxionai",
                        "fluxionai_api_key": "test-key",
                    },
                )
    assert result.startswith("Error:")
    assert str(status) in result


def test_fluxionai_registry_metadata():
    """锁定默认模型、协议、推广参数和模型链接，避免不同入口的信息不一致。"""
    provider = get_llm_provider("fluxionai")
    assert provider.default_model == "gpt-5.5"
    assert provider.default_base_url == "https://fluxionai.space/v1"
    assert provider.adapter == "openai_compatible"
    assert provider.requires_api_key
    assert (
        provider.api_key_url
        == "https://fluxionai.space/register?source=github&campaign=moneyprinterturbo&promo=MONEYPRINTERTURBO"
    )
    assert provider.model_docs_url == "https://fluxionai.space/model-plaza"
