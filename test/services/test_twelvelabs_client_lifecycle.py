from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.services import twelvelabs as service

sdk = pytest.importorskip("twelvelabs")


@pytest.mark.parametrize("operation", ["embed", "analyze"])
@pytest.mark.parametrize("fails", [False, True])
def test_owned_sdk_http_transport_closes_on_every_outcome(operation, fails):
    real_client = sdk.TwelveLabs
    transports = []

    def construct(**kwargs):
        client = real_client(**kwargs)
        transport = client._client_wrapper.httpx_client.httpx_client
        transports.append(transport)

        def result(**kwargs):
            if fails:
                raise RuntimeError("provider unavailable")
            return SimpleNamespace(
                text_embedding=SimpleNamespace(
                    segments=[SimpleNamespace(float_=[1.0, 0.0])]
                ),
                data="A coffee scene",
            )

        client.embed.create = result
        client.analyze = result
        return client

    service._embed_text_cached.cache_clear()
    try:
        with (
            patch.object(service.config, "app", {"twelvelabs_api_keys": ["fake-key"]}),
            patch.object(sdk, "TwelveLabs", side_effect=construct),
        ):
            result = (
                service.embed_text("coffee")
                if operation == "embed"
                else service.analyze_clip("https://example.test/coffee.mp4")
            )
        assert result == (
            None if fails else [1.0, 0.0] if operation == "embed" else "A coffee scene"
        )
        assert len(transports) == 1
        assert transports[0].is_closed
    finally:
        for transport in transports:
            transport.close()
        service._embed_text_cached.cache_clear()
