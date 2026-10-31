"""kimi_code OAuth 模块的单元测试。

覆盖设备授权状态机：设备码请求、pending / slow_down / expired / denied 轮询、
token 持久化与 refresh 轮换、过期余量下的透明续期、并发续期串行化、凭证落盘、
以及凭证清除。网络层（requests.post）与时间（time.time）全部打桩，不访问真实
端点；除专门的落盘测试外，配置保存统一打桩，避免触碰真实 config.toml。
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
        # 默认打桩配置保存，避免测试写真实 config.toml；落盘测试会临时恢复真实实现。
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
        # 新一轮 payload 未携带 refresh token 时，保留已有的，避免覆盖为空。
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
        # 纯 API 调用路径没有后续 WebUI 保存，写凭证时必须主动请求落盘。
        oauth.store_token_bundle(
            "china", {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900}
        )
        self.mock_try_save_config.assert_called()

    def test_store_token_bundle_saved_to_disk_and_survives_reload(self):
        """refresh token 轮换后必须可靠落盘：模拟重启后凭磁盘状态仍能续期。"""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            original_cfg = dict(config._cfg)
            try:
                with (
                    # 临时文件与目标文件放在同一目录，保证 os.replace 同盘原子替换。
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
                # save_config 会重写模块级 _cfg，恢复以免影响其它测试。
                config._cfg.clear()
                config._cfg.update(original_cfg)
        self.assertEqual(on_disk["app"]["kimi_code_access_token"], "at-1")
        self.assertEqual(on_disk["app"]["kimi_code_refresh_token"], "rt-new")
        # 模拟重启：清空内存配置，只从磁盘内容恢复。
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
        self._prime_tokens(expires_in=10)  # 小于 60s 余量，触发续期
        refreshed = {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 900}
        with patch.object(
            oauth.requests, "post", return_value=_response(refreshed)
        ) as post:
            token = oauth.get_valid_access_token()
        self.assertEqual(token, "at-2")
        # 续期结果必须写回配置，下一次调用不再重复刷新。
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
        """并发续期必须串行：旧 refresh token 只能换一次，其余线程复用结果。"""
        self._prime_tokens(expires_in=-1)
        refresh_calls = []

        def fake_refresh(region, refresh_token):
            refresh_calls.append(refresh_token)
            time.sleep(0.05)  # 放大竞态窗口
            return {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 900}

        results = []
        errors = []

        def worker():
            try:
                results.append(oauth.get_valid_access_token())
            except Exception as exc:  # pragma: no cover - 失败时便于诊断
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

    # ---- 配置锁持锁期间的可见性（视频任务并发场景） ----

    def test_credentials_visible_while_config_lock_held(self):
        """视频任务持锁时 _set 只排队：刚完成的登录必须立即对读取可见。"""
        with config.runtime_config_lock():
            oauth.store_token_bundle(
                "china",
                {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900},
            )
            # 排队中的凭证也必须算数：不能误判为未授权。
            self.assertTrue(oauth.is_authorized())
            self.assertEqual(oauth.get_valid_access_token(), "at-1")

    def test_successive_calls_reuse_queued_refresh_while_lock_held(self):
        """持锁期间 refresh 结果仍在队列：后续调用不能重放已轮换的旧 token。"""
        redeemed = []

        def rotating_refresh(region, refresh_token):
            if refresh_token in redeemed:
                # 模拟服务端轮换后拒绝旧 token 重放
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
            self._prime_tokens(expires_in=-1)  # at-1 已过期，rt-1 可兑换一次
            first = oauth.get_valid_access_token()
            second = oauth.get_valid_access_token()

        self.assertEqual(first, second)
        self.assertEqual(redeemed, ["rt-1"])

    # ---- 在途 refresh 与凭证清除/更换的竞态 ----

    def test_in_flight_refresh_discarded_after_disconnect(self):
        """refresh 响应在途时用户断开连接：结果必须丢弃，授权状态不能复活。"""
        self._prime_tokens(expires_in=-1)

        def refresh_then_disconnect(region, refresh_token):
            # 模拟响应返回前用户在另一个会话点了 Disconnect
            oauth.clear_credentials()
            return {"access_token": "at-zombie", "refresh_token": "rt-zombie", "expires_in": 900}

        with patch.object(oauth, "_refresh", side_effect=refresh_then_disconnect):
            with self.assertRaisesRegex(ValueError, "credentials changed"):
                oauth.get_valid_access_token()
        self.assertFalse(oauth.is_authorized())
        self.assertEqual(config.app["kimi_code_access_token"], "")

    def test_in_flight_refresh_discarded_after_credential_replacement(self):
        """在途 refresh 期间凭证被新登录替换：旧结果不能覆盖新凭证。"""
        self._prime_tokens(expires_in=-1)

        def refresh_then_replace(region, refresh_token):
            # 模拟响应返回前用户完成了一次新的登录
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

    # ---- 身份头（真实应用身份） ----

    def test_identity_headers_use_genuine_application_identity(self):
        """身份头必须是 MoneyPrinterTurbo 自己的，不伪装成 kimi_code_cli。"""
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

    # ---- network error contract (WebUI 依赖) ----

    def test_request_device_code_network_error_propagates(self):
        """网络异常以 RequestException 原样抛出，WebUI 据此展示可重试错误。"""
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
