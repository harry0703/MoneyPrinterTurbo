import unittest
from unittest.mock import patch
import httpx
from openai import OpenAI, AzureOpenAI
from app.services import llm


class TestLlmClientCleanup(unittest.TestCase):
    def test_sdk_transport_closed_after_success_and_request_failure(self):
        cases = [
            ("openai", "OpenAI", {"openai_api_key": "test-key", "openai_model_name": "test-model", "openai_base_url": "https://example.test/v1"}),
            ("azure", "AzureOpenAI", {"azure_api_key": "test-key", "azure_model_name": "test-model", "azure_base_url": "https://example.test", "azure_api_version": "2024-02-15-preview"}),
            ("cloudflare", "OpenAI", {"cloudflare_api_key": "test-key", "cloudflare_model_name": "test-model", "cloudflare_account_id": "test-account", "cloudflare_gateway_id": "test-gateway"}),
        ]
        for provider, constructor, settings in cases:
            for failed in (False, True):
                with self.subTest(provider=provider, failed=failed):
                    def request(req):
                        if failed:
                            raise httpx.ReadTimeout("lost response", request=req)
                        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "test-model", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "valid narration"}}]})
                    transport = httpx.Client(transport=httpx.MockTransport(request))
                    cls = AzureOpenAI if constructor == "AzureOpenAI" else OpenAI
                    def create(**kwargs):
                        return cls(**kwargs, max_retries=0, http_client=transport)
                    with patch.object(llm, constructor, side_effect=create):
                        result = llm._generate_response("hello", app_config={"llm_provider": provider, **settings})
                    self.assertEqual(result.startswith("Error:"), failed, result)
                    self.assertTrue(transport.is_closed)

    def test_stream_transport_closed_after_partial_stream_error(self):
        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"id":"test","object":"chat.completion.chunk","created":1,"model":"test-model","choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n'
                raise httpx.ReadError("lost SSE connection")
        transport = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=BrokenStream())))
        def create(**kwargs):
            return OpenAI(**kwargs, max_retries=0, http_client=transport)
        with patch.object(llm, "OpenAI", side_effect=create):
            result = llm._generate_response("hello", app_config={"llm_provider": "modelscope", "modelscope_api_key": "test-key", "modelscope_model_name": "test-model", "modelscope_base_url": "https://example.test/v1"})
        self.assertTrue(result.startswith("Error:"), result)
        self.assertTrue(transport.is_closed)
