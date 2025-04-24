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
    print("******** sys.path ********")
    print(sys.path)
    print("")

from app.config import config
from app.models.const import FILE_TYPE_IMAGES, FILE_TYPE_VIDEOS
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


hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

st.title(f"MoneyPrinterTurbo v{config.project_version}")

support_locales = [
    "zh-CN",
    "zh-HK",
    "zh-TW",
    "de-DE",
    "en-US",
    "fr-FR",
    "vi-VN",
    "th-TH",
]

font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
system_locale = utils.get_system_locale()
# print(f"******** system locale: {system_locale} ********")


def get_all_fonts():
    fonts = []
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
    fonts.sort()
    return fonts


if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = config.ui.get("language", system_locale)


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
    # 使用st.markdown代替st.components.v1.html
    st.markdown(js, unsafe_allow_html=True)


def load_font_css():
    """Load all fonts from the font directory and create CSS for them"""
    css = "<style>\n"
    for font_file in get_all_fonts():
        font_name = font_file.split('.')[0]  # Remove file extension
        font_path = os.path.join(font_dir, font_file)
        # Convert font path to relative path for CSS
        css += f"@font-face {{\n"
        css += f"  font-family: '{font_name}';\n"
        css += f"  src: url('file://{font_path}') format('truetype');\n"
        css += f"}}\n"
    css += "</style>"
    return css


def init_log():
    logger.remove()
    _lvl = "DEBUG"

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

    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
    )


init_log()

locales = utils.load_locales(i18n_dir)


def tr(key):
    loc = locales.get(st.session_state["ui_language"], {})
    return loc.get("Translation", {}).get(key, key)


st.write(tr("Get Help"))

llm_provider = config.app.get("llm_provider", "").lower()

if not config.app.get("hide_config", False):
    with st.expander(tr("Basic Settings"), expanded=False):
        config_panels = st.columns(3)
        left_config_panel = config_panels[0]
        middle_config_panel = config_panels[1]
        right_config_panel = config_panels[2]
        with left_config_panel:
            display_languages = []
            selected_index = 0
            for i, code in enumerate(locales.keys()):
                display_languages.append(f"{code} - {locales[code].get('Language')}")
                if code == st.session_state["ui_language"]:
                    selected_index = i

            selected_language = st.selectbox(
                tr("Language"), options=display_languages, index=selected_index
            )
            if selected_language:
                code = selected_language.split(" - ")[0].strip()
                st.session_state["ui_language"] = code
                config.ui["language"] = code

            # 是否禁用日志显示
            hide_log = st.checkbox(
                tr("Hide Log"), value=config.app.get("hide_log", False)
            )
            config.ui["hide_log"] = hide_log

        with middle_config_panel:
            #   openai
            #   moonshot (月之暗面)
            #   oneapi
            #   g4f
            #   azure
            #   qwen (通义千问)
            #   gemini
            #   ollama
            llm_providers = [
                "OpenAI",
                "Moonshot",
                "Azure",
                "Qwen",
                "DeepSeek",
                "Gemini",
                "Ollama",
                "G4f",
                "OneAPI",
                "Cloudflare",
                "ERNIE",
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

            if llm_provider == "ernie":
                with llm_helper:
                    tips = """
                           ##### 百度文心一言 配置说明
                           - **API Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                           - **Secret Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                           - **Base Url**: 填写 **请求地址** [点击查看文档](https://cloud.baidu.com/doc/WENXINWORKSHOP/s/jlil56u11#%E8%AF%B7%E6%B1%82%E8%AF%B4%E6%98%8E)
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

panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

params = VideoParams(video_subject="")
uploaded_files = []

with left_panel:
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        params.video_subject = st.text_input(
            tr("Video Subject"), value=st.session_state["video_subject"]
        ).strip()

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
            tr("Video Keywords"), value=st.session_state["video_terms"]
        )

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
            _supported_types = FILE_TYPE_VIDEOS + FILE_TYPE_IMAGES
            uploaded_files = st.file_uploader(
                "Upload Local Files",
                type=["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"],
                accept_multiple_files=True,
            )

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
            index=1,  # 默认选择随机转场
        )
        params.video_transition_mode = VideoTransitionMode(
            video_transition_modes[selected_index][1]
        )

        video_aspect_ratios = [
            (tr("Portrait"), VideoAspect.portrait.value),
            (tr("Landscape"), VideoAspect.landscape.value),
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
            tr("Clip Duration"), options=[2, 3, 4, 5, 6, 7, 8, 9, 10], index=3
        )
        params.video_count = st.selectbox(
            tr("Number of Videos Generated Simultaneously"),
            options=[1, 2, 3, 4, 5],
            index=0,
        )
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # tts_providers = ['edge', 'azure']
        # tts_provider = st.selectbox(tr("TTS Provider"), tts_providers)

        voices = voice.get_all_azure_voices(filter_locals=support_locales)
        friendly_names = {
            v: v.replace("Female", tr("Female"))
            .replace("Male", tr("Male"))
            .replace("Neural", "")
            for v in voices
        }
        saved_voice_name = config.ui.get("voice_name", "")
        saved_voice_name_index = 0
        if saved_voice_name in friendly_names:
            saved_voice_name_index = list(friendly_names.keys()).index(saved_voice_name)
        else:
            for i, v in enumerate(voices):
                if (
                    v.lower().startswith(st.session_state["ui_language"].lower())
                    and "V2" not in v
                ):
                    saved_voice_name_index = i
                    break

        selected_friendly_name = st.selectbox(
            tr("Speech Synthesis"),
            options=list(friendly_names.values()),
            index=saved_voice_name_index,
        )

        voice_name = list(friendly_names.keys())[
            list(friendly_names.values()).index(selected_friendly_name)
        ]
        params.voice_name = voice_name
        config.ui["voice_name"] = voice_name

        if st.button(tr("Play Voice")):
            play_content = params.video_subject
            if not play_content:
                play_content = params.video_script
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
                )
                # if the voice file generation failed, try again with a default content.
                if not sub_maker:
                    play_content = "This is a example voice. if you hear this, the voice synthesis failed with the original content."
                    sub_maker = voice.tts(
                        text=play_content,
                        voice_name=voice_name,
                        voice_rate=params.voice_rate,
                        voice_file=audio_file,
                    )

                if sub_maker and os.path.exists(audio_file):
                    st.audio(audio_file, format="audio/mp3")
                    if os.path.exists(audio_file):
                        os.remove(audio_file)

        if voice.is_azure_v2_voice(voice_name):
            saved_azure_speech_region = config.azure.get("speech_region", "")
            saved_azure_speech_key = config.azure.get("speech_key", "")
            azure_speech_region = st.text_input(
                tr("Speech Region"), value=saved_azure_speech_region
            )
            azure_speech_key = st.text_input(
                tr("Speech Key"), value=saved_azure_speech_key, type="password"
            )
            config.azure["speech_region"] = azure_speech_region
            config.azure["speech_key"] = azure_speech_key

        params.voice_volume = st.selectbox(
            tr("Speech Volume"),
            options=[0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0],
            index=2,
        )

        params.voice_rate = st.selectbox(
            tr("Speech Rate"),
            options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
            index=2,
        )

        bgm_options = [
            (tr("No Background Music"), ""),
            (tr("Random Background Music"), "random"),
            (tr("Custom Background Music"), "custom"),
        ]
        selected_index = st.selectbox(
            tr("Background Music"),
            index=1,
            options=range(
                len(bgm_options)
            ),  # Use the index as the internal option value
            format_func=lambda x: bgm_options[x][
                0
            ],  # The label is displayed to the user
        )
        # Get the selected background music type
        params.bgm_type = bgm_options[selected_index][1]

        # Show or hide components based on the selection
        if params.bgm_type == "custom":
            custom_bgm_file = st.text_input(tr("Custom Background Music File"))
            if custom_bgm_file and os.path.exists(custom_bgm_file):
                params.bgm_file = custom_bgm_file
                # st.write(f":red[已选择自定义背景音乐]：**{custom_bgm_file}**")
        params.bgm_volume = st.selectbox(
            tr("Background Music Volume"),
            options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            index=2,
        )

with right_panel:
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=True)
        font_names = get_all_fonts()
        saved_font_name = config.ui.get("font_name", "")
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
        selected_index = st.selectbox(
            tr("Position"),
            index=3,  # 默认选择自定义位置
            options=range(len(subtitle_positions)),
            format_func=lambda x: subtitle_positions[x][0],
        )
        params.subtitle_position = subtitle_positions[selected_index][1]

        if params.subtitle_position == "custom":
            custom_position = st.text_input(
                tr("Custom Position (% from top)"), value="85.0"
            )
            try:
                params.custom_position = float(custom_position)
                if params.custom_position < 0 or params.custom_position > 100:
                    st.error(tr("Please enter a value between 0 and 100"))
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
            params.font_size = st.slider(tr("Font Size"), 30, 150, saved_font_size)
            config.ui["font_size"] = params.font_size

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            # 添加随机描边颜色选项
            stroke_color_options = [
                (tr("White"), "#FFFFFF"),
                (tr("Black"), "#000000"),
                (tr("Random"), "random"),
            ]
            selected_stroke_index = st.selectbox(
                tr("Stroke Color"),
                options=range(len(stroke_color_options)),
                format_func=lambda x: stroke_color_options[x][0],
                index=0,
            )
            params.stroke_color = stroke_color_options[selected_stroke_index][1]
        with stroke_cols[1]:
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, 4.0)

        # 艺术字体设置
        st.write(tr("Art Font Settings"))
        params.art_font_enabled = st.checkbox(tr("Enable Art Font"), value=False)

        if params.art_font_enabled:
            art_font_types = [
                (tr("Normal"), "normal"),
                (tr("Shadow"), "shadow"),
                (tr("Outline"), "outline"),
                (tr("3D"), "3d"),
                (tr("Neon"), "neon"),
                (tr("Metallic"), "metallic"),
            ]
            selected_index = st.selectbox(
                tr("Art Font Type"),
                index=2,  # 默认选择3D立体
                options=range(len(art_font_types)),
                format_func=lambda x: art_font_types[x][0],
            )
            params.art_font_type = art_font_types[selected_index][1]

            art_font_backgrounds = [
                (tr("None"), "none"),
                (tr("Red"), "red"),
                (tr("Blue"), "blue"),
                (tr("Green"), "green"),
                (tr("Yellow"), "yellow"),
                (tr("Purple"), "purple"),
                (tr("Orange"), "orange"),
                (tr("Custom"), "custom"),
            ]
            selected_index = st.selectbox(
                tr("Art Font Background"),
                index=0,
                options=range(len(art_font_backgrounds)),
                format_func=lambda x: art_font_backgrounds[x][0],
            )
            params.art_font_background = art_font_backgrounds[selected_index][1]

            if params.art_font_background == "custom":
                params.art_font_background = st.color_picker(tr("Custom Background Color"), "#FF0000")

            # 预览效果
            st.write(tr("Preview"))
            preview_text = tr("Art Font Preview")

            # 根据选择的艺术字体类型生成不同的CSS样式
            font_style = ""
            bg_style = "background-color: #333;"

            # 设置背景颜色
            if params.art_font_background != "none":
                if params.art_font_background == "red":
                    bg_style = "background-color: rgba(255, 0, 0, 0.7);"
                elif params.art_font_background == "blue":
                    bg_style = "background-color: rgba(0, 0, 255, 0.7);"
                elif params.art_font_background == "green":
                    bg_style = "background-color: rgba(0, 128, 0, 0.7);"
                elif params.art_font_background == "yellow":
                    bg_style = "background-color: rgba(255, 255, 0, 0.7);"
                elif params.art_font_background == "purple":
                    bg_style = "background-color: rgba(128, 0, 128, 0.7);"
                elif params.art_font_background == "orange":
                    bg_style = "background-color: rgba(255, 165, 0, 0.7);"
                elif params.art_font_background.startswith("#"):
                    # 处理自定义颜色
                    bg_style = f"background-color: {params.art_font_background}aa;"

            # 设置字体样式
            if params.art_font_type == "normal":
                font_style = f"color: {params.text_fore_color}; font-weight: bold;"
            elif params.art_font_type == "shadow":
                font_style = f"color: {params.text_fore_color}; font-weight: bold; text-shadow: 3px 3px 5px #000;"
            elif params.art_font_type == "outline":
                font_style = f"color: {params.text_fore_color}; font-weight: bold; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;"
            elif params.art_font_type == "3d":
                font_style = f"color: {params.text_fore_color}; font-weight: bold; text-shadow: 0px 1px 0px #999, 0px 2px 0px #888, 0px 3px 0px #777, 0px 4px 0px #666, 0px 5px 0px #555, 0px 6px 0px #444, 0px 7px 0px #333, 0px 8px 7px #001135;"
            elif params.art_font_type == "neon":
                font_style = f"color: {params.text_fore_color}; font-weight: bold; text-shadow: 0 0 5px #fff, 0 0 10px #fff, 0 0 15px #0073e6, 0 0 20px #0073e6, 0 0 25px #0073e6, 0 0 30px #0073e6, 0 0 35px #0073e6;"
            elif params.art_font_type == "metallic":
                font_style = f"color: {params.text_fore_color}; font-weight: bold; background: -webkit-linear-gradient(#eee, #333); -webkit-background-clip: text; -webkit-text-fill-color: transparent; text-shadow: 2px 2px 4px rgba(0,0,0,0.3);"

            # 不再需要单独的预览代码，因为我们使用了统一预览区域

        # 标题贴纸设置
        st.write(tr("Title Sticker Settings"))
        params.title_sticker_enabled = st.checkbox(tr("Enable Title Sticker"), value=True)

        if params.title_sticker_enabled:
            params.title_sticker_text = st.text_input(tr("Title Text"), value="")

            # 标题贴纸字体选择
            title_font_names = get_all_fonts()
            saved_title_font_name = config.ui.get("title_sticker_font", params.font_name)
            saved_title_font_index = 0
            if saved_title_font_name in title_font_names:
                saved_title_font_index = title_font_names.index(saved_title_font_name)
            params.title_sticker_font = st.selectbox(
                tr("Title Font"), title_font_names, index=saved_title_font_index, key="title_font_select"
            )
            config.ui["title_sticker_font"] = params.title_sticker_font

            # 标题贴纸字体大小
            saved_title_font_size = config.ui.get("title_sticker_font_size", 80)
            params.title_sticker_font_size = st.slider(tr("Title Font Size"), 40, 200, 160, key="title_font_size")
            config.ui["title_sticker_font_size"] = params.title_sticker_font_size

            # 标题文字颜色选择器
            saved_title_text_color = config.ui.get("title_sticker_text_color", "#FF0000")
            params.title_sticker_text_color = st.color_picker(tr("Title Text Color"), saved_title_text_color, key="title_text_color")
            config.ui["title_sticker_text_color"] = params.title_sticker_text_color

            # 标题贴纸样式
            title_sticker_styles = [
                (tr("Rainbow"), "rainbow"),
                (tr("Neon"), "neon"),
                (tr("Gradient"), "gradient"),
                (tr("Normal"), "normal"),
                (tr("3D"), "3d"),
                (tr("Metallic"), "metallic"),
                (tr("Shadow"), "shadow"),
                (tr("Outline"), "outline"),
                (tr("Chinese Style"), "chinese_style"),
            ]
            selected_style_index = st.selectbox(
                tr("Title Style"),
                index=8,  # 默认选择Chinese Style
                options=range(len(title_sticker_styles)),
                format_func=lambda x: title_sticker_styles[x][0],
                key="title_style_select"
            )
            params.title_sticker_style = title_sticker_styles[selected_style_index][1]

            # 标题贴纸位置
            title_sticker_positions = [
                (tr("Upper Middle"), "upper_middle"),
                (tr("Middle"), "middle"),
                (tr("Lower Middle"), "lower_middle"),
                (tr("Custom"), "custom"),
            ]
            selected_pos_index = st.selectbox(
                tr("Title Position"),
                index=3,  # 默认选择自定义位置
                options=range(len(title_sticker_positions)),
                format_func=lambda x: title_sticker_positions[x][0],
                key="title_pos_select"
            )
            params.title_sticker_position = title_sticker_positions[selected_pos_index][1]

            # 如果选择自定义位置，显示位置设置滑块
            if params.title_sticker_position == "custom":
                params.title_sticker_custom_position = st.slider(
                    tr("Custom Position (% from top)"),
                    0.0, 100.0, 15.0, 1.0,
                    key="title_custom_pos"
                )

            # 标题贴纸背景启用选项
            params.title_sticker_background_enabled = st.checkbox(tr("Enable Title Background"), value=False, key="title_bg_enabled")

            if params.title_sticker_background_enabled:
                # 标题贴纸背景类型
                title_sticker_backgrounds = [
                    (tr("Rounded Rectangle"), "rounded_rect"),
                    (tr("Rectangle"), "rect"),
                ]
                selected_bg_index = st.selectbox(
                    tr("Title Background Type"),
                    index=0,
                    options=range(len(title_sticker_backgrounds)),
                    format_func=lambda x: title_sticker_backgrounds[x][0],
                    key="title_bg_select"
                )
                params.title_sticker_background = title_sticker_backgrounds[selected_bg_index][1]

                # 标题贴纸背景颜色
                params.title_sticker_background_color = st.color_picker(tr("Title Background Color"), "#000000", key="title_bg_color")
            else:
                # 如果不启用背景，设置为无背景
                params.title_sticker_background = "none"

            # 标题贴纸边框
            params.title_sticker_border = st.checkbox(tr("Enable Title Border"), value=False, key="title_border")
            if params.title_sticker_border:
                params.title_sticker_border_color = st.color_picker(tr("Title Border Color"), "#FFFFFF", key="title_border_color")

            # 标题动画特效
            st.write(tr("Title Animation Effects"))
            title_animation_types = [
                (tr("None"), "none"),
                (tr("Bounce (Character)"), "bounce"),
                (tr("Pulse (Character)"), "pulse"),
                (tr("Whole Bounce"), "whole_bounce"),
                (tr("Light Sweep"), "light_sweep"),
                (tr("Rotate"), "rotate"),
                (tr("Blink"), "blink"),
                (tr("Wave"), "wave"),
                (tr("Random"), "random"),
            ]
            selected_animation_index = st.selectbox(
                tr("Title Animation"),
                index=0,  # 默认选择无动画
                options=range(len(title_animation_types)),
                format_func=lambda x: title_animation_types[x][0],
                key="title_animation_select"
            )
            params.title_sticker_animation = title_animation_types[selected_animation_index][1]

            # 如果选择了动画，显示动画速度设置
            if params.title_sticker_animation != "none":
                params.title_sticker_animation_speed = st.slider(
                    tr("Animation Speed"),
                    0.5, 2.0, 1.0, 0.1,
                    key="title_animation_speed"
                )

            # 预览效果
            st.write(tr("Title Sticker Preview"))
            title_preview_text = params.title_sticker_text or tr("Title Sticker Preview")

            # 生成标题贴纸预览样式
            title_font_style = ""
            title_bg_style = ""

            # 设置背景样式
            if params.title_sticker_background_enabled and params.title_sticker_background != "none":
                if params.title_sticker_background == "rounded_rect":
                    title_bg_style = f"background-color: {params.title_sticker_background_color}; border-radius: 15px;"
                else:
                    title_bg_style = f"background-color: {params.title_sticker_background_color};"

            # 设置边框
            border_style = ""
            if params.title_sticker_border:
                border_style = f"border: 2px solid {params.title_sticker_border_color};"

            # 设置文字样式
            if params.title_sticker_style == "rainbow":
                title_font_style = "background: linear-gradient(to right, red, orange, yellow, green, blue, indigo, violet); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: bold;"
            elif params.title_sticker_style == "neon":
                title_font_style = "color: #FF4500; font-weight: bold; text-shadow: 0 0 5px #FFFF00, 0 0 10px #FFFF00, 0 0 15px #FF4500, 0 0 20px #FF4500;"
            elif params.title_sticker_style == "gradient":
                title_font_style = "background: linear-gradient(to bottom, #ff0000, #0000ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: bold;"
            elif params.title_sticker_style == "3d":
                title_font_style = "color: #FFFFFF; font-weight: bold; text-shadow: 0px 1px 0px #999, 0px 2px 0px #888, 0px 3px 0px #777, 0px 4px 0px #666, 0px 5px 0px #555, 0px 6px 0px #444, 0px 7px 0px #333, 0px 8px 7px #001135;"
            elif params.title_sticker_style == "metallic":
                title_font_style = "color: #D4AF37; font-weight: bold; background: -webkit-linear-gradient(#eee, #D4AF37); -webkit-background-clip: text; -webkit-text-fill-color: transparent; text-shadow: 2px 2px 4px rgba(0,0,0,0.3);"
            elif params.title_sticker_style == "shadow":
                title_font_style = "color: #FFFFFF; font-weight: bold; text-shadow: 3px 3px 5px #000;"
            elif params.title_sticker_style == "outline":
                title_font_style = "color: #FFFFFF; font-weight: bold; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;"
            else:  # normal
                title_font_style = "color: #FFFFFF; font-weight: bold;"

            # 不再需要单独的预览代码，因为我们使用了统一预览区域

# 添加统一预览区域
# 在生成视频按钮之前显示统一预览区域
with st.container(border=True):
    st.write(tr("Video Preview"))

    # 准备字幕参数
    subtitle_params = None
    if params.subtitle_enabled:
        # 获取字幕字体路径
        subtitle_font_path = os.path.join(font_dir, params.font_name)

        # 准备字幕参数
        subtitle_params = {
            "enabled": params.subtitle_enabled,
            "text": "字幕预览",
            "font_path": subtitle_font_path,
            "font_size": params.font_size,
            "style": params.art_font_type if params.art_font_enabled else "normal",
            "background": "rounded_rect" if params.art_font_background != "none" else "none",
            "background_color": params.art_font_background if params.art_font_background != "none" else "#000000",
            "border": True,
            "border_color": params.stroke_color,
            "position": params.subtitle_position,
            "custom_position": params.custom_position,
            "background_enabled": params.art_font_background != "none"
        }

    # 准备标题参数
    title_params = None
    if params.title_sticker_enabled:
        # 获取标题字体路径
        title_font_path = os.path.join(font_dir, params.title_sticker_font)

        # 准备标题参数
        title_params = {
            "enabled": params.title_sticker_enabled,
            "text": params.title_sticker_text or "标题预览",
            "font_path": title_font_path,
            "font_size": params.title_sticker_font_size,
            "style": params.title_sticker_style,
            "background": params.title_sticker_background,
            "background_color": params.title_sticker_background_color,
            "border": params.title_sticker_border,
            "border_color": params.title_sticker_border_color,
            "position": params.title_sticker_position,
            "custom_position": params.title_sticker_custom_position,
            "background_enabled": params.title_sticker_background_enabled,
            "text_color": params.title_sticker_text_color,
            "animation": getattr(params, "title_sticker_animation", "none"),
            "animation_speed": getattr(params, "title_sticker_animation_speed", 1.0)
        }

    # 生成预览图像
    from app.services.video import create_unified_preview
    preview_img_path = create_unified_preview(
        video_aspect=params.video_aspect,
        subtitle_params=subtitle_params,
        title_params=title_params
    )

    # 显示预览图像
    st.image(preview_img_path, use_container_width=True)

    # 删除临时文件
    try:
        os.remove(preview_img_path)
    except Exception as e:
        logger.warning(f"Failed to remove temporary preview image file: {e}")

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

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        for file in uploaded_files:
            file_path = os.path.join(local_videos_dir, f"{file.file_id}_{file.name}")
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
                m = MaterialInfo()
                m.provider = "local"
                m.url = file_path
                if not params.video_materials:
                    params.video_materials = []
                params.video_materials.append(m)

    log_container = st.empty()
    log_records = []

    def log_received(msg):
        if config.ui["hide_log"]:
            return
        with log_container:
            log_records.append(msg)
            st.code("\n".join(log_records))

    logger.add(log_received)

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    result = tm.start(task_id=task_id, params=params)
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
