"""ChatGPT subscription sign-in, owned by the current browser session."""

import time

import streamlit as st

from app.services import codex_oauth

FLOW_KEY = "openai_codex_login_flow"


@st.fragment(run_every="2s")
def render_codex_login(tr):
    st.caption(tr("codex.oauth.shared"))
    stored_error = False
    try:
        authorized = codex_oauth.account_status()
    except codex_oauth.CodexError as error:
        st.error(tr(error.key).format(**error.params))
        authorized = False
        stored_error = True
    flow = st.session_state.get(FLOW_KEY)
    if flow:
        try:
            if flow["generation"] != codex_oauth.authorization_generation():
                raise codex_oauth.CodexError("codex.oauth.changed")
            if time.time() >= flow["expires_at"]:
                raise codex_oauth.CodexError("codex.oauth.expired")
            if time.time() >= flow["next_poll_at"]:
                completed = codex_oauth.poll_login(flow)
                flow["next_poll_at"] = time.time() + flow["interval"]
                if completed:
                    st.session_state.pop(FLOW_KEY, None)
                    st.rerun()
        except codex_oauth.CodexError as error:
            st.session_state.pop(FLOW_KEY, None)
            st.error(tr(error.key).format(**error.params))
            flow = None
    if authorized:
        st.success(tr("codex.oauth.connected"))
    if authorized or flow or stored_error:
        if st.button(
            tr("codex.oauth.disconnect" if authorized or stored_error else "Cancel"),
            key="codex_disconnect",
        ):
            if authorized or stored_error:
                codex_oauth.disconnect()
            st.session_state.pop(FLOW_KEY, None)
            st.rerun()
    if flow:
        st.info(tr("codex.oauth.pending"))
        st.code(flow["user_code"], language=None)
        st.link_button(tr("codex.oauth.open"), codex_oauth.VERIFY_URL)
    elif not authorized:
        if st.button(tr("codex.oauth.login"), key="codex_login", type="primary"):
            try:
                flow = codex_oauth.request_device_code()
                flow["next_poll_at"] = time.time() + flow["interval"]
                st.session_state[FLOW_KEY] = flow
                st.rerun()
            except codex_oauth.CodexError as error:
                st.error(tr(error.key).format(**error.params))
