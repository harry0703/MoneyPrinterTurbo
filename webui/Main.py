import asyncio
import sys
import os
from uuid import uuid4
import streamlit as st
from loguru import logger
from app.models.schema import VideoParams, VideoAspect, VoiceNames
from app.services import task as tm

st.set_page_config(page_title="MoneyPrinterTurbo", page_icon="🤖", layout="wide",
                   initial_sidebar_state="auto")
st.title("MoneyPrinterTurbo")

root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")


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

panel = st.columns(2)
left_panel = panel[0]
right_panel = panel[1]

# define cfg as VideoParams class
cfg = VideoParams()

with left_panel:
    with st.container(border=True):
        st.write("**视频设置**")
        cfg.video_subject = st.text_area("视频主题", help="请输入视频主题")
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

    with st.container(border=True):
        st.write("**声音设置**")
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
        selected_friendly_name = st.selectbox("声音", options=list(friendly_names.values()))
        voice_name = list(friendly_names.keys())[list(friendly_names.values()).index(selected_friendly_name)]
        cfg.voice_name = voice_name

        song_names = [
            ("无背景音乐 No BGM", ""),
            ("随机背景音乐 Random BGM", "random"),
            *[(song, song) for song in get_all_songs()]
        ]
        selected_index = st.selectbox("背景音乐",
                                      index=1,
                                      options=range(len(song_names)),  # 使用索引作为内部选项值
                                      format_func=lambda x: song_names[x][0]  # 显示给用户的是标签
                                      )
        cfg.bgm_name = song_names[selected_index][1]

with right_panel:
    with st.container(border=True):
        st.write("**字幕设置**")
        font_names = get_all_fonts()
        cfg.font_name = st.selectbox("字体", font_names)
        cfg.text_fore_color = st.color_picker("字幕颜色", "#FFFFFF")
        cfg.font_size = st.slider("字幕大小", 30, 100, 60)
        cfg.stroke_color = st.color_picker("描边颜色", "#000000")
        cfg.stroke_width = st.slider("描边粗细", 0.0, 10.0, 1.5)

start_button = st.button("开始生成视频", use_container_width=True, type="primary")
if start_button:
    task_id = str(uuid4())
    st.session_state['started'] = True
    if not cfg.video_subject:
        st.error("视频主题不能为空")
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
