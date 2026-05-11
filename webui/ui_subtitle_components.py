import os
import sys
import streamlit as st
from typing import Optional
from loguru import logger

root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)


def get_all_fonts():
    font_dir = os.path.join(root_dir, "resource", "fonts")
    fonts = []
    if os.path.exists(font_dir):
        for file in os.listdir(font_dir):
            if file.endswith((".ttf", ".ttc", ".otf")):
                fonts.append(file)
    if not fonts:
        fonts = ["MicrosoftYaHeiBold.ttc"]
    return fonts


def _save_subtitle_param(config, param_name, old_value, new_value):
    if new_value != old_value:
        config.ui[param_name] = new_value
        config.save_config()
        logger.info(f"[Config Save] {param_name} changed from '{old_value}' to '{new_value}'")
        return True
    return False


def render_subtitle_settings(params, config, tr):
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        
        saved_subtitle_enabled = config.ui.get("subtitle_enabled", True)
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=saved_subtitle_enabled, key="subtitle_enabled")
        _save_subtitle_param(config, "subtitle_enabled", saved_subtitle_enabled, params.subtitle_enabled)
        
        if params.subtitle_enabled:
            font_names = get_all_fonts()
            saved_font_name = config.ui.get("font_name", "MicrosoftYaHeiBold.ttc")
            saved_font_name_index = font_names.index(saved_font_name) if saved_font_name in font_names else 0
            params.font_name = st.selectbox(tr("Font"), font_names, index=saved_font_name_index, key="subtitle_font_name")
            _save_subtitle_param(config, "font_name", saved_font_name, params.font_name)

            subtitle_positions = [
                (tr("Top"), "top"),
                (tr("Center"), "center"),
                (tr("Bottom"), "bottom"),
                (tr("Custom"), "custom"),
            ]
            saved_position = config.ui.get("subtitle_position", "bottom")
            selected_index = next((i for i, (_, value) in enumerate(subtitle_positions) if value == saved_position), 2)
            selected_index = st.selectbox(
                tr("Position"),
                index=selected_index,
                options=range(len(subtitle_positions)),
                format_func=lambda x: subtitle_positions[x][0],
                key="subtitle_position",
            )
            params.subtitle_position = subtitle_positions[selected_index][1]
            _save_subtitle_param(config, "subtitle_position", saved_position, params.subtitle_position)

            if params.subtitle_position == "custom":
                saved_custom_position = config.ui.get("subtitle_custom_position", 70.0)
                custom_position = st.text_input(
                    tr("Custom Position (% from top)"),
                    value=str(saved_custom_position),
                    key="subtitle_custom_position_input",
                )
                try:
                    params.custom_position = float(custom_position)
                    if params.custom_position < 0 or params.custom_position > 100:
                        st.error(tr("Please enter a value between 0 and 100"))
                    else:
                        _save_subtitle_param(config, "subtitle_custom_position", saved_custom_position, params.custom_position)
                except ValueError:
                    st.error(tr("Please enter a valid number"))

            font_cols = st.columns([0.3, 0.7])
            with font_cols[0]:
                saved_text_fore_color = config.ui.get("text_fore_color", "#FFFFFF")
                params.text_fore_color = st.color_picker(tr("Font Color"), saved_text_fore_color, key="subtitle_text_fore_color")
                _save_subtitle_param(config, "text_fore_color", saved_text_fore_color, params.text_fore_color)

            with font_cols[1]:
                saved_font_size = config.ui.get("font_size", 60)
                params.font_size = st.slider(tr("Font Size"), 30, 100, saved_font_size, key="subtitle_font_size")
                _save_subtitle_param(config, "font_size", saved_font_size, params.font_size)

            stroke_cols = st.columns([0.3, 0.7])
            with stroke_cols[0]:
                saved_stroke_color = config.ui.get("stroke_color", "#000000")
                params.stroke_color = st.color_picker(tr("Stroke Color"), saved_stroke_color, key="subtitle_stroke_color")
                _save_subtitle_param(config, "stroke_color", saved_stroke_color, params.stroke_color)
            
            with stroke_cols[1]:
                saved_stroke_width = config.ui.get("stroke_width", 1.5)
                params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, saved_stroke_width, key="subtitle_stroke_width")
                _save_subtitle_param(config, "stroke_width", saved_stroke_width, params.stroke_width)

            saved_text_background_color = config.ui.get("text_background_color", True)
            params.text_background_color = st.checkbox(tr("Enable Background Color"), value=saved_text_background_color, key="subtitle_text_background_color")
            _save_subtitle_param(config, "text_background_color", saved_text_background_color, params.text_background_color)

            saved_subtitle_margin = config.ui.get("subtitle_margin", 0.1)
            params.subtitle_margin = st.slider(tr("Subtitle Margin"), 0.0, 0.3, saved_subtitle_margin, step=0.01, key="subtitle_margin")
            _save_subtitle_param(config, "subtitle_margin", saved_subtitle_margin, params.subtitle_margin)
