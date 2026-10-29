"""Account-specific model selector; a saved choice does not imply access."""

import streamlit as st

from app.services import chatgpt_models, chatgpt_oauth


def render_chatgpt_model_selector(current_model, tr):
    try:
        if not chatgpt_oauth.account_status():
            st.caption(tr("chatgpt.oauth.not_connected"))
            return current_model
        field, action = st.columns([1, 0.13], vertical_alignment="bottom")
        refresh = action.button(
            "↻", help=tr("chatgpt.models.refresh"), key="chatgpt_models_refresh"
        )
        catalog = chatgpt_models.get_catalog(force_refresh=refresh)
    except chatgpt_oauth.ChatGPTError as error:
        st.warning(tr(error.key).format(**error.params))
        return current_model
    except chatgpt_models.CatalogError:
        st.warning(tr("chatgpt.models.failed"))
        return current_model
    names = [model.name for model in catalog.models]
    choices = {
        model.id: model.name
        if names.count(model.name) == 1
        else f"{model.name} ({model.id})"
        for model in catalog.models
    }
    if current_model and current_model not in choices:
        st.warning(tr("chatgpt.models.saved"))
    if (
        st.session_state.get("chatgpt_model_config_snapshot") != current_model
        or st.session_state.get("openai_chatgpt_model_name_select") not in choices
    ):
        st.session_state["openai_chatgpt_model_name_select"] = (
            current_model if current_model in choices else None
        )
    selected = field.selectbox(
        tr("Model Name"),
        list(choices),
        index=None,
        format_func=choices.get,
        key="openai_chatgpt_model_name_select",
        placeholder=tr("chatgpt.models.choose"),
        disabled=not choices,
    )
    st.caption(tr("chatgpt.models.source"))
    result = selected or current_model
    st.session_state["chatgpt_model_config_snapshot"] = result
    return result
