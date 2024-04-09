import sys
import os

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    print("******** sys.path ********")
    print(sys.path)
    print("")

import json
import locale
import streamlit as st

import os
from uuid import uuid4
import platform
import streamlit.components.v1 as components
import toml
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

hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
st.title("MoneyPrinterTurbo")

font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")


def load_config() -> dict:
    try:
        return toml.load(config_file)
    except Exception as e:
        return {}


cfg = load_config()


def save_config():
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(toml.dumps(cfg))


def get_system_locale():
    try:
        loc = locale.getdefaultlocale()
        # zh_CN, zh_TW return zh
        # en_US, en_GB return en
        language_code = loc[0].split("_")[0]
        return language_code
    except Exception as e:
        return "en"


if 'video_subject' not in st.session_state:
    st.session_state['video_subject'] = ''
if 'video_script' not in st.session_state:
    st.session_state['video_script'] = ''
if 'video_terms' not in st.session_state:
    st.session_state['video_terms'] = ''
if 'ui_language' not in st.session_state:
    st.session_state['ui_language'] = cfg.get("ui_language", get_system_locale())


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


def load_locales():
    locales = {}
    for root, dirs, files in os.walk(i18n_dir):
        for file in files:
            if file.endswith(".json"):
                lang = file.split(".")[0]
                with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                    locales[lang] = json.loads(f.read())
    return locales


locales = load_locales()


def tr(key):
    loc = locales.get(st.session_state['ui_language'], {})
    return loc.get("Translation", {}).get(key, key)


display_languages = []
selected_index = 0
for i, code in enumerate(locales.keys()):
    display_languages.append(f"{code} - {locales[code].get('Language')}")
    if code == st.session_state['ui_language']:
        selected_index = i

selected_language = st.selectbox("Language", options=display_languages, label_visibility='collapsed',
                                 index=selected_index)
if selected_language:
    code = selected_language.split(" - ")[0].strip()
    st.session_state['ui_language'] = code
    cfg['ui_language'] = code
    save_config()

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
        saved_voice_name = cfg.get("voice_name", "")
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
        cfg['voice_name'] = voice_name
        save_config()

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
        params.font_name = st.selectbox(tr("Font"), font_names)

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
            params.text_fore_color = st.color_picker(tr("Font Color"), "#FFFFFF")
        with font_cols[1]:
            params.font_size = st.slider(tr("Font Size"), 30, 100, 60)

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            params.stroke_color = st.color_picker(tr("Stroke Color"), "#000000")
        with stroke_cols[1]:
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, 1.5)

start_button = st.button(tr("Generate Video"), use_container_width=True, type="primary")
if start_button:
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
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
