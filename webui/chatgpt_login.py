"""Local browser-based Sign in with ChatGPT; no API server is required."""

import streamlit as st

from app.services import chatgpt_oauth

FLOW_KEY = "openai_chatgpt_login_flow"


def render_chatgpt_login(tr):
    # Poll only while the browser authorization is pending. A permanent nested
    # fragment inside the settings dialog can clear its sibling model widgets
    # after the dialog itself reruns (for example when a model is selected).
    if st.session_state.get(FLOW_KEY):
        _poll_pending_login(tr)
    else:
        _render_login_controls(tr)


@st.fragment(run_every="2s")
def _poll_pending_login(tr):
    _render_login_controls(tr)


def _render_account_actions(tr, details, profiles, flow):
    if len(profiles) > 1:
        snapshot = (details["active"], details["revision"])
        if st.session_state.get("chatgpt_account_snapshot") != snapshot:
            st.session_state["chatgpt_account_picker"] = (
                details["active"] if details["active"] in profiles else None
            )
            st.session_state["chatgpt_account_snapshot"] = snapshot
        selected = st.selectbox(
            tr("chatgpt.oauth.account"),
            list(profiles),
            index=None,
            format_func=profiles.get,
            key="chatgpt_account_picker",
            disabled=bool(flow),
        )
        if selected and selected != details["active"]:
            chatgpt_oauth.select_account(selected)
            st.session_state["chatgpt_account_actions_open"] = False
            st.rerun()
    if details["connected"]:
        st.link_button(
            tr("chatgpt.oauth.manage_usage"),
            chatgpt_oauth.USAGE_URL,
            type="tertiary",
            icon=":material/open_in_new:",
        )
    if profiles and st.button(
        tr("chatgpt.oauth.add_account"),
        key="chatgpt_add_account",
        type="tertiary",
        icon=":material/person_add:",
        disabled=bool(flow),
    ):
        st.session_state[FLOW_KEY] = chatgpt_oauth.begin_login(new_account=True)
        st.session_state["chatgpt_account_actions_open"] = False
        st.rerun()
    if details["connected"] and st.button(
        tr("chatgpt.oauth.disconnect"),
        key="chatgpt_disconnect",
        type="tertiary",
        icon=":material/logout:",
    ):
        if flow:
            chatgpt_oauth.cancel_login(flow)
        with st.spinner(tr("chatgpt.oauth.disconnect") + "…"):
            confirmed = chatgpt_oauth.disconnect()
        st.session_state.pop(FLOW_KEY, None)
        st.session_state["chatgpt_revocation_unconfirmed"] = not confirmed
        st.session_state["chatgpt_account_actions_open"] = False
        st.rerun()


def _render_login_controls(tr):
    st.caption(tr("chatgpt.oauth.eligibility"))
    try:
        flow = st.session_state.get(FLOW_KEY)
        if flow:
            try:
                if chatgpt_oauth.poll_login(flow):
                    st.session_state.pop(FLOW_KEY, None)
                    st.rerun()
            except chatgpt_oauth.ChatGPTError as error:
                st.session_state.pop(FLOW_KEY, None)
                st.error(tr(error.key).format(**error.params))
                flow = None
        details = chatgpt_oauth.account_details()
        profiles = dict(details["profiles"])
        if details["connected"] or profiles:
            summary, actions = st.columns([1, 0.16], vertical_alignment="center")
            with summary:
                st.caption(tr("chatgpt.oauth.account"))
                st.text(details["email"] or profiles.get(details["active"], "ChatGPT"))
                if details["authorized"]:
                    st.caption(":green[●] " + tr("chatgpt.oauth.connected"))
            # Keep controls in the dialog's DOM tree. A portalled popover
            # inside st.dialog can look clickable while the modal treats it as inert.
            if actions.button(
                "⋯",
                help=tr("chatgpt.oauth.account"),
                type="tertiary",
                key="chatgpt_account_actions_toggle",
            ):
                st.session_state[
                    "chatgpt_account_actions_open"
                ] = not st.session_state.get("chatgpt_account_actions_open", False)
            if st.session_state.get("chatgpt_account_actions_open", False):
                with st.container(border=True, key="chatgpt_account_actions"):
                    _render_account_actions(tr, details, profiles, flow)
        if details["connected"] and not details["authorized"]:
            st.info(tr("chatgpt.oauth.plan_required"))
        if st.session_state.get("chatgpt_revocation_unconfirmed"):
            st.warning(tr("chatgpt.oauth.revocation_unconfirmed"))
        if flow:
            st.caption(tr("chatgpt.oauth.pending"))
            with st.container(horizontal=True, vertical_alignment="center"):
                st.link_button(
                    tr("chatgpt.oauth.open"), flow["authorize_url"], type="primary"
                )
                if st.button(tr("Cancel"), key="chatgpt_cancel", type="tertiary"):
                    chatgpt_oauth.cancel_login(flow)
                    st.session_state.pop(FLOW_KEY, None)
                    st.rerun()
        else:
            if not details["authorized"] and st.button(
                tr("chatgpt.oauth.login"), key="chatgpt_login", type="primary"
            ):
                st.session_state[FLOW_KEY] = chatgpt_oauth.begin_login(
                    enable_plan=details["connected"]
                )
                st.rerun()
    except chatgpt_oauth.ChatGPTError as error:
        if error.key == "chatgpt.oauth.busy":
            st.info(tr(error.key))
            if st.button(tr("chatgpt.oauth.retry"), key="chatgpt_retry"):
                st.rerun()
        else:
            st.error(tr(error.key).format(**error.params))
