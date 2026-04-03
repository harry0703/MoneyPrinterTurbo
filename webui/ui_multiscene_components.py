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
        .stContainer + .stContainer {
            margin-top: -35px !important;
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
        # Use st.write with custom CSS to reduce spacing
        st.write(tr("Scenes Management"))
        # Add CSS to reduce spacing after the title and between title and buttons
        st.markdown('''
        <style>
            /* Target the specific container for scenes management */
            .stContainer:has(> div > div > div[data-testid="stWrite"]) > div > div {
                margin-bottom: -30px !important;
            }
            /* Target the columns containing import/export buttons */
            .stContainer:has(> div > div > div[data-testid="stWrite"]) > div > div + div {
                margin-top: -20px !important;
            }
        </style>
        ''', unsafe_allow_html=True)
        # Set default parse mode to auto
        st.session_state["auto_parse_mode"] = "auto"
        parse_mode = "auto"
        
        # Clear any pending scenes and evaluation to avoid review interface
        if "pending_scenes" in st.session_state:
            del st.session_state["pending_scenes"]
        if "pending_evaluation" in st.session_state:
            del st.session_state["pending_evaluation"]
        
        # Simple import/export buttons
        # Removed margin to minimize spacing
        
        # Create a horizontal layout for two simple buttons
        col1, col2 = st.columns(2, gap="small")
        
        with col1:
            # Simple export button - disabled when no scenes
            if st.button(tr("Export Scenes"), use_container_width=True, disabled=len(st.session_state["scenes"]) == 0):
                import json
                
                # Convert to JSON
                scenes_json = json.dumps(st.session_state["scenes"], ensure_ascii=False, indent=2)
                
                # Create download button
                st.download_button(
                    label=tr("Download scenes.json"),
                    data=scenes_json,
                    file_name="scenes.json",
                    mime="application/json"
                )

        with col2:
            # Simple import button that triggers file upload
            import json
            from io import StringIO
            
            # Create a button that will trigger file upload
            if st.button(tr("Import Scenes"), use_container_width=True):
                # Use a hidden file uploader that appears when button is clicked
                # We'll use session state to control visibility
                if "show_import_uploader" not in st.session_state:
                    st.session_state["show_import_uploader"] = True
                else:
                    st.session_state["show_import_uploader"] = not st.session_state["show_import_uploader"]
                
                # Force a rerun to show the uploader
                st.rerun()
            
            # Show file uploader if triggered
            if "show_import_uploader" in st.session_state and st.session_state["show_import_uploader"]:
                uploaded_file = st.file_uploader(
                    tr("Choose JSON file"),
                    type=["json"],
                    key="import_scenes_uploader"
                )
                
                if uploaded_file is not None:
                    try:
                        # Read and parse JSON file
                        stringio = StringIO(uploaded_file.getvalue().decode("utf-8"))
                        scenes_data = json.load(stringio)
                        
                        # Validate data format
                        if isinstance(scenes_data, list):
                            # Check each scene for required fields
                            valid_scenes = []
                            for scene in scenes_data:
                                if isinstance(scene, dict) and "id" in scene:
                                    # Ensure all required fields exist
                                    if "duration" not in scene:
                                        scene["duration"] = 5
                                    if "visual_requirement" not in scene:
                                        scene["visual_requirement"] = ""
                                    if "keywords" not in scene:
                                        scene["keywords"] = ""
                                    if "script" not in scene:
                                        scene["script"] = ""
                                    valid_scenes.append(scene)
                            
                            # Update session state
                            st.session_state["scenes"] = valid_scenes
                            st.success(tr(f"Successfully imported {len(valid_scenes)} scenes"))
                            # Hide the uploader after successful import
                            st.session_state["show_import_uploader"] = False
                            st.rerun()
                        else:
                            st.error(tr("Invalid scenes data format"))
                    except json.JSONDecodeError:
                        st.error(tr("Invalid JSON file"))
                    except Exception as e:
                        st.error(tr(f"Error importing scenes: {str(e)}"))


        # Display placeholder if no scenes
        if len(st.session_state["scenes"]) == 0:
            st.markdown('''
            <div style="display: flex; align-items: center; justify-content: center; height: 120px; background-color: #f8f9fa; border-radius: 8px; border: 1px dashed #dee2e6; margin: 10px 0;">
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
                            "Duration",
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
                        tr("Scene Lines"),
                        value=scene["script"],
                        height=90,  # Default height 90px
                        key=f"script_{scene['id']}"
                    )


        # Add new scene button at the bottom with reduced spacing
        st.markdown('<div style="margin-top: 10px;"></div>', unsafe_allow_html=True)
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
