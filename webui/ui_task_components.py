import streamlit as st


def render_task_status_panel(tr):
    """
    Render task status panel that displays background task status information.
    
    Args:
        tr: Translation function
    """
    from app.services.state import is_task_running, get_running_task_type
    
    with st.container(border=True):
        st.write(f"📋 {tr('Task Status')}")
        
        # Check if task is running
        if is_task_running():
            task_type = get_running_task_type()
            
            # Display running task status
            st.info(f"{tr('Task in progress')}: {tr('Video Integration') if task_type == 'video_integration' else tr('Complete Video')}")
            
            # Check if integration progress is available
            if st.session_state.get("integration_running"):
                progress = st.session_state.get("integration_progress", 0)
                status = st.session_state.get("integration_status", "")
                st.progress(progress / 100, text=f"{progress}% - {status}")
            else:
                # Generic progress indicator for other task types
                st.progress(0, text=tr("Processing..."))
        else:
            st.success(tr("No tasks running"))
        
        # Add refresh button for task status
        if st.button(tr("Refresh Status"), key="refresh_status_btn"):
            # Button click will trigger a rerun
            pass
