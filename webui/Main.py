import streamlit as st

st.set_page_config(page_title="MoneyPrinterTurbo", page_icon="🤖", layout="wide",
                   initial_sidebar_state="auto")
import sys
import os
from uuid import uuid4

from loguru import logger
from app.models.schema import VideoParams, VideoAspect, VoiceNames, VideoConcatMode
from app.services import task as tm, llm

hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
st.title("MoneyPrinterTurbo")
st.write(
    "⚠️ 先在 **config.toml** 中设置 `pexels_api_keys` 和 `llm_provider` 参数，根据不同的 llm_provider，配置对应的 **API KEY**"
)

root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")

# st.session_state

if 'video_subject' not in st.session_state:
    st.session_state['video_subject'] = ''
if 'video_script' not in st.session_state:
    st.session_state['video_script'] = ''
if 'video_terms' not in st.session_state:
    st.session_state['video_terms'] = ''


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

panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

# define cfg as VideoParams class
cfg = VideoParams()

with left_panel:
    with st.container(border=True):
        st.write("**文案设置**")
        cfg.video_subject = st.text_input("视频主题（给定一个关键词，:red[AI自动生成]视频文案）",
                                          value=st.session_state['video_subject']).strip()
        if st.button("点击使用AI根据**主题**生成 【视频文案】 和 【视频关键词】", key="auto_generate_script"):
            with st.spinner("AI正在生成视频文案和关键词..."):
                script = llm.generate_script(cfg.video_subject)
                terms = llm.generate_terms(cfg.video_subject, script)
                st.toast('AI生成成功')
                st.session_state['video_script'] = script
                st.session_state['video_terms'] = ", ".join(terms)

        cfg.video_script = st.text_area(
            "视频文案（:blue[①可不填，使用AI生成  ②合理使用标点断句，有助于生成字幕]）",
            value=st.session_state['video_script'],
            height=280
        )
        if st.button("点击使用AI根据**文案**生成【视频关键词】", key="auto_generate_terms"):
            if not cfg.video_script:
                st.error("请先填写视频文案")
                st.stop()

            with st.spinner("AI正在生成视频关键词..."):
                terms = llm.generate_terms(cfg.video_subject, cfg.video_script)
                st.toast('AI生成成功')
                st.session_state['video_terms'] = ", ".join(terms)

        cfg.video_terms = st.text_area(
            "视频关键词（:blue[①可不填，使用AI生成 ②用**英文逗号**分隔，只支持英文]）",
            value=st.session_state['video_terms'],
            height=50)

with middle_panel:
    with st.container(border=True):
        st.write("**视频设置**")
        video_concat_modes = [
            ("顺序拼接", "sequential"),
            ("随机拼接（推荐）", "random"),
        ]
        selected_index = st.selectbox("视频拼接模式",
                                      index=1,
                                      options=range(len(video_concat_modes)),  # 使用索引作为内部选项值
                                      format_func=lambda x: video_concat_modes[x][0]  # 显示给用户的是标签
                                      )
        cfg.video_concat_mode = VideoConcatMode(video_concat_modes[selected_index][1])

        video_aspect_ratios = [
            ("竖屏 9:16（抖音视频）", VideoAspect.portrait.value),
            ("横屏 16:9（西瓜视频）", VideoAspect.landscape.value),
            # ("方形 1:1", VideoAspect.square.value)
        ]
        selected_index = st.selectbox("视频比例",
                                      options=range(len(video_aspect_ratios)),  # 使用索引作为内部选项值
                                      format_func=lambda x: video_aspect_ratios[x][0]  # 显示给用户的是标签
                                      )
        cfg.video_aspect = VideoAspect(video_aspect_ratios[selected_index][1])

        cfg.video_clip_duration = st.selectbox("视频片段最大时长(秒)", options=[2, 3, 4, 5, 6], index=1)
        cfg.video_count = st.selectbox("同时生成视频数量", options=[1, 2, 3, 4, 5], index=0)
    with st.container(border=True):
        st.write("**音频设置**")
        # 创建一个映射字典，将原始值映射到友好名称
        friendly_names = {
            voice: voice.
            replace("female", "女性").
            replace("male", "男性").
            replace("zh-CN", "中文").
            replace("zh-HK", "香港").
            replace("zh-TW", "台湾").
            replace("en-US", "英文").
            replace("Neural", "") for
            voice in VoiceNames}
        selected_friendly_name = st.selectbox("朗读声音", options=list(friendly_names.values()))
        voice_name = list(friendly_names.keys())[list(friendly_names.values()).index(selected_friendly_name)]
        cfg.voice_name = voice_name

        bgm_options = [
            ("无背景音乐 No BGM", ""),
            ("随机背景音乐 Random BGM", "random"),
            ("自定义背景音乐 Custom BGM", "custom"),
        ]
        selected_index = st.selectbox("背景音乐",
                                      index=1,
                                      options=range(len(bgm_options)),  # 使用索引作为内部选项值
                                      format_func=lambda x: bgm_options[x][0]  # 显示给用户的是标签
                                      )
        # 获取选择的背景音乐类型
        bgm_type = bgm_options[selected_index][1]

        # 根据选择显示或隐藏组件
        if bgm_type == "custom":
            custom_bgm_file = st.text_input("请输入自定义背景音乐的文件路径：")
            if custom_bgm_file and os.path.exists(custom_bgm_file):
                cfg.bgm_file = custom_bgm_file
                # st.write(f":red[已选择自定义背景音乐]：**{custom_bgm_file}**")
        cfg.bgm_volume = st.selectbox("背景音乐音量（0.2表示20%，背景声音不宜过高）",
                                      options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], index=2)

with right_panel:
    with st.container(border=True):
        st.write("**字幕设置**")
        cfg.subtitle_enabled = st.checkbox("生成字幕（若取消勾选，下面的设置都将不生效）", value=True)
        font_names = get_all_fonts()
        cfg.font_name = st.selectbox("字体", font_names)

        subtitle_positions = [
            ("顶部（top）", "top"),
            ("居中（center）", "center"),
            ("底部（bottom，推荐）", "bottom"),
        ]
        selected_index = st.selectbox("字幕位置",
                                      index=2,
                                      options=range(len(subtitle_positions)),  # 使用索引作为内部选项值
                                      format_func=lambda x: subtitle_positions[x][0]  # 显示给用户的是标签
                                      )
        cfg.subtitle_position = subtitle_positions[selected_index][1]

        font_cols = st.columns([0.3, 0.7])
        with font_cols[0]:
            cfg.text_fore_color = st.color_picker("字幕颜色", "#FFFFFF")
        with font_cols[1]:
            cfg.font_size = st.slider("字幕大小", 30, 100, 60)

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            cfg.stroke_color = st.color_picker("描边颜色", "#000000")
        with stroke_cols[1]:
            cfg.stroke_width = st.slider("描边粗细", 0.0, 10.0, 1.5)

start_button = st.button("开始生成视频", use_container_width=True, type="primary")
if start_button:
    task_id = str(uuid4())
    if not cfg.video_subject and not cfg.video_script:
        st.error("视频主题 或 视频文案，不能同时为空")
        st.stop()

    st.write(cfg)

    log_container = st.empty()

    log_records = []


    def log_received(msg):
        with log_container:
            log_records.append(msg)
            st.code("\n".join(log_records))


    logger.add(log_received)

    logger.info("开始生成视频")

    tm.start(task_id=task_id, params=cfg)
