"""Dynamic Codex model selector, preserving saved choices across catalog refreshes."""

import streamlit as st

from app.services import codex_models


def _notify_model_change(widget_key, on_change):
    if on_change is not None:
        on_change(str(st.session_state.get(widget_key) or "").strip())


def render_codex_model_selector(
    current_model, tr, *, prefix="openai_codex", on_change=None
):
    refresh_key = (
        "codex_models_refresh"
        if prefix == "openai_codex"
        else f"{prefix}_models_refresh"
    )
    refresh = st.button(tr("codex.models.refresh"), key=refresh_key)
    try:
        catalog = codex_models.get_catalog(force_refresh=refresh)
    except codex_models.CatalogError:
        st.warning(tr("codex.models.failed"))
        # A catalog outage must not erase or replace a previously selected model.
        return st.text_input(
            tr("Model Name"),
            value=current_model,
            key=f"{prefix}_model_name_input",
            on_change=_notify_model_change,
            args=(f"{prefix}_model_name_input", on_change),
        ).strip()
    if catalog.stale:
        st.caption(tr("codex.models.stale"))
    choices = {model.id: f"{model.name} ({model.id})" for model in catalog.models}
    if current_model and current_model not in choices:
        choices = {current_model: current_model, **choices}
        st.caption(tr("codex.models.saved"))
    options = list(choices)
    selected = st.selectbox(
        tr("Model Name"),
        options=options,
        index=options.index(current_model) if current_model in choices else None,
        format_func=choices.get,
        key=f"{prefix}_model_name_select",
        placeholder=tr("codex.models.choose"),
        on_change=_notify_model_change,
        args=(f"{prefix}_model_name_select", on_change),
    )
    st.caption(tr("codex.models.source"))
    return selected or ""
