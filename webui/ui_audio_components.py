import os
import sys
from uuid import uuid4
import streamlit as st
from loguru import logger

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.config import config
from app.services import voice
from app.utils import utils

# Load locales for translation
i18n_dir = os.path.join(root_dir, "webui", "i18n")

# 延迟加载locales，确保在使用时能够获取到最新的语言设置
def get_locales():
    """Get the latest locales"""
    return utils.load_locales(i18n_dir)

def tr(key):
    """Translate key to current UI language"""
    locales = get_locales()
    loc = locales.get(st.session_state.get("ui_language", "en"), {})
    return loc.get("Translation", {}).get(key, key)

def render_audio_settings(params):
    """
    Render the audio settings component
    
    Args:
        params: VideoParams object to store audio settings
    """
    # Audio Settings section
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # Add TTS server selection dropdown
        tts_servers = [
            ("azure-tts-v1", tr("Azure TTS V1")),
            ("azure-tts-v2", tr("Azure TTS V2")),
            ("siliconflow", tr("SiliconFlow TTS")),
            ("gemini-tts", tr("Google Gemini TTS")),
            ("coze-tts", tr("Coze TTS")),
        ]

        # Get saved TTS server, default to v1
        saved_tts_server = config.ui.get("tts_server", "azure-tts-v1")
        
        saved_tts_server_index = 0
        for i, (server_value, _) in enumerate(tts_servers):
            if server_value == saved_tts_server:
                saved_tts_server_index = i
                break

        # Use session_state to track TTS selection
        if "tts_server_index" not in st.session_state:
            st.session_state["tts_server_index"] = saved_tts_server_index

        # Define callback function for TTS change
        def on_tts_change():
            """Callback function when TTS server changes"""
            # Get new value from session_state
            new_index = st.session_state.get("tts_server_select", saved_tts_server_index)
            st.session_state["tts_server_index"] = new_index

        # Use key to bind to session_state
        selected_tts_server_index = st.selectbox(
            tr("TTS Servers"),
            options=range(len(tts_servers)),
            format_func=lambda x: tts_servers[x][1],
            index=st.session_state["tts_server_index"],
            key="tts_server_select",
            on_change=on_tts_change,
        )

        # Prefer value from session_state
        if "tts_server_select" in st.session_state:
            selected_tts_server_index = st.session_state["tts_server_select"]

        selected_tts_server = tts_servers[selected_tts_server_index][0]
        
        # Directly compare selected and saved values
        if selected_tts_server != saved_tts_server:
            # Reset voice_name
            config.ui["voice_name"] = ""
            # Save to config
            config.ui["tts_server"] = selected_tts_server
            config.save_config()
            logger.info(f"[TTS Change] TTS server changed from '{saved_tts_server}' to '{selected_tts_server}', config saved")
            
            # Delete all TTS-related session_state
            for key in list(st.session_state.keys()):
                if key.startswith("voice_select_"):
                    del st.session_state[key]
                    logger.info(f"[TTS Change] Deleted session_state: {key}")

        # Get voice list based on selected TTS server
        filtered_voices = []

        if selected_tts_server == "siliconflow":
            # Get SiliconFlow voices
            filtered_voices = voice.get_siliconflow_voices()
        elif selected_tts_server == "gemini-tts":
            # Get Gemini TTS voices
            filtered_voices = voice.get_gemini_voices()
        elif selected_tts_server == "coze-tts":
            # Get Coze TTS voices
            # Add refresh button and search box in the same row
            # Adjust column widths to ensure proper spacing
            col1, col2 = st.columns([8, 2])
            with col1:
                # Search box
                search_term = st.text_input(
                    tr("Search"),
                    key=f"voice_search_{selected_tts_server}",
                    label_visibility="collapsed",
                    placeholder=tr("Type to search...")
                )
            with col2:
                # Refresh button
                if st.button("🔄", key="refresh_coze_voices", help=tr("Refresh Coze voice list")):
                    # Force refresh cache
                    filtered_voices = voice.get_coze_voices(force_refresh=True)
                    st.success(tr("Coze voice list refreshed"))
            
            # Normal voice retrieval (using cache)
            if not filtered_voices:
                filtered_voices = voice.get_coze_voices()
        else:
            # Get Azure voices
            all_voices = voice.get_all_azure_voices(filter_locals=None)

            # Filter voices based on selected TTS server
            for v in all_voices:
                if selected_tts_server == "azure-tts-v2":
                    # V2 voices contain "v2"
                    if "V2" in v:
                        filtered_voices.append(v)
                else:
                    # V1 voices don't contain "v2"
                    if "V2" not in v:
                        filtered_voices.append(v)

        friendly_names = {}
        for v in filtered_voices:
            # For Coze voices, extract friendly display name (remove preview_audio and preview_text)
            if v.startswith("coze|"):
                parts = v.split("|")
                if len(parts) >= 3:
                    # Format: coze|voice_id|voice_name-gender|preview_audio|preview_text
                    # Display as: voice_name-gender
                    display_name = parts[2].replace("Female", tr("Female")).replace("Male", tr("Male"))
                else:
                    display_name = v
            else:
                display_name = v.replace("Female", tr("Female")).replace("Male", tr("Male")).replace("Neural", "")
            friendly_names[v] = display_name

        saved_voice_name = config.ui.get("voice_name", "")
        saved_voice_name_index = 0
        
        logger.info(f"[Voice Load] Saved voice_name from config: {saved_voice_name}")
        logger.info(f"[Voice Load] Total available voices: {len(friendly_names)}")
        
        # Check if saved voice is in current filtered voice list
        # For Coze voices, use voice_id for matching since URL signatures change
        if saved_voice_name and saved_voice_name in friendly_names:
            saved_voice_name_index = list(friendly_names.keys()).index(saved_voice_name)
            logger.info(f"[Voice Load] Found saved voice in list, index: {saved_voice_name_index}")
        elif saved_voice_name and saved_voice_name.startswith("coze|"):
            # For Coze voices, extract voice_id for matching
            saved_parts = saved_voice_name.split("|")
            if len(saved_parts) >= 2:
                saved_voice_id = saved_parts[1]
                logger.info(f"[Voice Load] Trying to match coze voice by ID: {saved_voice_id}")
                
                # Find matching voice_id in current voice list
                for i, voice_key in enumerate(friendly_names.keys()):
                    if voice_key.startswith("coze|"):
                        current_parts = voice_key.split("|")
                        if len(current_parts) >= 2 and current_parts[1] == saved_voice_id:
                            saved_voice_name_index = i
                            saved_voice_name = voice_key
                            logger.info(f"[Voice Load] Found matching voice ID in list, index: {saved_voice_name_index}")
                            break
                else:
                    # If not found, use first voice
                    saved_voice_name_index = 0
                    logger.info(f"[Voice Load] Saved voice ID not found in list, using index 0")
            else:
                saved_voice_name_index = 0
                logger.info(f"[Voice Load] Invalid saved voice format, using index 0")
        else:
            # If not found, use first voice
            saved_voice_name_index = 0
            logger.info(f"[Voice Load] Saved voice not found in list, using index 0")

        # Ensure index is within valid range
        if friendly_names:
            saved_voice_name_index = min(saved_voice_name_index, len(friendly_names) - 1)

        # Initialize voice_name variable
        voice_name = ""
        
        # Ensure voices are available
        if friendly_names:
            # Set label dynamically based on TTS service
            if selected_tts_server == "azure-tts-v1":
                # Azure TTS V1 needs to display V2 prompt
                speech_synthesis_label = f"{tr('Speech Synthesis')} (:red[**{tr('Keep consistent with script language')}**. {tr('Note: V2 version is better, but requires API KEY')}])"
            else:
                # Other TTS services only display basic prompt
                speech_synthesis_label = f"{tr('Speech Synthesis')} (:red[**{tr('Keep consistent with script language')}**])"
            
            # For non-Coze TTS, initialize search_term to empty
            if selected_tts_server != "coze-tts":
                search_term = ""
            
            # Filter voice list
            filtered_friendly_names = {}
            if search_term:
                search_term_lower = search_term.lower()
                for voice_key, voice_name in friendly_names.items():
                    if search_term_lower in voice_name.lower():
                        filtered_friendly_names[voice_key] = voice_name
            else:
                filtered_friendly_names = friendly_names
            
            # Determine current index
            if filtered_friendly_names:
                # Use session_state to track voice selection
                voice_select_key = f"voice_select_{selected_tts_server}"
                
                # Check if reset is needed (TTS server changed or saved voice_name not in list)
                # Initialize index variable
                filtered_saved_voice_name_index = 0
                
                # Prefer value from session_state
                if voice_select_key in st.session_state:
                    # If session_state has value, use it
                    logger.info(f"[Selectbox] Using session_state value: {st.session_state[voice_select_key]}")
                    # Try to find corresponding index
                    for i, display_name in enumerate(filtered_friendly_names.values()):
                        if display_name == st.session_state[voice_select_key]:
                            filtered_saved_voice_name_index = i
                            break
                elif saved_voice_name and saved_voice_name in filtered_friendly_names:
                    # If session_state has no value but config file has value, use config file value
                    filtered_saved_voice_name_index = list(filtered_friendly_names.keys()).index(saved_voice_name)
                    logger.info(f"[Selectbox] Found saved voice in filtered list, index: {filtered_saved_voice_name_index}")
                elif saved_voice_name and saved_voice_name.startswith("coze|"):
                    # For Coze voices, extract voice_id for matching
                    saved_parts = saved_voice_name.split("|")
                    if len(saved_parts) >= 2:
                        saved_voice_id = saved_parts[1]
                        logger.info(f"[Selectbox] Trying to match coze voice by ID in filtered list: {saved_voice_id}")
                        
                        # Find matching voice_id in filtered voice list
                        for i, voice_key in enumerate(filtered_friendly_names.keys()):
                            if voice_key.startswith("coze|"):
                                current_parts = voice_key.split("|")
                                if len(current_parts) >= 2 and current_parts[1] == saved_voice_id:
                                    filtered_saved_voice_name_index = i
                                    saved_voice_name = voice_key
                                    logger.info(f"[Selectbox] Found matching voice ID in filtered list, index: {filtered_saved_voice_name_index}")
                                    break
                        else:
                            # If not found, use first
                            filtered_saved_voice_name_index = 0
                            logger.info(f"[Selectbox] Saved voice ID not found in filtered list, using index 0")
                    else:
                        filtered_saved_voice_name_index = 0
                        logger.info(f"[Selectbox] Invalid saved voice format, using index 0")
                else:
                    # If no values, use first
                    filtered_saved_voice_name_index = 0
                    logger.info(f"[Selectbox] Saved voice not in filtered list, using index 0")
                    # Reset session_state
                    if voice_select_key in st.session_state:
                        del st.session_state[voice_select_key]
                        logger.info(f"[Selectbox] Deleted old session_state for voice_select")
                
                # Calculate correct index
                selectbox_index = min(filtered_saved_voice_name_index, len(filtered_friendly_names) - 1)
                logger.info(f"[Selectbox] Total filtered voices: {len(filtered_friendly_names)}")
                logger.info(f"[Selectbox] Selectbox index: {selectbox_index}")
                logger.info(f"[Selectbox] Session state value: {st.session_state.get(voice_select_key, 'not set')}")
                
                selected_friendly_name = st.selectbox(
                    speech_synthesis_label,
                    options=list(filtered_friendly_names.values()),
                    index=selectbox_index,
                    key=voice_select_key,
                )
                
                # Find corresponding voice_name
                for voice_key, display_name in filtered_friendly_names.items():
                    if display_name == selected_friendly_name:
                        voice_name = voice_key
                        break
                else:
                    # If not found, use first
                    voice_name = list(filtered_friendly_names.keys())[0]
                    logger.warning(f"[Selectbox] Could not find voice for display name: {selected_friendly_name}, using first voice")
            else:
                # No matching voices
                st.warning("No matching voices found")
                voice_name = list(friendly_names.keys())[0]
            params.voice_name = voice_name
            
            # Check if voice_name changed, save to config if changed
            current_saved_voice = config.ui.get("voice_name", "")
            if current_saved_voice != voice_name:
                config.ui["voice_name"] = voice_name
                config.save_config()
                logger.info(f"[Config Save] Voice name changed from '{current_saved_voice}' to '{voice_name}', saved to config file")
            
            # Handle Coze voice emotion selection
            params.voice_emotion = ""
            if voice_name.startswith("coze|"):
                parts = voice_name.split("|")
                if len(parts) > 5 and parts[5]:
                    emotions = parts[5].split(",")
                    if emotions:
                        # Filter empty strings and clean
                        emotion_options = [e.strip() for e in emotions if e.strip()]
                        
                        if emotion_options:
                            # Display emotion selection dropdown (format: emotion-display_name)
                            selected_emotion = st.selectbox(
                                tr("Voice Emotion"),
                                options=emotion_options,
                                index=0,
                                key=f"emotion_select_{selected_tts_server}_{voice_name[:30]}",
                            )
                            # Extract emotion value (format: emotion-display_name -> emotion)
                            if "-" in selected_emotion:
                                params.voice_emotion = selected_emotion.split("-")[0]
                            else:
                                params.voice_emotion = selected_emotion

        else:
            # If no voices available, display message
            st.warning(
                tr("No voices available for the selected TTS server. Please select another server.")
            )
            params.voice_name = ""
            config.ui["voice_name"] = ""
            config.save_config()

        # Only display play button if voices are available
        if friendly_names and st.button(tr("Play Voice")):
            play_content = params.video_subject
            if not play_content:
                play_content = params.video_script
            if not play_content:
                # For Coze voices, use preview_text as test text
                if voice_name and voice.is_coze_voice(voice_name):
                    # Extract preview_text from voice_name (format: coze|voice_id|voice_name-gender|preview_audio|preview_text)
                    parts = voice_name.split("|")
                    if len(parts) > 4:
                        play_content = parts[4]
                if not play_content:
                    play_content = tr("Voice Example")
            with st.spinner(tr("Synthesizing Voice")):
                temp_dir = utils.storage_dir("temp", create=True)
                audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")
                sub_maker = voice.tts(
                    text=play_content,
                    voice_name=voice_name,
                    voice_rate=params.voice_rate,
                    voice_file=audio_file,
                    voice_volume=params.voice_volume,
                    emotion=params.voice_emotion,
                    is_preview=True,
                )
                # If voice file generation failed, try again with default content
                if not sub_maker and not os.path.exists(audio_file):
                    play_content = tr("This is a example voice. if you hear this, the voice synthesis failed with the original content.")
                    sub_maker = voice.tts(
                        text=play_content,
                        voice_name=voice_name,
                        voice_rate=params.voice_rate,
                        voice_file=audio_file,
                        voice_volume=params.voice_volume,
                        emotion=params.voice_emotion,
                        is_preview=True,
                    )

                if sub_maker or os.path.exists(audio_file):
                    st.audio(audio_file, format="audio/mp3")
                    if os.path.exists(audio_file):
                        os.remove(audio_file)

        # Display service region and API key input when V2 version or V2 voice is selected
        if selected_tts_server == "azure-tts-v2" or (
            voice_name and voice.is_azure_v2_voice(voice_name)
        ):
            saved_azure_speech_region = config.azure.get("speech_region", "")
            saved_azure_speech_key = config.azure.get("speech_key", "")
            azure_speech_region = st.text_input(
                tr("Speech Region"),
                value=saved_azure_speech_region,
                key="azure_speech_region_input",
            )
            azure_speech_key = st.text_input(
                tr("Speech Key"),
                value=saved_azure_speech_key,
                type="password",
                key="azure_speech_key_input",
            )
            config.azure["speech_region"] = azure_speech_region
            config.azure["speech_key"] = azure_speech_key

        # Display API key input and info when SiliconFlow is selected
        if selected_tts_server == "siliconflow" or (
            voice_name and voice.is_siliconflow_voice(voice_name)
        ):
            saved_siliconflow_api_key = config.siliconflow.get("api_key", "")

            siliconflow_api_key = st.text_input(
                tr("SiliconFlow API Key"),
                value=saved_siliconflow_api_key,
                type="password",
                key="siliconflow_api_key_input",
            )

            # Display SiliconFlow info
            st.info(
                tr("SiliconFlow TTS Settings") + ":\n" +
                "- " + tr("Speed: Range [0.25, 4.0], default is 1.0") + "\n" +
                "- " + tr("Volume: Uses Speech Volume setting, default 1.0 maps to gain 0")
            )
            config.siliconflow["api_key"] = siliconflow_api_key

        # Display API key input and info when Coze is selected
        if selected_tts_server == "coze-tts" or (
            voice_name and voice.is_coze_voice(voice_name)
        ):
            saved_coze_api_key = config.coze.get("api_key", "")

            coze_api_key = st.text_input(
                tr("Coze API Key"),
                value=saved_coze_api_key,
                type="password",
                key="coze_api_key_input",
            )

            # Display Coze info
            st.info(
                tr("Coze TTS Settings") + ":\n" +
                "- " + tr("Speed: Range [0.5, 2.0], default is 1.0") + "\n" +
                "- " + tr("Volume: Range [0.1, 2.0], default is 1.0") + "\n" +
                "- " + tr("Get API key from https://www.coze.cn")
            )
            config.coze["api_key"] = coze_api_key

        # Voice Volume setting
        params.voice_volume = st.selectbox(
            tr("Speech Volume"),
            options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0],
            index=10,  # Default to 1.0
        )

        # Voice Rate setting
        params.voice_rate = st.selectbox(
            tr("Speech Rate"),
            options=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0],
            index=5,  # Default to 1.0
        )

        # Background Music settings
        bgm_options = [
            (tr("No Background Music"), ""),
            (tr("Random Background Music"), "random"),
            (tr("Custom Background Music"), "custom"),
        ]
        selected_index = st.selectbox(
            tr("Background Music"),
            options=range(len(bgm_options)),
            format_func=lambda x: bgm_options[x][0],
            index=0,
        )
        params.bgm_type = bgm_options[selected_index][1]

        if params.bgm_type == "custom":
            # 创建一个空列表来存储上传的文件
            uploaded_files = st.file_uploader(
                tr("Upload Background Music"),
                accept_multiple_files=True,
                type=["mp3", "wav", "ogg"],
                key="bgm_uploader",
            )

            # 处理上传的文件
            if uploaded_files:
                # 清空之前的文件信息
                st.session_state["uploaded_file_info"] = []
                
                for uploaded_file in uploaded_files:
                    # 检查文件大小（限制为50MB）
                    if uploaded_file.size > 50 * 1024 * 1024:
                        st.warning(f"{uploaded_file.name} {tr('is too large, please upload files smaller than 50MB')}")
                        continue
                    
                    # 保存文件到临时目录
                    temp_dir = utils.storage_dir("temp", create=True)
                    file_path = os.path.join(temp_dir, uploaded_file.name)
                    
                    # 写入文件
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    # 记录文件信息
                    st.session_state["uploaded_file_info"].append(
                        {
                            "name": uploaded_file.name,
                            "type": uploaded_file.type,
                            "size": uploaded_file.size,
                            "path": file_path,
                        }
                    )
                
                # 显示上传的文件列表
                st.write(tr("Uploaded Files:"))
                for file_info in st.session_state["uploaded_file_info"]:
                    st.write(f"- {file_info['name']} ({file_info['size']} bytes)")
            
            # 保存上传的文件路径到参数
            if "uploaded_file_info" in st.session_state and st.session_state["uploaded_file_info"]:
                # 使用第一个上传的文件作为bgm_file
                params.bgm_file = st.session_state["uploaded_file_info"][0]["path"]
            else:
                params.bgm_file = ""
        else:
            # 如果不是自定义音乐，清空上传的文件信息
            if "uploaded_file_info" in st.session_state:
                st.session_state["uploaded_file_info"] = []
            params.bgm_file = ""

        params.bgm_volume = st.selectbox(
            tr("Background Music Volume"),
            options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            index=2,
        )
