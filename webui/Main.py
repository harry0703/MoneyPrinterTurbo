import glob
import io
import math
import os
import sys
import threading
import time
import webbrowser
from uuid import UUID, uuid4

import streamlit as st
from loguru import logger
from PIL import Image, ImageDraw

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

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
# _BG_TASKS lives in this imported module so the dict persists across Streamlit reruns.
# Streamlit re-executes Main.py on every rerun but does NOT re-import cached modules.
from app.services.bg_tasks import _TASKS as _BG_TASKS
from app.services import voice_preview
from app.utils import utils


PDF_UPLOAD_SIGNATURE = b"%PDF-"
_MISSING_VIDEO_PARAMS_WARNED = set()

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

# 定义资源目录
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
system_locale = utils.get_system_locale()


if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "content_source" not in st.session_state:
    st.session_state["content_source"] = config.ui.get("content_source", "text")
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "voice_preview_text" not in st.session_state:
    st.session_state["voice_preview_text"] = config.ui.get("voice_preview_text", "")
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = config.ui.get("language", system_locale)
if "local_video_materials" not in st.session_state:
    # 记住用户最近一次已经落盘的本地素材，避免仅修改文案后二次生成时丢失素材列表。
    st.session_state["local_video_materials"] = []

# 加载语言文件
locales = utils.load_locales(i18n_dir)

# 创建一个顶部栏，包含标题和语言选择
title_col, lang_col = st.columns([3, 1])

with title_col:
    st.title(f"MoneyPrinterTurbo v{config.project_version}")

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
        # task_id 应始终是服务端生成的 UUID。这里先做格式校验，避免异常值
        # 通过路径拼接访问任务目录之外的位置，也避免后续打开目录时触发
        # 平台 shell 对特殊字符的解释。
        normalized_task_id = str(UUID(str(task_id)))
        tasks_root = os.path.abspath(os.path.join(root_dir, "storage", "tasks"))
        resolved_folder = utils.resolve_task_storage_name(normalized_task_id)
        path = os.path.abspath(os.path.join(tasks_root, resolved_folder))

        # 即使 UUID 校验通过，也再次确认最终路径仍在任务根目录内，避免
        # 未来调用方调整 task_id 来源时引入路径穿越风险。
        if not path.startswith(tasks_root + os.sep):
            logger.warning(f"invalid task folder path: {path}")
            return

        if os.path.isdir(path):
            webbrowser.open(f"file://{path}")
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


def build_character_mapping_preview(
    uploaded_character_file,
    face_x: float,
    face_y: float,
    face_w: float,
    face_h: float,
    mouth_x: float,
    mouth_y: float,
    mouth_w: float,
    mouth_h: float,
):
    if not uploaded_character_file:
        return None, None

    try:
        image_bytes = uploaded_character_file.getvalue()
        with Image.open(io.BytesIO(image_bytes)) as source_image:
            preview_image = source_image.convert("RGBA")
    except Exception as exc:
        logger.warning(f"failed to load character preview image: {str(exc)}")
        return None, None

    image_width, image_height = preview_image.size
    if image_width <= 0 or image_height <= 0:
        return None, None

    def clamp_percent(value: float) -> float:
        try:
            parsed_value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(parsed_value):
            return 0.0
        return float(min(100.0, max(0.0, parsed_value)))

    def percent_to_px_x(value: float) -> int:
        return int(round((clamp_percent(value) / 100.0) * image_width))

    def percent_to_px_y(value: float) -> int:
        return int(round((clamp_percent(value) / 100.0) * image_height))

    def percent_to_w(value: float) -> int:
        return max(1, int(round((clamp_percent(value) / 100.0) * image_width)))

    def percent_to_h(value: float) -> int:
        return max(1, int(round((clamp_percent(value) / 100.0) * image_height)))

    fx1 = percent_to_px_x(face_x)
    fy1 = percent_to_px_y(face_y)
    fx2 = min(image_width, max(fx1 + 1, fx1 + percent_to_w(face_w)))
    fy2 = min(image_height, max(fy1 + 1, fy1 + percent_to_h(face_h)))

    mx1 = percent_to_px_x(mouth_x)
    my1 = percent_to_px_y(mouth_y)
    mx2 = min(image_width, max(mx1 + 1, mx1 + percent_to_w(mouth_w)))
    my2 = min(image_height, max(my1 + 1, my1 + percent_to_h(mouth_h)))

    if fx2 > fx1 and fy2 > fy1:
        mx1 = min(max(mx1, fx1), fx2 - 1)
        my1 = min(max(my1, fy1), fy2 - 1)
        mx2 = min(max(mx2, mx1 + 1), fx2)
        my2 = min(max(my2, my1 + 1), fy2)

    overlay = Image.new("RGBA", preview_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    line_width = max(2, int(round(min(image_width, image_height) * 0.006)))
    mouth_line_width = max(line_width + 2, int(round(min(image_width, image_height) * 0.01)))

    if fx2 > fx1 and fy2 > fy1:
        draw.rectangle((fx1, fy1, fx2, fy2), outline=(0, 220, 120, 255), width=line_width)
    if mx2 > mx1 and my2 > my1:
        # Dim all non-mouth area so the mouth selector stands out strongly.
        draw.rectangle((0, 0, image_width, image_height), fill=(0, 0, 0, 86))
        draw.rectangle((mx1, my1, mx2, my2), fill=(0, 0, 0, 0))

        # Double stroke mouth box for better visibility over any background.
        draw.rectangle((mx1, my1, mx2, my2), outline=(255, 255, 255, 255), width=max(2, mouth_line_width + 2))
        draw.rectangle((mx1, my1, mx2, my2), outline=(255, 56, 56, 255), width=mouth_line_width)
        draw.rectangle((mx1, my1, mx2, my2), fill=(255, 64, 64, 52))

        # Draw corner handles to make the selector area easier to locate.
        handle_size = max(4, mouth_line_width + 2)
        handle_color = (255, 245, 245, 255)
        handle_positions = [
            (mx1, my1),
            (mx2 - handle_size, my1),
            (mx1, my2 - handle_size),
            (mx2 - handle_size, my2 - handle_size),
        ]
        for hx, hy in handle_positions:
            draw.rectangle((hx, hy, hx + handle_size, hy + handle_size), fill=handle_color)

        # Center crosshair for quick visual targeting while fine-tuning sliders.
        center_x = mx1 + ((mx2 - mx1) // 2)
        center_y = my1 + ((my2 - my1) // 2)
        cross_half = max(6, mouth_line_width + 2)
        draw.line((center_x - cross_half, center_y, center_x + cross_half, center_y), fill=(255, 245, 245, 230), width=2)
        draw.line((center_x, center_y - cross_half, center_x, center_y + cross_half), fill=(255, 245, 245, 230), width=2)

    final_preview = Image.alpha_composite(preview_image, overlay).convert("RGB")
    mouth_box = (mx1, my1, mx2, my2) if (mx2 > mx1 and my2 > my1) else None
    return final_preview, mouth_box


def set_video_param_safe(params: VideoParams, field_name: str, value):
    model_fields = getattr(type(params), "model_fields", {})
    if field_name in model_fields:
        setattr(params, field_name, value)
        return True
    if field_name not in _MISSING_VIDEO_PARAMS_WARNED:
        logger.warning(f"VideoParams field not available in current runtime: {field_name}")
        _MISSING_VIDEO_PARAMS_WARNED.add(field_name)
    return False


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
                "LiteLLM",
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
                            - **Base Url**: 官方 OpenAI 可留空；如果使用 OpenAI 兼容供应商（例如 OpenRouter），请填写对应的兼容接口地址
                            - **Model Name**: 填写**有权限**的模型；如果使用兼容供应商，请填写该平台支持的模型 ID
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

            if llm_provider == "litellm":
                if not llm_model_name:
                    llm_model_name = "openai/gpt-4o-mini"
                with llm_helper:
                    tips = """
                            ##### LiteLLM Configuration
                            > [LiteLLM](https://github.com/BerriAI/litellm) routes to 100+ LLM providers via a unified interface.
                            > Set your provider's API key as an env var: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AWS_ACCESS_KEY_ID`, etc.
                            - **Model Name**: LiteLLM format — `openai/gpt-4o`, `anthropic/claude-sonnet-4-20250514`, `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`, `gemini/gemini-2.5-flash`. See [full provider list](https://docs.litellm.ai/docs/providers)
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

            def save_single_key_to_config(cfg_key, value):
                config.app[cfg_key] = str(value or "").strip()

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

            st.write(tr("External Provider Keys"))

            getimg_api_key = st.text_input(
                tr("Getimg API Key"),
                value=str(config.app.get("getimg_api_key", "")),
                type="password",
            )
            save_single_key_to_config("getimg_api_key", getimg_api_key)

            fal_api_key = st.text_input(
                tr("Fal API Key"),
                value=str(config.app.get("fal_api_key", "")),
                type="password",
            )
            save_single_key_to_config("fal_api_key", fal_api_key)

            stability_api_key = st.text_input(
                tr("Stability API Key"),
                value=str(config.app.get("stability_api_key", "")),
                type="password",
            )
            save_single_key_to_config("stability_api_key", stability_api_key)

            did_api_key = st.text_input(
                tr("D-ID API Key"),
                value=str(config.app.get("did_api_key", "")),
                type="password",
            )
            save_single_key_to_config("did_api_key", did_api_key)

            heygen_api_key = st.text_input(
                tr("HeyGen API Key"),
                value=str(config.app.get("heygen_api_key", "")),
                type="password",
            )
            save_single_key_to_config("heygen_api_key", heygen_api_key)

            bannerbear_api_key = st.text_input(
                tr("Bannerbear API Key"),
                value=str(config.app.get("bannerbear_api_key", "")),
                type="password",
            )
            save_single_key_to_config("bannerbear_api_key", bannerbear_api_key)

            replicate_api_token = st.text_input(
                tr("Replicate API Token"),
                value=str(config.app.get("replicate_api_token", "")),
                type="password",
            )
            save_single_key_to_config("replicate_api_token", replicate_api_token)

            shotstack_api_key = st.text_input(
                tr("Shotstack API Key"),
                value=str(config.app.get("shotstack_api_key", "")),
                type="password",
            )
            save_single_key_to_config("shotstack_api_key", shotstack_api_key)

llm_provider = config.app.get("llm_provider", "").lower()
panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

params = VideoParams(video_subject="")
uploaded_files = []
uploaded_audio_file = None
uploaded_bgm_file = None
uploaded_pdf_file = None
uploaded_custom_cover_file = None
uploaded_character_file = None
uploaded_avatar_file = None

with left_panel:
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        content_sources = [
            (tr("Typed / Generated Text"), "text"),
            (tr("PDF Audiobook"), "pdf"),
        ]
        saved_content_source = st.session_state.get("content_source", "text")
        saved_content_source_index = 0
        for i, (_, value) in enumerate(content_sources):
            if value == saved_content_source:
                saved_content_source_index = i
                break

        selected_content_source_index = st.selectbox(
            tr("Narration Source"),
            options=range(len(content_sources)),
            format_func=lambda x: content_sources[x][0],
            index=saved_content_source_index,
        )
        params.content_source = content_sources[selected_content_source_index][1]
        st.session_state["content_source"] = params.content_source
        config.ui["content_source"] = params.content_source
        if params.content_source == "pdf":
            st.session_state["video_script"] = ""

        params.video_subject = st.text_input(
            tr("Video Subject"),
            value=st.session_state["video_subject"],
            key="video_subject_input",
        ).strip()

        if params.content_source == "pdf":
            uploaded_pdf_file = st.file_uploader(
                tr("PDF for Audiobook"),
                type=["pdf", "PDF"],
                accept_multiple_files=False,
                key="pdf_audiobook_uploader",
                help=tr("Upload a long PDF with readable text. The narration will be extracted directly from the document."),
            )
            if uploaded_pdf_file:
                pdf_header = bytes(uploaded_pdf_file.getbuffer()[: len(PDF_UPLOAD_SIGNATURE)])
                if not pdf_header.startswith(PDF_UPLOAD_SIGNATURE):
                    st.error(tr("The uploaded file is not a valid PDF."))
                else:
                    st.info(tr("The uploaded PDF will be used as the audiobook narration source."))

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

        if params.content_source == "text" and st.button(
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
            tr("Video Script"),
            value=st.session_state["video_script"] if params.content_source == "text" else "",
            height=280,
            disabled=params.content_source == "pdf",
            help=tr("When PDF Audiobook is selected, this field is replaced by the extracted text from the uploaded PDF."),
        )
        params.generate_cover = st.checkbox(
            tr("Generate Cover Image"),
            value=config.ui.get("generate_cover", True),
            help=tr("Creates a thematic cover image from the selected materials and script topic."),
        )
        config.ui["generate_cover"] = params.generate_cover
        custom_cover_file_types = ["png", "jpg", "jpeg", "webp", "bmp"]
        uploaded_custom_cover_file = st.file_uploader(
            tr("Custom Cover Image"),
            type=custom_cover_file_types,
            accept_multiple_files=False,
            key="custom_cover_image_uploader",
            help=tr("Optional. If uploaded, this image will be used as the output cover. Automatic cover generation remains available when no custom cover is provided."),
        )
        if uploaded_custom_cover_file:
            st.image(uploaded_custom_cover_file, caption=tr("Custom Cover Preview"), use_container_width=True)
        if params.content_source == "text" and st.button(tr("Generate Video Keywords"), key="auto_generate_terms"):
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
            (tr("External provider"), "external"),
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

        if params.video_source == "external":
            external_providers = [
                ("getimg.ai", "getimg"),
                ("fal.ai", "fal"),
                ("Shotstack", "shotstack"),
                ("Stability AI", "stability"),
                ("D-ID", "did"),
                ("HeyGen", "heygen"),
                ("Bannerbear", "bannerbear"),
                ("Replicate", "replicate"),
            ]
            saved_external_provider = config.app.get("external_provider", "getimg")
            saved_external_provider_index = 0
            for i, provider in enumerate(external_providers):
                if provider[1] == saved_external_provider:
                    saved_external_provider_index = i
                    break

            selected_external_provider = st.selectbox(
                tr("External Provider"),
                options=range(len(external_providers)),
                format_func=lambda x: external_providers[x][0],
                index=saved_external_provider_index,
            )
            params.external_provider = external_providers[selected_external_provider][1]
            config.app["external_provider"] = params.external_provider

            external_output_types = [
                (tr("Video"), "video"),
                (tr("Image"), "image"),
            ]
            saved_external_output_type = config.app.get("external_output_type", "video")
            saved_external_output_type_index = 0
            for i, (_, output_value) in enumerate(external_output_types):
                if output_value == saved_external_output_type:
                    saved_external_output_type_index = i
                    break
            selected_external_output_type_index = st.selectbox(
                tr("External Output Type"),
                options=range(len(external_output_types)),
                format_func=lambda x: external_output_types[x][0],
                index=saved_external_output_type_index,
            )
            external_output_type_value = external_output_types[selected_external_output_type_index][1]
            set_video_param_safe(params, "external_output_type", external_output_type_value)
            config.app["external_output_type"] = external_output_type_value

        if params.video_source == "local":
            local_file_types = ["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"]
            uploaded_files = st.file_uploader(
                "Upload Local Files",
                type=local_file_types,
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
            index=0,
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

        duration_modes = [
            (tr("Manual"), "manual"),
            (tr("Auto by Text Length"), "auto_text"),
        ]
        saved_duration_mode = config.ui.get("duration_mode", "manual")
        if params.content_source == "pdf" and saved_duration_mode == "manual":
            saved_duration_mode = "auto_text"
        duration_mode_index = 0
        for i, (_, value) in enumerate(duration_modes):
            if value == saved_duration_mode:
                duration_mode_index = i
                break

        selected_duration_mode_index = st.selectbox(
            tr("Duration Mode"),
            options=range(len(duration_modes)),
            format_func=lambda x: duration_modes[x][0],
            index=duration_mode_index,
        )
        params.duration_mode = duration_modes[selected_duration_mode_index][1]
        config.ui["duration_mode"] = params.duration_mode

        if params.duration_mode == "auto_text":
            params.video_clip_duration = 0
            st.caption(
                tr("Clip pacing will be computed from the final narration length, which is recommended for long texts and PDF audiobooks.")
            )
        else:
            params.video_clip_duration = st.selectbox(
                tr("Clip Duration"),
                options=list(range(2, 121)),
                index=3,
                help=tr("Manual mode keeps a fixed clip duration for the visual pacing."),
            )
        params.video_count = st.selectbox(
            tr("Number of Videos Generated Simultaneously"),
            options=[1, 2, 3],
            index=0,
            help=tr("Recommended: 1. Each extra video repeats the full render with the same clips."),
        )
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # 添加TTS服务器选择下拉框
        tts_servers = [
            ("azure-tts-v1", "Azure TTS V1"),
            ("azure-tts-v2", "Azure TTS V2"),
            ("siliconflow", "SiliconFlow TTS"),
            ("gemini-tts", "Google Gemini TTS"),
            ("omnivoice", "OmniVoice Studio (Local)"),
        ]

        # 获取保存的TTS服务器，默认为v1
        saved_tts_server = config.ui.get("tts_server", "azure-tts-v1")
        saved_tts_server_index = 0
        for i, (server_value, _) in enumerate(tts_servers):
            if server_value == saved_tts_server:
                saved_tts_server_index = i
                break

        selected_tts_server_index = st.selectbox(
            tr("TTS Servers"),
            options=range(len(tts_servers)),
            format_func=lambda x: tts_servers[x][1],
            index=saved_tts_server_index,
        )

        selected_tts_server = tts_servers[selected_tts_server_index][0]
        config.ui["tts_server"] = selected_tts_server

        # 根据选择的TTS服务器获取声音列表
        filtered_voices = []

        if selected_tts_server == "siliconflow":
            # 获取硅基流动的声音列表
            filtered_voices = voice.get_siliconflow_voices()
        elif selected_tts_server == "gemini-tts":
            # 获取Gemini TTS的声音列表
            filtered_voices = voice.get_gemini_voices()
        elif selected_tts_server == "omnivoice":
            # 本地 OmniVoice Studio 的声音（含克隆的 voice profiles）
            filtered_voices = voice.get_omnivoice_voices()
            if len(filtered_voices) <= 1:
                st.info(
                    "OmniVoice Studio offers only the default voice right now. "
                    "Start it (port 3900) to load your cloned profiles."
                )
        else:
            # 获取Azure的声音列表
            all_voices = voice.get_all_azure_voices(filter_locals=None)

            # 根据选择的TTS服务器筛选声音
            for v in all_voices:
                if selected_tts_server == "azure-tts-v2":
                    # V2版本的声音名称中包含"v2"
                    if "V2" in v:
                        filtered_voices.append(v)
                else:
                    # V1版本的声音名称中不包含"v2"
                    if "V2" not in v:
                        filtered_voices.append(v)

        friendly_names = {
            v: v.replace("Female", tr("Female"))
            .replace("Male", tr("Male"))
            .replace("Neural", "")
            for v in filtered_voices
        }

        saved_voice_name = config.ui.get("voice_name", "")
        saved_voice_name_index = 0

        # 检查保存的声音是否在当前筛选的声音列表中
        if saved_voice_name in friendly_names:
            saved_voice_name_index = list(friendly_names.keys()).index(saved_voice_name)
        else:
            # 如果不在，则根据当前UI语言选择一个默认声音
            for i, v in enumerate(filtered_voices):
                if v.lower().startswith(st.session_state["ui_language"].lower()):
                    saved_voice_name_index = i
                    break

        # 如果没有找到匹配的声音，使用第一个声音
        if saved_voice_name_index >= len(friendly_names) and friendly_names:
            saved_voice_name_index = 0

        # 确保有声音可选
        if friendly_names:
            selected_friendly_name = st.selectbox(
                tr("Speech Synthesis"),
                options=list(friendly_names.values()),
                index=min(saved_voice_name_index, len(friendly_names) - 1)
                if friendly_names
                else 0,
            )

            voice_name = list(friendly_names.keys())[
                list(friendly_names.values()).index(selected_friendly_name)
            ]
            params.voice_name = voice_name
            config.ui["voice_name"] = voice_name
        else:
            # 如果没有声音可选，显示提示信息
            st.warning(
                tr(
                    "No voices available for the selected TTS server. Please select another server."
                )
            )
            params.voice_name = ""
            config.ui["voice_name"] = ""

        preview_text_value = st.text_area(
            tr("Voice Preview Text"),
            value=st.session_state["voice_preview_text"],
            height=100,
            help=tr("Used only for the voice preview. Long previews are capped at 500 characters."),
        )
        st.session_state["voice_preview_text"] = preview_text_value
        config.ui["voice_preview_text"] = preview_text_value

        if friendly_names and st.button(tr("Generate Voice Preview")):
            play_content = preview_text_value.strip()
            if not play_content:
                play_content = params.video_subject or params.video_script or tr("Voice Example")
            with st.spinner(tr("Synthesizing Voice")):
                try:
                    preview_audio_path = voice_preview.generate_preview_audio(
                        preview_text=play_content,
                        voice_name=voice_name,
                        voice_rate=params.voice_rate,
                        voice_volume=params.voice_volume,
                    )
                    st.audio(preview_audio_path, format="audio/mp3")
                except Exception as exc:
                    st.error(str(exc))

        # 当选择V2版本或者声音是V2声音时，显示服务区域和API key输入框
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

        # 当选择硅基流动时，显示API key输入框和说明信息
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

            # 显示硅基流动的说明信息
            st.info(
                tr("SiliconFlow TTS Settings")
                + ":\n"
                + "- "
                + tr("Speed: Range [0.25, 4.0], default is 1.0")
                + "\n"
                + "- "
                + tr("Volume: Uses Speech Volume setting, default 1.0 maps to gain 0")
            )

            config.siliconflow["api_key"] = siliconflow_api_key

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

        custom_audio_file_types = ["mp3", "wav", "m4a", "aac", "flac", "ogg"]
        uploaded_audio_file = st.file_uploader(
            tr("Custom Audio File"),
            type=custom_audio_file_types,
            accept_multiple_files=False,
            key="custom_audio_file_uploader",
        )
        if uploaded_audio_file:
            st.audio(uploaded_audio_file, format="audio/mp3")
            st.info(
                tr(
                    "Custom audio will be used directly. TTS synthesis will be skipped for this task."
                )
            )

        bgm_catalog_dir = os.path.join(song_dir, "copyright_free")
        bgm_catalog_files = []
        for ext in ["mp3", "wav", "m4a", "aac", "flac", "ogg"]:
            bgm_catalog_files.extend(glob.glob(os.path.join(bgm_catalog_dir, f"*.{ext}")))
        bgm_catalog_files = sorted(bgm_catalog_files, key=lambda path: os.path.basename(path).lower())

        bgm_options = [
            (tr("No Background Music"), ""),
            (tr("Random Copyright-Free Music"), "random"),
            (tr("Copyright-Free Catalog"), "catalog"),
            (tr("Upload My Own Music"), "upload"),
            (tr("Custom Background Music Path"), "custom"),
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
        uploaded_bgm_file = None
        if params.bgm_type == "catalog":
            if bgm_catalog_files:
                selected_bgm_name = st.selectbox(
                    tr("Copyright-Free Track"),
                    options=[os.path.basename(path) for path in bgm_catalog_files],
                    index=0,
                    key="catalog_bgm_selector",
                )
                selected_bgm_path = next(
                    (path for path in bgm_catalog_files if os.path.basename(path) == selected_bgm_name),
                    "",
                )
                if selected_bgm_path:
                    params.bgm_file = selected_bgm_path
            else:
                st.info(
                    tr("No copyright-free tracks were found in resource/songs/copyright_free. Upload your own or add files to that folder.")
                )
                params.bgm_type = ""
        elif params.bgm_type == "upload":
            uploaded_bgm_file = st.file_uploader(
                tr("Upload Background Music"),
                type=["mp3", "wav", "m4a", "aac", "flac", "ogg"],
                accept_multiple_files=False,
                key="custom_bgm_upload_uploader",
            )
            if uploaded_bgm_file:
                st.audio(uploaded_bgm_file)
                st.caption(tr("Only upload music you own or are licensed to use on YouTube/TikTok/Instagram."))
        elif params.bgm_type == "custom":
            custom_bgm_file = st.text_input(
                tr("Custom Background Music File"), key="custom_bgm_file_input"
            )
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
        st.write(tr("Character Overlay"))
        params.character_overlay_enabled = st.checkbox(
            tr("Enable Character Overlay"),
            value=config.ui.get("character_overlay_enabled", False),
            help=tr("Adds a character image above the final video without replacing the background."),
        )
        config.ui["character_overlay_enabled"] = params.character_overlay_enabled

        if params.character_overlay_enabled:
            character_overlay_uploader_key = f"character_overlay_uploader_{config.project_version.replace('.', '_')}"
            uploaded_character_file = st.file_uploader(
                tr("Character Image"),
                accept_multiple_files=False,
                key=character_overlay_uploader_key,
                help=tr("Transparent or simple-background portraits work best for the overlay."),
            )
            if uploaded_character_file:
                _, character_ext = os.path.splitext(os.path.basename(uploaded_character_file.name))
                if character_ext.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    st.error(tr("Please upload a PNG, JPG, JPEG, or WEBP image for the character overlay."))
                    uploaded_character_file = None
                else:
                    st.image(uploaded_character_file, caption=tr("Character Preview"), use_container_width=True)

            params.character_remove_background = st.checkbox(
                tr("Remove Background"),
                value=config.ui.get("character_remove_background", True),
            )
            config.ui["character_remove_background"] = params.character_remove_background

            character_positions = [
                (tr("Top Left"), "top_left"),
                (tr("Top Right"), "top_right"),
                (tr("Bottom Left"), "bottom_left"),
                (tr("Bottom Right"), "bottom_right"),
                (tr("Top Center"), "top_center"),
                (tr("Bottom Center"), "bottom_center"),
                (tr("Center"), "center"),
                (tr("Custom"), "custom"),
            ]
            saved_character_position = config.ui.get("character_position", "bottom_right")
            saved_character_position_index = 3
            for index, (_, position_value) in enumerate(character_positions):
                if position_value == saved_character_position:
                    saved_character_position_index = index
                    break
            selected_character_position_index = st.selectbox(
                tr("Character Position"),
                options=range(len(character_positions)),
                format_func=lambda x: character_positions[x][0],
                index=saved_character_position_index,
            )
            params.character_position = character_positions[selected_character_position_index][1]
            config.ui["character_position"] = params.character_position

            params.character_scale = st.slider(
                tr("Character Scale"),
                min_value=0.10,
                max_value=0.60,
                value=float(config.ui.get("character_scale", 0.28)),
                step=0.01,
            )
            config.ui["character_scale"] = params.character_scale

            margin_columns = st.columns(2)
            with margin_columns[0]:
                params.character_margin_x = st.slider(
                    tr("Character Margin X"),
                    min_value=0,
                    max_value=200,
                    value=int(config.ui.get("character_margin_x", 36)),
                    step=2,
                )
                config.ui["character_margin_x"] = params.character_margin_x
            with margin_columns[1]:
                params.character_margin_y = st.slider(
                    tr("Character Margin Y"),
                    min_value=0,
                    max_value=240,
                    value=int(config.ui.get("character_margin_y", 36)),
                    step=2,
                )
                config.ui["character_margin_y"] = params.character_margin_y

            params.character_lipsync_enabled = st.checkbox(
                tr("Character Lip Sync"),
                value=config.ui.get("character_lipsync_enabled", True),
            )
            config.ui["character_lipsync_enabled"] = params.character_lipsync_enabled

            if params.character_lipsync_enabled:
                lipsync_intensity_value = st.slider(
                    tr("Lip Sync Intensity"),
                    min_value=0.4,
                    max_value=2.0,
                    value=float(config.ui.get("character_lipsync_intensity", 1.0)),
                    step=0.05,
                    help=tr("Increase if lips look too subtle. Decrease if movement looks exaggerated."),
                )
                set_video_param_safe(params, "character_lipsync_intensity", lipsync_intensity_value)
                config.ui["character_lipsync_intensity"] = lipsync_intensity_value

                character_manual_mapping_enabled_value = st.checkbox(
                    tr("Manual Face/Lips Mapping"),
                    value=config.ui.get("character_manual_mapping_enabled", False),
                    help=tr("Use manual face/lips coordinates when automatic detection is not accurate."),
                )
                set_video_param_safe(params, "character_manual_mapping_enabled", character_manual_mapping_enabled_value)
                config.ui["character_manual_mapping_enabled"] = character_manual_mapping_enabled_value

                manual_mapping_enabled = bool(getattr(params, "character_manual_mapping_enabled", character_manual_mapping_enabled_value))

                if manual_mapping_enabled:
                    st.caption(
                        tr("Coordinates are percentages over the character image. Start with mouth area first, then fine tune.")
                    )
                    face_columns = st.columns(2)
                    with face_columns[0]:
                        character_face_x_value = st.slider(
                            tr("Face X (%)"),
                            min_value=0.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_face_x", 30.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_face_x", character_face_x_value)
                        config.ui["character_face_x"] = character_face_x_value
                    with face_columns[1]:
                        character_face_y_value = st.slider(
                            tr("Face Y (%)"),
                            min_value=0.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_face_y", 16.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_face_y", character_face_y_value)
                        config.ui["character_face_y"] = character_face_y_value

                    face_size_columns = st.columns(2)
                    with face_size_columns[0]:
                        character_face_w_value = st.slider(
                            tr("Face Width (%)"),
                            min_value=1.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_face_w", 40.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_face_w", character_face_w_value)
                        config.ui["character_face_w"] = character_face_w_value
                    with face_size_columns[1]:
                        character_face_h_value = st.slider(
                            tr("Face Height (%)"),
                            min_value=1.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_face_h", 48.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_face_h", character_face_h_value)
                        config.ui["character_face_h"] = character_face_h_value

                    mouth_columns = st.columns(2)
                    with mouth_columns[0]:
                        character_mouth_x_value = st.slider(
                            tr("Mouth X (%)"),
                            min_value=0.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_mouth_x", 40.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_mouth_x", character_mouth_x_value)
                        config.ui["character_mouth_x"] = character_mouth_x_value
                    with mouth_columns[1]:
                        character_mouth_y_value = st.slider(
                            tr("Mouth Y (%)"),
                            min_value=0.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_mouth_y", 60.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_mouth_y", character_mouth_y_value)
                        config.ui["character_mouth_y"] = character_mouth_y_value

                    mouth_size_columns = st.columns(2)
                    with mouth_size_columns[0]:
                        character_mouth_w_value = st.slider(
                            tr("Mouth Width (%)"),
                            min_value=1.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_mouth_w", 22.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_mouth_w", character_mouth_w_value)
                        config.ui["character_mouth_w"] = character_mouth_w_value
                    with mouth_size_columns[1]:
                        character_mouth_h_value = st.slider(
                            tr("Mouth Height (%)"),
                            min_value=1.0,
                            max_value=100.0,
                            value=float(config.ui.get("character_mouth_h", 14.0)),
                            step=1.0,
                        )
                        set_video_param_safe(params, "character_mouth_h", character_mouth_h_value)
                        config.ui["character_mouth_h"] = character_mouth_h_value

                    preview_image, mouth_box = build_character_mapping_preview(
                        uploaded_character_file=uploaded_character_file,
                        face_x=float(config.ui.get("character_face_x", 30.0)),
                        face_y=float(config.ui.get("character_face_y", 16.0)),
                        face_w=float(config.ui.get("character_face_w", 40.0)),
                        face_h=float(config.ui.get("character_face_h", 48.0)),
                        mouth_x=float(config.ui.get("character_mouth_x", 40.0)),
                        mouth_y=float(config.ui.get("character_mouth_y", 60.0)),
                        mouth_w=float(config.ui.get("character_mouth_w", 22.0)),
                        mouth_h=float(config.ui.get("character_mouth_h", 14.0)),
                    )
                    if preview_image is not None:
                        st.image(preview_image, caption=tr("Manual Mapping Preview"), use_container_width=True)

                        zoom_preview_enabled = st.checkbox(
                            tr("Zoom to Mouth Preview"),
                            value=bool(config.ui.get("character_mapping_zoom_preview", True)),
                            help=tr("Shows a magnified crop around the mapped mouth area for fine adjustments."),
                        )
                        config.ui["character_mapping_zoom_preview"] = zoom_preview_enabled

                        if zoom_preview_enabled and mouth_box is not None:
                            mx1, my1, mx2, my2 = mouth_box
                            if mx2 > mx1 and my2 > my1:
                                mouth_width = mx2 - mx1
                                mouth_height = my2 - my1
                                pad_x = max(8, int(round(mouth_width * 1.2)))
                                pad_y = max(8, int(round(mouth_height * 1.4)))

                                preview_width, preview_height = preview_image.size
                                zoom_x1 = max(0, mx1 - pad_x)
                                zoom_y1 = max(0, my1 - pad_y)
                                zoom_x2 = min(preview_width, mx2 + pad_x)
                                zoom_y2 = min(preview_height, my2 + pad_y)

                                if zoom_x2 > zoom_x1 and zoom_y2 > zoom_y1:
                                    mouth_zoom_preview = preview_image.crop((zoom_x1, zoom_y1, zoom_x2, zoom_y2))
                                    st.image(
                                        mouth_zoom_preview,
                                        caption=tr("Mouth Zoom Preview"),
                                        use_container_width=True,
                                    )
                                else:
                                    st.warning(tr("Mouth area is too small for zoom preview. Adjust mouth width/height."))
                            else:
                                st.warning(tr("Manual mouth mapping is invalid. Adjust mouth coordinates."))
                    else:
                        st.info(tr("Upload a character image to display manual mapping preview."))

            params.character_idle_motion_enabled = st.checkbox(
                tr("Character Idle Motion"),
                value=config.ui.get("character_idle_motion_enabled", True),
            )
            config.ui["character_idle_motion_enabled"] = params.character_idle_motion_enabled

            layer_orders = [
                (tr("Behind Subtitles"), "behind_subtitles"),
                (tr("In Front of Subtitles"), "front_of_subtitles"),
            ]
            saved_layer_order = config.ui.get("character_layer_order", "behind_subtitles")
            saved_layer_order_index = 0 if saved_layer_order != "front_of_subtitles" else 1
            selected_layer_order_index = st.selectbox(
                tr("Character Layer Order"),
                options=range(len(layer_orders)),
                format_func=lambda x: layer_orders[x][0],
                index=saved_layer_order_index,
            )
            params.character_layer_order = layer_orders[selected_layer_order_index][1]
            config.ui["character_layer_order"] = params.character_layer_order

            if params.character_position == "custom":
                custom_columns = st.columns(2)
                with custom_columns[0]:
                    params.character_custom_x = st.slider(
                        tr("Character Custom X (%)"),
                        min_value=0.0,
                        max_value=100.0,
                        value=float(config.ui.get("character_custom_x", 0.0)),
                        step=1.0,
                    )
                    config.ui["character_custom_x"] = params.character_custom_x
                with custom_columns[1]:
                    params.character_custom_y = st.slider(
                        tr("Character Custom Y (%)"),
                        min_value=0.0,
                        max_value=100.0,
                        value=float(config.ui.get("character_custom_y", 0.0)),
                        step=1.0,
                    )
                    config.ui["character_custom_y"] = params.character_custom_y

    with st.container(border=True):
        st.write(tr("Advanced AI"))
        enable_musetalk_value = st.checkbox(
            tr("Enable MuseTalk"),
            value=config.ui.get("enable_musetalk", False),
            help=tr("Shows the MuseTalk lip sync option in the generated task and keeps the setting visible in the frontend."),
        )
        set_video_param_safe(params, "enable_musetalk", enable_musetalk_value)
        config.ui["enable_musetalk"] = enable_musetalk_value

        enable_cinematic_render_value = st.checkbox(
            tr("Enable Cinematic Render"),
            value=config.ui.get("enable_cinematic_render", False),
            help=tr("Marks the task to use cinematic rendering settings from the frontend."),
        )
        set_video_param_safe(params, "enable_cinematic_render", enable_cinematic_render_value)
        config.ui["enable_cinematic_render"] = enable_cinematic_render_value

        enable_animatediff_value = st.checkbox(
            tr("Enable AnimateDiff"),
            value=config.ui.get("enable_animatediff", False),
            help=tr("Shows the AnimateDiff motion option in the frontend task settings."),
        )
        set_video_param_safe(params, "enable_animatediff", enable_animatediff_value)
        config.ui["enable_animatediff"] = enable_animatediff_value

        avatar_lipsync_modes = [
            ("auto (MuseTalk -> Wav2Lip)", "auto"),
            ("MuseTalk only", "musetalk"),
            ("Wav2Lip only", "wav2lip"),
        ]
        saved_avatar_lipsync_mode = config.ui.get("avatar_lipsync_mode", "auto")
        saved_avatar_lipsync_mode_index = 0
        for index, (_, mode_value) in enumerate(avatar_lipsync_modes):
            if mode_value == saved_avatar_lipsync_mode:
                saved_avatar_lipsync_mode_index = index
                break
        selected_avatar_lipsync_mode_index = st.selectbox(
            tr("Avatar LipSync Mode"),
            options=range(len(avatar_lipsync_modes)),
            format_func=lambda x: avatar_lipsync_modes[x][0],
            index=saved_avatar_lipsync_mode_index,
        )
        avatar_lipsync_mode_value = avatar_lipsync_modes[selected_avatar_lipsync_mode_index][1]
        set_video_param_safe(params, "avatar_lipsync_mode", avatar_lipsync_mode_value)
        config.ui["avatar_lipsync_mode"] = avatar_lipsync_mode_value

        avatar_positions = [
            (tr("Top Left"), "top_left"),
            (tr("Top Right"), "top_right"),
            (tr("Bottom Left"), "bottom_left"),
            (tr("Bottom Right"), "bottom_right"),
            (tr("Center"), "center"),
            (tr("Custom"), "custom"),
        ]
        saved_avatar_position = config.ui.get("avatar_position", "bottom_right")
        saved_avatar_position_index = 3
        for i, (_, position_value) in enumerate(avatar_positions):
            if position_value == saved_avatar_position:
                saved_avatar_position_index = i
                break
        selected_avatar_position_index = st.selectbox(
            tr("Avatar Position"),
            options=range(len(avatar_positions)),
            format_func=lambda x: avatar_positions[x][0],
            index=saved_avatar_position_index,
        )
        avatar_position_value = avatar_positions[selected_avatar_position_index][1]
        set_video_param_safe(params, "avatar_position", avatar_position_value)
        config.ui["avatar_position"] = avatar_position_value

        avatar_offset_columns = st.columns(2)
        with avatar_offset_columns[0]:
            avatar_offset_x_value = st.slider(
                tr("Avatar Offset X (%)"),
                min_value=-50,
                max_value=50,
                value=int(config.ui.get("avatar_offset_x", 0)),
                step=1,
            )
            set_video_param_safe(params, "avatar_offset_x", avatar_offset_x_value)
            config.ui["avatar_offset_x"] = avatar_offset_x_value
        with avatar_offset_columns[1]:
            avatar_offset_y_value = st.slider(
                tr("Avatar Offset Y (%)"),
                min_value=-50,
                max_value=50,
                value=int(config.ui.get("avatar_offset_y", 0)),
                step=1,
            )
            set_video_param_safe(params, "avatar_offset_y", avatar_offset_y_value)
            config.ui["avatar_offset_y"] = avatar_offset_y_value

        uploaded_avatar_file = st.file_uploader(
            tr("Avatar Base Image or Video"),
            type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "webm"],
            accept_multiple_files=False,
            key=f"avatar_base_uploader_{config.project_version.replace('.', '_')}",
            help=tr("Optional input used for avatar lip sync and advanced render experiments."),
        )
        if uploaded_avatar_file:
            avatar_name = (uploaded_avatar_file.name or "").lower()
            if avatar_name.endswith((".mp4", ".mov", ".webm")):
                st.video(uploaded_avatar_file)
            else:
                st.image(uploaded_avatar_file, caption=tr("Avatar Preview"), use_container_width=True)

    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=True)
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
        saved_subtitle_position = config.ui.get("subtitle_position", "bottom")
        saved_position_index = 2
        for i, (_, pos_value) in enumerate(subtitle_positions):
            if pos_value == saved_subtitle_position:
                saved_position_index = i
                break
        selected_index = st.selectbox(
            tr("Position"),
            index=saved_position_index,
            options=range(len(subtitle_positions)),
            format_func=lambda x: subtitle_positions[x][0],
        )
        params.subtitle_position = subtitle_positions[selected_index][1]
        config.ui["subtitle_position"] = params.subtitle_position

        if params.subtitle_position == "custom":
            saved_custom_position = config.ui.get("custom_position", 70.0)
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
                    config.ui["custom_position"] = params.custom_position
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
            params.stroke_color = st.color_picker(tr("Stroke Color"), "#000000")
        with stroke_cols[1]:
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, 1.5)
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
    if params.content_source == "pdf":
        if not uploaded_pdf_file:
            st.error(tr("Please upload a PDF to generate the audiobook."))
            scroll_to_bottom()
            st.stop()

        pdf_header = bytes(uploaded_pdf_file.getbuffer()[: len(PDF_UPLOAD_SIGNATURE)])
        if not pdf_header.startswith(PDF_UPLOAD_SIGNATURE):
            st.error(tr("The uploaded file is not a valid PDF."))
            scroll_to_bottom()
            st.stop()
    elif not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        scroll_to_bottom()
        st.stop()

    if params.video_source not in ["pexels", "pixabay", "local", "external"]:
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

    if params.character_overlay_enabled and not uploaded_character_file:
        st.error(tr("Please upload a character image to enable the character overlay."))
        scroll_to_bottom()
        st.stop()

    utils.ensure_task_dir(
        task_id,
        utils.build_task_title(
            video_subject=params.video_subject,
            video_script=params.video_script,
            fallback_title=os.path.splitext(os.path.basename(uploaded_pdf_file.name))[0]
            if uploaded_pdf_file
            else "",
        ),
    )

    if uploaded_pdf_file:
        task_dir = utils.task_dir(task_id)
        pdf_path = os.path.join(task_dir, "source-document.pdf")
        with open(pdf_path, "wb") as f:
            f.write(uploaded_pdf_file.getbuffer())
        params.pdf_file = pdf_path

    if uploaded_custom_cover_file:
        task_dir = utils.task_dir(task_id)
        _, cover_ext = os.path.splitext(os.path.basename(uploaded_custom_cover_file.name))
        cover_ext = cover_ext.lower() or ".png"
        custom_cover_path = os.path.join(task_dir, f"custom-cover{cover_ext}")
        with open(custom_cover_path, "wb") as f:
            f.write(uploaded_custom_cover_file.getbuffer())
        params.custom_cover_file = custom_cover_path

    if uploaded_character_file:
        task_dir = utils.task_dir(task_id)
        _, character_ext = os.path.splitext(os.path.basename(uploaded_character_file.name))
        character_ext = character_ext.lower() or ".png"
        character_image_path = os.path.join(task_dir, f"character-overlay{character_ext}")
        with open(character_image_path, "wb") as f:
            f.write(uploaded_character_file.getbuffer())
        params.character_image_file = character_image_path

    if uploaded_avatar_file:
        task_dir = utils.task_dir(task_id)
        _, avatar_ext = os.path.splitext(os.path.basename(uploaded_avatar_file.name))
        avatar_ext = avatar_ext.lower() or ".png"
        avatar_image_path = os.path.join(task_dir, f"avatar-base{avatar_ext}")
        with open(avatar_image_path, "wb") as f:
            f.write(uploaded_avatar_file.getbuffer())
        set_video_param_safe(params, "avatar_image_file", avatar_image_path)

    advanced_metadata = dict(getattr(params, "external_metadata", None) or {})
    advanced_metadata["avatar_position"] = str(config.ui.get("avatar_position", "bottom_right"))
    advanced_metadata["avatar_offset_x"] = int(config.ui.get("avatar_offset_x", 0))
    advanced_metadata["avatar_offset_y"] = int(config.ui.get("avatar_offset_y", 0))
    set_video_param_safe(params, "external_metadata", advanced_metadata)

    if uploaded_audio_file:
        task_dir = utils.task_dir(task_id)
        # 上传文件名来自浏览器，不能直接拼到磁盘路径里；这里只保留扩展名，
        # 并使用固定文件名保存到当前任务目录，避免路径穿越或特殊字符问题。
        _, audio_ext = os.path.splitext(os.path.basename(uploaded_audio_file.name))
        audio_ext = audio_ext.lower() or ".mp3"
        custom_audio_path = os.path.join(task_dir, f"custom-audio{audio_ext}")
        with open(custom_audio_path, "wb") as f:
            f.write(uploaded_audio_file.getbuffer())
        params.custom_audio_file = custom_audio_path

    if uploaded_bgm_file:
        task_dir = utils.task_dir(task_id)
        _, bgm_ext = os.path.splitext(os.path.basename(uploaded_bgm_file.name))
        bgm_ext = bgm_ext.lower() or ".mp3"
        custom_bgm_path = os.path.join(task_dir, f"custom-bgm{bgm_ext}")
        with open(custom_bgm_path, "wb") as f:
            f.write(uploaded_bgm_file.getbuffer())
        params.bgm_type = "upload"
        params.bgm_file = custom_bgm_path

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        local_videos_dir_abs = os.path.abspath(local_videos_dir)
        # 每次重新上传时都以本次选择的素材为准，避免旧素材不断重复追加。
        params.video_materials = []
        persisted_local_materials = []
        for file in uploaded_files:
            safe_name = os.path.basename(str(file.name or "upload.bin"))
            safe_name = safe_name.replace("..", "").replace("/", "_").replace("\\", "_")
            file_path = os.path.abspath(os.path.join(local_videos_dir_abs, f"{file.file_id}_{safe_name}"))
            if not file_path.startswith(local_videos_dir_abs + os.sep):
                logger.warning(f"blocked unsafe upload path: {file.name}")
                continue
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
                m = MaterialInfo()
                m.provider = "local"
                m.url = file_path
                params.video_materials.append(m)
                persisted_local_materials.append(
                    {
                        "provider": m.provider,
                        "url": m.url,
                        "duration": m.duration,
                    }
                )
        # 将已上传并保存到本地的视频素材写入会话，供后续只改文案时直接复用。
        st.session_state["local_video_materials"] = persisted_local_materials
    elif params.video_source == "local" and st.session_state["local_video_materials"]:
        # 当用户没有重新上传文件时，复用最近一次已经保存到磁盘的本地素材列表。
        params.video_materials = []
        for material in st.session_state["local_video_materials"]:
            m = MaterialInfo()
            m.provider = material.get("provider", "local")
            m.url = material.get("url", "")
            m.duration = material.get("duration", 0)
            if m.url:
                params.video_materials.append(m)

    # log_records lives inside _BG_TASKS (a module-level dict in bg_tasks.py),
    # NOT in st.session_state — background threads cannot safely access session_state.
    st.session_state["_active_task_id"] = task_id
    _BG_TASKS[task_id] = {"result": None, "error": None, "done": False, "logs": []}

    def log_received(msg):
        if config.ui.get("hide_log", False):
            return
        task = _BG_TASKS.get(task_id)
        if task is not None:
            task["logs"].append(msg)

    # Store the logger handler id so we can remove it when the task finishes.
    handler_id = logger.add(log_received)
    st.session_state["_log_handler_id"] = handler_id

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    def _worker(tid, p):
        try:
            r = tm.start(task_id=tid, params=p)
            _BG_TASKS[tid]["result"] = r
        except Exception as exc:
            _BG_TASKS[tid]["error"] = str(exc)
        finally:
            _BG_TASKS[tid]["done"] = True

    threading.Thread(target=_worker, args=(task_id, params), daemon=True).start()

# ── Polling block: runs on every rerun while a task is in progress ──────────
_active_tid = st.session_state.get("_active_task_id")
if _active_tid and _active_tid in _BG_TASKS:
    _task_state = _BG_TASKS[_active_tid]
    if not _task_state["done"]:
        st.info(tr("Generating Video") + " … " + tr("Please wait, this may take several minutes."))
        # Show live log output — logs list lives in _BG_TASKS (safe for thread writes).
        if not config.ui.get("hide_log", False):
            _log_lines = _task_state.get("logs", [])
            if _log_lines:
                st.code("\n".join(_log_lines))
        scroll_to_bottom()
        time.sleep(3)
        st.rerun()
    else:
        # Task finished — remove logger handler and clear active task state.
        _handler_id = st.session_state.pop("_log_handler_id", None)
        if _handler_id is not None:
            try:
                logger.remove(_handler_id)
            except Exception:
                pass
        st.session_state.pop("_active_task_id", None)
        _BG_TASKS.pop(_active_tid, None)

        if _task_state["error"]:
            st.error(tr("Video Generation Failed") + f": {_task_state['error']}")
            logger.error(tr("Video Generation Failed") + f": {_task_state['error']}")
            scroll_to_bottom()
            st.stop()

        result = _task_state["result"]
        if not result or "videos" not in result:
            st.error(tr("Video Generation Failed"))
            logger.error(tr("Video Generation Failed"))
            scroll_to_bottom()
            st.stop()

        video_files = result.get("videos", [])
        cover_image = result.get("cover_image", "")
        st.success(tr("Video Generation Completed"))
        try:
            if cover_image:
                st.image(cover_image, caption=tr("Generated Cover Image"), use_container_width=True)
            if video_files:
                player_cols = st.columns(len(video_files) * 2 + 1)
                for i, url in enumerate(video_files):
                    player_cols[i * 2 + 1].video(url)
        except Exception:
            pass

        open_task_folder(_active_tid)
        logger.info(tr("Video Generation Completed"))
        scroll_to_bottom()

config.save_config()
