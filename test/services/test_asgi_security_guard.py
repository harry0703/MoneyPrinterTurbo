import asyncio
import itertools
import json
import runpy
import socket
import threading
import time
from pathlib import Path
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from guard_core.handlers import ratelimit_handler
from guard.adapters import StarletteGuardResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app import asgi
from app.config import config
from app.router import root_api_router

ORIGIN = "https://frontend.example"
ROOT_DIR = Path(__file__).resolve().parents[2]
# guard-core keeps rate-limit counters process-wide, so every test uses fresh IPs.
_ips = itertools.count(1)


def _fresh_ip() -> str:
    n = next(_ips)
    return f"198.51.{n // 250}.{n % 250 + 1}"


class TestASGISecurityGuard(unittest.TestCase):
    """The opt-in fastapi-guard layer: default off, safe client IP, CORS outside."""

    @staticmethod
    def _create_app(guard_config: dict, allowed_origins=None) -> FastAPI:
        application = FastAPI()

        @application.get("/probe")
        def probe():
            return {"status": "ok"}

        @application.post("/body")
        def body():
            return {"status": "ok"}

        asgi.configure_middleware(application, allowed_origins or [], guard_config)
        return application

    def test_disabled_adds_no_middleware_and_skips_import(self):
        # A None entry makes ``import guard`` raise, proving it is never imported.
        with patch.dict("sys.modules", {"guard": None}):
            for guard_config in ({}, {"enabled": False}):
                application = self._create_app(guard_config)
                # Only the existing browser-origin check remains registered.
                self.assertEqual(len(application.user_middleware), 1)

    def test_missing_package_raises_clear_error(self):
        with patch.dict("sys.modules", {"guard": None}):
            with self.assertRaisesRegex(RuntimeError, "requires fastapi-guard"):
                self._create_app({"enabled": True})

    def test_spoofed_forwarded_for_from_untrusted_peer_shares_one_bucket(self):
        application = self._create_app({"enabled": True, "rate_limit": 2})
        client = TestClient(application, client=(_fresh_ip(), 50000))

        codes = [
            client.get("/probe", headers={"X-Forwarded-For": f"192.0.2.{i}"})
            for i in range(3)
        ]

        self.assertEqual([r.status_code for r in codes], [200, 200, 429])

    def test_forwarded_for_is_honored_from_trusted_proxy(self):
        application = self._create_app({"enabled": True, "rate_limit": 1})
        client = TestClient(application, client=("127.0.0.1", 50000))
        ip, ip2 = _fresh_ip(), _fresh_ip()

        first = client.get("/probe", headers={"X-Forwarded-For": ip})
        other = client.get("/probe", headers={"X-Forwarded-For": ip2})
        repeat = client.get("/probe", headers={"X-Forwarded-For": ip})

        self.assertEqual(
            [first.status_code, other.status_code, repeat.status_code],
            [200, 200, 429],
        )

    def test_custom_trusted_proxies_replace_the_loopback_default(self):
        application = self._create_app(
            {"enabled": True, "rate_limit": 1, "trusted_proxies": ["10.0.0.0/8"]}
        )
        client = TestClient(application, client=("127.0.0.1", 50000))
        ip, ip2 = _fresh_ip(), _fresh_ip()

        first = client.get("/probe", headers={"X-Forwarded-For": ip})
        second = client.get("/probe", headers={"X-Forwarded-For": ip2})

        self.assertEqual([first.status_code, second.status_code], [200, 429])

    def test_body_is_not_scanned_by_default_but_query_is(self):
        application = self._create_app({"enabled": True, "rate_limit": 100})
        client = TestClient(application, client=(_fresh_ip(), 50000))
        script = "<script>alert(1)</script>"

        body = client.post("/body", content=script, headers={"content-type": "text/plain"})
        query = client.get("/probe", params={"q": script})

        self.assertEqual(body.status_code, 200)
        self.assertEqual(query.status_code, 400)

    def test_localhost_and_lan_referers_are_not_blocked(self):
        application = self._create_app({"enabled": True, "rate_limit": 100})

        for referer in (
            "http://localhost:8501/",
            "http://127.0.0.1:8501/",
            "http://192.168.1.20:8501/",
        ):
            with self.subTest(referer=referer):
                client = TestClient(application, client=(_fresh_ip(), 50000))
                response = client.get("/probe", headers={"Referer": referer})
                self.assertEqual(response.status_code, 200)

    def test_attack_in_referer_is_still_blocked(self):
        application = self._create_app({"enabled": True, "rate_limit": 100})
        client = TestClient(application, client=(_fresh_ip(), 50000))

        response = client.get(
            "/probe", headers={"Referer": "<script>alert(1)</script>"}
        )

        self.assertEqual(response.status_code, 400)

    def test_body_scan_is_an_explicit_opt_in(self):
        application = self._create_app(
            {"enabled": True, "rate_limit": 100, "scan_body": True}
        )
        client = TestClient(application, client=(_fresh_ip(), 50000))

        response = client.post(
            "/body",
            content="<script>alert(1)</script>",
            headers={"content-type": "text/plain"},
        )

        self.assertEqual(response.status_code, 400)

    def test_guard_rejections_still_carry_cors_headers(self):
        application = self._create_app(
            {"enabled": True, "rate_limit": 1}, allowed_origins=[ORIGIN]
        )
        client = TestClient(application, client=(_fresh_ip(), 50000))
        headers = {"Origin": ORIGIN}

        client.get("/probe", headers=headers)
        limited = client.get("/probe", headers=headers)
        attack = client.get("/probe", params={"q": "<script>x</script>"}, headers=headers)

        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers.get("access-control-allow-origin"), ORIGIN)
        self.assertEqual(attack.headers.get("access-control-allow-origin"), ORIGIN)

    def test_middleware_order_is_cors_then_origin_check_then_guard(self):
        application = self._create_app(
            {"enabled": True}, allowed_origins=[ORIGIN]
        )

        names = [
            getattr(m.cls, "__name__", "") or str(m.cls)
            for m in application.user_middleware
        ]

        # user_middleware is ordered outermost first.
        self.assertIs(application.user_middleware[0].cls, CORSMiddleware)
        self.assertEqual(
            names[1:], ["BaseHTTPMiddleware", "PureASGISecurityMiddleware"]
        )


class TestGuardRejectionsUseProjectJsonFormat(unittest.TestCase):
    """Guard rejections use the same JSON shape as the project's API errors."""

    @staticmethod
    def _api(guard_config: dict) -> TestClient:
        application = FastAPI()
        application.include_router(root_api_router)
        asgi.configure_middleware(application, [], guard_config)
        return TestClient(application, client=(_fresh_ip(), 50000))

    def test_rate_limit_on_tasks_endpoint_is_json(self):
        client = self._api({"enabled": True, "rate_limit": 1})

        client.get("/api/v1/tasks")
        limited = client.get("/api/v1/tasks")

        self.assertEqual(limited.status_code, 429)
        self.assertTrue(limited.headers["content-type"].startswith("application/json"))
        self.assertEqual(limited.json(), {"status": 429, "message": "Too many requests"})

    def test_attack_payload_is_json_400(self):
        client = self._api({"enabled": True})

        blocked = client.get("/api/v1/tasks", params={"q": "<script>alert(1)</script>"})

        self.assertEqual(blocked.status_code, 400)
        self.assertTrue(blocked.headers["content-type"].startswith("application/json"))
        self.assertEqual(blocked.json()["status"], 400)
        self.assertTrue(blocked.json()["message"])

    def test_every_guard_status_is_converted_and_keeps_its_headers(self):
        for status in (400, 401, 403, 413, 415, 429, 503):
            with self.subTest(status=status):
                original = StarletteGuardResponse(
                    Response("Denied", status, {"Retry-After": "5"}, "text/plain")
                )
                converted = asyncio.run(asgi.json_error_response(original))
                self.assertEqual(converted.status_code, status)
                self.assertEqual(
                    converted.headers["content-type"], "application/json"
                )
                self.assertEqual(converted.headers["retry-after"], "5")
                self.assertEqual(
                    json.loads(converted.body),
                    {"status": status, "message": "Denied"},
                )

    def test_application_responses_are_left_alone(self):
        for response in (
            Response("ok", 200, media_type="text/plain"),
            Response('{"a": 1}', 404, media_type="application/json"),
        ):
            wrapped = StarletteGuardResponse(response)
            self.assertIs(asyncio.run(asgi.json_error_response(wrapped)), wrapped)


class TestUvicornProxyOptions(unittest.TestCase):
    def test_disabled_guard_leaves_uvicorn_defaults(self):
        self.assertEqual(config.uvicorn_proxy_options({}), {})
        self.assertEqual(
            config.uvicorn_proxy_options({"enabled": False, "trusted_proxies": []}), {}
        )

    def test_no_trusted_proxies_turns_proxy_headers_off(self):
        self.assertEqual(
            config.uvicorn_proxy_options({"enabled": True, "trusted_proxies": []}),
            {"proxy_headers": False},
        )

    def test_trusted_proxies_are_passed_to_uvicorn(self):
        self.assertEqual(
            config.uvicorn_proxy_options({"enabled": True}),
            {"forwarded_allow_ips": "127.0.0.1,::1"},
        )
        self.assertEqual(
            config.uvicorn_proxy_options(
                {"enabled": True, "trusted_proxies": ["10.0.0.0/8", "192.0.2.7"]}
            ),
            {"forwarded_allow_ips": "10.0.0.0/8,192.0.2.7"},
        )

    def test_wildcard_proxy_logs_a_warning(self):
        for wildcard in ("*", "0.0.0.0/0", "::/0"):
            with self.subTest(wildcard=wildcard), patch.object(config.logger, "warning") as warn:
                options = config.uvicorn_proxy_options(
                    {"enabled": True, "trusted_proxies": [wildcard]}
                )
                warn.assert_called_once()
                self.assertEqual(options, {"forwarded_allow_ips": wildcard})

    def test_main_passes_the_options_to_uvicorn(self):
        options = {"proxy_headers": False}
        with (
            patch.object(config, "uvicorn_proxy_options", return_value=options),
            patch("uvicorn.run") as run_server,
        ):
            runpy.run_path(str(ROOT_DIR / "main.py"), run_name="__main__")

        self.assertIs(run_server.call_args.kwargs["proxy_headers"], False)


class TestRealUvicornProxyHeaders(unittest.TestCase):
    """TestClient skips Uvicorn, which rewrites the client from X-Forwarded-For."""

    def _serve(self, guard_config: dict) -> int:
        # Earlier tests leave counters for 127.0.0.1 in guard-core's process-wide state.
        ratelimit_handler._by_ip_request_timestamps.clear()
        ratelimit_handler.RateLimitManager._instance = None
        application = FastAPI()

        @application.get("/probe")
        def probe():
            return {"status": "ok"}

        asgi.configure_middleware(application, [], guard_config)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                log_level="error",
                **config.uvicorn_proxy_options(guard_config),
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
        thread.start()
        self.addCleanup(sock.close)
        self.addCleanup(thread.join, 10)
        self.addCleanup(setattr, server, "should_exit", True)
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(server.started)
        return sock.getsockname()[1]

    @staticmethod
    def _get(port: int, forwarded_for: str) -> int:
        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", "/probe", headers={"X-Forwarded-For": forwarded_for})
            return connection.getresponse().status
        finally:
            connection.close()

    def test_rotating_forwarded_for_cannot_dodge_the_limit_without_trusted_proxies(self):
        port = self._serve({"enabled": True, "rate_limit": 2, "trusted_proxies": []})

        codes = [self._get(port, _fresh_ip()) for _ in range(3)]

        self.assertEqual(codes, [200, 200, 429])

    def test_forwarded_for_is_honored_from_a_trusted_proxy(self):
        port = self._serve(
            {"enabled": True, "rate_limit": 2, "trusted_proxies": ["127.0.0.1"]}
        )
        first, second = _fresh_ip(), _fresh_ip()

        codes = [self._get(port, ip) for ip in (first, first, first, second)]

        self.assertEqual(codes, [200, 200, 429, 200])


if __name__ == "__main__":
    unittest.main()
