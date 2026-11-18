"""Unit tests for the kimi_code OAuth module.

Covers the device authorization state machine: device code requests, pending / slow_down / expired / denied polling,
token persistence and refresh rotation, transparent renewal within the expiry margin, serialized concurrent renewal, credentials on disk,
and credential clearing. The network layer (requests.post) and time (time.time) are all stubbed, so no real
endpoint is accessed; apart from the dedicated on-disk test, config saving is stubbed so the real config.toml is never touched.
"""

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import toml

from app.config import config
from app.services import kimi_code_oauth as oauth


def _response(payload, status_code=200):
    class _Resp:
        def __init__(self, data, code):
            self._data = data
            self.status_code = code
            self.text = str(data)

        def json(self):
            if isinstance(self._data, Exception):
                raise self._data
            return self._data

    return _Resp(payload, status_code)


class TestKimiCodeOAuth(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app.clear()
        # Stub config saving by default so tests don't write the real config.toml; the on-disk test temporarily restores the real implementation.
        self.real_try_save_config = config.try_save_config
        save_patcher = patch.object(config, "try_save_config", return_value=True)
        self.mock_try_save_config = save_patcher.start()
        self.addCleanup(save_patcher.stop)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    # ---- request_device_code ----

    def test_request_device_code_uses_regional_endpoint(self):
        payload = {
            "device_code": "dc-1",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://www.kimi.com/code/authorize_device",
            "verification_uri_complete": "https://www.kimi.com/code/authorize_device?user_code=ABCD-EFGH",
            "expires_in": 1800,
            "interval": 5,
        }
        with patch.object(
            oauth.requests, "post", return_value=_response(payload)
        ) as post:
            result = oauth.request_device_code("china")
        self.assertEqual(result["device_code"], "dc-1")
        self.assertEqual(result["user_code"], "ABCD-EFGH")
        url = post.call_args.args[0]
        self.assertTrue(url.startswith("https://auth.kimi.com/"))
        self.assertEqual(
            post.call_args.kwargs["data"]["client_id"], oauth.DEFAULT_CLIENT_ID
        )

    def test_request_device_code_global_region(self):
        payload = {
            "device_code": "dc-2",
            "user_code": "WXYZ-1234",
            "verification_uri_complete": "https://www.kimi.ai/code/authorize_device?user_code=WXYZ-1234",
        }
        with patch.object(
            oauth.requests, "post", return_value=_response(payload)
        ) as post:
            oauth.request_device_code("global")
        self.assertTrue(post.call_args.args[0].startswith("https://auth.kimi.ai/"))

    def test_request_device_code_requires_fields(self):
        with patch.object(
            oauth.requests, "post", return_value=_response({"device_code": "dc"})
        ):
            with self.assertRaises(ValueError):
                oauth.request_device_code("china")

    def test_request_device_code_non_json_raises_diagnosable(self):
        with patch.object(
            oauth.requests,
            "post",
            return_value=_response(ValueError("No JSON"), status_code=200),
        ):
            with self.assertRaisesRegex(ValueError, "non-JSON"):
                oauth.request_device_code("china")

    # ---- poll_token ----

    def _poll(self, payload):
        with patch.object(
            oauth.requests, "post", return_value=_response(payload)
        ):
            return oauth.poll_token("china", "dc")

    def test_poll_pending(self):
        self.assertEqual(
            self._poll({"error": "authorization_pending"}), {"pending": True}
        )

    def test_poll_slow_down_stays_pending(self):
        self.assertEqual(
            self._poll({"error": "slow_down"}),
            {"pending": True, "slow_down": True},
        )

    def test_poll_expired(self):
        self.assertEqual(self._poll({"error": "expired_token"}), {"expired": True})

    def test_poll_denied(self):
        self.assertEqual(self._poll({"error": "access_denied"}), {"denied": True})

    def test_poll_success_returns_payload(self):
        payload = {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900}
        self.assertEqual(self._poll(payload), payload)

    def test_poll_unknown_error_raises(self):
        with self.assertRaisesRegex(ValueError, "bad thing"):
            self._poll({"error": "unknown", "error_description": "bad thing"})

    def test_poll_non_json_raises_diagnosable(self):
        with patch.object(
            oauth.requests,
            "post",
            return_value=_response(ValueError("No JSON"), status_code=502),
        ):
            with self.assertRaisesRegex(ValueError, "non-JSON"):
                oauth.poll_token("china", "dc")

    # ---- store_token_bundle / rotation ----

    def test_store_token_bundle_persists_fields(self):
        oauth.store_token_bundle(
            "china", {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900}
        )
        self.assertEqual(config.app["kimi_code_access_token"], "at-1")
        self.assertEqual(config.app["kimi_code_refresh_token"], "rt-1")
        self.assertEqual(config.app["kimi_code_region"], "china")
        self.assertGreater(config.app["kimi_code_token_expires_at"], 0)

    def test_store_token_bundle_rotates_refresh_only_when_issued(self):
        oauth.store_token_bundle(
            "china", {"access_token": "at-1", "refresh_token": "rt-old", "expires_in": 900}
        )
        # When a new payload carries no refresh token, keep the existing one rather than overwriting it with empty.
        oauth.store_token_bundle(
            "china", {"access_token": "at-2", "expires_in": 900}
        )
        self.assertEqual(config.app["kimi_code_access_token"], "at-2")
        self.assertEqual(config.app["kimi_code_refresh_token"], "rt-old")
        oauth.store_token_bundle(
            "china", {"access_token": "at-3", "refresh_token": "rt-new", "expires_in": 900}
        )
        self.assertEqual(config.app["kimi_code_refresh_token"], "rt-new")

    def test_store_token_bundle_requests_config_save(self):
        # The pure API call path has no later WebUI save, so writing credentials must actively request a save to disk.
        oauth.store_token_bundle(
            "china", {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900}
        )
        self.mock_try_save_config.assert_called()

    def test_store_token_bundle_saved_to_disk_and_survives_reload(self):
        """After refresh token rotation it must be reliably saved to disk: after a simulated restart it can still renew from disk state."""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            original_cfg = dict(config._cfg)
            try:
                with (
                    # The temp file and target file are in the same directory, so os.replace is an atomic same-disk replace.
                    patch.object(config, "root_dir", temp_dir),
                    patch.object(config, "config_file", str(config_path)),
                    patch.object(
                        config, "try_save_config", self.real_try_save_config
                    ),
                ):
                    oauth.store_token_bundle(
                        "china",
                        {
                            "access_token": "at-1",
                            "refresh_token": "rt-new",
                            "expires_in": 900,
                        },
                    )
                    on_disk = toml.load(str(config_path))
            finally:
                # save_config rewrites the module-level _cfg, so restore it to avoid affecting other tests.
                config._cfg.clear()
                config._cfg.update(original_cfg)
        self.assertEqual(on_disk["app"]["kimi_code_access_token"], "at-1")
        self.assertEqual(on_disk["app"]["kimi_code_refresh_token"], "rt-new")
        # Simulate a restart: clear in-memory config and restore only from disk content.
        config.app.clear()
        config.app.update(on_disk["app"])
        self.assertTrue(oauth.is_authorized())
        self.assertEqual(oauth.get_valid_access_token(), "at-1")

    # ---- get_valid_access_token ----

    def _prime_tokens(self, expires_in=900):
        oauth.store_token_bundle(
            "china", {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": expires_in}
        )

    def test_get_valid_access_token_returns_cached(self):
        self._prime_tokens()
        self.assertEqual(oauth.get_valid_access_token(), "at-1")

    def test_get_valid_access_token_refreshes_near_expiry(self):
        self._prime_tokens(expires_in=10)  # Less than the 60s margin, triggering renewal
        refreshed = {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 900}
        with patch.object(
            oauth.requests, "post", return_value=_response(refreshed)
        ) as post:
            token = oauth.get_valid_access_token()
        self.assertEqual(token, "at-2")
        # The renewal result must be written back to config, so the next call doesn't refresh again.
        self.assertEqual(config.app["kimi_code_access_token"], "at-2")
        self.assertEqual(config.app["kimi_code_refresh_token"], "rt-2")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")

    def test_get_valid_access_token_expired_refresh(self):
        self._prime_tokens(expires_in=-1)
        refreshed = {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 900}
        with patch.object(oauth.requests, "post", return_value=_response(refreshed)):
            self.assertEqual(oauth.get_valid_access_token(), "at-2")

    def test_get_valid_access_token_requires_authorization(self):
        with self.assertRaisesRegex(ValueError, "not authorized"):
            oauth.get_valid_access_token()

    def test_get_valid_access_token_refresh_failure_raises(self):
        self._prime_tokens(expires_in=-1)
        with patch.object(
            oauth.requests,
            "post",
            return_value=_response({"error": "invalid_grant"}),
        ):
            with self.assertRaisesRegex(ValueError, "refresh failed"):
                oauth.get_valid_access_token()

    def test_concurrent_refresh_is_serialized(self):
        """Concurrent renewal must be serialized: an old refresh token can only be exchanged once, and other threads reuse the result."""
        self._prime_tokens(expires_in=-1)
        refresh_calls = []

        def fake_refresh(region, refresh_token):
            refresh_calls.append(refresh_token)
            time.sleep(0.05)  # Widen the race window
            return {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 900}

        results = []
        errors = []

        def worker():
            try:
                results.append(oauth.get_valid_access_token())
            except Exception as exc:  # pragma: no cover - helps diagnosis on failure
                errors.append(exc)

        with patch.object(oauth, "_refresh", side_effect=fake_refresh):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(refresh_calls), 1)
        self.assertEqual(sorted(results), ["at-new"] * 4)
        self.assertEqual(config.app["kimi_code_refresh_token"], "rt-new")

    # ---- Visibility while the config lock is held (concurrent video task scenario) ----

    def test_credentials_visible_while_config_lock_held(self):
        """While a video task holds the lock _set only queues: a just-completed login must be immediately visible to reads."""
        with config.runtime_config_lock():
            oauth.store_token_bundle(
                "china",
                {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900},
            )
            # Queued credentials must count too: it must not be misjudged as unauthorized.
            self.assertTrue(oauth.is_authorized())
            self.assertEqual(oauth.get_valid_access_token(), "at-1")

    def test_successive_calls_reuse_queued_refresh_while_lock_held(self):
        """While the lock is held the refresh result is still queued: later calls must not replay the already rotated old token."""
        redeemed = []

        def rotating_refresh(region, refresh_token):
            if refresh_token in redeemed:
                # Simulate the server rejecting a replay of the old token after rotation
                raise ValueError("kimi_code: token refresh failed: invalid_grant")
            redeemed.append(refresh_token)
            return {
                "access_token": f"at-{len(redeemed)}",
                "refresh_token": f"rt-{len(redeemed)}",
                "expires_in": 900,
            }

        with config.runtime_config_lock(), patch.object(
            oauth, "_refresh", side_effect=rotating_refresh
        ):
            self._prime_tokens(expires_in=-1)  # at-1 has expired, rt-1 can be exchanged once
            first = oauth.get_valid_access_token()
            second = oauth.get_valid_access_token()

        self.assertEqual(first, second)
        self.assertEqual(redeemed, ["rt-1"])

    # ---- Races between an in-flight refresh and clearing/replacing credentials ----

    def test_in_flight_refresh_discarded_after_disconnect(self):
        """The user disconnects while a refresh response is in flight: the result must be discarded and authorization must not come back to life."""
        self._prime_tokens(expires_in=-1)

        def refresh_then_disconnect(region, refresh_token):
            # Simulate the user clicking Disconnect in another session before the response returns
            oauth.clear_credentials()
            return {"access_token": "at-zombie", "refresh_token": "rt-zombie", "expires_in": 900}

        with patch.object(oauth, "_refresh", side_effect=refresh_then_disconnect):
            with self.assertRaisesRegex(ValueError, "credentials changed"):
                oauth.get_valid_access_token()
        self.assertFalse(oauth.is_authorized())
        self.assertEqual(config.app["kimi_code_access_token"], "")

    def test_in_flight_refresh_discarded_after_credential_replacement(self):
        """Credentials are replaced by a new login during an in-flight refresh: the old result must not overwrite the new credentials."""
        self._prime_tokens(expires_in=-1)

        def refresh_then_replace(region, refresh_token):
            # Simulate the user completing a new login before the response returns
            oauth.store_token_bundle(
                "china",
                {"access_token": "at-new-login", "refresh_token": "rt-new-login", "expires_in": 900},
            )
            return {"access_token": "at-stale", "refresh_token": "rt-stale", "expires_in": 900}

        with patch.object(oauth, "_refresh", side_effect=refresh_then_replace):
            with self.assertRaisesRegex(ValueError, "credentials changed"):
                oauth.get_valid_access_token()
        self.assertEqual(config.app["kimi_code_access_token"], "at-new-login")
        self.assertEqual(config.app["kimi_code_refresh_token"], "rt-new-login")

    # ---- Identity headers (the real application identity) ----

    def test_identity_headers_use_genuine_application_identity(self):
        """Identity headers must be MoneyPrinterTurbo's own, not disguised as kimi_code_cli."""
        headers = oauth._identity_headers()
        self.assertEqual(headers["X-Msh-Platform"], "MoneyPrinterTurbo")
        self.assertEqual(headers["X-Msh-Version"], oauth.__version__)
        self.assertTrue(headers["User-Agent"].startswith("MoneyPrinterTurbo/"))
        self.assertNotIn("kimi_code_cli", headers.values())

        payload = {
            "device_code": "dc-1",
            "user_code": "ABCD-EFGH",
            "verification_uri_complete": "https://www.kimi.com/code/authorize_device?user_code=ABCD-EFGH",
        }
        with patch.object(
            oauth.requests, "post", return_value=_response(payload)
        ) as post:
            oauth.request_device_code("china")
        sent = post.call_args.kwargs["headers"]
        self.assertEqual(sent["X-Msh-Platform"], "MoneyPrinterTurbo")
        self.assertTrue(sent["User-Agent"].startswith("MoneyPrinterTurbo/"))

    # ---- network error contract (relied on by the WebUI) ----

    def test_request_device_code_network_error_propagates(self):
        """Network exceptions are raised as RequestException unchanged, so the WebUI can show a retryable error."""
        with patch.object(
            oauth.requests,
            "post",
            side_effect=oauth.requests.exceptions.ConnectTimeout("boom"),
        ):
            with self.assertRaises(oauth.requests.exceptions.RequestException):
                oauth.request_device_code("china")

    def test_poll_token_network_error_propagates(self):
        with patch.object(
            oauth.requests,
            "post",
            side_effect=oauth.requests.exceptions.ReadTimeout("boom"),
        ):
            with self.assertRaises(oauth.requests.exceptions.RequestException):
                oauth.poll_token("china", "dc")

    # ---- clear / helpers ----

    def test_clear_credentials(self):
        self._prime_tokens()
        oauth.clear_credentials()
        self.assertFalse(oauth.is_authorized())
        self.assertEqual(config.app["kimi_code_access_token"], "")

    def test_is_authorized_variants(self):
        self.assertFalse(oauth.is_authorized())
        self._prime_tokens()
        self.assertTrue(oauth.is_authorized())

    def test_resolve_region(self):
        self.assertEqual(oauth.resolve_region("https://api.kimi.ai/coding/v1"), "global")
        self.assertEqual(oauth.resolve_region("https://api.kimi.com/coding/v1"), "china")
        self.assertEqual(oauth.resolve_region(""), "china")

    def test_coerce_timeout(self):
        self.assertEqual(oauth.coerce_timeout(None), oauth.DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(oauth.coerce_timeout("120"), 120.0)
        with self.assertRaises(ValueError):
            oauth.coerce_timeout("abc")
        with self.assertRaises(ValueError):
            oauth.coerce_timeout("0")
        with self.assertRaises(ValueError):
            oauth.coerce_timeout("nan")
        with self.assertRaises(ValueError):
            oauth.coerce_timeout("inf")


if __name__ == "__main__":
    unittest.main()
