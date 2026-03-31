import streamlit as st
from typing import Optional


def get_all_fonts():
    """获取所有可用字体"""
    import os
    font_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resource", "fonts")
    fonts = []
    if os.path.exists(font_dir):
        for file in os.listdir(font_dir):
            if file.endswith((".ttf", ".ttc", ".otf")):
                fonts.append(file)
    if not fonts:
        fonts = ["MicrosoftYaHeiBold.ttc"]
    return fonts


def render_subtitle_settings(params, config, tr):
    """
    渲染字幕设置面板
    
    Args:
        params: 参数对象
        config: 配置对象
        tr: 翻译函数
    """
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=config.ui.get("subtitle_enabled", True))
        config.ui["subtitle_enabled"] = params.subtitle_enabled
        
        if params.subtitle_enabled:
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
