import http.server
import json
import threading

import pytest

from app.services import twelvelabs as service


@pytest.mark.parametrize("invalid", [[], [0.0] * 512])
def test_native_sdk_does_not_cache_invalid_embeddings(tmp_path, monkeypatch, invalid):
    TwelveLabs = pytest.importorskip("twelvelabs").TwelveLabs

    requests = []
    good = [1.0] + [0.0] * 511

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.rfile.read(int(self.headers["Content-Length"])))
            vector = invalid if len(requests) == 1 else good
            body = json.dumps(
                {
                    "model_name": "marengo3.0",
                    "text_embedding": {"segments": [{"float": vector}]},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setitem(service.config.app, "twelvelabs_api_keys", ["synthetic"])
    monkeypatch.setattr(
        service,
        "_client",
        lambda httpx_client=None: TwelveLabs(
            api_key="synthetic",
            base_url=f"http://127.0.0.1:{server.server_port}",
            httpx_client=httpx_client,
        ),
    )
    service._embed_text_cached.cache_clear()
    try:
        assert service.embed_text("topic") is None
        assert service.embed_text("topic") == good
        assert len(requests) == 2
        assert service.embed_text("topic") == good
        assert len(requests) == 2
    finally:
        service._embed_text_cached.cache_clear()
        server.shutdown()
        server.server_close()
        worker.join(2)


@pytest.mark.parametrize(
    "invalid", [[], [0.0, 0.0], [float("inf"), 1.0], [float("nan"), 1.0]]
)
def test_invalid_embedding_retry_and_cache_without_optional_sdk(monkeypatch, invalid):
    from contextlib import contextmanager
    from types import SimpleNamespace

    calls = []
    good = [1.0, 0.0]

    def create(**kwargs):
        calls.append(kwargs)
        segment = SimpleNamespace(float_=invalid if len(calls) == 1 else good)
        return SimpleNamespace(text_embedding=SimpleNamespace(segments=[segment]))

    @contextmanager
    def managed_client():
        yield SimpleNamespace(embed=SimpleNamespace(create=create))

    monkeypatch.setitem(service.config.app, "twelvelabs_api_keys", ["synthetic"])
    monkeypatch.setattr(service, "_managed_client", managed_client)
    service._embed_text_cached.cache_clear()
    try:
        assert service.embed_text("topic") is None
        assert service.embed_text("topic") == good
        assert service.embed_text("topic") == good
        assert len(calls) == 2
    finally:
        service._embed_text_cached.cache_clear()
