"""Authenticated HTTP bridge for the host's logged-in Codex CLI."""

import argparse
import hmac
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tools.codex_oauth_bridge.codex_runner import CodexRunError, run_codex


MAX_REQUEST_BYTES = 262_144
MAX_OUTPUT_BYTES = 131_072
DEFAULT_TIMEOUT_SECONDS = 300
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 900

UNAUTHORIZED_ERROR = {"error": {"code": "unauthorized", "message": "Invalid bridge token"}}
INVALID_REQUEST_ERROR = {
    "error": {"code": "invalid_request", "message": "Request body is invalid"}
}
BUSY_ERROR = {
    "error": {
        "code": "busy",
        "message": "Codex bridge is processing another request",
    }
}


class CodexBridgeServer(ThreadingHTTPServer):
    """HTTP server state shared by the bridge request handlers."""

    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], bridge_token: str, codex_executable: str):
        super().__init__(server_address, CodexBridgeRequestHandler)
        self.bridge_token = bridge_token
        self.codex_executable = codex_executable
        self.generation_semaphore = threading.BoundedSemaphore(1)


class CodexBridgeRequestHandler(BaseHTTPRequestHandler):
    """Serve health checks and one authenticated generation at a time."""

    server_version = "CodexOAuthBridge"
    sys_version = ""

    @property
    def bridge_server(self) -> CodexBridgeServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        """Avoid recording request paths or payload-derived values in logs."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Keep all bridge failures in the documented, non-sensitive JSON shape."""
        del message, explain
        self._send_invalid_request(400 if code == 501 else code)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_invalid_request(self, status: int = 400) -> None:
        self._send_json(status, INVALID_REQUEST_ERROR)

    def _is_authorized(self) -> bool:
        authorization = self.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return False
        supplied_token = authorization.removeprefix("Bearer ")
        return hmac.compare_digest(
            supplied_token.encode("utf-8"), self.bridge_server.bridge_token.encode("utf-8")
        )

    def _read_request(self) -> tuple[dict[str, Any] | None, int]:
        content_lengths = self.headers.get_all("Content-Length", [])
        if len(content_lengths) != 1:
            return None, 400
        content_length = content_lengths[0]
        if not content_length.isascii() or not content_length.isdecimal():
            return None, 400
        body_size = int(content_length)
        if body_size > MAX_REQUEST_BYTES:
            return None, 413
        body = self.rfile.read(body_size)
        if len(body) != body_size:
            return None, 400
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, 400
        return (payload, 400) if isinstance(payload, dict) else (None, 400)

    @staticmethod
    def _validated_generation(payload: dict[str, Any]) -> tuple[str, str, str, int] | None:
        allowed_fields = {"instructions", "input", "model", "timeout_seconds"}
        if set(payload) - allowed_fields or not {"instructions", "input"} <= set(payload):
            return None

        instructions = payload["instructions"]
        input_text = payload["input"]
        model = payload.get("model", "")
        timeout_seconds = payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if (
            not isinstance(instructions, str)
            or not instructions.strip()
            or not isinstance(input_text, str)
            or not input_text.strip()
            or not isinstance(model, str)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            return None
        return instructions, input_text, model, timeout_seconds

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_invalid_request()
            return
        self._send_json(
            200,
            {
                "status": "ok",
                "codex_available": shutil.which(self.bridge_server.codex_executable) is not None,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/generate":
            self._send_invalid_request()
            return
        if not self._is_authorized():
            self._send_json(401, UNAUTHORIZED_ERROR)
            return

        payload, invalid_status = self._read_request()
        if payload is None:
            self._send_invalid_request(invalid_status)
            return
        generation = self._validated_generation(payload)
        if generation is None:
            self._send_invalid_request()
            return
        instructions, input_text, model, timeout_seconds = generation

        if not self.bridge_server.generation_semaphore.acquire(blocking=False):
            self._send_json(429, BUSY_ERROR)
            return
        try:
            output_text = run_codex(
                instructions=instructions,
                input_text=input_text,
                model=model,
                timeout_seconds=timeout_seconds,
                executable=self.bridge_server.codex_executable,
            )
            try:
                output_size = len(output_text.encode("utf-8"))
            except (AttributeError, UnicodeEncodeError) as error:
                raise CodexRunError("invalid_output", "Codex returned invalid output.") from error
            if output_size > MAX_OUTPUT_BYTES:
                raise CodexRunError("invalid_output", "Codex output exceeded maximum size.")
        except CodexRunError as error:
            status = 504 if error.code == "timeout" else 502
            self._send_json(status, {"error": {"code": error.code, "message": str(error)}})
            return
        except Exception:
            self._send_json(
                502,
                {"error": {"code": "codex_failed", "message": "Codex run failed."}},
            )
            return
        finally:
            self.bridge_server.generation_semaphore.release()

        self._send_json(200, {"output_text": output_text})


def create_server(
    host: str, port: int, bridge_token: str, codex_executable: str
) -> ThreadingHTTPServer:
    """Create a bridge server with a required, separate bearer token."""
    if not bridge_token:
        raise ValueError("bridge_token is required")
    return CodexBridgeServer((host, port), bridge_token, codex_executable)


def main(argv: list[str] | None = None) -> int:
    """Run the host bridge after obtaining its token from the environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--codex-executable", default="codex")
    arguments = parser.parse_args(argv)
    bridge_token = os.environ.get("CODEX_BRIDGE_TOKEN")
    if not bridge_token:
        parser.error("CODEX_BRIDGE_TOKEN environment variable is required")

    bridge = create_server(
        arguments.host,
        arguments.port,
        bridge_token,
        arguments.codex_executable,
    )
    try:
        bridge.serve_forever()
    finally:
        bridge.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
