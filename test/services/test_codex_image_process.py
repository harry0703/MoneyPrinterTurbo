"""Real processes share synthetic credentials and a loopback-only SSE server."""

import base64
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]


def _wait(path, process=None):
    deadline = time.monotonic() + 20
    while not path.exists():
        if process is not None and process.poll() is not None:
            output, error = process.communicate()
            pytest.fail(f"Synthetic child exited before barrier: {output}\n{error}")
        if time.monotonic() > deadline:
            pytest.fail("Synthetic process barrier timed out")
        time.sleep(0.01)


def _result(process):
    output, error = process.communicate(timeout=30)
    assert process.returncode == 0, (output, error)
    return json.loads(output.splitlines()[-1])


@pytest.fixture
def exchange(tmp_path):
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    state = {
        "account": "account-A",
        "posts": [],
        "refreshes": 0,
        "hold_image": False,
        "reject_first": False,
        "received": threading.Event(),
        "release": threading.Event(),
        "png": image.getvalue(),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = (
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/responses"
                else None
            )
            if payload is not None:
                state["posts"].append(self.headers.get("chatgpt-account-id"))
                if state["reject_first"]:
                    state["reject_first"] = False
                    self.send_response(401)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                event = {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": [
                            {
                                "id": "synthetic-image",
                                "type": "image_generation_call",
                                "status": "completed",
                                "result": base64.b64encode(state["png"]).decode(),
                            }
                        ],
                    },
                }
                body = b"data: " + json.dumps(event).encode() + b"\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.flush()
                state["received"].set()
                if state["hold_image"]:
                    state["release"].wait(20)
                self.wfile.write(body)
                return
            data = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/token":
                if b"refresh_token" in data:
                    state["refreshes"] += 1
                account = state["account"]
                claims = (
                    base64.urlsafe_b64encode(
                        json.dumps(
                            {
                                "https://api.openai.com/auth": {
                                    "chatgpt_account_id": account
                                }
                            }
                        ).encode()
                    )
                    .decode()
                    .rstrip("=")
                )
                result = {
                    "access_token": "access-" + account,
                    "refresh_token": "refresh-" + account,
                    "id_token": "header." + claims + ".sig",
                    "expires_in": 3600,
                }
            else:
                result = {
                    "authorization_code": "synthetic-code",
                    "code_verifier": "synthetic-verifier",
                }
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    prelude = f"""
import json, time
from pathlib import Path
from app.services import codex_oauth as oauth, codex_image as image
oauth.ISSUER = {url!r}
oauth.TOKEN_URL = {url + "/token"!r}
oauth.RESPONSES_URL = {url + "/responses"!r}
"""
    children = []

    def child(script):
        environment = dict(
            os.environ, MPT_HOME=str(tmp_path / "runtime"), PYTHONPATH=str(ROOT)
        )
        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", prelude + script],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        children.append(process)
        return process

    def login(account):
        state["account"] = account
        return _result(
            child("""
oauth.disconnect()
flow = dict(device_auth_id='synthetic-device', user_code='synthetic-code',
            generation=oauth.authorization_generation(), session_revision=None, expires_at=time.time()+60)
assert oauth.poll_login(flow)
print(json.dumps({'revision': oauth.capture_session_binding().revision}))
""")
        )

    state.update(child=child, login=login, root=tmp_path)
    try:
        login("account-A")
        yield state
    finally:
        state["release"].set()
        for process in children:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def queued(exchange):
    ready, resume = exchange["root"] / "ready", exchange["root"] / "resume"
    process = exchange["child"](f"""
context=image.capture_context({{'codex_image_model_name':'synthetic-model'}})
Path({str(ready)!r}).touch()
deadline=time.monotonic()+20
while not Path({str(resume)!r}).exists():
    if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
    time.sleep(0.01)
try:
    result=image.generate_image('synthetic prompt',context)
    print(json.dumps({{'ok':True,'bytes':len(result),'generation':context.generation}}))
except oauth.CodexError as error:
    print(json.dumps({{'ok':False,'error':error.key,'generation':context.generation}}))
""")
    _wait(ready, process)
    try:
        yield process, resume
    finally:
        resume.touch()


@pytest.mark.parametrize("next_account", ["account-B", "account-A"])
def test_queued_request_rejects_other_process_switch_or_relogin(exchange, next_account):
    with queued(exchange) as (process, resume):
        exchange["login"](next_account)
        resume.touch()
        result = _result(process)
    assert result == {"ok": False, "error": "codex.oauth.changed", "generation": 0}
    assert exchange["posts"] == []


def test_inflight_image_rejected_after_other_process_account_switch(exchange):
    exchange["hold_image"] = True
    with queued(exchange) as (process, resume):
        resume.touch()
        assert exchange["received"].wait(20)
        # This must finish while the image stream is still waiting: the file
        # lock protects dispatch, not the lifetime of the stream.
        exchange["login"]("account-B")
        exchange["release"].set()
        result = _result(process)
    assert result["error"] == "codex.oauth.changed"
    assert exchange["posts"] == ["account-A"]


def test_refresh_in_another_process_preserves_queued_authorization(exchange):
    with queued(exchange) as (process, resume):
        refreshed = _result(
            exchange["child"]("""
before=oauth.capture_session_binding()
oauth._credentials(force=True,session=before)
print(json.dumps({'stable':before==oauth.capture_session_binding()}))
""")
        )
        assert refreshed["stable"]
        resume.touch()
        result = _result(process)
    assert result["ok"]
    assert exchange["posts"] == ["account-A"]
    assert exchange["refreshes"] == 1


def test_two_processes_refresh_rotating_token_once(exchange):
    _result(
        exchange["child"]("""
with oauth._store_guard():
    bundle=oauth._load()
    bundle['expires_at']=0
    oauth._save(bundle)
print('{}')
""")
    )
    script = """
binding=oauth.capture_session_binding()
credentials=oauth._credentials(session=binding)
print(json.dumps({'stable':binding==oauth.capture_session_binding(),'access':credentials['access_token']}))
"""
    first, second = exchange["child"](script), exchange["child"](script)
    results = [_result(first), _result(second)]
    assert all(
        result == {"stable": True, "access": "access-account-A"} for result in results
    )
    assert exchange["refreshes"] == 1


def test_two_processes_migrate_one_legacy_session_revision(exchange):
    _result(
        exchange["child"]("""
with oauth._store_guard():
    bundle=oauth._load()
    bundle.pop('session_revision')
    oauth._credential_path().write_bytes(oauth._protect(json.dumps(bundle).encode()))
print('{}')
""")
    )
    script = "print(json.dumps({'revision':oauth.capture_session_binding().revision}))"
    first, second = exchange["child"](script), exchange["child"](script)
    assert _result(first)["revision"] == _result(second)["revision"]


def test_switch_before_401_refresh_never_sends_as_new_account(exchange):
    exchange["reject_first"] = True
    ready = exchange["root"] / "refresh-ready"
    resume = exchange["root"] / "refresh-resume"
    process = exchange["child"](
        f"""
context=image.capture_context({{'codex_image_model_name':'synthetic-model'}})
original=oauth._credentials
def wait_before_refresh(force=False, **kwargs):
    if force:
        Path({str(ready)!r}).touch()
        deadline=time.monotonic()+20
        while not Path({str(resume)!r}).exists():
            if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
            time.sleep(0.01)
    return original(force=force, **kwargs)
oauth._credentials=wait_before_refresh
try:
    image.generate_image('synthetic prompt',context)
    print(json.dumps({{'ok':True}}))
except oauth.CodexError as error:
    print(json.dumps({{'ok':False,'error':error.key}}))
"""
    )
    _wait(ready, process)
    exchange["login"]("account-B")
    resume.touch()
    result = _result(process)
    assert result == {"ok": False, "error": "codex.oauth.changed"}
    assert exchange["posts"] == ["account-A"]
    assert exchange["refreshes"] == 0
