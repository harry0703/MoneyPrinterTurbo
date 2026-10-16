import itertools
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app import asgi

ORIGIN = "https://frontend.example"
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


if __name__ == "__main__":
    unittest.main()
