import streamlit as st
from uuid import uuid4
from app.services.scene_parser import auto_parse_script
from webui.ui_multiscene_components import render_multiscene_management

def render_script_settings(params, tr, llm):
    # 初始化session state以保持文件上传状态
    if "uploaded_files" not in st.session_state:
        st.session_state["uploaded_files"] = []
    if "uploaded_file_info" not in st.session_state:
        st.session_state["uploaded_file_info"] = []
    
    # 初始化scenes in session state
    if "scenes" not in st.session_state:
        st.session_state["scenes"] = []
    
    # 初始化auto-parse settings
    if "auto_parse_mode" not in st.session_state:
        st.session_state["auto_parse_mode"] = "auto"  # "auto" or "manual"
    
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        st.session_state["video_subject"] = st.text_input(
            tr("Video Subject"),
            value=st.session_state.get("video_subject", ""),
            key="video_subject_input",
        ).strip()
        params.video_subject = st.session_state["video_subject"]

        video_languages = [
            (tr("Auto Detect"), ""),
        ]
        support_locales = [
            "zh-CN",
            "zh-HK",
            "zh-TW",
            "de-DE",
            "en-US",
            "fr-FR",
            "vi-VN",
            "th-TH",
            "tr-TR",
        ]
        for code in support_locales:
            video_languages.append((code, code))

        selected_index = st.selectbox(
            tr("Script Language"),
            index=0,
            options=range(
                len(video_languages)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_languages[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_language = video_languages[selected_index][1]

        # Always enable multi-scene mode
        # Map old "无场景模式" to a single scene in multi-scene architecture
        multi_scene_enabled = True
        st.session_state["multi_scene_enabled"] = multi_scene_enabled
        params.multi_scene_enabled = multi_scene_enabled

        if st.button(
            tr("Generate Video Script and Keywords"), key="auto_generate_script", use_container_width=True
        ):
            with st.spinner(tr("Generating Video Script")):
                script = llm.generate_script(
                    video_subject=params.video_subject, language=params.video_language
                )
                if "Error: " in script:
                    st.error(tr(script))
                else:
                    st.session_state["video_script"] = script

        params.video_script = st.text_area(
            tr("Video Script"), value=st.session_state.get("video_script", ""), height=280
        )
        if st.button(tr("Generate Video Keywords"), key="auto_generate_terms", use_container_width=True):
            if not params.video_script:
                st.error(tr("Please Enter the Video Subject"))
                st.stop()

            with st.spinner(tr("Generating Video Keywords")):
                terms = llm.generate_terms(params.video_subject, params.video_script)
                if "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_terms"] = ", ".join(terms)

        params.video_terms = st.text_area(
            tr("Video Keywords"), value=st.session_state.get("video_terms", ""),
            key="video_terms_single"
        )

        # Parse button - moved to the bottom of script settings panel
        if st.button(tr("Parse Current Script"), key="parse_script_btn", use_container_width=True):
            if not st.session_state.get("video_script", "").strip():
                st.warning(tr("Please enter a script first"))
            else:
                with st.spinner(tr("Parsing script...")):
                    # Set default parse mode to auto
                    parse_mode = "auto"
                    st.session_state["auto_parse_mode"] = parse_mode
                    
                    result = auto_parse_script(
                        st.session_state["video_script"],
                        max_retries=3,
                        auto_mode=(parse_mode == "auto")
                    )
                    
                    if result["status"] == "success":
                        # Auto-accepted
                        st.session_state["scenes"] = result["scenes"]
                        st.success(tr(f"Successfully parsed {len(result['scenes'])} scenes (Score: {result['evaluation']['total_score']:.0f})"))
                        st.rerun()
                    elif result["status"] == "manual":
                        # Need user confirmation
                        st.session_state["pending_scenes"] = result["scenes"]
                        st.session_state["pending_evaluation"] = result["evaluation"]
                        st.info(tr("Please review the parsed scenes below"))
                    else:
                        # Failed
                        st.error(tr(f"Parsing failed: {result.get('message', 'Unknown error')}"))

    # Scene management panel - moved outside the script settings container
    if multi_scene_enabled:
        render_multiscene_management(tr)
    
    return params
