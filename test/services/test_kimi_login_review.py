"""审查复现：旧的设备授权和刷新结果不得撤销另一个页面的断开操作。"""

import threading
import time
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import kimi_code_oauth as oauth


@pytest.fixture
def isolated_credentials():
    app_config = {
        "kimi_code_region": "china",
        "kimi_code_access_token": "review-expired",
        "kimi_code_refresh_token": "review-refresh",
        "kimi_code_token_expires_at": time.time() - 1,
    }
    with (
        patch.object(config, "app", app_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        yield app_config


def _click_link(app, key):
    link = next(item for item in app.get("link_button") if item.proto.id.endswith(key))
    states = app._tree.get_widget_states()
    states.widgets.add(id=link.proto.id, trigger_value=True)
    return app._run(states)


@pytest.mark.parametrize("replace", [False, True])
def test_refresh_commit_respects_disconnect_or_new_login(isolated_credentials, replace):
    """暂停真实写回入口，让另一线程断开／登录，再恢复旧刷新。"""
    ready, release = threading.Event(), threading.Event()
    original_store = oauth.store_token_bundle
    errors = []

    def delayed_store(region, payload, **kwargs):
        ready.set()
        assert release.wait(3)
        return original_store(region, payload, **kwargs)

    def worker():
        try:
            oauth.get_valid_access_token()
        except Exception as error:
            errors.append(error)

    with (
        patch.object(
            oauth,
            "_refresh",
            return_value={
                "access_token": "review-stale",
                "refresh_token": "review-stale-refresh",
                "expires_in": 900,
            },
        ),
        patch.object(oauth, "store_token_bundle", side_effect=delayed_store),
    ):
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            assert ready.wait(3)
            oauth.clear_credentials()
            if replace:
                original_store(
                    "global",
                    {
                        "access_token": "review-new-login",
                        "refresh_token": "review-new-refresh",
                        "expires_in": 900,
                    },
                )
        finally:
            release.set()
            thread.join(3)
    assert not thread.is_alive()
    assert isolated_credentials["kimi_code_access_token"] == (
        "review-new-login" if replace else ""
    )
    assert len(errors) == 1 and isinstance(errors[0], ValueError)


@pytest.mark.parametrize("replace", [False, True])
def test_device_authorization_does_not_restore_or_replace_newer_login(
    isolated_credentials, replace
):
    """真实 Streamlit 登录面板：轮询响应返回前另一个页面断开／重新登录。"""
    from webui import kimi_login

    new_payload = {
        "access_token": "review-new-login",
        "refresh_token": "review-new-refresh",
        "expires_in": 900,
    }

    def response_after_account_change(region, code):
        oauth.clear_credentials()
        if replace:
            oauth.store_token_bundle("china", new_payload)
        return {
            "access_token": "review-stale-device",
            "refresh_token": "review-stale-device-refresh",
            "expires_in": 900,
        }

    with (
        patch.object(
            oauth,
            "request_device_code",
            return_value={
                "device_code": "review-device",
                "user_code": "REVIEW-CODE",
                "interval": 5,
                "verification_uri_complete": "https://www.kimi.ai/code/authorize_device?user_code=REVIEW-CODE",
            },
        ),
        patch.object(oauth, "poll_token", side_effect=response_after_account_change),
    ):
        app = AppTest.from_string(
            "from webui.kimi_login import render_kimi_login\n"
            'render_kimi_login("global", lambda key: key)\n'
        )
        app.run()
        _click_link(app, "kimi_code_reauth_button")
        flow = dict(app.session_state[kimi_login.FLOW_KEY])
        flow["next_poll_at"] = 0
        app.session_state[kimi_login.FLOW_KEY] = flow
        app.run()
        assert not app.exception
        assert isolated_credentials["kimi_code_access_token"] == (
            "review-new-login" if replace else ""
        )
        assert kimi_login.FLOW_KEY not in app.session_state


def test_idle_authorization_link_renews_before_expiry():
    """控制时钟验证未点击链接会更新，但不会提前轮询 token。"""
    from webui import kimi_login

    now = time.time()

    def issue(region):
        n = issuer.call_count
        return {
            "device_code": f"device-{n}",
            "user_code": f"TEST-{n}",
            "verification_uri_complete": f"https://www.kimi.com/?user_code=TEST-{n}",
            "interval": 2,
            "expires_in": 8,
        }

    with (
        patch.object(config, "app", {}),
        patch.object(oauth, "request_device_code", side_effect=issue) as issuer,
        patch.object(oauth, "poll_token") as poll,
        patch.object(kimi_login.time, "time", return_value=now) as clock,
    ):
        app = AppTest.from_string(
            'from webui.kimi_login import render_kimi_login\nrender_kimi_login("china", lambda key: key)'
        )
        app.run()
        assert issuer.call_count == 1
        clock.return_value = now + 3
        app.run()
        assert issuer.call_count == 1
        clock.return_value = now + 5
        app.run()
        assert issuer.call_count == 2
        assert app.get("link_button")[0].proto.url.endswith("TEST-2")
        assert not app.exception
        poll.assert_not_called()


def test_credentials_remain_nonblocking_with_video_config_lock(isolated_credentials):
    """另一线程持有视频配置锁，登录／断开仍能完成并读到排队更新。"""
    held, release = threading.Event(), threading.Event()

    def hold_video_lock():
        with config.runtime_config_lock():
            held.set()
            assert release.wait(5)

    thread = threading.Thread(target=hold_video_lock)
    thread.start()
    try:
        assert held.wait(3)
        oauth.store_token_bundle(
            "china",
            {"access_token": "review-live", "refresh_token": "review-live-refresh"},
        )
        assert oauth.get_valid_access_token() == "review-live"
        oauth.clear_credentials()
        assert not oauth.is_authorized()
        assert thread.is_alive()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
