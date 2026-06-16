import os
import sys
import webbrowser
from uuid import UUID, uuid4

import requests
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
if "match_materials_to_script" not in st.session_state:
    st.session_state["match_materials_to_script"] = bool(
        config.app.get("match_materials_to_script", False)
    )
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = config.ui.get("language", system_locale)
if "local_video_materials" not in st.session_state:
    # 记住用户最近一次已经落盘的本地素材，避免仅修改文案后二次生成时丢失素材列表。
    st.session_state["local_video_materials"] = []

# 加载语言文件
locales = utils.load_locales(i18n_dir)

# Criar barra superior com título, botão do modo preguiçoso e seleção de idioma
title_col, mode_col, lang_col = st.columns([3.5, 1.8, 1.2])

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
        "Language / Idioma",
        options=display_languages,
        index=selected_index,
        key="top_language_selector",
        label_visibility="collapsed",
    )
    if selected_language:
        code = selected_language.split(" - ")[0].strip()
        st.session_state["ui_language"] = code
        config.ui["language"] = code

with mode_col:
    lazy_mode_text = "Modo Fácil 😴" if st.session_state.get("ui_language", "en") == "pt" else "Easy Mode 0"
    lazy_mode_help = "Um assistente passo-a-passo simples para iniciantes" if st.session_state.get("ui_language", "en") == "pt" else "A simple step-by-step wizard for beginners"
    st.session_state["lazy_mode"] = st.toggle(
        lazy_mode_text,
        value=st.session_state.get("lazy_mode", False),
        help=lazy_mode_help,
        key="lazy_mode_toggle"
    )

support_locales = [
    "zh-CN",
    "zh-HK",
    "zh-TW",
    "de-DE",
    "en-US",
    "fr-FR",
    "ru-RU",
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
        path = os.path.abspath(os.path.join(tasks_root, normalized_task_id))

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

@st.cache_data(ttl=300, show_spinner=False)
def get_groq_model_ids(api_key: str, base_url: str) -> list[str]:
    if not api_key:
        return []

    normalized_base_url = (base_url or "https://api.groq.com/openai/v1").strip().rstrip("/")
    models_url = f"{normalized_base_url}/models"

    try:
        response = requests.get(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])

        model_ids = []
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_ids.append(model_id.strip())

        return sorted(set(model_ids))
    except Exception as e:
        logger.warning(f"failed to fetch groq models: {e}")
        return []

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
            # 下拉框需要展示“AIHubMix（推荐）”这类面向用户的文案，
            # 但配置文件和后端逻辑必须继续使用稳定的小写 provider id。
            # 因此这里显式维护 display label 和 provider id 的映射，避免
            # UI 文案变化污染 `config.app["llm_provider"]`。
            aihubmix_label = f"AIHubMix ({tr('Recommended')})"
            if config.ui.get("language") == "zh":
                aihubmix_label = "AIHubMix（推荐）"
            llm_provider_options = [
                ("OpenAI", "openai"),
                (aihubmix_label, "aihubmix"),
                ("AIML API", "aimlapi"),
                ("Moonshot", "moonshot"),
                ("Azure", "azure"),
                ("Qwen", "qwen"),
                ("DeepSeek", "deepseek"),
                ("ModelScope", "modelscope"),
                ("Gemini", "gemini"),
                ("Grok", "grok"),
                ("Groq", "groq"),
                ("Ollama", "ollama"),
                ("G4f", "g4f"),
                ("OneAPI", "oneapi"),
                ("Cloudflare", "cloudflare"),
                ("ERNIE", "ernie"),
                ("MiniMax", "minimax"),
                ("MiMo", "mimo"),
                ("Pollinations", "pollinations"),
                ("LiteLLM", "litellm"),
            ]
            llm_provider_labels = [label for label, _ in llm_provider_options]
            llm_provider_values = {
                label: provider_id for label, provider_id in llm_provider_options
            }
params = VideoParams(video_subject="")
params.match_materials_to_script = bool(
    st.session_state.get("match_materials_to_script", False)
)
uploaded_files = []
uploaded_audio_file = None

if st.session_state.get("lazy_mode", False):
    st.info("💡 **Modo Fácil Ativado:** Siga os 4 passos abaixo para criar o seu vídeo de forma super simples!")
    
    # Passo 1: Provedor de IA
    with st.container(border=True):
        st.markdown("### 🤖 Passo 1: Configurar a Inteligência Artificial (LLM)")
        st.write("Necessário para escrever o roteiro e sugerir palavras-chave do vídeo.")
        llm_providers = [
            ("OpenAI (Recomendado)", "openai"),
            ("AIHubMix (Compatível)", "aihubmix"),
            ("Google Gemini", "gemini"),
            ("DeepSeek", "deepseek"),
            ("Ollama (Local)", "ollama"),
        ]
        provider_labels = [p[0] for p in llm_providers]
        provider_values = {p[0]: p[1] for p in llm_providers}
        saved_provider = config.app.get("llm_provider", "openai").lower()
        default_idx = 0
        for idx, p in enumerate(llm_providers):
            if p[1] == saved_provider:
                default_idx = idx
                break
        selected_p = st.selectbox("Escolha o Provedor de IA", options=provider_labels, index=default_idx)
        llm_provider = provider_values[selected_p]
        config.app["llm_provider"] = llm_provider
        saved_api_key = config.app.get(f"{llm_provider}_api_key", "")
        api_key = st.text_input(f"Chave da API (API Key) para {selected_p}", value=saved_api_key, type="password")
        if api_key:
            config.app[f"{llm_provider}_api_key"] = api_key
            
    # Passo 2: Fonte de Vídeos
    with st.container(border=True):
        st.markdown("### 🎬 Passo 2: Chave de API de Vídeo Grátis (Pexels)")
        st.write("Permite descarregar automaticamente os vídeos de fundo para o seu tema.")
        st.markdown("[Clique aqui para obter uma chave gratuita do Pexels](https://www.pexels.com/api/)")
        saved_pexels_keys = config.app.get("pexels_api_keys", [])
        saved_pexels_key = saved_pexels_keys[0] if saved_pexels_keys else ""
        pexels_key = st.text_input("Chave do Pexels", value=saved_pexels_key, type="password")
        if pexels_key:
            config.app["pexels_api_keys"] = [pexels_key]
            
    # Passo 3: Tema do Vídeo
    with st.container(border=True):
        st.markdown("### 📝 Passo 3: O Tema do seu Vídeo")
        st.write("Escreva resumidamente o assunto do vídeo.")
        params.video_subject = st.text_input("Tema do Vídeo", placeholder="Ex: Curiosidades fascinantes sobre o espaço sideral", key="lazy_video_subject").strip()
        
    # Passo 4: Formato e Voz
    with st.container(border=True):
        st.markdown("### 🗣 Passo 4: Formato e Voz do Narrador")
        aspect_options = [("Vertical (9:16) - Para Shorts, TikTok, Reels", "9:16"), ("Horizontal (16:9) - Para YouTube", "16:9")]
        selected_aspect_idx = st.selectbox("Formato do Vídeo", options=[a[0] for a in aspect_options], index=0)
        selected_aspect = aspect_options[0][1] if "Vertical" in selected_aspect_idx else aspect_options[1][1]
        params.video_aspect = selected_aspect
        
        pt_voices = [
            ("Duarte (Português de Portugal - Masculino)", "pt-PT-DuarteNeural"),
            ("Raquel (Português de Portugal - Feminino)", "pt-PT-RaquelNeural"),
            ("Antonio (Português do Brasil - Masculino)", "pt-BR-AntonioNeural"),
            ("Francisca (Português do Brasil - Feminino)", "pt-BR-FranciscaNeural"),
        ]
        selected_voice_label = st.selectbox("Voz do Narrador", options=[v[0] for v in pt_voices], index=0)
        selected_voice = next(v[1] for v in pt_voices if v[0] == selected_voice_label)
        params.voice_name = selected_voice
        config.app["voice_name"] = selected_voice
        config.app["tts_provider"] = "edge"
        params.bgm_type = "random"
        params.bgm_volume = 0.2
        params.subtitle_enabled = True
        params.video_source = "pexels"
        params.video_clip_duration = 5
        params.voice_volume = 1.0
        params.voice_rate = 1.0
        params.subtitle_position = "bottom"
        params.font_size = 60
        params.text_fore_color = "#FFFFFF"
        params.stroke_color = "#000000"
        params.stroke_width = 1.5
        params.bgm_file = ""
        params.font_name = "STHeitiMedium.ttc"
        params.n_threads = 2
        params.paragraph_number = 2

else:
    llm_provider = config.app.get("llm_provider", "").lower()
    panel = st.columns(3)
    left_panel = panel[0]
    middle_panel = panel[1]
    right_panel = panel[2]
    with left_panel:
        with st.container(border=True):
            st.write(tr("Video Script Settings"))
            params.video_subject = st.text_input(
                tr("Video Subject"),
                key="video_subject",
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
    
            with st.expander(tr("Advanced Script Settings"), expanded=False):
                params.paragraph_number = st.slider(
                    tr("Script Paragraph Number"),
                    min_value=llm.MIN_SCRIPT_PARAGRAPH_NUMBER,
                    max_value=llm.MAX_SCRIPT_PARAGRAPH_NUMBER,
                    value=st.session_state.get("paragraph_number_input", 1),
                    key="paragraph_number_input",
                )
                params.video_script_prompt = st.text_area(
                    tr("Custom Script Requirements"),
                    height=100,
                    max_chars=llm.MAX_SCRIPT_PROMPT_LENGTH,
                    placeholder=tr("Custom Script Requirements Placeholder"),
                    key="video_script_prompt",
                ).strip()
    
                use_custom_system_prompt = st.checkbox(
                    tr("Use Custom System Prompt"),
                    help=tr("Use Custom System Prompt Help"),
                    key="use_custom_system_prompt",
                )
    
                if use_custom_system_prompt:
                    custom_system_prompt = st.text_area(
                        tr("Custom System Prompt"),
                        height=240,
                        max_chars=llm.MAX_SCRIPT_SYSTEM_PROMPT_LENGTH,
                        key="custom_system_prompt",
                    ).strip()
                    params.custom_system_prompt = custom_system_prompt
                else:
                    params.custom_system_prompt = ""
    
            if st.button(
                tr("Generate Video Script and Keywords"), key="auto_generate_script"
            ):
                with st.spinner(tr("Generating Video Script and Keywords")):
                    script = llm.generate_script(
                        video_subject=params.video_subject,
                        language=params.video_language,
                        paragraph_number=params.paragraph_number,
                        video_script_prompt=params.video_script_prompt,
                        custom_system_prompt=params.custom_system_prompt,
                    )
                    terms = llm.generate_terms(
                        params.video_subject,
                        script,
                        amount=8 if params.match_materials_to_script else 5,
                        match_script_order=params.match_materials_to_script,
                    )
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
                    terms = llm.generate_terms(
                        params.video_subject,
                        params.video_script,
                        amount=8 if params.match_materials_to_script else 5,
                        match_script_order=params.match_materials_to_script,
                    )
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
                (tr("Coverr"), "coverr"),
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
                # Streamlit 的文件类型校验对扩展名大小写敏感，这里同时放行大小写两种形式。
                local_file_types = ["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"]
                uploaded_files = st.file_uploader(
                    tr("Upload Local Files"),
                    type=local_file_types + [file_type.upper() for file_type in local_file_types],
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
            # Coverr 库 99% 是 16:9 横屏,默认竖屏会让画面被大量黑边包围。
            # 用 source-specific widget key 让每个 source 各自记忆 aspect 选择:
            #   - 首次切到 coverr → 默认 Landscape(index=1)
            #   - 其他 source 沿用 Portrait(index=0)
            #   - 用户在某 source 下手动改过 aspect,session_state 会记住,
            #     下次回到同一 source 时尊重用户选择,不会再被强制覆盖。
            default_aspect_index = 1 if params.video_source == "coverr" else 0
            selected_index = st.selectbox(
                tr("Video Ratio"),
                options=range(
                    len(video_aspect_ratios)
                ),  # Use the index as the internal option value
                format_func=lambda x: video_aspect_ratios[x][
                    0
                ],  # The label is displayed to the user
                index=default_aspect_index,
                key=f"video_aspect_for_{params.video_source}",
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
    
            with st.expander(tr("Advanced Video Settings"), expanded=False):
                # 默认关闭，避免影响老用户的随机素材体验。开启后只改变关键词和素材
                # 下载/拼接顺序，用于改善画面主题早于或晚于旁白的问题。
                params.match_materials_to_script = st.checkbox(
                    tr("Match Materials to Script Order"),
                    help=tr("Match Materials to Script Order Help"),
                    key="match_materials_to_script",
                )
                config.app["match_materials_to_script"] = params.match_materials_to_script
    
                video_codec_options = [
                    ("libx264 (CPU)", "libx264"),
                    ("NVIDIA NVENC (h264_nvenc)", "h264_nvenc"),
                    ("AMD AMF (h264_amf)", "h264_amf"),
                    ("Intel QSV (h264_qsv)", "h264_qsv"),
                    ("Windows MediaFoundation (h264_mf)", "h264_mf"),
                    ("macOS VideoToolbox (h264_videotoolbox)", "h264_videotoolbox"),
                ]
                saved_video_codec = config.app.get("video_codec", "libx264")
                saved_video_codec_values = [item[1] for item in video_codec_options]
                if saved_video_codec not in saved_video_codec_values:
                    saved_video_codec = "libx264"
                selected_codec_index = saved_video_codec_values.index(saved_video_codec)
                selected_codec_index = st.selectbox(
                    tr("Video Encoder"),
                    options=range(len(video_codec_options)),
                    index=selected_codec_index,
                    format_func=lambda x: video_codec_options[x][0],
                    help=tr("Video Encoder Help"),
                )
                config.app["video_codec"] = video_codec_options[selected_codec_index][1]
        with st.container(border=True):
            st.write(tr("Audio Settings"))
    
            # 添加TTS服务器选择下拉框
            tts_servers = [
                (voice.NO_VOICE_NAME, tr("No Voice")),
                ("azure-tts-v1", "Azure TTS V1"),
                ("azure-tts-v2", "Azure TTS V2"),
                ("siliconflow", "SiliconFlow TTS"),
                ("gemini-tts", "Google Gemini TTS"),
                ("mimo-tts", "Xiaomi MiMo TTS"),
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
    
            if selected_tts_server == voice.NO_VOICE_NAME:
                # 无配音是显式模式，只提供一个稳定 sentinel。这样普通 TTS 的空配置
                # 不会被误判为静音，后端也能继续通过同一条音频/字幕流程生成视频。
                filtered_voices = [voice.NO_VOICE_NAME]
            elif selected_tts_server == "siliconflow":
                # 获取硅基流动的声音列表
                filtered_voices = voice.get_siliconflow_voices()
            elif selected_tts_server == "gemini-tts":
                # 获取Gemini TTS的声音列表
                filtered_voices = voice.get_gemini_voices()
            elif selected_tts_server == "mimo-tts":
                # 获取 Xiaomi MiMo TTS 的预置音色列表
                filtered_voices = voice.get_mimo_voices()
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
    
            if selected_tts_server == voice.NO_VOICE_NAME:
                friendly_names = {voice.NO_VOICE_NAME: tr("No Voice")}
            else:
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
    
            # 无配音模式会生成静音占位音频，不展示试听按钮，避免用户误以为需要测试声音。
            if (
                friendly_names
                and selected_tts_server != voice.NO_VOICE_NAME
                and st.button(tr("Play Voice"))
            ):
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
                        voice_volume=params.voice_volume,
                    )
                    # if the voice file generation failed, try again with a default content.
                    if not sub_maker:
                        play_content = "This is a example voice. if you hear this, the voice synthesis failed with the original content."
                        sub_maker = voice.tts(
                            text=play_content,
                            voice_name=voice_name,
                            voice_rate=params.voice_rate,
                            voice_file=audio_file,
                            voice_volume=params.voice_volume,
                        )
    
                    if sub_maker and os.path.exists(audio_file):
                        st.audio(audio_file, format="audio/mp3")
                        if os.path.exists(audio_file):
                            os.remove(audio_file)
    
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
    
            # 当选择 Xiaomi MiMo TTS 时，复用 MiMo LLM provider 的 API Key。
            # 这样用户如果同时使用 MiMo 生成文案和语音，只需要维护一份密钥。
            if selected_tts_server == "mimo-tts" or (
                voice_name and voice.is_mimo_voice(voice_name)
            ):
                saved_mimo_api_key = config.app.get("mimo_api_key", "")
    
                mimo_api_key = st.text_input(
                    tr("MiMo API Key"),
                    value=saved_mimo_api_key,
                    type="password",
                    key="mimo_tts_api_key_input",
                )
    
                st.info(
                    tr("MiMo TTS Settings")
                    + ":\n"
                    + "- "
                    + tr("Uses Xiaomi MiMo V2.5 TTS preset voices")
                    + "\n"
                    + "- "
                    + tr("Speed and volume are currently handled by the provider defaults")
                )
    
                config.app["mimo_api_key"] = mimo_api_key
    
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
                type=custom_audio_file_types
                + [file_type.upper() for file_type in custom_audio_file_types],
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
                custom_bgm_file = st.text_input(
                    tr("Custom Background Music File"), key="custom_bgm_file_input"
                )
                if custom_bgm_file:
                    # 这里不直接用 os.path.exists 判断，因为用户常见输入是
                    # output000.mp3，这个文件名需要由服务层映射到 resource/songs
                    # 目录后再校验。服务层会统一限制目录和文件类型，避免任意路径读取。
                    params.bgm_file = custom_bgm_file.strip()
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
    
            subtitle_bg_cols = st.columns([0.4, 0.6])
            saved_subtitle_background_enabled = config.ui.get(
                "subtitle_background_enabled", True
            )
            with subtitle_bg_cols[0]:
                subtitle_background_enabled = st.checkbox(
                    tr("Enable Subtitle Background"),
                    value=saved_subtitle_background_enabled,
                )
            config.ui["subtitle_background_enabled"] = subtitle_background_enabled
            if subtitle_background_enabled:
                with subtitle_bg_cols[1]:
                    saved_subtitle_background_color = config.ui.get(
                        "subtitle_background_color", "#000000"
                    )
                    params.text_background_color = st.color_picker(
                        tr("Subtitle Background Color"),
                        saved_subtitle_background_color,
                    )
                    config.ui["subtitle_background_color"] = params.text_background_color
            else:
                params.text_background_color = False
    
            saved_rounded_subtitle_background = config.ui.get(
                "rounded_subtitle_background", False
            )
            # 背景关闭时，圆角背景没有可渲染的底色。这里禁用控件并保留原配置，
            # 用户下次重新开启字幕背景后，可以继续使用之前保存的圆角偏好。
            params.rounded_subtitle_background = st.checkbox(
                tr("Rounded Subtitle Background"),
                value=(
                    saved_rounded_subtitle_background
                    if subtitle_background_enabled
                    else False
                ),
                help=tr("Rounded Subtitle Background Help"),
                disabled=not subtitle_background_enabled,
            )
            if subtitle_background_enabled:
                config.ui["rounded_subtitle_background"] = (
                    params.rounded_subtitle_background
                )
        with st.expander(tr("Click to show API Key management"), expanded=False):
            st.subheader(tr("Manage Pexels, Pixabay and Coverr API Keys"))
    
            col1, col2, col3 = st.tabs([
                tr("Pexels API Keys"),
                tr("Pixabay API Keys"),
                tr("Coverr API Keys"),
            ])
    
            with col1:
                st.subheader(tr("Pexels API Keys"))
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
                st.subheader(tr("Pixabay API Keys"))
    
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
    
            with col3:
                st.subheader(tr("Coverr API Keys"))
    
                # 与 pexels/pixabay 不同,coverr_api_keys 是 PR 新增配置项,
                # 老用户的 config.toml 不一定包含,这里先兜底初始化为空列表,
                # 防止下面 .append / 索引访问触发 KeyError。
                if "coverr_api_keys" not in config.app or config.app["coverr_api_keys"] is None:
                    config.app["coverr_api_keys"] = []
    
                if config.app["coverr_api_keys"]:
                    st.write(tr("Current Keys:"))
                    for key in config.app["coverr_api_keys"]:
                        st.code(key)
                else:
                    st.info(tr("No Coverr API Keys currently"))
    
                new_key = st.text_input(tr("Add Coverr API Key"), key="coverr_new_key")
                if st.button(tr("Add Coverr API Key")):
                    if new_key and new_key not in config.app["coverr_api_keys"]:
                        config.app["coverr_api_keys"].append(new_key)
                        config.save_config()
                        st.success(tr("Coverr API Key added successfully"))
                    elif new_key in config.app["coverr_api_keys"]:
                        st.warning(tr("This API Key already exists"))
                    else:
                        st.error(tr("Please enter a valid API Key"))
    
                if config.app["coverr_api_keys"]:
                    delete_key = st.selectbox(
                        tr("Select Coverr API Key to delete"), config.app["coverr_api_keys"], key="coverr_delete_key"
                    )
                    if st.button(tr("Delete Selected Coverr API Key")):
                        config.app["coverr_api_keys"].remove(delete_key)
                        config.save_config()
                        st.success(tr("Coverr API Key deleted successfully"))
    
start_button = st.button(tr("Generate Video"), use_container_width=True, type="primary")
if start_button:
    config.save_config()
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        scroll_to_bottom()
        st.stop()

    if params.video_source not in ["pexels", "pixabay", "coverr", "local"]:
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

    if params.video_source == "coverr" and not config.app.get("coverr_api_keys", ""):
        st.error(tr("Please Enter the Coverr API Key"))
        scroll_to_bottom()
        st.stop()

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

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        # 每次重新上传时都以本次选择的素材为准，避免旧素材不断重复追加。
        params.video_materials = []
        persisted_local_materials = []
        for file in uploaded_files:
            file_path = os.path.join(local_videos_dir, f"{file.file_id}_{file.name}")
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
