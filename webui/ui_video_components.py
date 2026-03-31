import streamlit as st
import os
import uuid
from app.models.schema import VideoParams, VideoConcatMode, VideoTransitionMode, VideoAspect
from app.utils.utils import storage_dir
import logging

logger = logging.getLogger(__name__)

def render_video_settings(params, config, uploaded_files, tr):
    """
    渲染视频设置组件
    """
    with st.container(border=True):
        st.write(tr("Video Settings"))
        video_concat_modes = [
            (tr("Sequential"), "sequential"),
            (tr("Random"), "random"),
        ]
        video_sources = [
            (tr("Pexels"), "pexels"),
            (tr("Pixabay"), "pixabay"),
            (tr("Local file"), "local"),
            (tr("TikTok"), "douyin"),
            (tr("Bilibili"), "bilibili"),
            (tr("Xiaohongshu"), "xiaohongshu"),
        ]

        saved_video_source_name = config.app.get("video_source", "pexels")
        saved_video_source_index = [v[1] for v in video_sources].index(
            saved_video_source_name
        )

        selected_index = st.selectbox(
            tr("Video Source"),
            options=range(len(video_sources)),
            format_func=lambda x: video_sources[x][0],
            index=saved_video_source_index,
        )
        params.video_source = video_sources[selected_index][1]
        config.app["video_source"] = params.video_source

        if params.video_source == "local":
            # 显示已上传的文件信息
            if st.session_state.get("uploaded_file_info"):
                st.info(f"已上传 {len(st.session_state['uploaded_file_info'])} 个文件")
                for file_info in st.session_state["uploaded_file_info"]:
                    st.text(f"📄 {file_info['name']}")
            
            uploaded_files = st.file_uploader(
                tr("Upload Local Files"),
                type=["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"],
                accept_multiple_files=True,
            )
            # 存储到 session state
            if uploaded_files is not None:
                # 立即保存文件到本地目录
                local_videos_dir = storage_dir("local_videos", create=True)
                saved_files = []
                file_info_list = []
                for file in uploaded_files:
                    try:
                        unique_id = str(uuid.uuid4())
                        file_path = os.path.join(local_videos_dir, f"{unique_id}_{file.name}")
                        with open(file_path, "wb") as f:
                            f.write(file.getbuffer())
                        saved_files.append(file_path)
                        file_info_list.append({
                            'name': file.name,
                            'type': file.type,
                            'size': file.size,
                            'path': file_path
                        })
                        logger.info(f"Uploaded file saved to: {file_path}")
                    except Exception as e:
                        logger.error(f"Failed to save uploaded file {file.name}: {str(e)}")
                        st.error(f"Failed to save file {file.name}: {str(e)}")
                
                if saved_files:
                    st.session_state["uploaded_files"] = saved_files
                    st.session_state["uploaded_file_info"] = file_info_list
                    st.success(f"Successfully uploaded {len(saved_files)} files")
        else:
            # 从 session state 获取已上传的文件
            uploaded_files = st.session_state.get("uploaded_files", [])

        selected_index = st.selectbox(
            tr("Video Concat Mode"),
            index=1,
            options=range(
                len(video_concat_modes)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_concat_modes[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_concat_mode = VideoConcatMode(
            video_concat_modes[selected_index][1]
        )

        # 视频转场模式
        video_transition_modes = [
            (tr("None"), VideoTransitionMode.none.value),
            (tr("Shuffle"), VideoTransitionMode.shuffle.value),
            (tr("FadeIn"), VideoTransitionMode.fade_in.value),
            (tr("FadeOut"), VideoTransitionMode.fade_out.value),
            (tr("SlideIn"), VideoTransitionMode.slide_in.value),
            (tr("SlideOut"), VideoTransitionMode.slide_out.value),
        ]
        selected_index = st.selectbox(
            tr("Video Transition Mode"),
            options=range(len(video_transition_modes)),
            format_func=lambda x: video_transition_modes[x][0],
            index=0,
        )
        params.video_transition_mode = VideoTransitionMode(
            video_transition_modes[selected_index][1]
        )

        video_aspect_ratios = [
            (tr("Portrait"), VideoAspect.portrait.value),
            (tr("Landscape"), VideoAspect.landscape.value),
            (tr("Square"), VideoAspect.square.value),
            (tr("3:4 Portrait"), VideoAspect.portrait_3_4.value),
        ]
        selected_index = st.selectbox(
            tr("Video Ratio"),
            options=range(
                len(video_aspect_ratios)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_aspect_ratios[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_aspect = VideoAspect(video_aspect_ratios[selected_index][1])

        params.video_clip_duration = st.selectbox(
            tr("Clip Duration"), options=[2, 3, 4, 5, 6, 7, 8, 9, 10], index=1
        )
        params.video_count = st.selectbox(
            tr("Number of Videos Generated Simultaneously"),
            options=[1, 2, 3, 4, 5],
            index=0,
        )
    return uploaded_files
