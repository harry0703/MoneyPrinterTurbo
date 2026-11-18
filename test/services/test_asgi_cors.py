import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from app import asgi


class TestASGICORS(unittest.TestCase):
    """Verify browser cross-origin defaults and explicit compatibility config, so open CORS isn't reintroduced."""

    @staticmethod
    def _create_client(allowed_origins: list[str]) -> TestClient:
        """Build an app containing only a probe route, isolating business tasks and external API calls."""

        application = FastAPI()

        @application.get("/probe")
        def probe():
            return {"status": "ok"}

        asgi.configure_browser_access(application, allowed_origins)
        return TestClient(application)

    def test_origin_parser_trims_values_and_ignores_empty_items(self):
        """Spaces and trailing commas in the environment variable must not break matching of valid origins."""

        origins = asgi.parse_cors_allowed_origins(
            " https://a.example,https://b.example, ,"
        )

        self.assertEqual(
            origins,
            ["https://a.example", "https://b.example"],
        )
        self.assertEqual(asgi.parse_cors_allowed_origins(""), [])
        self.assertEqual(asgi.parse_cors_allowed_origins(None), [])

    def test_origin_parser_normalizes_every_item_to_origin_header_shape(self):
        """Config entries must be folded into the canonical form of the Origin header, or the allowlist silently fails."""

        origins = asgi.parse_cors_allowed_origins(
            "https://frontend.example/,"
            "HTTPS://Admin.Example,"
            "https://frontend.example/,"
            "localhost:3000,"
            "ftp://files.example,"
            "*"
        )

        # Trailing slashes, case differences and duplicates all normalize to the same origin; hostnames missing a scheme
        # and non-http/https schemes can never appear in an Origin header, so they're dropped.
        self.assertEqual(
            origins,
            ["https://frontend.example", "https://admin.example", "*"],
        )

    def test_malformed_entry_is_dropped_without_losing_valid_origins(self):
        """A malformed entry may only drop itself with a warning and must not interrupt parsing of the whole config."""

        with patch.object(asgi, "logger") as mocked_logger:
            origins = asgi.parse_cors_allowed_origins(
                "https://valid.example,"
                "https://[::1,"
                "https://frontend.example:bad,"
                "https://frontend.example:99999,"
                "https://second.example"
            )

        # Malformed IPv6 literals and invalid ports can never appear in an Origin header. Their parse exceptions
        # must be contained here: this function is called at module import time, and an escaping exception means the whole API can't start.
        self.assertEqual(
            origins,
            ["https://valid.example", "https://second.example"],
        )
        self.assertEqual(mocked_logger.warning.call_count, 3)

    def test_explicit_default_port_is_folded_into_the_origin(self):
        """Forms that write out the default port explicitly must fold into the Origin the browser actually sends."""

        origins = asgi.parse_cors_allowed_origins(
            "https://secure.example:443,"
            "http://plain.example:80,"
            "https://padded.example:0443,"
            "https://custom.example:8443,"
            "https://[::1]:3000"
        )

        # :443 / :0443 / :80 all equal the protocol's default port, which browsers omit when serializing Origin;
        # non-default ports must be kept, and IPv6 literals keep their square brackets.
        self.assertEqual(
            origins,
            [
                "https://secure.example",
                "http://plain.example",
                "https://padded.example",
                "https://custom.example:8443",
                "https://[::1]:3000",
            ],
        )

    def test_address_bar_style_origin_admits_the_trusted_frontend(self):
        """A form with a trailing slash copied from the address bar must give the same frontend access result as the canonical form."""

        trusted_origin = "https://frontend.example"
        client = self._create_client(
            asgi.parse_cors_allowed_origins("https://frontend.example/")
        )

        response = client.get("/probe", headers={"Origin": trusted_origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], trusted_origin
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"], trusted_origin
        )

    def test_default_port_configuration_admits_the_trusted_frontend(self):
        """When the config includes the default port, a browser Origin without the port must still be allowed."""

        trusted_origin = "https://frontend.example"
        client = self._create_client(
            asgi.parse_cors_allowed_origins("https://frontend.example:443")
        )

        response = client.get("/probe", headers={"Origin": trusted_origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], trusted_origin
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"], trusted_origin
        )

    def test_empty_configuration_keeps_browser_same_origin_policy(self):
        """Without an allowlist, third-party web pages can't read responses or pass preflights."""

        client = self._create_client([])
        origin = "https://evil.attacker.example"

        response = client.get("/probe", headers={"Origin": origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(preflight.status_code, 403)
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    def test_same_origin_and_server_clients_remain_compatible(self):
        """Same-origin browsers and server-side clients that send no Origin must keep working normally."""

        client = self._create_client([])

        same_origin = client.get(
            "/probe",
            headers={"Origin": "http://testserver"},
        )
        server_client = client.get("/probe")

        self.assertEqual(same_origin.status_code, 200)
        self.assertEqual(server_client.status_code, 200)

    def test_explicit_origin_allows_only_the_trusted_frontend(self):
        """A separate web frontend can access once explicitly configured, while other origins must still be rejected."""

        trusted_origin = "https://frontend.example"
        untrusted_origin = "https://evil.attacker.example"
        client = self._create_client([trusted_origin])

        trusted = client.get("/probe", headers={"Origin": trusted_origin})
        untrusted = client.get("/probe", headers={"Origin": untrusted_origin})
        trusted_preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        untrusted_preflight = client.options(
            "/probe",
            headers={
                "Origin": untrusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(trusted.headers["access-control-allow-origin"], trusted_origin)
        self.assertEqual(trusted.headers["access-control-allow-credentials"], "true")
        self.assertNotIn("access-control-allow-origin", untrusted.headers)
        self.assertEqual(trusted_preflight.status_code, 200)
        self.assertEqual(untrusted_preflight.status_code, 400)

    def test_trusted_origin_can_request_private_network_access(self):
        """An exact allowlist should support the extra preflight when a remote web page accesses an API on the local machine or LAN."""

        trusted_origin = "https://frontend.example"
        client = self._create_client([trusted_origin])

        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )

        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-private-network"],
            "true",
        )

    def test_explicit_wildcard_does_not_enable_credentials(self):
        """An explicit wildcard keeps compatibility but must not form an Origin-reflecting combination again."""

        client = self._create_client(["*"])
        origin = "https://frontend.example"

        response = client.get("/probe", headers={"Origin": origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", preflight.headers)

    def test_untrusted_multipart_request_is_rejected_before_side_effect(self):
        """Multipart requests that need no preflight must also get 403 before reaching the upload handler."""

        application = FastAPI()
        save_upload = Mock(return_value="stored.mp3")

        @application.post("/upload")
        def upload(file: UploadFile = File(...)):
            return {"file": save_upload(file.filename)}

        asgi.configure_browser_access(application, [])
        client = TestClient(application)

        response = client.post(
            "/upload",
            headers={"Origin": "https://evil.attacker.example"},
            files={
                "file": (
                    "attack.mp3",
                    b"attacker-controlled",
                    "audio/mpeg",
                )
            },
        )

        self.assertEqual(response.status_code, 403)
        save_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
