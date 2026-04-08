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
    
    # Initialize scenes in session state
    if "scenes" not in st.session_state:
        st.session_state["scenes"] = []

    logger.info(f"Rendering multi-scene management, total scenes: {len(st.session_state['scenes'])}")

    # Initialize auto-parse settings
    if "auto_parse_mode" not in st.session_state:
        st.session_state["auto_parse_mode"] = "auto"  # "auto" or "manual"

    # Initialize selected scenes
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
                                    if "intro_video" not in scene:
                                        scene["intro_video"] = ""
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
                    header_cols = st.columns([2, 1.2, 1.2, 1.2])
                    with header_cols[0]:
                        st.subheader(f"{tr('Scene')} {i+1}")
                    with header_cols[1]:
                        if st.button(tr("Delete"), key=f"delete_scene_{scene['id']}", use_container_width=True):
                            st.session_state["scenes"].pop(i)
                            st.rerun()
                    with header_cols[2]:
                        if i > 0 and st.button(tr("Move Up"), key=f"up_{scene['id']}", use_container_width=True):
                            st.session_state["scenes"][i], st.session_state["scenes"][i-1] = st.session_state["scenes"][i-1], st.session_state["scenes"][i]
                            st.rerun()
                    with header_cols[3]:
                        if i < len(st.session_state["scenes"])-1 and st.button(tr("Move Down"), key=f"down_{scene['id']}", use_container_width=True):
                            st.session_state["scenes"][i], st.session_state["scenes"][i+1] = st.session_state["scenes"][i+1], st.session_state["scenes"][i]
                            st.rerun()
                    
                    # Scene duration - custom layout with label, input and button on same row
                    # Create horizontal layout with simple columns including vertical divider
                    col1, col2, divider, col3, col4, col5 = st.columns([1.3, 1.5, 0.1, 1, 1.5, 0.5], gap="small")
                    
                    # Duration label (left-aligned)
                    with col1:
                        st.markdown(f"<div style='margin-top: 8px;'>{tr('~Duration(s)')}:</div>", unsafe_allow_html=True)
                    
                    # Duration value (left-aligned)
                    with col2:
                        # Use text to display duration, add border and background for better appearance
                        st.markdown(f"<div style='border: 1px solid #e0e0e0; border-radius: 4px; padding: 6px 10px; background-color: #f8f9fa; text-align: center;'>{scene['duration']}</div>", unsafe_allow_html=True)

                    # Vertical divider
                    with divider:
                        st.markdown('<div style="width: 1px; height: 30px; background-color: #e0e0e0; margin: 5px 0;"></div>', unsafe_allow_html=True)

                    # Intro video button
                    with col3:
                        # Button style: highlight when video exists
                        button_kwargs = {}
                        if scene.get("intro_video"):
                            button_kwargs["type"] = "primary"

                        if st.button("🎬", key=f"intro_video_btn_{scene['id']}", **button_kwargs):
                            # Show file uploader
                            if f"show_uploader_{scene['id']}" not in st.session_state:
                                st.session_state[f"show_uploader_{scene['id']}"] = True
                            else:
                                st.session_state[f"show_uploader_{scene['id']}"] = not st.session_state[f"show_uploader_{scene['id']}"]
                            st.rerun()

                    # Intro duration input
                    with col4:
                        # Intro video duration setting, using number input
                        if "intro_duration" not in scene:
                            scene["intro_duration"] = 10
                        scene["intro_duration"] = st.number_input(
                            "",
                            min_value=1, max_value=60, value=scene["intro_duration"],
                            key=f"intro_duration_{scene['id']}",
                            label_visibility="collapsed"
                        )

                    # Unit "s"
                    with col5:
                        # Display unit "s"
                        st.markdown(f"<div style='margin-top: 8px;'>s</div>", unsafe_allow_html=True)

                    # Show file uploader (if triggered)
                    if f"show_uploader_{scene['id']}" in st.session_state and st.session_state[f"show_uploader_{scene['id']}"]:
                        uploaded_file = st.file_uploader(
                            "Select intro video or image",
                            type=["mp4", "avi", "mov", "wmv", "jpg", "jpeg", "png", "bmp"],
                            key=f"uploader_{scene['id']}"
                        )
                        
                        if uploaded_file is not None:
                            # Save file to intro_video directory
                            import os
                            import shutil
                            from app.utils import utils
                            
                            # Create intro_video directory in storage
                            intro_video_dir = os.path.join(utils.storage_dir(), "intro_video")
                            os.makedirs(intro_video_dir, exist_ok=True)
                            
                            # Create scene-specific subdirectory
                            scene_intro_dir = os.path.join(intro_video_dir, f"scene_{scene['id']}")
                            os.makedirs(scene_intro_dir, exist_ok=True)
                            
                            # Save original file
                            file_path = os.path.join(scene_intro_dir, uploaded_file.name)
                            with open(file_path, "wb") as f:
                                f.write(uploaded_file.getvalue())
                            
                            # Check file type, convert image to video if needed
                            import subprocess
                            
                            video_path = file_path
                            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
                            if file_ext in [".jpg", ".jpeg", ".png", ".bmp"]:
                                # Image to video (5 seconds)
                                video_path = os.path.join(scene_intro_dir, f"{os.path.splitext(uploaded_file.name)[0]}.mp4")
                                try:
                                    # Use ffmpeg to convert image to 5-second video
                                    subprocess.run([
                                        "ffmpeg", "-loop", "1", "-i", file_path, 
                                        "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", 
                                        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=blue",
                                        "-y", video_path
                                    ], check=True, capture_output=True)
                                    st.success("Image converted to 5-second video")
                                except Exception as e:
                                    st.error(f"Conversion failed: {str(e)}")
                                    # Hide uploader
                                    del st.session_state[f"show_uploader_{scene['id']}"]
                                    st.rerun()
                            
                            # Update scene data
                            scene["intro_video"] = video_path
                            # Hide uploader
                            del st.session_state[f"show_uploader_{scene['id']}"]
                            st.success("Intro video added")
                            st.rerun()

                    # Display video path (if exists)
                    if scene.get("intro_video"):
                        # Use st.columns to maintain horizontal layout, only adjust vertical alignment
                        col_path, col_clear = st.columns([4, 1])
                        with col_path:
                            st.text_input(
                                "",
                                value=scene["intro_video"],
                                disabled=True,
                                key=f"intro_video_path_{scene['id']}"
                            )
                        with col_clear:
                            # Adjust button vertical alignment
                            st.markdown('<div style="display: flex; align-items: center; height: 100%;">', unsafe_allow_html=True)
                            if st.button(tr("Clear"), key=f"clear_intro_video_{scene['id']}"):
                                scene["intro_video"] = ""
                                st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
                    

                    
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
                "duration": 5,
                "intro_video": ""
            }
            st.session_state["scenes"].append(new_scene)
            st.rerun()
