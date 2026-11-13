import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from PIL import Image

# the example server lives in docs/ and imports policy.py from its own folder
SERVER_DIR = Path(__file__).resolve().parents[2] / "docs" / "local-image-server"
sys.path.insert(0, str(SERVER_DIR))
_spec = importlib.util.spec_from_file_location("local_image_server", SERVER_DIR / "server.py")
srv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = srv
_spec.loader.exec_module(srv)


class FakePipe:
    def __init__(self):
        self.devices = []

    def to(self, device):
        self.devices.append(device)
        return self


class FakeOllama:
    """Stands in for ollama's /api/ps and /api/generate."""

    def __init__(self, models=()):
        self.models = list(models)
        self.unloaded = []

    def get(self, url, timeout=None):
        assert url.endswith("/api/ps")
        models = [{"name": m} for m in self.models]
        return type("Resp", (), {"json": lambda _self: {"models": models}})()

    def post(self, url, json=None, timeout=None):
        assert url.endswith("/api/generate") and json["keep_alive"] == 0
        self.models.remove(json["model"])
        self.unloaded.append(json["model"])


@pytest.fixture
def server(monkeypatch):
    ollama = FakeOllama()
    pipe = FakePipe()
    painted = []

    def fake_paint(p, prompt, negative, width, height):
        # ollama must be gone before every image
        painted.append({"size": (width, height), "ollama": list(ollama.models)})
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(srv, "pipe", None)
    monkeypatch.setattr(srv, "on_gpu", False)
    monkeypatch.setattr(srv, "last_used", 0.0)
    monkeypatch.setattr(srv, "IDLE_SECONDS", 3600)
    monkeypatch.setattr(srv, "IDLE_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(srv, "OLLAMA_UNLOAD_TIMEOUT", 1)
    monkeypatch.setattr(srv, "load_pipeline", lambda: pipe)
    monkeypatch.setattr(srv, "paint", fake_paint)
    monkeypatch.setattr(srv.requests, "get", ollama.get)
    monkeypatch.setattr(srv.requests, "post", ollama.post)
    with TestClient(srv.app) as client:
        yield type("Server", (), {"client": client, "ollama": ollama, "pipe": pipe, "painted": painted})


def post_image(client, **body):
    return client.post("/v1/images/generations", json={"prompt": "mountain", **body})


@pytest.mark.parametrize("size", ["1024x0", "0x1024", "-1x1024", "1024", "axb", "1024x1536x2", "x"])
def test_invalid_size_is_rejected(server, size):
    r = post_image(server.client, size=size)
    assert r.status_code == 422
    assert server.painted == []


@pytest.mark.parametrize(
    "size, expected",
    [("1024x1536", (832, 1216)), ("1920x1080", (1344, 768)), ("1024x1024", (1024, 1024)), ("auto", (832, 1216)), (None, (832, 1216))],
)
def test_valid_size_picks_sdxl_bucket(server, size, expected):
    r = post_image(server.client, size=size)
    assert r.status_code == 200
    assert r.json()["data"][0]["b64_json"]
    assert server.painted[0]["size"] == expected


def test_cuda_cache_is_released_after_each_request(server, monkeypatch):
    calls = []
    monkeypatch.setattr(srv, "empty_cuda_cache", lambda: calls.append(1))
    assert post_image(server.client).status_code == 200
    assert post_image(server.client).status_code == 200
    assert len(calls) == 2


def test_ollama_is_unloaded_before_every_image(server):
    server.ollama.models = ["qwen3:14b"]
    assert post_image(server.client).status_code == 200

    # ollama loads again while sdxl is still on the gpu
    server.ollama.models = ["qwen3:14b"]
    assert post_image(server.client).status_code == 200

    assert server.ollama.unloaded == ["qwen3:14b", "qwen3:14b"]
    assert [p["ollama"] for p in server.painted] == [[], []]
    assert server.pipe.devices == ["cuda"]


def test_ollama_unloaded_between_images_in_one_request(server, monkeypatch):
    painted = []

    def paint_while_ollama_loads(p, prompt, negative, width, height):
        painted.append(list(server.ollama.models))
        server.ollama.models = ["qwen3:14b"]  # ollama loads during this image
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(srv, "paint", paint_while_ollama_loads)
    r = post_image(server.client, n=3)
    assert r.status_code == 200 and len(r.json()["data"]) == 3
    assert painted == [[], [], []]
    assert server.ollama.unloaded == ["qwen3:14b", "qwen3:14b"]


def test_image_painted_when_ollama_is_not_running(server, monkeypatch):
    def refuse(url, timeout=None):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(srv.requests, "get", refuse)
    assert post_image(server.client).status_code == 200
    assert len(server.painted) == 1


def test_image_painted_when_ollama_will_not_unload(server, monkeypatch):
    server.ollama.models = ["qwen3:14b"]
    monkeypatch.setattr(server.ollama, "post", lambda url, json=None, timeout=None: None)
    monkeypatch.setattr(srv.requests, "post", server.ollama.post)
    monkeypatch.setattr(srv, "OLLAMA_UNLOAD_TIMEOUT", 0.3)
    start = time.time()
    assert post_image(server.client).status_code == 200
    assert time.time() - start < 5
    assert server.painted[0]["ollama"] == ["qwen3:14b"]


def test_ollama_reloaded_after_idle_offload(server, monkeypatch):
    assert post_image(server.client).status_code == 200
    monkeypatch.setattr(srv, "IDLE_SECONDS", 0)
    assert srv.offload_if_idle()

    server.ollama.models = ["qwen3:14b"]
    monkeypatch.setattr(srv, "IDLE_SECONDS", 3600)
    assert post_image(server.client).status_code == 200

    assert server.ollama.unloaded == ["qwen3:14b"]
    assert server.painted[-1]["ollama"] == []
    assert server.pipe.devices == ["cuda", "cpu", "cuda"]


def test_idle_worker_offloads_under_lifespan(server, monkeypatch):
    assert server.client.get("/health").json()["idle_worker"] is True
    assert post_image(server.client).status_code == 200
    assert srv.on_gpu

    monkeypatch.setattr(srv, "IDLE_SECONDS", 0)
    deadline = time.time() + 5
    while srv.on_gpu and time.time() < deadline:
        time.sleep(0.05)
    assert not srv.on_gpu
    assert server.pipe.devices == ["cuda", "cpu"]


def test_idle_worker_stops_on_shutdown(monkeypatch):
    monkeypatch.setattr(srv, "IDLE_CHECK_SECONDS", 0.05)
    with TestClient(srv.app):
        thread = srv.idle_thread
        assert thread.is_alive()
    assert not thread.is_alive()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("launch", ["script", "asgi"])
def test_idle_worker_starts_in_both_launch_modes(launch):
    port = free_port()
    if launch == "script":
        cmd = [sys.executable, "server.py"]
    else:
        cmd = [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)]
    env = {**os.environ, "IMAGE_PORT": str(port), "OLLAMA_URL": "http://127.0.0.1:9"}
    proc = subprocess.Popen(cmd, cwd=SERVER_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        health = None
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                health = requests.get(f"http://127.0.0.1:{port}/health", timeout=1).json()
                break
            except requests.RequestException:
                time.sleep(0.2)
        assert health is not None, "server did not start"
        assert health["idle_worker"] is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)
