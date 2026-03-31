import streamlit as st
from uuid import uuid4
from app.services.scene_parser import format_evaluation_result

def render_multiscene_management(tr):
    # 初始化scenes in session state
    if "scenes" not in st.session_state:
        st.session_state["scenes"] = []
    
    # 初始化auto-parse settings
    if "auto_parse_mode" not in st.session_state:
        st.session_state["auto_parse_mode"] = "auto"  # "auto" or "manual"
    
    # Create a container with border for visible border
    with st.container(border=True):
        st.write(tr("Scenes Management"))
        # Set default parse mode to auto
        st.session_state["auto_parse_mode"] = "auto"
        parse_mode = "auto"
        
        # Display pending scenes for manual confirmation
        if "pending_scenes" in st.session_state and "pending_evaluation" in st.session_state:
            st.subheader(tr("Parsed Scenes Review"))
            
            # Show evaluation
            evaluation_data = format_evaluation_result(st.session_state["pending_evaluation"])
            
            # Get status text
            status_text_map = {
                "excellent": tr("Excellent"),
                "good": tr("Good"),
                "fair": tr("Fair"),
                "poor": tr("Poor")
            }
            status_text = status_text_map.get(evaluation_data["status"], tr("Unknown"))
            
            # Format evaluation result with i18n
            evaluation_text = f"{evaluation_data['icon']} {tr('Smart Recognition Evaluation')}: {status_text} ({evaluation_data['total_score']:.0f} points)\n\n"
            
            # Individual scores - new evaluation dimensions
            evaluation_text += f"{tr('Detailed Scores')}:\n"
            evaluation_text += f"- {tr('Time Marker Completeness')}: {'✅' if evaluation_data['individual_scores'].get('time_marker_completeness', 0) >= 80 else '⚠️'} {evaluation_data['individual_scores'].get('time_marker_completeness', 0):.0f} {tr('points')}\n"
            evaluation_text += f"- {tr('Time Continuity')}: {'✅' if evaluation_data['individual_scores'].get('time_continuity', 0) >= 80 else '⚠️'} {evaluation_data['individual_scores'].get('time_continuity', 0):.0f} {tr('points')}\n"
            evaluation_text += f"- {tr('Visual Completeness')}: {'✅' if evaluation_data['individual_scores'].get('visual_completeness', 0) >= 80 else '⚠️'} {evaluation_data['individual_scores'].get('visual_completeness', 0):.0f} {tr('points')}\n"
            evaluation_text += f"- {tr('Script Duration Match')}: {'✅' if evaluation_data['individual_scores'].get('script_duration_match', 0) >= 80 else '⚠️'} {evaluation_data['individual_scores'].get('script_duration_match', 0):.0f} {tr('points')}\n"
            evaluation_text += f"- {tr('Scene Structure Completeness')}: {'✅' if evaluation_data['individual_scores'].get('scene_structure_completeness', 0) >= 80 else '⚠️'} {evaluation_data['individual_scores'].get('scene_structure_completeness', 0):.0f} {tr('points')}\n\n"
            
            # Issues
            if evaluation_data.get('issues'):
                evaluation_text += f"{tr('Suggestions for Improvement')}:\n"
                for issue in evaluation_data['issues']:
                    # Translate issue based on type
                    if isinstance(issue, dict):
                        issue_type = issue.get('type')
                        params = issue.get('params', {})
                        
                        if issue_type == 'time_marker_incomplete':
                            evaluation_text += f"- {tr('Time marker incomplete')}: {params.get('count')}/{params.get('total')} {tr('scenes have time markers')}\n"
                        elif issue_type == 'time_gap':
                            evaluation_text += f"- {tr('Time gap detected')}: {tr('Scene')} {params.get('scene')} {tr('gap')} {params.get('gap')} {tr('seconds between scenes')}\n"
                        elif issue_type == 'time_overlap':
                            evaluation_text += f"- {tr('Time overlap detected')}: {tr('Scene')} {params.get('scene')} {tr('overlap')} {params.get('overlap')} {tr('seconds overlap')}\n"
                        elif issue_type == 'total_duration_short':
                            evaluation_text += f"- {tr('Total duration too short')}: {tr('Total duration')} {params.get('duration')}s, {tr('recommended minimum')} 30s\n"
                        elif issue_type == 'total_duration_long':
                            evaluation_text += f"- {tr('Total duration too long')}: {tr('Total duration')} {params.get('duration')}s, {tr('recommended maximum')} 300s\n"
                        elif issue_type == 'visual_incomplete':
                            evaluation_text += f"- {tr('Visual incomplete')}: {params.get('count')}/{params.get('total')} {tr('scenes have visual requirements')}\n"
                        elif issue_type == 'script_too_short':
                            evaluation_text += f"- {tr('Script too short')}: {tr('actual')} {params.get('actual')} {tr('characters')}, {tr('expected')} {params.get('expected')} {tr('characters')}\n"
                        elif issue_type == 'script_too_long':
                            evaluation_text += f"- {tr('Script too long')}: {tr('actual')} {params.get('actual')} {tr('characters')}, {tr('expected')} {params.get('expected')} {tr('characters')}\n"
                        elif issue_type == 'structure_incomplete':
                            evaluation_text += f"- {tr('Structure incomplete')}: {params.get('count')}/{params.get('total')} {tr('scenes have complete structure')}\n"
                        else:
                            evaluation_text += f"- {str(issue)}\n"
                    else:
                        evaluation_text += f"- {issue}\n"
            
            st.markdown(evaluation_text)
            
            # Preview scenes
            with st.expander(tr("Preview Parsed Scenes")):
                for i, scene in enumerate(st.session_state["pending_scenes"]):
                    st.write(f"**{tr('Scene')} {i+1}** ({scene['duration']}s)")
                    st.write(f"{tr('Script')}: {scene['script'][:100]}...")
            
            # Action buttons
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(tr("Use These Scenes"), key="use_parsed_scenes"):
                    st.session_state["scenes"] = st.session_state["pending_scenes"]
                    del st.session_state["pending_scenes"]
                    del st.session_state["pending_evaluation"]
                    st.success(tr("Scenes applied successfully!"))
                    st.rerun()
            with col2:
                if st.button(tr("Re-parse"), key="reparse_scenes"):
                    del st.session_state["pending_scenes"]
                    del st.session_state["pending_evaluation"]
                    st.rerun()
            with col3:
                if st.button(tr("Cancel"), key="cancel_parsed_scenes"):
                    del st.session_state["pending_scenes"]
                    del st.session_state["pending_evaluation"]
                    st.rerun()
        
        # Add new scene button
        if st.button(tr("Add New Scene")):
            new_scene = {
                "id": str(uuid4()),
                "script": "",
                "visual_requirement": "",
                "keywords": "",
                "duration": 5
            }
            st.session_state["scenes"].append(new_scene)
            st.rerun()
            
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
                with st.container(border=True):
                    scene_header, scene_actions = st.columns([3, 1])
                    with scene_header:
                        st.subheader(f"{tr('Scene')} {i+1}")
                    with scene_actions:
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(tr("Delete"), key=f"delete_scene_{scene['id']}"):
                                st.session_state["scenes"].pop(i)
                                st.rerun()
                        with col2:
                            if st.button(tr("Copy"), key=f"copy_scene_{scene['id']}"):
                                copied_scene = scene.copy()
                                copied_scene["id"] = str(uuid4())
                                st.session_state["scenes"].append(copied_scene)
                                st.rerun()
                        
                        # Scene duration
                        scene["duration"] = st.number_input(
                            tr("Duration (seconds)"),
                            min_value=1, max_value=60, value=scene["duration"],
                            key=f"duration_{scene['id']}"
                        )
                        
                        # Visual requirement with tags support
                        st.write(tr("Visual Requirements"))
                        scene["visual_requirement"] = st.text_area(
                            tr("Detailed Description"),
                            value=scene["visual_requirement"],
                            height=100,
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
                            height=150,
                            key=f"script_{scene['id']}"
                        )
                        
                        # Scene order adjustment
                        order_cols = st.columns(3)
                        with order_cols[0]:
                            if i > 0 and st.button(tr("Move Up"), key=f"up_{scene['id']}"):
                                st.session_state["scenes"][i], st.session_state["scenes"][i-1] = st.session_state["scenes"][i-1], st.session_state["scenes"][i]
                                st.rerun()
                        with order_cols[2]:
                            if i < len(st.session_state["scenes"])-1 and st.button(tr("Move Down"), key=f"down_{scene['id']}"):
                                st.session_state["scenes"][i], st.session_state["scenes"][i+1] = st.session_state["scenes"][i+1], st.session_state["scenes"][i]
                                st.rerun()
        
        # Add spacing at the bottom of scene cards display area
        st.markdown('<br><br>', unsafe_allow_html=True)
