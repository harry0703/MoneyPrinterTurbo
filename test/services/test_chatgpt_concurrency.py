"""Real cross-process lock/HTTP regressions with synthetic credentials only."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import sys
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import pytest
import requests
from streamlit.testing.v1 import AppTest

from app.services import chatgpt_auth as auth


def _refresh_worker(path, base_url):
    auth._credential_path = lambda: Path(path)
    original = requests.request

    def local_request(method, url, **kwargs):
        assert url.startswith(auth.ISSUER + "/")
        return original(method, base_url + urlsplit(url).path, **kwargs)

    auth.requests.request = local_request
    try:
        profile, _ = auth.credentials(deadline=time.monotonic() + 15)
        print(
            json.dumps({"refreshed": profile["access_token"] == "synthetic-new-access"})
        )
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))


def _worker_process(*args):
    # Streamlit AppTest replaces __main__; use a fresh interpreter rather than
    # multiprocessing spawn, which would try to run the last UI script as main.
    code = (
        "from test.services.test_chatgpt_concurrency import _refresh_worker; "
        "import sys; _refresh_worker(*sys.argv[1:])"
    )
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", code, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.fixture
def synthetic_store(tmp_path, monkeypatch):
    path = tmp_path / "openai_chatgpt.bin"
    monkeypatch.setattr(auth, "_credential_path", lambda: path)
    auth._save(
        {
            "version": 2,
            "host_id": "urn:uuid:test",
            "active": "client",
            "revision": 1,
            "profiles": {
                "client": {
                    "client_id": "client",
                    "subject": "test-user",
                    "issuer": auth.ISSUER,
                    "email": "test@example.invalid",
                    "id_token": "synthetic-id",
                    "access_token": "synthetic-old-access",
                    "refresh_token": "synthetic-refresh",
                    "scopes": auth.SCOPES.split(),
                    "expires_at": 0,
                }
            },
        }
    )
    return path


def test_slow_refresh_keeps_ui_recoverable_and_rotates_once(synthetic_store):
    discovery_started = threading.Event()
    token_started = threading.Event()
    release_token = threading.Event()
    refresh_count = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            discovery_started.set()
            time.sleep(0.4)
            self.respond(
                {"issuer": auth.ISSUER, "jwks_uri": auth.ISSUER + "/jwks"}
                if self.path.endswith("openid-configuration")
                else {"keys": []}
            )

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            refresh_count.append(1)
            token_started.set()
            release_token.wait(15)
            self.respond(
                {
                    "access_token": "synthetic-new-access",
                    "refresh_token": "synthetic-new-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    workers = []
    before = synthetic_store.read_bytes()
    try:
        workers.append(
            _worker_process(
                str(synthetic_store), f"http://127.0.0.1:{server.server_port}"
            )
        )
        assert discovery_started.wait(10)
        # Discovery/JWKS must not hold the credential lock.
        assert auth.account_details()["authorized"]
        workers.append(
            _worker_process(
                str(synthetic_store), f"http://127.0.0.1:{server.server_port}"
            )
        )
        assert token_started.wait(10)
        ui = AppTest.from_string(
            "from webui.chatgpt_login import render_chatgpt_login\n"
            "render_chatgpt_login(lambda key: key)",
            default_timeout=10,
        ).run()
        assert not ui.exception
        assert any(item.value == "chatgpt.oauth.busy" for item in ui.info)
        assert ui.button(key="chatgpt_retry")
        assert synthetic_store.read_bytes() == before
        release_token.set()
        outcomes = [json.loads(worker.communicate(timeout=10)[0]) for worker in workers]
        assert outcomes == [{"refreshed": True}] * 2
        assert all(worker.returncode == 0 for worker in workers)
        assert len(refresh_count) == 1
        assert (
            auth._load()["profiles"]["client"]["refresh_token"]
            == "synthetic-new-refresh"
        )
        ui.button(key="chatgpt_retry").click().run()
        assert not ui.exception
        assert not any(item.value == "chatgpt.oauth.busy" for item in ui.info)
    finally:
        release_token.set()
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
                worker.communicate(timeout=5)
        server.shutdown()
        server.server_close()


def test_cross_process_lock_wait_obeys_request_budget(synthetic_store, monkeypatch):
    code = (
        "from filelock import FileLock; import sys; "
        "lock=FileLock(sys.argv[1]+'.lock'); lock.acquire(timeout=5); "
        "print('locked',flush=True); sys.stdin.readline(); lock.release()"
    )
    holder = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", code, str(synthetic_store)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    original = synthetic_store.read_bytes()
    try:
        assert holder.stdout.readline().strip() == "locked"
        monkeypatch.setattr(
            auth,
            "_request_json",
            lambda *a, **kw: pytest.fail("No network while locked"),
        )
        started = time.monotonic()
        with pytest.raises(auth.ChatGPTError) as error:
            auth.credentials(deadline=started + 0.15)
        assert error.value.key == "chatgpt.oauth.busy"
        assert time.monotonic() - started < 1
        assert synthetic_store.read_bytes() == original
    finally:
        holder.communicate(input="release\n", timeout=5)


def test_in_process_lock_wait_is_also_bounded(synthetic_store):
    with auth._lock, ThreadPoolExecutor(max_workers=1) as pool:
        started = time.monotonic()
        future = pool.submit(auth.account_details)
        with pytest.raises(auth.ChatGPTError) as error:
            future.result(timeout=2)
        assert error.value.key == "chatgpt.oauth.busy"
        assert time.monotonic() - started < 2


def test_discovery_and_refresh_share_a_deadline(synthetic_store, monkeypatch):
    calls = []

    def delayed_json(method, url, **kwargs):
        calls.append((url, kwargs["deadline"]))
        auth._remaining(kwargs["deadline"])
        time.sleep(0.08)
        return {"issuer": auth.ISSUER, "jwks_uri": auth.ISSUER + "/jwks"}

    monkeypatch.setattr(auth, "_request_json", delayed_json)
    original = synthetic_store.read_bytes()
    deadline = time.monotonic() + 0.05
    with pytest.raises(auth.ChatGPTError) as error:
        auth.credentials(deadline=deadline)
    assert error.value.key == "chatgpt.oauth.timeout"
    assert all(call_deadline == deadline for _, call_deadline in calls)
    assert auth.TOKEN_URL not in [url for url, _ in calls]
    assert synthetic_store.read_bytes() == original
