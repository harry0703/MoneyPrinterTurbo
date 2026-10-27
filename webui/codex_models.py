"""Account-specific model selector; a saved choice does not imply access."""

import streamlit as st

from app.services import codex_models, codex_oauth


def render_codex_model_selector(current_model, tr):
    try:
        if not codex_oauth.account_status():
            st.caption(tr("codex.oauth.not_connected"))
            return current_model
        field, action = st.columns([1, 0.13], vertical_alignment="bottom")
        refresh = action.button(
            "↻", help=tr("codex.models.refresh"), key="codex_models_refresh"
        )
        catalog = codex_models.get_catalog(force_refresh=refresh)
    except codex_oauth.CodexError as error:
        st.warning(tr(error.key).format(**error.params))
        return current_model
    except codex_models.CatalogError:
        st.warning(tr("codex.models.failed"))
        return current_model
    names = [model.name for model in catalog.models]
    choices = {
        model.id: model.name
        if names.count(model.name) == 1
        else f"{model.name} ({model.id})"
        for model in catalog.models
    }
    if current_model and current_model not in choices:
        st.warning(tr("codex.models.saved"))
    if (
        st.session_state.get("codex_model_config_snapshot") != current_model
        or st.session_state.get("openai_codex_model_name_select") not in choices
    ):
        st.session_state["openai_codex_model_name_select"] = (
            current_model if current_model in choices else None
        )
    selected = field.selectbox(
        tr("Model Name"),
        list(choices),
        index=None,
        format_func=choices.get,
        key="openai_codex_model_name_select",
        placeholder=tr("codex.models.choose"),
        disabled=not choices,
    )
    st.caption(tr("codex.models.source"))
    result = selected or current_model
    st.session_state["codex_model_config_snapshot"] = result
    return result
