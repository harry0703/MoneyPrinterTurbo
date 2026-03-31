import streamlit as st
from uuid import uuid4
from app.services.scene_parser import format_evaluation_result

def render_multiscene_management(tr):
    """
    Render multi-scene management panel.
    
    Args:
        tr: Translation function
    """
    from loguru import logger
    
    # 初始化scenes in session state
    if "scenes" not in st.session_state:
        st.session_state["scenes"] = []
    
    logger.info(f"Rendering multi-scene management, total scenes: {len(st.session_state['scenes'])}")
    
    # 初始化auto-parse settings
    if "auto_parse_mode" not in st.session_state:
        st.session_state["auto_parse_mode"] = "auto"  # "auto" or "manual"
    
    # 初始化选中的场景
    if "selected_scenes" not in st.session_state:
        st.session_state["selected_scenes"] = []
    
    # Add custom CSS to reduce spacing
    st.markdown('''
    <style>
        /* Reduce spacing between markdown/text and textarea */
        .stMarkdown + .stTextArea {
            margin-top: -10px !important;
        }

        /* Reduce spacing between label and textarea */
        .stTextArea {
            margin-top: -10px !important;
        }

        /* Reduce spacing between label and text input */
        .stTextInput {
            margin-top: -10px !important;
        }

        /* Reduce spacing between script settings and scene management */
        .stContainer + div {
            margin-top: -20px !important;
        }

        /* Reduce spacing around buttons */
        .stButton > button {
            margin: 0 !important;
            padding: 4px 8px !important;
        }

        /* Reduce spacing between columns */
        .st-emotion-cache-1v0mbdj {
            padding-right: 2px !important;
            padding-left: 2px !important;
        }

        /* Reduce top spacing for scene card headers */
        [data-testid="stHorizontalBlock"]:has([data-testid="stSubheader"]) {
            margin-top: -15px !important;
        }

        /* Reduce bottom spacing for Add New Scene button */
        [data-testid="stHorizontalBlock"]:has(button) {
            margin-bottom: -15px !important;
        }

        /* Scene card container top padding */
        [data-testid="stHorizontalBlock"]:has(.stButton) {
            padding-top: 5px !important;
            padding-bottom: 5px !important;
        }

        /* Reduce scene ID font size */
        [data-testid="stHorizontalBlock"] h5 {
            font-size: 0.9rem !important;
            font-weight: 500 !important;
        }
    </style>
    ''', unsafe_allow_html=True)
    
    # Create a container with border for visible border
    with st.container(border=True):
        st.write(tr("Scenes Management"))
        # Set default parse mode to auto
        st.session_state["auto_parse_mode"] = "auto"
        parse_mode = "auto"
        
        # Clear any pending scenes and evaluation to avoid review interface
        if "pending_scenes" in st.session_state:
            del st.session_state["pending_scenes"]
        if "pending_evaluation" in st.session_state:
            del st.session_state["pending_evaluation"]
        

        
        # Display placeholder if no scenes
        if len(st.session_state["scenes"]) == 0:
            st.markdown('''
            <div style="display: flex; align-items: center; justify-content: center; height: 200px; background-color: #f8f9fa; border-radius: 8px; border: 1px dashed #dee2e6; margin: 20px 0;">
                <span style="color: #6c757d; font-size: 16px;">这里显示多场景文案</span>
            </div>
            ''', unsafe_allow_html=True)
        else:
            # Display scenes as cards
            for i, scene in enumerate(st.session_state["scenes"]):
                logger.info(f"Scene {i+1} - Rendering scene card: visual_requirement='{scene.get('visual_requirement', 'N/A')}', keywords='{scene.get('keywords', 'N/A')}'")
                with st.container(border=True):
                    # Card style with shadow
                    st.markdown('''
                    <style>
                        .scene-card {
                            border-radius: 8px;
                            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                            transition: box-shadow 0.3s ease;
                        }
                        .scene-card:hover {
                            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
                        }
                    </style>
                    ''', unsafe_allow_html=True)
                    
                    # Create header with scene number and action buttons
                    header_cols = st.columns([3, 0.8, 0.8, 0.8])
                    with header_cols[0]:
                        st.subheader(f"{tr('Scene')} {i+1}")
                    with header_cols[1]:
                        if st.button("删除", key=f"delete_scene_{scene['id']}", use_container_width=True):
                            st.session_state["scenes"].pop(i)
                            st.rerun()
                    with header_cols[2]:
                        if i > 0 and st.button("上移", key=f"up_{scene['id']}", use_container_width=True):
                            st.session_state["scenes"][i], st.session_state["scenes"][i-1] = st.session_state["scenes"][i-1], st.session_state["scenes"][i]
                            st.rerun()
                    with header_cols[3]:
                        if i < len(st.session_state["scenes"])-1 and st.button("下移", key=f"down_{scene['id']}", use_container_width=True):
                            st.session_state["scenes"][i], st.session_state["scenes"][i+1] = st.session_state["scenes"][i+1], st.session_state["scenes"][i]
                            st.rerun()
                    
                    # Scene duration - custom layout with label and input on same row
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        st.text(f"{tr('Duration (seconds)')}:")
                    with col2:
                        scene["duration"] = st.number_input(
                            "",
                            min_value=1, max_value=60, value=scene["duration"],
                            label_visibility="collapsed",
                            key=f"duration_{scene['id']}"
                        )
                    
                    # Visual requirement with tags support
                    scene["visual_requirement"] = st.text_area(
                        tr("Visual Requirements"),
                        value=scene["visual_requirement"],
                        height=68,  # Set minimum height as required by Streamlit
                        key=f"visual_{scene['id']}"
                    )
                    
                    # Keywords input
                    scene["keywords"] = st.text_input(
                        tr("Keywords (separated by commas)"),
                        value=scene["keywords"],
                        key=f"keywords_{scene['id']}"
                    )
                    
                    # Script input
                    scene["script"] = st.text_area(
                        tr("Scene Script"),
                        value=scene["script"],
                        height=90,  # Default height 90px
                        key=f"script_{scene['id']}"
                    )
                    

        # Add new scene button at the bottom
        if st.button(tr("Add New Scene"), use_container_width=True):
            new_scene = {
                "id": str(uuid4()),
                "script": "",
                "visual_requirement": "",
                "keywords": "",
                "duration": 5
            }
            st.session_state["scenes"].append(new_scene)
            st.rerun()
        
        # Add spacing at the bottom of scene cards display area
        st.markdown('<br><br>', unsafe_allow_html=True)
