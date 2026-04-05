import os
import platform
import sys
from uuid import uuid4

import streamlit as st
from loguru import logger

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.config import config
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import llm, voice
from app.services import task as tm
from app.utils import utils
from webui.ui_audio_components import render_audio_settings
from webui.ui_video_components import render_video_settings
from webui.ui_subtitle_components import render_subtitle_settings
from webui.ui_script_components import render_script_settings
from webui.ui_video_integration import render_video_integration_panel

st.set_page_config(
    page_title="MoneyPrinterTurbo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        "Report a bug": "https://github.com/harry0703/MoneyPrinterTurbo/issues",
        "About": "# MoneyPrinterTurbo\nSimply provide a topic or keyword for a video, and it will "
        "automatically generate the video copy, video materials, video subtitles, "
        "and video background music before synthesizing a high-definition short "
        "video.\n\nhttps://github.com/harry0703/MoneyPrinterTurbo",
    },
)


streamlit_style = """
<style>
h1 {
    padding-top: 0 !important;
}
/* Reduce button font size globally */
.stButton > button {
    font-size: 0.7rem !important;
}
/* Reduce dropdown option font size */
.stSelectbox select {
    font-size: 0.7rem !important;
}
/* Reduce dropdown menu font size */
[role="listbox"] {
    font-size: 0.7rem !important;
}
</style>
"""

st.markdown(streamlit_style, unsafe_allow_html=True)

# Define resource directories
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
system_locale = utils.get_system_locale()


if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = config.ui.get("language", system_locale)

# Load language files
locales = utils.load_locales(i18n_dir)

# Create a top bar with title and language selection
title_col, lang_col = st.columns([3, 1])

with title_col:
    st.title(f"{config.project_name} v{config.project_version}")

with lang_col:
    display_languages = []
    selected_index = 0
    for i, code in enumerate(locales.keys()):
        display_languages.append(f"{code} - {locales[code].get('Language')}")
        if code == st.session_state.get("ui_language", ""):
            selected_index = i

    selected_language = st.selectbox(
        "Language / 语言",
        options=display_languages,
        index=selected_index,
        key="top_language_selector",
        label_visibility="collapsed",
    )
    if selected_language:
        code = selected_language.split(" - ")[0].strip()
        st.session_state["ui_language"] = code
        config.ui["language"] = code

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


def get_all_songs():
    songs = []
    for root, dirs, files in os.walk(song_dir):
        for file in files:
            if file.endswith(".mp3"):
                songs.append(file)
    return songs


def open_task_folder(task_id):
    try:
        sys = platform.system()
        path = os.path.join(root_dir, "storage", "tasks", task_id)
        if os.path.exists(path):
            if sys == "Windows":
                os.system(f"start {path}")
            if sys == "Darwin":
                os.system(f"open {path}")
    except Exception as e:
        logger.error(e)


def scroll_to_bottom():
    js = """
    <script>
        console.log("scroll_to_bottom");
        function scroll(dummy_var_to_force_repeat_execution){
            var sections = parent.document.querySelectorAll('section.main');
            console.log(sections);
            for(let index = 0; index<sections.length; index++) {
                sections[index].scrollTop = sections[index].scrollHeight;
            }
        }
        scroll(1);
    </script>
    """
    st.components.v1.html(js, height=0, width=0)


def init_log():
    logger.remove()
    _lvl = "INFO"

    def format_record(record):
        # 获取日志记录中的文件全路径
        file_path = record["file"].path
        # 将绝对路径转换为相对于项目根目录的路径
        relative_path = os.path.relpath(file_path, root_dir)
        # 更新记录中的文件路径
        record["file"].path = f"./{relative_path}"
        # 返回修改后的格式字符串
        # 您可以根据需要调整这里的格式
        record["message"] = record["message"].replace(root_dir, ".")

        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    # Set timezone to local time
    import os
    import datetime
    import pytz
    
    # Try to get timezone from host system
    def get_host_timezone():
        # Try to read from /etc/timezone (Linux/Mac)
        try:
            with open('/etc/timezone', 'r') as f:
                return f.read().strip()
        except Exception:
            pass
        
        # Try to get from environment variable
        tz_name = os.environ.get('TZ')
        if tz_name:
            return tz_name
        
        # Default to local timezone
        return 'Asia/Shanghai'
    
    # Get timezone
    tz_name = get_host_timezone()
    try:
        local_tz = pytz.timezone(tz_name)
    except pytz.exceptions.UnknownTimeZoneError:
        local_tz = pytz.timezone('Asia/Shanghai')
    
    # Create a custom format that includes local timezone
    def format_record_with_timezone(record):
        # Get local time
        local_time = record['time'].astimezone(local_tz)
        # Get function name, handle <module> case
        function_name = record['function']
        if function_name == '<module>':
            function_name = 'module'
        # Update record with processed values
        record['time'] = local_time
        record['function'] = function_name
        # Return format string
        return "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    
    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record_with_timezone,
        colorize=True
    )


init_log()

locales = utils.load_locales(i18n_dir)


def tr(key):
    loc = locales.get(st.session_state["ui_language"], {})
    return loc.get("Translation", {}).get(key, key)


# 创建基础设置折叠框
if not config.app.get("hide_config", False):
    with st.expander(tr("Basic Settings"), expanded=False):
        config_panels = st.columns(3)
        left_config_panel = config_panels[0]
        middle_config_panel = config_panels[1]
        right_config_panel = config_panels[2]

        # 左侧面板 - 日志设置
        with left_config_panel:
            # 是否隐藏配置面板
            hide_config = st.checkbox(
                tr("Hide Basic Settings"), value=config.app.get("hide_config", False)
            )
            config.app["hide_config"] = hide_config

            # 是否禁用日志显示
            hide_log = st.checkbox(
                tr("Hide Log"), value=config.ui.get("hide_log", False)
            )
            config.ui["hide_log"] = hide_log

        # 中间面板 - LLM 设置

        with middle_config_panel:
            st.write(tr("LLM Settings"))
            llm_providers = [
                "OpenAI",
                "Moonshot",
                "Azure",
                "Qwen",
                "DeepSeek",
                "ModelScope",
                "Gemini",
                "Ollama",
                "G4f",
                "OneAPI",
                "Cloudflare",
                "ERNIE",
                "Pollinations",
            ]
            saved_llm_provider = config.app.get("llm_provider", "OpenAI").lower()
            saved_llm_provider_index = 0
            for i, provider in enumerate(llm_providers):
                if provider.lower() == saved_llm_provider:
                    saved_llm_provider_index = i
                    break

            llm_provider = st.selectbox(
                tr("LLM Provider"),
                options=llm_providers,
                index=saved_llm_provider_index,
            )
            llm_helper = st.container()
            llm_provider = llm_provider.lower()
            config.app["llm_provider"] = llm_provider

            llm_api_key = config.app.get(f"{llm_provider}_api_key", "")
            llm_secret_key = config.app.get(
                f"{llm_provider}_secret_key", ""
            )  # only for baidu ernie
            llm_base_url = config.app.get(f"{llm_provider}_base_url", "")
            llm_model_name = config.app.get(f"{llm_provider}_model_name", "")
            llm_account_id = config.app.get(f"{llm_provider}_account_id", "")

            tips = ""
            if llm_provider == "ollama":
                if not llm_model_name:
                    llm_model_name = "qwen:7b"
                if not llm_base_url:
                    llm_base_url = "http://localhost:11434/v1"

                with llm_helper:
                    tips = """
                            ##### Ollama配置说明
                            - **API Key**: 随便填写，比如 123
                            - **Base Url**: 一般为 http://localhost:11434/v1
                                - 如果 `MoneyPrinterTurbo` 和 `Ollama` **不在同一台机器上**，需要填写 `Ollama` 机器的IP地址
                                - 如果 `MoneyPrinterTurbo` 是 `Docker` 部署，建议填写 `http://host.docker.internal:11434/v1`
                            - **Model Name**: 使用 `ollama list` 查看，比如 `qwen:7b`
                            """

            if llm_provider == "openai":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                            ##### OpenAI 配置说明
                            > 需要VPN开启全局流量模式
                            - **API Key**: [点击到官网申请](https://platform.openai.com/api-keys)
                            - **Base Url**: 可以留空
                            - **Model Name**: 填写**有权限**的模型，[点击查看模型列表](https://platform.openai.com/settings/organization/limits)
                            """

            if llm_provider == "moonshot":
                if not llm_model_name:
                    llm_model_name = "moonshot-v1-8k"
                with llm_helper:
                    tips = """
                            ##### Moonshot 配置说明
                            - **API Key**: [点击到官网申请](https://platform.moonshot.cn/console/api-keys)
                            - **Base Url**: 固定为 https://api.moonshot.cn/v1
                            - **Model Name**: 比如 moonshot-v1-8k，[点击查看模型列表](https://platform.moonshot.cn/docs/intro#%E6%A8%A1%E5%9E%8B%E5%88%97%E8%A1%A8)
                            """
            if llm_provider == "oneapi":
                if not llm_model_name:
                    llm_model_name = (
                        "claude-3-5-sonnet-20240620"  # 默认模型，可以根据需要调整
                    )
                with llm_helper:
                    tips = """
                        ##### OneAPI 配置说明
                        - **API Key**: 填写您的 OneAPI 密钥
                        - **Base Url**: 填写 OneAPI 的基础 URL
                        - **Model Name**: 填写您要使用的模型名称，例如 claude-3-5-sonnet-20240620
                        """

            if llm_provider == "qwen":
                if not llm_model_name:
                    llm_model_name = "qwen-max"
                with llm_helper:
                    tips = """
                            ##### 通义千问Qwen 配置说明
                            - **API Key**: [点击到官网申请](https://dashscope.console.aliyun.com/apiKey)
                            - **Base Url**: 留空
                            - **Model Name**: 比如 qwen-max，[点击查看模型列表](https://help.aliyun.com/zh/dashscope/developer-reference/model-introduction#3ef6d0bcf91wy)
                            """

            if llm_provider == "g4f":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                            ##### gpt4free 配置说明
                            > [GitHub开源项目](https://github.com/xtekky/gpt4free)，可以免费使用GPT模型，但是**稳定性较差**
                            - **API Key**: 随便填写，比如 123
                            - **Base Url**: 留空
                            - **Model Name**: 比如 gpt-3.5-turbo，[点击查看模型列表](https://github.com/xtekky/gpt4free/blob/main/g4f/models.py#L308)
                            """
            if llm_provider == "azure":
                with llm_helper:
                    tips = """
                            ##### Azure 配置说明
                            > [点击查看如何部署模型](https://learn.microsoft.com/zh-cn/azure/ai-services/openai/how-to/create-resource)
                            - **API Key**: [点击到Azure后台创建](https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/OpenAI)
                            - **Base Url**: 留空
                            - **Model Name**: 填写你实际的部署名
                            """

            if llm_provider == "gemini":
                if not llm_model_name:
                    llm_model_name = "gemini-1.0-pro"

                with llm_helper:
                    tips = """
                            ##### Gemini 配置说明
                            > 需要VPN开启全局流量模式
                            - **API Key**: [点击到官网申请](https://ai.google.dev/)
                            - **Base Url**: 留空
                            - **Model Name**: 比如 gemini-1.0-pro
                            """

            if llm_provider == "deepseek":
                if not llm_model_name:
                    llm_model_name = "deepseek-chat"
                if not llm_base_url:
                    llm_base_url = "https://api.deepseek.com"
                with llm_helper:
                    tips = """
                            ##### DeepSeek 配置说明
                            - **API Key**: [点击到官网申请](https://platform.deepseek.com/api_keys)
                            - **Base Url**: 固定为 https://api.deepseek.com
                            - **Model Name**: 固定为 deepseek-chat
                            """

            if llm_provider == "modelscope":
                if not llm_model_name:
                    llm_model_name = "Qwen/Qwen3-32B"
                if not llm_base_url:
                    llm_base_url = "https://api-inference.modelscope.cn/v1/"
                with llm_helper:
                    tips = """
                            ##### ModelScope 配置说明
                            - **API Key**: [点击到官网申请](https://modelscope.cn/docs/model-service/API-Inference/intro)
                            - **Base Url**: 固定为 https://api-inference.modelscope.cn/v1/
                            - **Model Name**: 比如 Qwen/Qwen3-32B，[点击查看模型列表](https://modelscope.cn/models?filter=inference_type&page=1)
                            """

            if llm_provider == "ernie":
                with llm_helper:
                    tips = """
                            ##### 百度文心一言 配置说明
                            - **API Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                            - **Secret Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                            - **Base Url**: 填写 **请求地址** [点击查看文档](https://cloud.baidu.com/doc/WENXINWORKSHOP/s/jlil56u11#%E8%AF%B7%E6%B1%82%E8%AF%B4%E6%98%8E)
                            """

            if llm_provider == "pollinations":
                if not llm_model_name:
                    llm_model_name = "default"
                with llm_helper:
                    tips = """
                            ##### Pollinations AI Configuration
                            - **API Key**: Optional - Leave empty for public access
                            - **Base Url**: Default is https://text.pollinations.ai/openai
                            - **Model Name**: Use 'openai-fast' or specify a model name
                            """

            if tips and config.ui["language"] == "zh":
                st.warning(
                    "中国用户建议使用 **DeepSeek** 或 **Moonshot** 作为大模型提供商\n- 国内可直接访问，不需要VPN \n- 注册就送额度，基本够用"
                )
                st.info(tips)

            st_llm_api_key = st.text_input(
                tr("API Key"), value=llm_api_key, type="password"
            )
            st_llm_base_url = st.text_input(tr("Base Url"), value=llm_base_url)
            st_llm_model_name = ""
            if llm_provider != "ernie":
                st_llm_model_name = st.text_input(
                    tr("Model Name"),
                    value=llm_model_name,
                    key=f"{llm_provider}_model_name_input",
                )
                if st_llm_model_name:
                    config.app[f"{llm_provider}_model_name"] = st_llm_model_name
            else:
                st_llm_model_name = None

            if st_llm_api_key:
                config.app[f"{llm_provider}_api_key"] = st_llm_api_key
            if st_llm_base_url:
                config.app[f"{llm_provider}_base_url"] = st_llm_base_url
            if st_llm_model_name:
                config.app[f"{llm_provider}_model_name"] = st_llm_model_name
            if llm_provider == "ernie":
                st_llm_secret_key = st.text_input(
                    tr("Secret Key"), value=llm_secret_key, type="password"
                )
                config.app[f"{llm_provider}_secret_key"] = st_llm_secret_key

            if llm_provider == "cloudflare":
                st_llm_account_id = st.text_input(
                    tr("Account ID"), value=llm_account_id
                )
                if st_llm_account_id:
                    config.app[f"{llm_provider}_account_id"] = st_llm_account_id

        # 右侧面板 - API 密钥设置
        with right_config_panel:

            def get_keys_from_config(cfg_key):
                api_keys = config.app.get(cfg_key, [])
                if isinstance(api_keys, str):
                    api_keys = [api_keys]
                api_key = ", ".join(api_keys)
                return api_key

            def save_keys_to_config(cfg_key, value):
                value = value.replace(" ", "")
                if value:
                    config.app[cfg_key] = value.split(",")

            st.write(tr("Video Source Settings"))

            pexels_api_key = get_keys_from_config("pexels_api_keys")
            pexels_api_key = st.text_input(
                tr("Pexels API Key"), value=pexels_api_key, type="password"
            )
            save_keys_to_config("pexels_api_keys", pexels_api_key)

            pixabay_api_key = get_keys_from_config("pixabay_api_keys")
            pixabay_api_key = st.text_input(
                tr("Pixabay API Key"), value=pixabay_api_key, type="password"
            )
            save_keys_to_config("pixabay_api_keys", pixabay_api_key)

            # Whisper settings
            st.write(tr("Whisper Settings"))
            
            # Device selection - 使用key参数让Streamlit自动管理状态
            whisper_devices = ["CPU", "GPU", "auto"]
            saved_device = config.whisper.get("device", "CPU")
            
            # 初始化session_state
            if "whisper_device" not in st.session_state:
                st.session_state["whisper_device"] = saved_device
            
            selected_device = st.selectbox(
                tr("Whisper Device"),
                options=whisper_devices,
                key="whisper_device"
            )
            
            # 检查值是否变化
            if selected_device != saved_device:
                logger.info(f"Whisper device changed from {saved_device} to {selected_device}")
                config.whisper["device"] = selected_device
                config.save_config()
                logger.info(f"Whisper device saved to config: {selected_device}")
            
            # Video Encoder GPU Acceleration - 使用key参数让Streamlit自动管理状态
            st.write(tr("Video Encoder Settings"))
            video_encoder_options = ["CPU", "GPU"]
            saved_use_gpu = config.app.get("use_gpu", False)
            saved_encoder_value = "GPU" if saved_use_gpu else "CPU"
            
            # 初始化session_state
            if "video_encoder" not in st.session_state:
                st.session_state["video_encoder"] = saved_encoder_value
            
            selected_encoder = st.selectbox(
                tr("Video Encoder"),
                options=video_encoder_options,
                key="video_encoder"
            )
            
            # 检查值是否变化
            if selected_encoder != saved_encoder_value:
                logger.info(f"Video encoder changed from {saved_encoder_value} to {selected_encoder}")
                config.app["use_gpu"] = (selected_encoder == "GPU")
                config.save_config()
                logger.info(f"Video encoder saved to config: {selected_encoder} (use_gpu={config.app.get('use_gpu')})")

llm_provider = config.app.get("llm_provider", "").lower()
panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

params = VideoParams(video_subject="")

# 初始化session state以保持文件上传状态
if "uploaded_files" not in st.session_state:
    st.session_state["uploaded_files"] = []
if "uploaded_file_info" not in st.session_state:
    st.session_state["uploaded_file_info"] = []

uploaded_files = []

with left_panel:
    params = render_script_settings(params, tr, llm)
        


with middle_panel:
    # Render video settings component
    uploaded_files = render_video_settings(params, config, uploaded_files, tr)
    # Render audio settings component
    render_audio_settings(params)

with right_panel:
    # Render subtitle settings component
    render_subtitle_settings(params, config, tr)
    
    # Render video integration panel
    render_video_integration_panel(tr)
    
    with st.expander(tr("Click to show API Key management"), expanded=False):
        st.subheader(tr("Manage Pexels and Pixabay API Keys"))

        col1, col2 = st.tabs(["Pexels API Keys", "Pixabay API Keys"])

        with col1:
            st.subheader("Pexels API Keys")
            if config.app["pexels_api_keys"]:
                st.write(tr("Current Keys:"))
                for key in config.app["pexels_api_keys"]:
                    st.code(key)
            else:
                st.info(tr("No Pexels API Keys currently"))

            new_key = st.text_input(tr("Add Pexels API Key"), key="pexels_new_key")
            if st.button(tr("Add Pexels API Key")):
                if new_key and new_key not in config.app["pexels_api_keys"]:
                    config.app["pexels_api_keys"].append(new_key)
                    config.save_config()
                    st.success(tr("Pexels API Key added successfully"))
                elif new_key in config.app["pexels_api_keys"]:
                    st.warning(tr("This API Key already exists"))
                else:
                    st.error(tr("Please enter a valid API Key"))

            if config.app["pexels_api_keys"]:
                delete_key = st.selectbox(
                    tr("Select Pexels API Key to delete"), config.app["pexels_api_keys"], key="pexels_delete_key"
                )
                if st.button(tr("Delete Selected Pexels API Key")):
                    config.app["pexels_api_keys"].remove(delete_key)
                    config.save_config()
                    st.success(tr("Pexels API Key deleted successfully"))

        with col2:
            st.subheader("Pixabay API Keys")

            if config.app["pixabay_api_keys"]:
                st.write(tr("Current Keys:"))
                for key in config.app["pixabay_api_keys"]:
                    st.code(key)
            else:
                st.info(tr("No Pixabay API Keys currently"))

            new_key = st.text_input(tr("Add Pixabay API Key"), key="pixabay_new_key")
            if st.button(tr("Add Pixabay API Key")):
                if new_key and new_key not in config.app["pixabay_api_keys"]:
                    config.app["pixabay_api_keys"].append(new_key)
                    config.save_config()
                    st.success(tr("Pixabay API Key added successfully"))
                elif new_key in config.app["pixabay_api_keys"]:
                    st.warning(tr("This API Key already exists"))
                else:
                    st.error(tr("Please enter a valid API Key"))

            if config.app["pixabay_api_keys"]:
                delete_key = st.selectbox(
                    tr("Select Pixabay API Key to delete"), config.app["pixabay_api_keys"], key="pixabay_delete_key"
                )
                if st.button(tr("Delete Selected Pixabay API Key")):
                    config.app["pixabay_api_keys"].remove(delete_key)
                    config.save_config()
                    st.success(tr("Pixabay API Key deleted successfully"))

start_button = st.button(tr("Generate Video"), use_container_width=True, type="primary")
if start_button:
    config.save_config()
    task_id = str(uuid4())
    
    # 层级递进校验逻辑
    # 1. 检查是否有场景信息
    has_scenes = st.session_state.get("scenes") and len(st.session_state["scenes"]) > 0
    
    # 2. 如果没有场景信息，检查是否有视频文案
    has_script = params.video_script and params.video_script.strip()
    
    # 3. 如果没有视频文案，检查是否有视频主题
    has_subject = params.video_subject and params.video_subject.strip()
    
    if not has_scenes and not has_script and not has_subject:
        st.error("请至少提供视频主题、视频文案或场景信息之一")
        scroll_to_bottom()
        st.stop()
    
    # 自动补全逻辑
    if not has_scenes:
        if has_script:
            # 有文案但没有场景，自动触发智能脚本解析
            st.info("正在自动解析文案为场景...")
            try:
                from app.services.scene_parser import auto_parse_script
                result = auto_parse_script(params.video_script, auto_mode=True)
                if result["status"] in ["success", "manual"] and result["scenes"]:
                    st.session_state["scenes"] = result["scenes"]
                    st.success(f"成功解析为 {len(result['scenes'])} 个场景")
                    has_scenes = True
                else:
                    st.error(f"文案解析失败: {result.get('message', '请检查文案格式')}")
                    scroll_to_bottom()
                    st.stop()
            except Exception as e:
                st.error(f"解析失败: {str(e)}")
                scroll_to_bottom()
                st.stop()
        elif has_subject:
            # 只有主题，先自动生成文案，再解析为场景
            st.info("正在基于主题生成文案...")
            try:
                # 使用LLM基于主题生成文案
                generated_script = llm.generate_script(
                    subject=params.video_subject,
                    language=config.ui.get("language", "zh"),
                    length=300  # 默认长度
                )
                if generated_script:
                    params.video_script = generated_script
                    st.session_state["video_script"] = generated_script
                    st.success("文案生成成功")
                    
                    # 然后解析为场景
                    st.info("正在自动解析文案为场景...")
                    from app.services.scene_parser import auto_parse_script
                    result = auto_parse_script(generated_script, auto_mode=True)
                    if result["status"] in ["success", "manual"] and result["scenes"]:
                        st.session_state["scenes"] = result["scenes"]
                        st.success(f"成功解析为 {len(result['scenes'])} 个场景")
                        has_scenes = True
                    else:
                        st.error(f"文案解析失败: {result.get('message', '未知错误')}")
                        scroll_to_bottom()
                        st.stop()
                else:
                    st.error("文案生成失败，请检查LLM配置")
                    scroll_to_bottom()
                    st.stop()
            except Exception as e:
                st.error(f"生成失败: {str(e)}")
                scroll_to_bottom()
                st.stop()

    if params.video_source not in ["pexels", "pixabay", "local"]:
        st.error(tr("Please Select a Valid Video Source"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pexels" and not config.app.get("pexels_api_keys", ""):
        st.error(tr("Please Enter the Pexels API Key"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pixabay" and not config.app.get("pixabay_api_keys", ""):
        st.error(tr("Please Enter the Pixabay API Key"))
        scroll_to_bottom()
        st.stop()

    # 调试日志：检查uploaded_files的状态
    logger.info(f"uploaded_files type: {type(uploaded_files)}")
    logger.info(f"uploaded_files length: {len(uploaded_files) if uploaded_files else 0}")
    logger.info(f"session_state uploaded_files: {len(st.session_state.get('uploaded_files', []))}")
    logger.info(f"session_state uploaded_file_info: {st.session_state.get('uploaded_file_info', [])}")
    
    # 总是优先使用session state中保存的文件路径
    if st.session_state.get("uploaded_files"):
        uploaded_files = st.session_state["uploaded_files"]
        logger.info(f"Using uploaded_files from session_state: {len(uploaded_files)} files")
    else:
        # 检查uploaded_files是否包含UploadedFile对象
        if uploaded_files and hasattr(uploaded_files[0], 'name'):
            # 这是新上传的文件，需要保存
            local_videos_dir = utils.storage_dir("local_videos", create=True)
            saved_files = []
            file_info_list = []
            for file in uploaded_files:
                try:
                    import uuid
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
                uploaded_files = saved_files
                st.success(f"Successfully uploaded {len(saved_files)} files")
            else:
                # 如果没有成功保存的文件，将uploaded_files设置为None
                uploaded_files = None

    if uploaded_files:
        material_list = []
        success_count = 0
        for item in uploaded_files:
            try:
                # 检查item是否是UploadedFile对象
                if hasattr(item, 'file_id') or (hasattr(item, 'name') and not isinstance(item, str)):
                    # 这是UploadedFile对象，需要先保存
                    local_videos_dir = utils.storage_dir("local_videos", create=True)
                    import uuid
                    unique_id = str(uuid.uuid4())
                    file_path = os.path.join(local_videos_dir, f"{unique_id}_{item.name}")
                    with open(file_path, "wb") as f:
                        f.write(item.getbuffer())
                    logger.info(f"Processed UploadedFile saved to: {file_path}")
                else:
                    # 这是文件路径
                    file_path = item
                
                # 检查文件是否存在
                if os.path.exists(file_path):
                    # 创建 MaterialInfo 对象
                    m = MaterialInfo()
                    m.provider = "local"
                    m.url = file_path
                    material_list.append(m)
                    success_count += 1
                    logger.info(f"Using uploaded file: {file_path}")
                else:
                    logger.error(f"Uploaded file not found: {file_path}")
            except Exception as e:
                logger.error(f"Failed to process uploaded file: {str(e)}")
                st.error(f"Failed to process file: {str(e)}")
        
        if material_list:
            # 直接修改__dict__绕过Pydantic验证
            if not hasattr(params, 'video_materials'):
                params.__dict__['video_materials'] = []
            params.__dict__['video_materials'] = material_list
            logger.info(f"Total {success_count} files processed successfully")
            logger.info(f"params.video_materials count: {len(params.__dict__['video_materials'])}")
            st.success(f"Successfully processed {success_count} files")
        else:
            logger.warning("No files were successfully processed")
            st.warning("No files were successfully processed")
    else:
        logger.warning("uploaded_files is None or empty")
        st.warning("No files were uploaded")

    # Handle multi-scene data - always enabled
    if st.session_state.get("scenes"):
        # Add scenes to params - directly use user-created scenes
        params.scenes = st.session_state["scenes"]
        
        # Generate combined script from scenes for display purposes only
        combined_script = ""
        for i, scene in enumerate(st.session_state["scenes"]):
            combined_script += f"[Scene {i+1}]\n"
            combined_script += f"Duration: {scene['duration']}s\n"
            combined_script += f"Visual: {scene['visual_requirement']}\n"
            combined_script += f"Script: {scene['script']}\n\n"
        
        # Set video_script to empty to prevent re-conversion in task.py
        # When video_script is empty, task.py will use params.scenes directly
        params.video_script = ""
        
        # Generate combined keywords from scenes
        combined_keywords = []
        for scene in st.session_state["scenes"]:
            if scene.get("keywords"):
                combined_keywords.extend([kw.strip() for kw in scene["keywords"].split(",")])
        params.video_terms = ", ".join(combined_keywords)
    else:
        # Auto-create a single scene from video_script if no scenes defined
        # This maps the old "无场景模式" to a single scene in multi-scene architecture
        if st.session_state.get("video_script", "").strip():
            auto_scene = {
                "id": str(uuid4()),
                "script": st.session_state["video_script"],
                "visual_requirement": "",
                "keywords": st.session_state.get("video_terms", ""),
                "duration": 30  # Default duration
            }
            st.session_state["scenes"] = [auto_scene]
            params.scenes = st.session_state["scenes"]

    # Initialize log container and session state for logs
    log_container = st.empty()
    if "log_records" not in st.session_state:
        st.session_state["log_records"] = []
    
    # Clear previous logs at the start of video generation
    st.session_state["log_records"] = []
    
    def log_received(msg):
        if config.ui["hide_log"]:
            return
        # Check if session_state is available and initialized
        try:
            if "log_records" not in st.session_state:
                return
        except Exception:
            # Session state not available (e.g., during thread execution)
            return
        
        # Extract log message from loguru Record object
        if hasattr(msg, 'message'):
            log_message = str(msg.message)
        else:
            log_message = str(msg)
        
        # Add to session state
        st.session_state["log_records"].append(log_message)
        
        # Update UI (limit to last 100 lines to prevent performance issues)
        with log_container:
            log_text = "\n".join(st.session_state["log_records"][-100:])
            st.code(log_text)

    # Add log handler and save handler ID for cleanup
    log_handler_id = logger.add(log_received)

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    result = tm.start(task_id=task_id, params=params)
    
    # Remove the log handler to prevent memory leaks and page reload issues
    try:
        logger.remove(log_handler_id)
    except ValueError:
        # Handler already removed, ignore
        pass
    
    if not result or "videos" not in result:
        st.error(tr("Video Generation Failed"))
        logger.error(tr("Video Generation Failed"))
        scroll_to_bottom()
        st.stop()

    video_files = result.get("videos", [])
    st.success(tr("Video Generation Completed"))
    try:
        if video_files:
            player_cols = st.columns(len(video_files) * 2 + 1)
            for i, url in enumerate(video_files):
                player_cols[i * 2 + 1].video(url)
    except Exception:
        pass

    open_task_folder(task_id)
    logger.info(tr("Video Generation Completed"))
    scroll_to_bottom()

config.save_config()