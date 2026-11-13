"""验证 Infistar 的真实 SDK 请求、默认配置和自定义覆盖。"""

import json
from unittest.mock import patch

import httpx
from openai import OpenAI
import pytest

from app.config import config
from app.services import llm


@pytest.mark.parametrize(
    "base_url,model,expected_url,expected_model",
    [
        ("", "", "https://infistar.cc/v1/chat/completions", "gpt-6-luna"),
        (
            "https://gateway.example.com/v1",
            "custom-model",
            "https://gateway.example.com/v1/chat/completions",
            "custom-model",
        ),
    ],
)
def test_infistar_chat_completion_request(
    base_url, model, expected_url, expected_model
):
    """通过真实 OpenAI SDK 编解码，避免只检查模拟客户端的调用参数。"""
    received = []

    def respond(request):
        received.append(request)
        return httpx.Response(
            200,
            json={
                "id": "infistar-test",
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
        return OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    app_config = dict(
        config.app,
        llm_provider="infistar",
        infistar_api_key="test-infistar-key",
        infistar_base_url=base_url,
        infistar_model_name=model,
    )
    with (
        patch.object(config, "app", app_config),
        patch.object(llm, "OpenAI", make_client),
    ):
        assert llm._generate_response("生成视频文案") == "测试成功"

    assert len(received) == 1
    request = received[0]
    assert str(request.url) == expected_url
    assert request.headers["Authorization"] == "Bearer test-infistar-key"
    assert json.loads(request.content) == {
        "model": expected_model,
        "messages": [{"role": "user", "content": "生成视频文案"}],
    }


def test_infistar_missing_key_does_not_send_request():
    """选择新 Provider 后必须使用专属 Key，不能意外复用其他服务的凭据。"""
    app_config = dict(
        config.app,
        llm_provider="infistar",
        infistar_api_key="",
        openai_api_key="other-key",
    )
    with patch.object(config, "app", app_config), patch.object(llm, "OpenAI") as client:
        assert "infistar: api_key is not set" in llm._generate_response("test")
    client.assert_not_called()
