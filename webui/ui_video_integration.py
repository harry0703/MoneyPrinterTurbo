import os
import streamlit as st
from loguru import logger
from app.services.video import scan_task_files, recover_video_synthesis
from app.utils import utils


def render_video_integration_panel(tr):
    """
    Render video integration panel for recovering video integration from existing task files.
    
    Args:
        tr: Translation function
    """
    with st.container(border=True):
        st.write(f"🎬 {tr('Video Integration')}")
        
        # Task ID or directory selection
        input_type = st.radio(
            tr("Input Type"),
            [tr("Task ID"), tr("Task Directory")],
            key="input_type"
        )
        
        if input_type == tr("Task ID"):
            task_input = st.text_input(
                tr("Task ID"),
                placeholder=tr("Enter task ID to recover integration"),
                key="integration_task_id"
            )
        else:
            task_input = st.text_input(
                tr("Task Directory"),
                placeholder=tr("Enter task directory path"),
                key="integration_task_dir"
            )
            st.info(tr("Please enter the full path to the task directory"))
        
        # Scan button
        scan_col, _ = st.columns([1, 3])
        with scan_col:
            scan_clicked = st.button(tr("Scan"), key="scan_task_btn")
        
        # Scan task directory when button clicked
        if scan_clicked and task_input:
            with st.spinner(tr("Scanning task directory...")):
                task_files = scan_task_files(task_input)
                st.session_state["task_files"] = task_files
                st.session_state["current_task_input"] = task_input
        
        # Display scan results
        if "task_files" in st.session_state:
            task_files = st.session_state["task_files"]
            
            if not task_files["is_valid"]:
                st.error(tr("No valid scene videos found in task directory"))
            else:
                # Display detected files
                st.write(f"**{tr('Detected Files')}:**")
                
                # Scene videos status
                valid_scenes = [s for s in task_files["scene_videos"] if s["video"] is not None]
                st.success(f"✅ {tr('Scene Videos')}: {len(valid_scenes)} {tr('scenes')}")
                
                # Audio file status
                if task_files["global_audio"]:
                    st.success(f"✅ {tr('Audio File')}: 1")
                elif valid_scenes and valid_scenes[0]["audio"]:
                    st.info(f"ℹ️ {tr('Audio File')}: {tr('Will use first scene audio')}")
                else:
                    st.warning(f"⚠️ {tr('Audio File')}: {tr('Not found')}")
                
                # Subtitle file status
                if task_files["global_subtitle"]:
                    st.success(f"✅ {tr('Subtitle File')}: 1")
                else:
                    # Check if there are scene subtitles
                    scene_subtitles = []
                    for scene in task_files["scene_videos"]:
                        if scene.get("subtitle") and os.path.exists(scene.get("subtitle")):
                            scene_subtitles.append(scene.get("subtitle"))
                    
                    if scene_subtitles:
                        st.info(f"ℹ️ {tr('Subtitle File')}: {tr('Will generate global subtitle from scene subtitles')}")
                    else:
                        st.warning(f"⚠️ {tr('Subtitle File')}: {tr('Not found, will proceed without subtitles')}")
                
                # Start integration button
                st.divider()
                start_col, progress_col = st.columns([1, 3])
                
                with start_col:
                    start_clicked = st.button(
                        tr("Start Integration"),
                        key="start_integration_btn",
                        type="primary",
                        disabled=st.session_state.get("integration_running", False)
                    )
                
                # Progress display
                with progress_col:
                    if st.session_state.get("integration_running"):
                        progress = st.session_state.get("integration_progress", 0)
                        status = st.session_state.get("integration_status", "")
                        st.progress(progress / 100, text=f"{progress}% - {status}")
                
                # Start integration when button clicked
                if start_clicked and task_files["is_valid"]:
                    st.session_state["integration_running"] = True
                    st.session_state["integration_progress"] = 0
                    st.session_state["integration_status"] = tr("Starting...")
                    
                    def progress_callback(progress, status):
                        st.session_state["integration_progress"] = progress
                        st.session_state["integration_status"] = status
                    
                    try:
                        with st.spinner(tr("Processing video integration...")):
                            current_task_input = st.session_state.get("current_task_input", task_input)
                            output_path = recover_video_synthesis(
                                current_task_input,
                                progress_callback=progress_callback
                            )
                            
                            if output_path and os.path.exists(output_path):
                                st.session_state["integration_result"] = output_path
                                st.success(f"{tr('Video integration completed')}: {output_path}")
                            else:
                                st.error(tr("Video integration failed"))
                                
                    except Exception as e:
                        logger.error(f"Video integration failed: {e}")
                        st.error(f"{tr('Video integration failed')}: {str(e)}")
                    finally:
                        st.session_state["integration_running"] = False
                
                # Display result if available
                if st.session_state.get("integration_result"):
                    result_path = st.session_state["integration_result"]
                    if os.path.exists(result_path):
                        st.divider()
                        st.write(f"**{tr('Generated Video')}:**")
                        st.video(result_path)
                        
                        # Download button
                        with open(result_path, "rb") as file:
                            st.download_button(
                                label=tr("Download Video"),
                                data=file,
                                file_name=os.path.basename(result_path),
                                mime="video/mp4"
                            )
