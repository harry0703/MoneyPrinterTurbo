"""Kimi 登录界面：直接打开授权链接，并局部轮询授权状态。"""

import time

import requests
import streamlit as st
from loguru import logger

from app.services import kimi_code_oauth

FLOW_KEY = "kimi_code_oauth_flow"
PREPARED_KEY = "kimi_code_oauth_prepared"
MESSAGE_KEY = "kimi_code_oauth_message"


def _prepare_link(region, tr):
    prepared = st.session_state.get(PREPARED_KEY)
    if prepared and prepared["region"] == region:
        if prepared.get("error") or time.time() < prepared["refresh_at"]:
            return prepared

    # 链接在展示按钮前准备好，点击时由浏览器原生打开新标签页。
    # 不用服务器的 webbrowser.open，也不依赖容易被拦截的异步弹窗。
    try:
        payload = kimi_code_oauth.request_device_code(region)
    except requests.RequestException:
        logger.warning("kimi_code: could not prepare the authorization link")
        prepared = {"region": region, "error": tr("kimi_code.oauth.network_error")}
    except ValueError as error:
        prepared = {"region": region, "error": str(error)}
    else:
        now = time.time()
        lifetime = float(payload.get("expires_in", 600))
        prepared = {
            "region": region,
            "device_code": payload["device_code"],
            "user_code": payload["user_code"],
            "verification_uri_complete": payload["verification_uri_complete"],
            "interval": max(int(payload.get("interval", 5)), 2),
            "expires_at": now + lifetime,
            "refresh_at": now + lifetime - min(10, lifetime / 2),
        }
    st.session_state[PREPARED_KEY] = prepared
    return prepared


def _begin_login(prepared):
    st.session_state[FLOW_KEY] = dict(
        prepared,
        next_poll_at=time.time() + prepared["interval"],
        generation=kimi_code_oauth.authorization_generation(),
    )
    st.session_state.pop(PREPARED_KEY, None)
    st.session_state.pop(MESSAGE_KEY, None)


def _finish_login(level, message):
    st.session_state.pop(FLOW_KEY, None)
    st.session_state.pop(PREPARED_KEY, None)
    st.session_state[MESSAGE_KEY] = (level, message)


def _poll_login(tr):
    flow = st.session_state.get(FLOW_KEY)
    if not flow:
        return
    if flow.get("generation") != kimi_code_oauth.authorization_generation():
        _finish_login("warning", tr("kimi_code.oauth.changed"))
        return
    now = time.time()
    if now >= flow["expires_at"]:
        _finish_login("warning", tr("kimi_code.oauth.expired"))
        return

    if now >= flow["next_poll_at"]:
        try:
            payload = kimi_code_oauth.poll_token(flow["region"], flow["device_code"])
        except requests.RequestException:
            flow["network_errors"] = flow.get("network_errors", 0) + 1
            logger.warning(
                "kimi_code: authorization poll network error "
                f"({flow['network_errors']}/5)"
            )
            if flow["network_errors"] >= 5:
                _finish_login("error", tr("kimi_code.oauth.network_error"))
                return
        except ValueError as error:
            _finish_login("error", str(error))
            return
        else:
            flow["network_errors"] = 0
            if payload.get("expired"):
                _finish_login("warning", tr("kimi_code.oauth.expired"))
                return
            elif payload.get("denied"):
                _finish_login("warning", tr("kimi_code.oauth.denied"))
                return
            elif payload.get("pending"):
                if payload.get("slow_down"):
                    flow["interval"] += 5
            else:
                try:
                    kimi_code_oauth.store_token_bundle(
                        flow["region"], payload, expected_generation=flow["generation"]
                    )
                except ValueError:
                    _finish_login("warning", tr("kimi_code.oauth.changed"))
                else:
                    _finish_login("success", tr("kimi_code.oauth.success"))
                return
        # 以响应结束时间计算下一次请求，避免慢请求之后立即再轮询。
        flow["next_poll_at"] = time.time() + flow["interval"]
        st.session_state[FLOW_KEY] = flow


def _cancel_login():
    st.session_state.pop(FLOW_KEY, None)
    st.session_state.pop(PREPARED_KEY, None)


def _disconnect():
    st.session_state.pop(FLOW_KEY, None)
    st.session_state.pop(PREPARED_KEY, None)
    st.session_state.pop(MESSAGE_KEY, None)
    kimi_code_oauth.clear_credentials()


@st.fragment(run_every="1s")
def render_kimi_login(region, tr):
    """在设置弹窗中渲染登录；未点击登录前不请求 token。"""
    flow = st.session_state.get(FLOW_KEY)
    if flow and flow["region"] != region:
        # 用户切换站点后停止旧站点的待授权流程，旧凭据仍按原区域使用。
        st.session_state.pop(FLOW_KEY, None)
        flow = None

    if flow:
        _poll_login(tr)
        flow = st.session_state.get(FLOW_KEY)

    message = st.session_state.get(MESSAGE_KEY)
    if message:
        level, text = message
        getattr(st, level)(text)

    authorized = kimi_code_oauth.is_authorized()
    auth_region = kimi_code_oauth.authorized_region() or region
    mismatch = authorized and auth_region != region
    if authorized:
        if mismatch:
            st.warning(
                tr("kimi_code.oauth.region_mismatch").format(
                    authorized=auth_region, selected=region
                )
            )
        else:
            st.success(tr("kimi_code.oauth.authorized").format(region=auth_region))
        st.button(
            tr("kimi_code.oauth.disconnect"),
            key="kimi_code_disconnect_button",
            on_click=_disconnect,
        )

    if flow:
        if flow.get("network_errors"):
            st.warning(tr("kimi_code.oauth.poll_retry"))
        st.info(tr("kimi_code.oauth.pending"))
        # 保留重新打开入口，与取消操作放在同一行。
        with st.container(horizontal=True, gap="small"):
            st.link_button(
                tr("kimi_code.oauth.open_page"), flow["verification_uri_complete"]
            )
            st.button(
                tr("Cancel"),
                key="kimi_code_cancel_login_button",
                on_click=_cancel_login,
            )
    elif not authorized or mismatch:
        prepared = _prepare_link(region, tr)
        label = tr("kimi_code.oauth.reauth" if mismatch else "kimi_code.oauth.login")
        key = "kimi_code_reauth_button" if mismatch else "kimi_code_login_button"
        if prepared.get("error"):
            st.error(prepared["error"])
            st.button(
                label,
                key=key,
                type="primary",
                icon=":material/login:",
                on_click=lambda: st.session_state.pop(PREPARED_KEY, None),
            )
        else:
            st.link_button(
                label,
                prepared["verification_uri_complete"],
                key=key,
                type="primary",
                icon=":material/login:",
                on_click=_begin_login,
                args=(prepared,),
            )
