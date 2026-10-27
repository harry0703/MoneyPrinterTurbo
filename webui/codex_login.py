"""Local browser-based Sign in with ChatGPT; no API server is required."""

import streamlit as st

from app.services import codex_oauth

FLOW_KEY = "openai_codex_login_flow"


def render_codex_login(tr):
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
        if st.session_state.get("codex_account_snapshot") != snapshot:
            st.session_state["codex_account_picker"] = (
                details["active"] if details["active"] in profiles else None
            )
            st.session_state["codex_account_snapshot"] = snapshot
        selected = st.selectbox(
            tr("codex.oauth.account"),
            list(profiles),
            index=None,
            format_func=profiles.get,
            key="codex_account_picker",
            disabled=bool(flow),
        )
        if selected and selected != details["active"]:
            codex_oauth.select_account(selected)
            st.session_state["codex_account_actions_open"] = False
            st.rerun()
    if details["connected"]:
        st.link_button(
            tr("codex.oauth.manage_usage"),
            codex_oauth.USAGE_URL,
            type="tertiary",
            icon=":material/open_in_new:",
        )
    if profiles and st.button(
        tr("codex.oauth.add_account"),
        key="codex_add_account",
        type="tertiary",
        icon=":material/person_add:",
        disabled=bool(flow),
    ):
        st.session_state[FLOW_KEY] = codex_oauth.begin_login(new_account=True)
        st.session_state["codex_account_actions_open"] = False
        st.rerun()
    if details["connected"] and st.button(
        tr("codex.oauth.disconnect"),
        key="codex_disconnect",
        type="tertiary",
        icon=":material/logout:",
    ):
        if flow:
            codex_oauth.cancel_login(flow)
        with st.spinner(tr("codex.oauth.disconnect") + "…"):
            confirmed = codex_oauth.disconnect()
        st.session_state.pop(FLOW_KEY, None)
        st.session_state["codex_revocation_unconfirmed"] = not confirmed
        st.session_state["codex_account_actions_open"] = False
        st.rerun()


def _render_login_controls(tr):
    try:
        flow = st.session_state.get(FLOW_KEY)
        if flow:
            try:
                if codex_oauth.poll_login(flow):
                    st.session_state.pop(FLOW_KEY, None)
                    st.rerun()
            except codex_oauth.CodexError as error:
                st.session_state.pop(FLOW_KEY, None)
                st.error(tr(error.key).format(**error.params))
                flow = None
        details = codex_oauth.account_details()
        profiles = dict(details["profiles"])
        if details["connected"] or profiles:
            summary, actions = st.columns([1, 0.16], vertical_alignment="center")
            with summary:
                st.caption(tr("codex.oauth.account"))
                st.text(details["email"] or profiles.get(details["active"], "ChatGPT"))
                if details["authorized"]:
                    st.caption(":green[●] " + tr("codex.oauth.connected"))
            # Keep controls in the dialog's DOM tree. A portalled popover
            # inside st.dialog can look clickable while the modal treats it as inert.
            if actions.button(
                "⋯",
                help=tr("codex.oauth.account"),
                type="tertiary",
                key="codex_account_actions_toggle",
            ):
                st.session_state[
                    "codex_account_actions_open"
                ] = not st.session_state.get("codex_account_actions_open", False)
            if st.session_state.get("codex_account_actions_open", False):
                with st.container(border=True, key="codex_account_actions"):
                    _render_account_actions(tr, details, profiles, flow)
        if details["legacy"]:
            st.info(tr("codex.oauth.legacy"))
        if details["connected"] and not details["authorized"]:
            st.info(tr("codex.oauth.plan_required"))
        if st.session_state.get("codex_revocation_unconfirmed"):
            st.warning(tr("codex.oauth.revocation_unconfirmed"))
        if flow:
            st.caption(tr("codex.oauth.pending"))
            with st.container(horizontal=True, vertical_alignment="center"):
                st.link_button(
                    tr("codex.oauth.open"), flow["authorize_url"], type="primary"
                )
                if st.button(tr("Cancel"), key="codex_cancel", type="tertiary"):
                    codex_oauth.cancel_login(flow)
                    st.session_state.pop(FLOW_KEY, None)
                    st.rerun()
        else:
            if not details["authorized"] and st.button(
                tr("codex.oauth.login"), key="codex_login", type="primary"
            ):
                st.session_state[FLOW_KEY] = codex_oauth.begin_login(
                    enable_plan=details["connected"]
                )
                st.rerun()
    except codex_oauth.CodexError as error:
        st.error(tr(error.key).format(**error.params))
