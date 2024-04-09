import sys
import os

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    print("******** sys.path ********")
    print(sys.path)
    print("")

import streamlit as st

import os
from uuid import uuid4
import platform
import streamlit.components.v1 as components
from loguru import logger

st.set_page_config(page_title="MoneyPrinterTurbo",
                   page_icon="🤖",
                   layout="wide",
                   initial_sidebar_state="auto",
                   menu_items={
                       'Report a bug': "https://github.com/harry0703/MoneyPrinterTurbo/issues",
                       'About': "# MoneyPrinterTurbo\nSimply provide a topic or keyword for a video, and it will "
                                "automatically generate the video copy, video materials, video subtitles, "
                                "and video background music before synthesizing a high-definition short "
                                "video.\n\nhttps://github.com/harry0703/MoneyPrinterTurbo"
                   })

from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
from app.services import task as tm, llm, voice
from app.utils import utils
from app.config import config

hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
st.title("MoneyPrinterTurbo")

font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
system_locale = utils.get_system_locale()

if 'video_subject' not in st.session_state:
    st.session_state['video_subject'] = ''
if 'video_script' not in st.session_state:
    st.session_state['video_script'] = ''
if 'video_terms' not in st.session_state:
    st.session_state['video_terms'] = ''
if 'ui_language' not in st.session_state:
    st.session_state['ui_language'] = config.ui.get("language", system_locale)


def get_all_fonts():
    fonts = []
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
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
            if sys == 'Windows':
                os.system(f"start {path}")
            if sys == 'Darwin':
                os.system(f"open {path}")
    except Exception as e:
        logger.error(e)


def scroll_to_bottom():
    js = f"""
    <script>
        console.log("scroll_to_bottom");
        function scroll(dummy_var_to_force_repeat_execution){{
            var sections = parent.document.querySelectorAll('section.main');
            console.log(sections);
            for(let index = 0; index<sections.length; index++) {{
                sections[index].scrollTop = sections[index].scrollHeight;
            }}
        }}
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
        record['message'] = record['message'].replace(root_dir, ".")

        _format = '<green>{time:%Y-%m-%d %H:%M:%S}</> | ' + \
                  '<level>{level}</> | ' + \
                  '"{file.path}:{line}":<blue> {function}</> ' + \
                  '- <level>{message}</>' + "\n"
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
    loc = locales.get(st.session_state['ui_language'], {})
    return loc.get("Translation", {}).get(key, key)


with st.expander(tr("Basic Settings"), expanded=True):
    config_panels = st.columns(3)
    left_config_panel = config_panels[0]
    middle_config_panel = config_panels[1]
    right_config_panel = config_panels[2]
    with left_config_panel:
        display_languages = []
        selected_index = 0
        for i, code in enumerate(locales.keys()):
            display_languages.append(f"{code} - {locales[code].get('Language')}")
            if code == st.session_state['ui_language']:
                selected_index = i

        selected_language = st.selectbox(tr("Language"), options=display_languages,
                                         index=selected_index)
        if selected_language:
            code = selected_language.split(" - ")[0].strip()
            st.session_state['ui_language'] = code
            config.ui['language'] = code
            config.save_config()

    with middle_config_panel:
        #   openai
        #   moonshot (月之暗面)
        #   oneapi
        #   g4f
        #   azure
        #   qwen (通义千问)
        #   gemini
        #   ollama
        llm_providers = ['OpenAI', 'Moonshot', 'Azure', 'Qwen', 'Gemini', 'Ollama', 'G4f', 'OneAPI']
        saved_llm_provider = config.app.get("llm_provider", "OpenAI").lower()
        saved_llm_provider_index = 0
        for i, provider in enumerate(llm_providers):
            if provider.lower() == saved_llm_provider:
                saved_llm_provider_index = i
                break

        llm_provider = st.selectbox(tr("LLM Provider"), options=llm_providers, index=saved_llm_provider_index)
        llm_provider = llm_provider.lower()
        config.app["llm_provider"] = llm_provider
        st.write(f"**{tr('LLM Provider')}:** {llm_provider}")

        llm_api_key = config.app.get(f"{llm_provider}_api_key", "")
        llm_base_url = config.app.get(f"{llm_provider}_base_url", "")
        llm_model_name = config.app.get(f"{llm_provider}_model_name", "")
        st_llm_api_key = st.text_input(tr("API Key"), value=llm_api_key, type="password")
        st_llm_base_url = st.text_input(tr("Base Url"), value=llm_base_url)
        st_llm_model_name = st.text_input(tr("Model Name"), value=llm_model_name)
        if st_llm_api_key:
            config.app[f"{llm_provider}_api_key"] = st_llm_api_key
        if st_llm_base_url:
            config.app[f"{llm_provider}_base_url"] = st_llm_base_url
        if st_llm_model_name:
            config.app[f"{llm_provider}_model_name"] = st_llm_model_name

        config.save_config()

    with right_config_panel:
        pexels_api_key = config.app.get("pexels_api_keys", "")
        pexels_api_key = st.text_input(tr("Pexels API Key"), value=pexels_api_key, type="password")
        if pexels_api_key:
            config.app["pexels_api_keys"] = pexels_api_key
            config.save_config()

panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

params = VideoParams()

with left_panel:
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        params.video_subject = st.text_input(tr("Video Subject"),
                                             value=st.session_state['video_subject']).strip()

        video_languages = [
            (tr("Auto Detect"), ""),
        ]
        for code in ["zh-CN", "zh-TW", "de-DE", "en-US"]:
            video_languages.append((code, code))

        selected_index = st.selectbox(tr("Script Language"),
                                      index=0,
                                      options=range(len(video_languages)),  # 使用索引作为内部选项值
                                      format_func=lambda x: video_languages[x][0]  # 显示给用户的是标签
                                      )
        params.video_language = video_languages[selected_index][1]

        if st.button(tr("Generate Video Script and Keywords"), key="auto_generate_script"):
            with st.spinner(tr("Generating Video Script and Keywords")):
                script = llm.generate_script(video_subject=params.video_subject, language=params.video_language)
                terms = llm.generate_terms(params.video_subject, script)
                st.session_state['video_script'] = script
                st.session_state['video_terms'] = ", ".join(terms)

        params.video_script = st.text_area(
            tr("Video Script"),
            value=st.session_state['video_script'],
            height=280
        )
        if st.button(tr("Generate Video Keywords"), key="auto_generate_terms"):
            if not params.video_script:
                st.error(tr("Please Enter the Video Subject"))
                st.stop()

            with st.spinner(tr("Generating Video Keywords")):
                terms = llm.generate_terms(params.video_subject, params.video_script)
                st.session_state['video_terms'] = ", ".join(terms)

        params.video_terms = st.text_area(
            tr("Video Keywords"),
            value=st.session_state['video_terms'],
            height=50)

with middle_panel:
    with st.container(border=True):
        st.write(tr("Video Settings"))
        video_concat_modes = [
            (tr("Sequential"), "sequential"),
            (tr("Random"), "random"),
        ]
        selected_index = st.selectbox(tr("Video Concat Mode"),
                                      index=1,
                                      options=range(len(video_concat_modes)),  # 使用索引作为内部选项值
                                      format_func=lambda x: video_concat_modes[x][0]  # 显示给用户的是标签
                                      )
        params.video_concat_mode = VideoConcatMode(video_concat_modes[selected_index][1])

        video_aspect_ratios = [
            (tr("Portrait"), VideoAspect.portrait.value),
            (tr("Landscape"), VideoAspect.landscape.value),
        ]
        selected_index = st.selectbox(tr("Video Ratio"),
                                      options=range(len(video_aspect_ratios)),  # 使用索引作为内部选项值
                                      format_func=lambda x: video_aspect_ratios[x][0]  # 显示给用户的是标签
                                      )
        params.video_aspect = VideoAspect(video_aspect_ratios[selected_index][1])

        params.video_clip_duration = st.selectbox(tr("Clip Duration"), options=[2, 3, 4, 5, 6], index=1)
        params.video_count = st.selectbox(tr("Number of Videos Generated Simultaneously"), options=[1, 2, 3, 4, 5],
                                          index=0)
    with st.container(border=True):
        st.write(tr("Audio Settings"))
        voices = voice.get_all_voices(filter_locals=["zh-CN", "zh-HK", "zh-TW", "de-DE", "en-US"])
        friendly_names = {
            voice: voice.
            replace("Female", tr("Female")).
            replace("Male", tr("Male")).
            replace("Neural", "") for
            voice in voices}
        saved_voice_name = config.ui.get("voice_name", "")
        saved_voice_name_index = 0
        if saved_voice_name in friendly_names:
            saved_voice_name_index = list(friendly_names.keys()).index(saved_voice_name)
        else:
            for i, voice in enumerate(voices):
                if voice.lower().startswith(st.session_state['ui_language'].lower()):
                    saved_voice_name_index = i
                    break

        selected_friendly_name = st.selectbox(tr("Speech Synthesis"),
                                              options=list(friendly_names.values()),
                                              index=saved_voice_name_index)

        voice_name = list(friendly_names.keys())[list(friendly_names.values()).index(selected_friendly_name)]
        params.voice_name = voice_name
        config.ui['voice_name'] = voice_name
        config.save_config()

        params.voice_volume = st.selectbox(tr("Speech Volume"),
                                           options=[0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0], index=2)
        bgm_options = [
            (tr("No Background Music"), ""),
            (tr("Random Background Music"), "random"),
            (tr("Custom Background Music"), "custom"),
        ]
        selected_index = st.selectbox(tr("Background Music"),
                                      index=1,
                                      options=range(len(bgm_options)),  # 使用索引作为内部选项值
                                      format_func=lambda x: bgm_options[x][0]  # 显示给用户的是标签
                                      )
        # 获取选择的背景音乐类型
        bgm_type = bgm_options[selected_index][1]

        # 根据选择显示或隐藏组件
        if bgm_type == "custom":
            custom_bgm_file = st.text_input(tr("Custom Background Music File"))
            if custom_bgm_file and os.path.exists(custom_bgm_file):
                params.bgm_file = custom_bgm_file
                # st.write(f":red[已选择自定义背景音乐]：**{custom_bgm_file}**")
        params.bgm_volume = st.selectbox(tr("Background Music Volume"),
                                         options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], index=2)

with right_panel:
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=True)
        font_names = get_all_fonts()
        saved_font_name = config.ui.get("font_name", "")
        saved_font_name_index = 0
        if saved_font_name in font_names:
            saved_font_name_index = font_names.index(saved_font_name)
        params.font_name = st.selectbox(tr("Font"), font_names, index=saved_font_name_index)
        config.ui['font_name'] = params.font_name
        config.save_config()

        subtitle_positions = [
            (tr("Top"), "top"),
            (tr("Center"), "center"),
            (tr("Bottom"), "bottom"),
        ]
        selected_index = st.selectbox(tr("Position"),
                                      index=2,
                                      options=range(len(subtitle_positions)),  # 使用索引作为内部选项值
                                      format_func=lambda x: subtitle_positions[x][0]  # 显示给用户的是标签
                                      )
        params.subtitle_position = subtitle_positions[selected_index][1]

        font_cols = st.columns([0.3, 0.7])
        with font_cols[0]:
            saved_text_fore_color = config.ui.get("text_fore_color", "#FFFFFF")
            params.text_fore_color = st.color_picker(tr("Font Color"), saved_text_fore_color)
            config.ui['text_fore_color'] = params.text_fore_color

        with font_cols[1]:
            saved_font_size = config.ui.get("font_size", 60)
            params.font_size = st.slider(tr("Font Size"), 30, 100, saved_font_size)
            config.ui['font_size'] = params.font_size

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            params.stroke_color = st.color_picker(tr("Stroke Color"), "#000000")
        with stroke_cols[1]:
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, 1.5)

start_button = st.button(tr("Generate Video"), use_container_width=True, type="primary")
if start_button:
    config.save_config()
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        scroll_to_bottom()
        st.stop()

    if not config.app.get(f"{llm_provider}_api_key", ""):
        st.error(tr("Please Enter the LLM API Key"))
        scroll_to_bottom()
        st.stop()

    if not config.app.get("pexels_api_keys", ""):
        st.error(tr("Please Enter the Pexels API Key"))
        scroll_to_bottom()
        st.stop()

    log_container = st.empty()
    log_records = []


    def log_received(msg):
        with log_container:
            log_records.append(msg)
            st.code("\n".join(log_records))


    logger.add(log_received)

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    result = tm.start(task_id=task_id, params=params)

    video_files = result.get("videos", [])
    st.success(tr("Video Generation Completed"))
    try:
        if video_files:
            # center the video player
            player_cols = st.columns(len(video_files) * 2 + 1)
            for i, url in enumerate(video_files):
                player_cols[i * 2 + 1].video(url)
    except Exception as e:
        pass

    open_task_folder(task_id)
    logger.info(tr("Video Generation Completed"))
    scroll_to_bottom()
