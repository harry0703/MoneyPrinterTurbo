import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

import streamlit as st

# 添加项目根目录到路径
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.config import config
from app.models import const
from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
    MaterialInfo,
)
from app.services import llm, task as tm, voice
from app.utils import utils
from loguru import logger


# 页面配置
st.set_page_config(
    page_title="视频合成器",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 自定义CSS样式
st.markdown("""
<style>
/* 顶部标题栏 */
.top-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 0.75rem 1.5rem;
    margin-bottom: 1rem;
    border-radius: 12px;
    box-shadow: 0 4px 16px rgba(102, 126, 234, 0.15);
}

.top-header h1 {
    color: white;
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* Streamlit组件美化 */
.streamlit-expanderHeader {
    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%) !important;
    border-radius: 8px !important;
    padding: 0.75rem 1rem !important;
}

.streamlit-expanderContent {
    padding: 1rem !important;
}

.stTextInput > div > div > input {
    border-radius: 8px !important;
}

.stTextArea > div > div > textarea {
    border-radius: 8px !important;
}

.stSelectbox > div > div {
    border-radius: 8px !important;
}

.stSlider > div > div > div {
    border-radius: 8px !important;
}

.stButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.3s ease !important;
}

.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
}

.stFileUploader > div {
    border-radius: 8px !important;
}

.stColorPicker > div > div > div {
    border-radius: 8px !important;
}

/* 视频历史列表 */
.video-history-container {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 20px;
}

.video-history-item {
    width: 120px;
    height: 80px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
}

.video-history-item:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}

.video-history-item .play-icon {
    color: white;
    font-size: 24px;
    z-index: 2;
}

.video-history-item .video-index {
    position: absolute;
    top: 4px;
    left: 8px;
    color: white;
    font-size: 12px;
    font-weight: bold;
    background: rgba(0,0,0,0.5);
    padding: 2px 8px;
    border-radius: 4px;
}

/* 弹窗样式 */
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0,0,0,0.8);
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.modal-content {
    background: white;
    border-radius: 12px;
    padding: 20px;
    max-width: 800px;
    width: 90%;
    position: relative;
    animation: slideIn 0.3s ease;
}

@keyframes slideIn {
    from { transform: scale(0.9); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
}

.modal-close {
    position: absolute;
    top: 10px;
    right: 10px;
    background: none;
    border: none;
    font-size: 24px;
    cursor: pointer;
    color: #666;
    z-index: 10;
}

.modal-close:hover {
    color: #000;
}
</style>
""", unsafe_allow_html=True)


# Session State 初始化
if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "video_script_prompt" not in st.session_state:
    st.session_state["video_script_prompt"] = ""
if "custom_system_prompt" not in st.session_state:
    st.session_state["custom_system_prompt"] = llm.DEFAULT_SCRIPT_SYSTEM_PROMPT
if "use_custom_system_prompt" not in st.session_state:
    st.session_state["use_custom_system_prompt"] = False
if "show_floating_progress" not in st.session_state:
    st.session_state["show_floating_progress"] = False
if "show_log_overlay" not in st.session_state:
    st.session_state["show_log_overlay"] = False
if "generated_video_path" not in st.session_state:
    st.session_state["generated_video_path"] = None
if "current_task_id" not in st.session_state:
    st.session_state["current_task_id"] = None
if "log_records" not in st.session_state:
    st.session_state["log_records"] = []
if "video_history" not in st.session_state:
    st.session_state["video_history"] = []
# 用于跟踪配置变化，自动恢复预览状态
if "prev_config" not in st.session_state:
    st.session_state["prev_config"] = None


def get_all_fonts():
    fonts = []
    font_dir = os.path.join(root_dir, "resource", "fonts")
    if os.path.exists(font_dir):
        for root, dirs, files in os.walk(font_dir):
            for file in files:
                if file.endswith(".ttf") or file.endswith(".ttc"):
                    fonts.append(file)
    
    # 把中文字体排在前面
    chinese_fonts = []
    other_fonts = []
    for font in fonts:
        if any(keyword in font.lower() for keyword in ["yahei", "heiti", "microsoft", "sthei"]):
            chinese_fonts.append(font)
        else:
            other_fonts.append(font)
    
    # 排序
    chinese_fonts.sort()
    other_fonts.sort()
    
    return chinese_fonts + other_fonts


def get_all_songs():
    songs = []
    song_dir = os.path.join(root_dir, "resource", "songs")
    if os.path.exists(song_dir):
        for root, dirs, files in os.walk(song_dir):
            for file in files:
                if file.endswith(".mp3"):
                    songs.append(file)
        songs.sort()
    return songs


# 顶部标题栏
top_header_html = """
<div class="top-header">
    <h1>🎬 视频合成器 v1.2.9</h1>
</div>
"""
st.markdown(top_header_html, unsafe_allow_html=True)


# 使用Streamlit columns实现三栏布局，比例2:3:1
col1, col2, col3 = st.columns([2, 3, 1])

# 在开始读取配置之前，先收集所有的配置值用于比较
# 这些配置值会在后面读取，但我们需要提前捕获变化
# 我们将在读取完所有配置后再进行比较

# ==================== 左侧：配置选项 ====================
with col1:
    
    # 视频主题设置
    with st.expander("🎯 视频脚本设置", expanded=False):
        video_subject = st.text_input(
            "视频主题",
            value=st.session_state["video_subject"],
            placeholder="例如：超级伤感的感情文学"
        )
        st.session_state["video_subject"] = video_subject
        
        video_language = st.selectbox(
            "脚本语言",
            options=["", "zh-CN", "zh-HK", "zh-TW", "de-DE", "en-US", "fr-FR", "vi-VN", "th-TH", "tr-TR"],
            index=0,
            format_func=lambda x: "自动检测" if x == "" else x,
            help="选择视频脚本的语言"
        )
        
        st.markdown("---")
        st.markdown("**⚙️ 高级脚本设置**")
        
        video_script_prompt = st.text_area(
            "自定义视频脚本提示词",
            value=st.session_state["video_script_prompt"],
            placeholder="自定义提示词将用于指导生成视频脚本"
        )
        st.session_state["video_script_prompt"] = video_script_prompt
        
        use_custom_system_prompt = st.checkbox(
            "使用自定义系统提示词",
            value=st.session_state["use_custom_system_prompt"]
        )
        st.session_state["use_custom_system_prompt"] = use_custom_system_prompt
        
        if use_custom_system_prompt:
            custom_system_prompt = st.text_area(
                "自定义系统提示词",
                value=st.session_state["custom_system_prompt"],
                height=200
            )
            st.session_state["custom_system_prompt"] = custom_system_prompt
        
        if st.button("✨ 自动生成视频脚本和关键词", key="gen_script"):
            with st.spinner("正在生成视频脚本..."):
                try:
                    _video_script_prompt = st.session_state.get("video_script_prompt", "").strip()
                    _use_custom_system_prompt = st.session_state.get("use_custom_system_prompt", False)
                    _custom_system_prompt = st.session_state.get("custom_system_prompt", "").strip()
                    script = llm.generate_script(
                        video_subject,
                        video_language,
                        paragraph_number=1,
                        video_script_prompt=_video_script_prompt,
                        custom_system_prompt=_custom_system_prompt if _use_custom_system_prompt else ""
                    )
                    st.session_state["video_script"] = script
                    terms = llm.generate_terms(video_subject, script)
                    st.session_state["video_terms"] = terms
                    st.success("✅ 脚本和关键词生成成功！")
                except Exception as e:
                    st.error(f"生成失败：{e}")
        
        video_script = st.text_area(
            "视频脚本",
            value=st.session_state["video_script"],
            height=150,
            help="根据视频主题生成的脚本内容，也可以手动修改"
        )
        st.session_state["video_script"] = video_script
        
        if st.button("🔑 生成视频关键词", key="gen_terms"):
            with st.spinner("正在生成关键词..."):
                try:
                    terms = llm.generate_terms(video_subject, video_script)
                    st.session_state["video_terms"] = terms
                    st.success("✅ 关键词生成成功！")
                except Exception as e:
                    st.error(f"生成失败：{e}")
        
        video_terms = st.text_area(
            "视频关键词",
            value=st.session_state["video_terms"],
            help="用于搜索视频素材"
        )
        st.session_state["video_terms"] = video_terms
    
    # 视频设置
    with st.expander("🎥 视频设置", expanded=False):
        video_aspect = st.selectbox(
            "视频比例",
            options=[
                VideoAspect.portrait_9_16.value,
                VideoAspect.landscape_16_9.value,
                VideoAspect.square_1_1.value,
                VideoAspect.landscape_4_3.value,
                VideoAspect.portrait_3_4.value,
                VideoAspect.landscape_21_9.value
            ],
            index=0
        )
        
        video_source = st.selectbox(
            "视频来源",
            options=["pexels", "pixabay", "local", "solid_color"],
            index=0,
            format_func=lambda x: {
                "pexels": "Pexels（网络素材）",
                "pixabay": "Pixabay（网络素材）",
                "local": "本地素材",
                "solid_color": "纯色背景"
            }[x]
        )
        
        solid_bg_color = "#667eea"
        uploaded_files = None
        
        if video_source == "solid_color":
            solid_bg_color = st.color_picker(
                "选择背景颜色",
                value="#667eea"
            )
        
        if video_source == "local":
            uploaded_files = st.file_uploader(
                "上传视频素材",
                type=["mp4", "mov", "avi", "mkv", "jpg", "jpeg", "png"],
                accept_multiple_files=True
            )
            if uploaded_files:
                st.success(f"已上传 {len(uploaded_files)} 个素材文件")
        
        video_concat_mode = st.selectbox(
            "视频组合方式",
            options=[VideoConcatMode.random.value, VideoConcatMode.sequential.value],
            index=0,
            format_func=lambda x: "随机" if x == "random" else "顺序"
        )
        
        video_clip_duration = st.slider(
            "视频片段时长（秒）",
            min_value=1,
            max_value=20,
            value=5
        )
        
        video_count = st.number_input(
            "生成视频数量",
            min_value=1,
            max_value=10,
            value=1
        )
        
        video_transition_mode = st.selectbox(
            "转场效果",
            options=[None, VideoTransitionMode.fade_in.value, VideoTransitionMode.fade_out.value, 
                     VideoTransitionMode.slide_in.value, VideoTransitionMode.slide_out.value],
            index=0,
            format_func=lambda x: {
                None: "无转场",
                VideoTransitionMode.fade_in.value: "淡入",
                VideoTransitionMode.fade_out.value: "淡出",
                VideoTransitionMode.slide_in.value: "滑入",
                VideoTransitionMode.slide_out.value: "滑出"
            }[x]
        )
        
        st.markdown("---")
        st.markdown("**📊 视频质量设置**")
        
        video_quality = st.selectbox(
            "视频质量",
            options=["low", "medium", "high", "ultra"],
            index=2,
            format_func=lambda x: {
                "low": "低质量",
                "medium": "中等质量",
                "high": "高质量",
                "ultra": "超高质"
            }[x]
        )
        custom_bitrate = st.text_input(
            "自定义码率（可选）",
            placeholder="例如：8M"
        )
        custom_crf = st.number_input(
            "自定义CRF（可选）",
            min_value=0,
            max_value=51,
            value=None,
            help="值越小画质越好，文件越大"
        )
    
    # 音频设置
    with st.expander("🎵 音频设置", expanded=False):
        # 添加配音来源选项
        voice_source = st.selectbox(
            "配音来源",
            options=["tts", "local"],
            index=0,
            format_func=lambda x: "AI配音" if x == "tts" else "上传配音"
        )
        
        custom_voice_files = None
        custom_voice_path = None
        
        if voice_source == "tts":
            voice_provider = st.selectbox(
                "配音提供商",
                options=["azure", "siliconflow", "gemini", "mimo"],
                index=0,
                format_func=lambda x: {
                    "azure": "Azure",
                    "siliconflow": "硅基流动",
                    "gemini": "Gemini",
                    "mimo": "小米Mimo"
                }[x]
            )
        
        # 根据配音来源处理
        if voice_source == "tts":
            # 根据提供商获取声音列表
            if voice_provider == "azure":
                voice_names = voice.get_all_azure_voices()
            elif voice_provider == "siliconflow":
                voice_names = voice.get_siliconflow_voices()
            elif voice_provider == "gemini":
                voice_names = voice.get_gemini_voices()
            else:
                voice_names = voice.get_mimo_voices()
            
            if voice_names:
                voice_name = st.selectbox(
                    "配音声音",
                    options=voice_names,
                    index=0
                )
                
                # 试听按钮
                if st.button("🎧 试听配音", key="preview_voice"):
                    try:
                        with st.spinner("正在生成试听音频..."):
                            test_text = video_script[:50] if video_script else "你好，这是一段测试音频，用来试听配音效果。"
                            temp_voice_file = os.path.join("storage", "temp", f"preview_{uuid4()}.mp3")
                            os.makedirs(os.path.dirname(temp_voice_file), exist_ok=True)
                            
                            voice.tts(
                                text=test_text,
                                voice_name=voice_name,
                                voice_file=temp_voice_file,
                                voice_rate=1.0,
                                voice_volume=1.0
                            )
                            
                            st.audio(temp_voice_file, format="audio/mp3")
                            st.success("✅ 试听音频生成成功！")
                    except Exception as e:
                        st.error(f"试听失败：{e}")
            else:
                voice_name = ""
                st.warning("⚠️ 未找到可用的配音声音")
            
            voice_volume = st.slider(
                "配音音量",
                min_value=0.0,
                max_value=2.0,
                value=1.0,
                step=0.1
            )
            
            voice_rate = st.slider(
                "配音语速",
                min_value=0.5,
                max_value=2.0,
                value=1.0,
                step=0.1
            )
        else:
            # 上传配音
            voice_name = ""
            voice_volume = 1.0
            voice_rate = 1.0
            custom_voice_files = st.file_uploader(
                "上传配音音频文件（支持多个，按顺序拼接）",
                type=["mp3", "wav", "flac", "m4a"],
                accept_multiple_files=True
            )
            if custom_voice_files:
                st.success(f"已上传 {len(custom_voice_files)} 个配音文件")
                # 预览第一个音频
                st.audio(custom_voice_files[0], format="audio/mp3")
        
        bgm_type = st.selectbox(
            "背景音乐类型",
            options=["random", "custom", "none"],
            index=0,
            format_func=lambda x: {
                "random": "随机背景音乐",
                "custom": "自定义背景音乐",
                "none": "无背景音乐"
            }[x]
        )
        
        custom_bgm_file = None
        uploaded_bgm = None
        if bgm_type == "custom":
            uploaded_bgm = st.file_uploader(
                "上传背景音乐",
                type=["mp3", "wav", "flac"]
            )
            
            # 试听背景音乐
            if uploaded_bgm is not None:
                if st.button("🎧 试听背景音乐", key="preview_bgm"):
                    st.audio(uploaded_bgm, format="audio/mp3")
        
        if bgm_type != "none":
            bgm_volume = st.slider(
                "背景音乐音量",
                min_value=0.0,
                max_value=1.0,
                value=0.2,
                step=0.05
            )
    
    # 字幕设置
    with st.expander("📝 字幕设置", expanded=False):
        subtitle_enabled = st.checkbox(
            "启用字幕",
            value=True
        )
        
        if subtitle_enabled:
            subtitle_position = st.selectbox(
                "字幕位置",
                options=["bottom", "top", "center", "custom"],
                index=0,
                format_func=lambda x: {
                    "bottom": "底部",
                    "top": "顶部",
                    "center": "居中",
                    "custom": "自定义位置"
                }[x]
            )
            
            if subtitle_position == "custom":
                custom_position = st.slider(
                    "自定义位置百分比",
                    min_value=0,
                    max_value=100,
                    value=70
                )
            else:
                custom_position = 70
            
            subtitle_animation = st.selectbox(
                "字幕动画",
                options=["none", "fade", "slide_up", "slide_down", "slide_left", "slide_right", "pop"],
                index=1,
                format_func=lambda x: {
                    "none": "无动画",
                    "fade": "淡入淡出",
                    "slide_up": "向上滑动",
                    "slide_down": "向下滑动",
                    "slide_left": "向左滑动",
                    "slide_right": "向右滑动",
                    "pop": "弹出"
                }[x]
            )
            
            all_fonts = get_all_fonts()
            if all_fonts:
                # 尝试找到配置文件中默认的字体
                default_font = "MicrosoftYaHeiBold.ttc"
                default_index = 0
                if default_font in all_fonts:
                    default_index = all_fonts.index(default_font)
                
                font_name = st.selectbox(
                    "字体",
                    options=all_fonts,
                    index=default_index
                )
            else:
                font_name = "STHeitiMedium.ttc"
                st.warning("⚠️ 未找到可用字体")
            
            text_fore_color = st.color_picker(
                "文字颜色",
                value="#ffffff"
            )
            
            text_background_color = st.color_picker(
                "字幕背景色",
                value="#000000"
            )
            
            font_size = st.number_input(
                "字体大小",
                min_value=10,
                max_value=200,
                value=60
            )
            
            stroke_color = st.color_picker(
                "描边颜色",
                value="#000000"
            )
            
            stroke_width = st.slider(
                "描边宽度",
                min_value=0.0,
                max_value=10.0,
                value=1.5,
                step=0.5
            )
    
    # 基础设置（可选隐藏）
    if not config.app.get("hide_config", False):
        with st.expander("⚙️ 基础设置", expanded=False):
            config_panels = st.columns(2)
            
            with config_panels[0]:
                st.subheader("🌐 LLM配置")
                llm_provider_labels = [
                    "OpenAI",
                    "Azure OpenAI",
                    "Moonshot AI (Kimi)",
                    "DeepSeek AI",
                    "Gitee AI",
                    "Ollama",
                    "Gemini",
                ]
                llm_provider_values = ["openai", "azure", "moonshot", "deepseek", "giteeai", "ollama", "gemini"]
                saved_llm_provider = config.app.get("llm_provider", "openai").lower()
                saved_llm_provider_index = 0
                for i, provider_id in enumerate(llm_provider_values):
                    if provider_id == saved_llm_provider:
                        saved_llm_provider_index = i
                        break
                
                llm_provider_label = st.selectbox(
                    "LLM 提供商",
                    options=llm_provider_labels,
                    index=saved_llm_provider_index
                )
                llm_provider = llm_provider_values[llm_provider_labels.index(llm_provider_label)]
                config.app["llm_provider"] = llm_provider
                
                llm_api_key = config.app.get(f"{llm_provider}_api_key", "")
                llm_secret_key = config.app.get(f"{llm_provider}_secret_key", "")
                llm_base_url = config.app.get(f"{llm_provider}_base_url", "")
                llm_model_name = config.app.get(f"{llm_provider}_model_name", "")
                
                llm_api_key = st.text_input(
                    "API Key",
                    value=llm_api_key,
                    type="password"
                )
                if llm_api_key:
                    config.app[f"{llm_provider}_api_key"] = llm_api_key
                
                if llm_provider in ["azure"]:
                    llm_secret_key = st.text_input(
                        "Secret Key",
                        value=llm_secret_key,
                        type="password"
                    )
                    if llm_secret_key:
                        config.app[f"{llm_provider}_secret_key"] = llm_secret_key
                
                llm_base_url = st.text_input(
                    "Base URL（可选）",
                    value=llm_base_url
                )
                if llm_base_url:
                    config.app[f"{llm_provider}_base_url"] = llm_base_url
                
                llm_model_name = st.text_input(
                    "Model Name（可选）",
                    value=llm_model_name
                )
                if llm_model_name:
                    config.app[f"{llm_provider}_model_name"] = llm_model_name
            
            with config_panels[1]:
                st.subheader("🎤 TTS配置")
                tts_provider_labels = [
                    "Edge TTS",
                    "Azure TTS",
                    "OpenAI TTS",
                    "SiliconFlow TTS",
                    "Gemini TTS",
                    "Mimo TTS",
                ]
                tts_provider_values = ["edge", "azure", "openai", "siliconflow", "gemini", "mimo"]
                saved_tts_provider = config.app.get("tts_provider", "edge").lower()
                saved_tts_provider_index = 0
                for i, provider_id in enumerate(tts_provider_values):
                    if provider_id == saved_tts_provider:
                        saved_tts_provider_index = i
                        break
                
                tts_provider_label = st.selectbox(
                    "TTS 提供商",
                    options=tts_provider_labels,
                    index=saved_tts_provider_index
                )
                tts_provider = tts_provider_values[tts_provider_labels.index(tts_provider_label)]
                config.app["tts_provider"] = tts_provider
                
                tts_api_key = config.app.get(f"{tts_provider}_api_key", "")
                tts_secret_key = config.app.get(f"{tts_provider}_secret_key", "")
                tts_base_url = config.app.get(f"{tts_provider}_base_url", "")
                tts_model_name = config.app.get(f"{tts_provider}_model_name", "")
                
                tts_api_key = st.text_input(
                    "API Key",
                    value=tts_api_key,
                    type="password"
                )
                if tts_api_key:
                    config.app[f"{tts_provider}_api_key"] = tts_api_key
                
                if tts_provider in ["azure"]:
                    tts_secret_key = st.text_input(
                        "Secret Key",
                        value=tts_secret_key,
                        type="password"
                    )
                    if tts_secret_key:
                        config.app[f"{tts_provider}_secret_key"] = tts_secret_key
                
                tts_base_url = st.text_input(
                    "Base URL（可选）",
                    value=tts_base_url
                )
                if tts_base_url:
                    config.app[f"{tts_provider}_base_url"] = tts_base_url
                
                tts_model_name = st.text_input(
                    "Model Name（可选）",
                    value=tts_model_name
                )
                if tts_model_name:
                    config.app[f"{tts_provider}_model_name"] = tts_model_name
    
    # 在读取完所有配置后，进行配置变化检测
    # 收集当前配置 - 只使用明确存在的配置项
    current_config = {
        "video_subject": video_subject,
        "video_script": video_script,
        "video_terms": video_terms,
        "video_aspect": video_aspect,
        "video_source": video_source,
        "solid_bg_color": solid_bg_color,
        "video_concat_mode": video_concat_mode,
        "subtitle_enabled": subtitle_enabled,
        "font_name": font_name,
        "text_fore_color": text_fore_color,
    }
    
    # 添加配音相关配置（确保变量存在）
    if 'voice_source' in locals():
        current_config["voice_source"] = voice_source
    if 'voice_provider' in locals():
        current_config["voice_provider"] = voice_provider
    if 'voice_name' in locals():
        current_config["voice_name"] = voice_name
    
    # 检测配置是否变化
    if st.session_state["prev_config"] is not None and st.session_state["generated_video_path"] is not None:
        config_changed = False
        for key, value in current_config.items():
            if key in st.session_state["prev_config"] and st.session_state["prev_config"][key] != value:
                config_changed = True
                break
        
        if config_changed:
            # 配置变化，恢复预览状态
            st.session_state["generated_video_path"] = None
            st.rerun()
    
    # 更新前一个配置
    st.session_state["prev_config"] = current_config
    
    # 生成按钮
    st.markdown("<hr>", unsafe_allow_html=True)
    
    # 生成按钮
    if st.button("🚀 生成视频", key="gen_video", type="primary"):
            if not video_subject and not video_script:
                st.error("请填写视频主题或视频脚本")
                st.stop()
            
            if not video_terms and video_source in ["pexels", "pixabay"]:
                st.error("请先生成视频关键词")
                st.stop()
            
            task_id = str(uuid4())
            st.session_state["current_task_id"] = task_id
            st.session_state["show_floating_progress"] = True
            st.session_state["log_records"] = []
            
            video_terms_list = []
            if video_terms:
                video_terms_list = [term.strip() for term in video_terms.split(",") if term.strip()]
            
            # 保存自定义背景音乐文件
            custom_bgm_path = None
            if bgm_type == "custom" and uploaded_bgm is not None:
                temp_bgm_dir = os.path.join("storage", "temp")
                os.makedirs(temp_bgm_dir, exist_ok=True)
                bgm_path = os.path.join(temp_bgm_dir, f"bgm_{uuid4()}.mp3")
                with open(bgm_path, "wb") as f:
                    f.write(uploaded_bgm.getvalue())
                custom_bgm_path = bgm_path
            
            # 处理自定义配音文件 - 先简化，只支持单个文件
            custom_voice_path = None
            try:
                if 'voice_source' in locals() and voice_source == "local" and custom_voice_files is not None and len(custom_voice_files) > 0:
                    temp_voice_dir = os.path.join("storage", "temp", task_id)
                    os.makedirs(temp_voice_dir, exist_ok=True)
                    
                    # 只保存第一个文件
                    uploaded_file = custom_voice_files[0]
                    file_path = os.path.join(temp_voice_dir, uploaded_file.name)
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getvalue())
                    custom_voice_path = file_path
                    st.session_state["log_records"].append(f"🎵 使用配音文件：{custom_voice_path}")
            except Exception as e:
                st.session_state["log_records"].append(f"⚠️ 处理配音文件时出错：{e}")
                custom_voice_path = None
            
            # 处理本地素材上传
            video_materials = None
            if video_source == "local" and uploaded_files is not None:
                temp_material_dir = os.path.join("storage", "temp", task_id)
                os.makedirs(temp_material_dir, exist_ok=True)
                video_materials = []
                for uploaded_file in uploaded_files:
                    file_path = os.path.join(temp_material_dir, uploaded_file.name)
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getvalue())
                    # 创建MaterialInfo对象
                    material_info = MaterialInfo(
                        provider="local",
                        url=file_path,
                        duration=0
                    )
                    video_materials.append(material_info)
            
            # 创建参数
            params = VideoParams(
                video_subject=video_subject,
                video_script=video_script,
                video_terms=video_terms_list,
                video_aspect=video_aspect,
                video_concat_mode=video_concat_mode,
                video_transition_mode=video_transition_mode,
                video_clip_duration=video_clip_duration,
                video_count=video_count,
                video_source=video_source,
                video_materials=video_materials,
                video_language=video_language,
                voice_name=voice_name,
                voice_volume=voice_volume,
                voice_rate=voice_rate,
                bgm_type=bgm_type,
                bgm_volume=bgm_volume if bgm_type != "none" else 0,
                custom_bgm_file=custom_bgm_path,
                custom_audio_file=custom_voice_path,
                subtitle_enabled=subtitle_enabled,
                subtitle_position=subtitle_position,
                custom_position=custom_position,
                font_name=font_name,
                text_fore_color=text_fore_color,
                text_background_color=text_background_color,
                font_size=font_size,
                stroke_color=stroke_color,
                stroke_width=stroke_width,
                subtitle_animation=subtitle_animation,
                video_quality=video_quality,
                n_threads=2,
                paragraph_number=1,
                video_script_prompt=st.session_state.get("video_script_prompt", ""),
                custom_system_prompt=st.session_state.get("custom_system_prompt", "")
            )
            
            if video_source == "solid_color":
                params.solid_bg_color = solid_bg_color
            
            if custom_bitrate:
                params.video_bitrate = custom_bitrate
            
            if custom_crf is not None:
                params.video_crf = custom_crf
            
            # 启动任务
            try:
                # 使用一个简单的进度条
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                status_text.text("正在启动视频生成任务...")
                st.session_state["log_records"].append("正在启动视频生成任务...")
                
                progress_bar.progress(10)
                
                # 实际执行任务 - tm.start() 是同步执行的，会完整执行所有步骤
                try:
                    result = tm.start(task_id=task_id, params=params)
                    st.session_state["log_records"].append(f"任务执行中，任务ID：{task_id}")
                    st.session_state["log_records"].append(f"任务返回结果：{result}")
                    if result:
                        for key, value in result.items():
                            st.session_state["log_records"].append(f"  - {key}: {value}")
                    
                    progress_bar.progress(100)
                    status_text.text("视频生成完成！")
                    st.session_state["log_records"].append("视频生成完成！")
                    
                    # 从返回结果中获取视频路径
                    video_found = False
                    try:
                        if result and "videos" in result and len(result["videos"]) > 0:
                            video_path = result["videos"][0]
                            st.session_state["log_records"].append(f"尝试使用返回的视频路径：{video_path}")
                            st.session_state["log_records"].append(f"  - 是否存在：{os.path.exists(video_path)}")
                            
                            # 尝试标准化路径
                            normalized_path = os.path.abspath(os.path.normpath(video_path))
                            st.session_state["log_records"].append(f"  - 标准化路径：{normalized_path}")
                            
                            if os.path.exists(normalized_path):
                                st.session_state["generated_video_path"] = normalized_path
                                st.success("视频生成完成！")
                                st.session_state["log_records"].append(f"视频文件：{normalized_path}")
                                video_found = True
                                # 添加到历史记录
                                if normalized_path not in st.session_state["video_history"]:
                                    st.session_state["video_history"].append(normalized_path)
                            else:
                                st.session_state["log_records"].append(f"返回的视频文件不存在，尝试其他方式查找")
                    except Exception as e:
                        st.session_state["log_records"].append(f"处理返回结果时出错：{e}")
                    
                    # 如果没找到，在任务目录中查找
                    if not video_found:
                        try:
                            task_dir = os.path.join(root_dir, "storage", "tasks", task_id)
                            task_dir = os.path.abspath(os.path.normpath(task_dir))
                            st.session_state["log_records"].append(f"尝试查找任务目录：{task_dir}")
                            
                            if os.path.exists(task_dir):
                                task_contents = os.listdir(task_dir)
                                st.session_state["log_records"].append(f"任务目录内容：{task_contents}")
                                
                                # 查找所有 mp4 文件
                                video_files = []
                                for f in task_contents:
                                    if f.endswith(".mp4"):
                                        full_path = os.path.join(task_dir, f)
                                        size = os.path.getsize(full_path)
                                        st.session_state["log_records"].append(f"  - 发现文件：{f} ({size} bytes)")
                                        video_files.append((f, size))
                                
                                # 优先找带 final 的
                                final_videos = [f for f in video_files if "final" in f[0]]
                                if final_videos:
                                    # 选最大的那个
                                    final_videos.sort(key=lambda x: x[1], reverse=True)
                                    video_path = os.path.join(task_dir, final_videos[0][0])
                                elif video_files:
                                    # 选最大的那个
                                    video_files.sort(key=lambda x: x[1], reverse=True)
                                    video_path = os.path.join(task_dir, video_files[0][0])
                                else:
                                    video_path = None
                                
                                if video_path and os.path.exists(video_path):
                                    st.session_state["generated_video_path"] = video_path
                                    st.success("视频生成完成！")
                                    st.session_state["log_records"].append(f"找到视频文件：{video_path}")
                                    # 添加到历史记录
                                    if video_path not in st.session_state["video_history"]:
                                        st.session_state["video_history"].append(video_path)
                                else:
                                    st.warning("任务已完成，但未找到视频文件")
                                    st.session_state["log_records"].append("未找到视频文件")
                            else:
                                st.warning("任务已完成，但任务目录不存在")
                                st.session_state["log_records"].append(f"任务目录不存在：{task_dir}")
                        except Exception as e:
                            st.session_state["log_records"].append(f"查找视频文件时出错：{e}")
                            st.error(f"查找视频文件时出错：{e}")
                    
                except Exception as e:
                    st.error(f"任务执行失败：{e}")
                    st.session_state["log_records"].append(f"错误：{e}")
                    st.session_state["show_floating_progress"] = False
            
            except Exception as e:
                st.error(f"任务启动失败：{e}")
                st.session_state["show_floating_progress"] = False
    
    # 日志显示区域
    st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
    with st.expander("生成日志", expanded=False):
        logs = st.session_state.get("log_records", [])
        if logs:
            for log in logs:
                st.markdown(f"- {log}")
        else:
            st.markdown("暂无日志记录")
    st.markdown('<div style="margin-bottom:30px;"></div>', unsafe_allow_html=True)

# ==================== 中间：预览区域 ====================
with col2:
    
    # 计算当前选择的视频比例，用于预览显示
    aspect_obj = VideoAspect(video_aspect)
    ratio_width, ratio_height = aspect_obj.to_resolution()
    # 转换为比例（保持宽高比）
    ratio_w = ratio_width
    ratio_h = ratio_height
    if ratio_width > ratio_height:
        # 横屏
        max_w = 500
        if ratio_width > max_w:
            scale = max_w / ratio_width
            ratio_w = max_w
            ratio_h = int(ratio_height * scale)
    else:
        # 竖屏或方屏
        max_h = 600
        if ratio_height > max_h:
            scale = max_h / ratio_height
            ratio_h = max_h
            ratio_w = int(ratio_width * scale)
    
    # 如果有生成的视频，显示视频
    if st.session_state.get("generated_video_path") and os.path.exists(st.session_state["generated_video_path"]):
        # 简单直接显示视频
        st.markdown(f'<div style="width:100%;max-width:{ratio_w}px;margin:0 auto;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.3);background:#000;">', unsafe_allow_html=True)
        st.video(st.session_state["generated_video_path"])
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        # 构建预览HTML
        preview_html = f'<div style="width:100%;max-width:{ratio_w}px;margin:0 auto;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.3);background:#000;position:relative;">'
        
        # 内部容器 - 使用padding-top实现比例
        preview_html += f'<div style="width:100%;padding-top:{(ratio_h/ratio_w)*100}%;position:relative;">'
        preview_html += '<div style="position:absolute;top:0;left:0;right:0;bottom:0;">'
        
        # 背景层
        if video_source == "solid_color":
            preview_html += f'<div style="width:100%;height:100%;background-color:{solid_bg_color};display:flex;align-items:center;justify-content:center;">'
            preview_html += f'<span style="color:white;text-shadow:1px 1px 3px rgba(0,0,0,0.5);font-weight:500;">背景: {solid_bg_color}</span>'
            preview_html += '</div>'
        elif video_source == "local" and uploaded_files:
            preview_html += '<div style="width:100%;height:100%;background:#333;display:flex;align-items:center;justify-content:center;color:#999;flex-direction:column;">'
            preview_html += '<span style="font-size:2.5rem;margin-bottom:0.5rem;">📷</span>'
            preview_html += '<span>本地素材已加载</span>'
            preview_html += '</div>'
        else:
            preview_html += '<div style="width:100%;height:100%;background:linear-gradient(135deg,#2d3436 0%,#636e72 100%);display:flex;align-items:center;justify-content:center;color:#b2bec3;flex-direction:column;border:2px dashed #636e72;">'
            preview_html += '<span style="font-size:3rem;margin-bottom:1rem;">📹</span>'
            preview_html += '<span style="font-size:1.1rem;">等待视频生成...</span>'
            preview_html += '<span style="font-size:0.9rem;margin-top:0.5rem;opacity:0.7;">配置参数后点击"生成视频"</span>'
            preview_html += '</div>'
        
        # 字幕层
        if subtitle_enabled and video_script:
            preview_text = video_script[:20] + "..." if len(video_script) > 20 else video_script
            
            subtitle_style = "position:absolute;left:50%;transform:translateX(-50%);text-align:center;padding:8px 16px;border-radius:8px;background:rgba(0,0,0,0.75);max-width:90%;z-index:10;"
            if subtitle_position == "top":
                subtitle_style += "top:20px;"
            elif subtitle_position == "center":
                subtitle_style += "top:50%;transform:translateX(-50%) translateY(-50%);"
            else:
                subtitle_style += "bottom:20px;"
            
            # 使用系统可用的中文字体
            font_family = "'Microsoft YaHei', 'PingFang SC', 'STHeitiSC-Light', sans-serif"
            
            preview_html += f'<div style="{subtitle_style}">'
            preview_html += f'<span style="color:{text_fore_color};font-size:{font_size}px;font-family:{font_family};text-shadow:-1px -1px 0 {stroke_color},1px -1px 0 {stroke_color},-1px 1px 0 {stroke_color},1px 1px 0 {stroke_color};">'
            preview_html += preview_text
            preview_html += '</span></div>'
        
        # 结束标签
        preview_html += '</div></div></div>'
        
        # 渲染预览
        st.markdown(preview_html, unsafe_allow_html=True)


# ==================== 右侧：历史视频列表 ====================
with col3:
    st.subheader("📁 视频历史")
    
    if len(st.session_state["video_history"]) > 0:
        # 反向显示历史（最新的在上面）
        reversed_history = list(reversed(st.session_state["video_history"]))
        num_videos = len(reversed_history)
        
        for idx, video_path in enumerate(reversed_history):
            if os.path.exists(video_path):
                video_num = num_videos - idx
                
                # 每个历史视频项
                with st.container():
                    # 显示视频缩略图
                    st.markdown(f"""
                    <div style="margin-bottom:12px;padding:10px;background:linear-gradient(135deg,#f8f9fa 0%,#e9ecef 100%);border-radius:8px;">
                        <div style="font-weight:600;margin-bottom:8px;color:#333;">🎬 视频 #{video_num}</div>
                        <div style="font-size:12px;color:#666;margin-bottom:8px;">
                            {os.path.basename(video_path)}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 使用按钮实现点击功能
                    if st.button(f"▶️ 播放 #{video_num}", key=f"history_video_{idx}", use_container_width=True):
                        st.session_state["generated_video_path"] = video_path
                        st.rerun()
    else:
        st.info("暂无视频历史记录，生成视频后将显示在这里")


# ==================== 右上角进度信息 ====================
if st.session_state.get("show_floating_progress"):
    # 用Streamlit原生组件显示进度信息
    st.info("🎬 视频生成进度 - 任务完成")
    if st.button("关闭", key="close_progress_info"):
        st.session_state["show_floating_progress"] = False
        st.rerun()


