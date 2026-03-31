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
</style>
"""
st.markdown(streamlit_style, unsafe_allow_html=True)

# Define resource directories
font_dir = os.path.join(root_dir, "resource", "fonts")
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


def get_all_fonts():
    fonts = []
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
    fonts.sort()
    return fonts


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
        # Format the record with local time
        _format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        return _format.format(
            time=local_time,
            level=record['level'].name,
            name=record['name'],
            function=record['function'],
            line=record['line'],
            message=record['message']
        )
    
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
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        st.session_state["video_subject"] = st.text_input(
            tr("Video Subject"),
            value=st.session_state["video_subject"],
            key="video_subject_input",
        ).strip()
        params.video_subject = st.session_state["video_subject"]

        video_languages = [
            (tr("Auto Detect"), ""),
        ]
        for code in support_locales:
            video_languages.append((code, code))

        selected_index = st.selectbox(
            tr("Script Language"),
            index=0,
            options=range(
                len(video_languages)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_languages[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_language = video_languages[selected_index][1]

        # Multi-scene mode switch
        if "multi_scene_enabled" not in st.session_state:
            st.session_state["multi_scene_enabled"] = False

        multi_scene_enabled = st.checkbox(
            tr("Enable Multi-Scene Mode"),
            value=st.session_state["multi_scene_enabled"],
            help=tr("When enabled, the video will be divided into multiple scenes, each with its own visual requirements and narration")
        )
        st.session_state["multi_scene_enabled"] = multi_scene_enabled
        params.multi_scene_enabled = multi_scene_enabled

        if st.button(
            tr("Generate Video Script and Keywords"), key="auto_generate_script"
        ):
            with st.spinner(tr("Generating Video Script and Keywords")):
                script = llm.generate_script(
                    video_subject=params.video_subject, language=params.video_language
                )
                terms = llm.generate_terms(params.video_subject, script)
                if "Error: " in script:
                    st.error(tr(script))
                elif "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_script"] = script
                    st.session_state["video_terms"] = ", ".join(terms)

        params.video_script = st.text_area(
            tr("Video Script"), value=st.session_state["video_script"], height=280
        )
        if st.button(tr("Generate Video Keywords"), key="auto_generate_terms"):
            if not params.video_script:
                st.error(tr("Please Enter the Video Subject"))
                st.stop()

            with st.spinner(tr("Generating Video Keywords")):
                terms = llm.generate_terms(params.video_subject, params.video_script)
                if "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_terms"] = ", ".join(terms)

        params.video_terms = st.text_area(
            tr("Video Keywords"), value=st.session_state["video_terms"],
            key="video_terms_single"
        )

        # Initialize scenes in session state
        if "scenes" not in st.session_state:
            st.session_state["scenes"] = []
        
        # Initialize auto-parse settings
        if "auto_parse_mode" not in st.session_state:
            st.session_state["auto_parse_mode"] = "auto"  # "auto" or "manual"

        # Multi-scene mode UI
        if multi_scene_enabled:
            st.write(tr("Scenes Management"))
            
            # Create a container with border for visible border
            with st.container(border=True):
                # Button row for import and cancel
                btn_cols = st.columns(2)
                with btn_cols[0]:
                    if st.button(tr("Import Script"), key="import_script_btn"):
                        imported_script = st.session_state.get("imported_script", "")
                        if imported_script.strip():
                            st.session_state["video_script"] = imported_script
                            st.success(tr("Script imported successfully!"))
                        else:
                            st.warning(tr("Please paste a script to import"))
                with btn_cols[1]:
                    if st.button(tr("Cancel Script"), key="cancel_script_btn"):
                        # Only clear the imported script, not the scenes
                        if "imported_script" in st.session_state:
                            st.session_state["imported_script"] = ""
                        st.info(tr("Imported script cleared"))
                
                # Display imported script area with placeholder
                imported_script = st.text_area(
                    "Script",
                    placeholder=tr("Here shows the imported script"),
                    height=150,
                    key="imported_script",
                    label_visibility="hidden"
                )
                
                # Parse mode selection - all in one line
                current_mode = st.session_state.get("auto_parse_mode", "auto")
                
                # Create a single line layout for parse mode
                st.markdown('''
                <style>
                .parse-mode-row {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                    margin: 10px 0;
                }
                </style>
                ''', unsafe_allow_html=True)
                
                # Create a single line parse mode selector using Streamlit's native radio button
                parse_mode = st.radio(
                    "解析模式",
                    options=["auto", "manual"],
                    format_func=lambda x: "完全自动" if x == "auto" else "手动确认",
                    index=0,
                    key="parse_mode_radio",
                    horizontal=True
                )
                st.session_state["auto_parse_mode"] = parse_mode
                
                # Parse button
                if st.button(tr("Parse Current Script"), key="parse_script_btn"):
                    if not st.session_state.get("video_script", "").strip():
                        st.warning(tr("Please enter a script first"))
                    else:
                        with st.spinner(tr("Parsing script...")):
                            from app.services.scene_parser import auto_parse_script, format_evaluation_result
                            
                            result = auto_parse_script(
                                st.session_state["video_script"],
                                max_retries=3,
                                auto_mode=(parse_mode == "auto")
                            )
                            
                            if result["status"] == "success":
                                # Auto-accepted
                                st.session_state["scenes"] = result["scenes"]
                                st.success(tr(f"Successfully parsed {len(result['scenes'])} scenes (Score: {result['evaluation']['total_score']:.0f})"))
                                st.rerun()
                            elif result["status"] == "manual":
                                # Need user confirmation
                                st.session_state["pending_scenes"] = result["scenes"]
                                st.session_state["pending_evaluation"] = result["evaluation"]
                                st.info(tr("Please review the parsed scenes below"))
                            else:
                                # Failed
                                st.error(tr(f"Parsing failed: {result.get('message', 'Unknown error')}"))
                
                st.divider()
                
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
                    <div style="display: flex; align-items: center; justify-content: center; height: 200px; background-color: #f8f9fa; border-radius: 8px; border: 1px dashed #dee2e6;">
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
        


with middle_panel:
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
                "Upload Local Files",
                type=["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"],
                accept_multiple_files=True,
            )
            # 存储到 session state
            if uploaded_files is not None:
                # 立即保存文件到本地目录
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
    # Render audio settings component
    render_audio_settings(params)

with right_panel:
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=config.ui.get("subtitle_enabled", True))
        config.ui["subtitle_enabled"] = params.subtitle_enabled
        font_names = get_all_fonts()
        saved_font_name = config.ui.get("font_name", "MicrosoftYaHeiBold.ttc")
        saved_font_name_index = 0
        if saved_font_name in font_names:
            saved_font_name_index = font_names.index(saved_font_name)
        params.font_name = st.selectbox(
            tr("Font"), font_names, index=saved_font_name_index
        )
        config.ui["font_name"] = params.font_name

        subtitle_positions = [
            (tr("Top"), "top"),
            (tr("Center"), "center"),
            (tr("Bottom"), "bottom"),
            (tr("Custom"), "custom"),
        ]
        # Get saved position from config or use default
        saved_position = config.ui.get("subtitle_position", "bottom")
        # Find the index of the saved position
        selected_index = 2  # Default to bottom
        for i, (_, value) in enumerate(subtitle_positions):
            if value == saved_position:
                selected_index = i
                break
        selected_index = st.selectbox(
            tr("Position"),
            index=selected_index,
            options=range(len(subtitle_positions)),
            format_func=lambda x: subtitle_positions[x][0],
        )
        params.subtitle_position = subtitle_positions[selected_index][1]
        config.ui["subtitle_position"] = params.subtitle_position

        if params.subtitle_position == "custom":
            saved_custom_position = config.ui.get("subtitle_custom_position", 70.0)
            custom_position = st.text_input(
                tr("Custom Position (% from top)"),
                value=str(saved_custom_position),
                key="custom_position_input",
            )
            try:
                params.custom_position = float(custom_position)
                if params.custom_position < 0 or params.custom_position > 100:
                    st.error(tr("Please enter a value between 0 and 100"))
                else:
                    config.ui["subtitle_custom_position"] = params.custom_position
            except ValueError:
                st.error(tr("Please enter a valid number"))

        font_cols = st.columns([0.3, 0.7])
        with font_cols[0]:
            saved_text_fore_color = config.ui.get("text_fore_color", "#FFFFFF")
            params.text_fore_color = st.color_picker(
                tr("Font Color"), saved_text_fore_color
            )
            config.ui["text_fore_color"] = params.text_fore_color

        with font_cols[1]:
            saved_font_size = config.ui.get("font_size", 60)
            params.font_size = st.slider(tr("Font Size"), 30, 100, saved_font_size)
            config.ui["font_size"] = params.font_size

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            saved_stroke_color = config.ui.get("stroke_color", "#000000")
            params.stroke_color = st.color_picker(tr("Stroke Color"), saved_stroke_color)
            config.ui["stroke_color"] = params.stroke_color
        with stroke_cols[1]:
            saved_stroke_width = config.ui.get("stroke_width", 1.5)
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, saved_stroke_width)
            config.ui["stroke_width"] = params.stroke_width
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
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
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