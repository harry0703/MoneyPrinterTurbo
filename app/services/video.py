import glob
import os
import random
import uuid
from typing import List

from loguru import logger
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.services.utils import title_animations
from app.utils import utils


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"max duration of audio: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"each clip will be maximum {req_dur} seconds long")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    clips = []
    video_duration = 0

    raw_clips = []
    for video_path in video_paths:
        clip = VideoFileClip(video_path).without_audio()
        clip_duration = clip.duration
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)
            split_clip = clip.subclipped(start_time, end_time)
            raw_clips.append(split_clip)
            # logger.info(f"splitting from {start_time:.2f} to {end_time:.2f}, clip duration {clip_duration:.2f}, split_clip duration {split_clip.duration:.2f}")
            start_time = end_time
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random video_paths order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(raw_clips)

    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    # 用于跟踪是否是第一个视频片段
    is_first_clip = True

    while video_duration < audio_duration:
        for clip in raw_clips:
            # Check if clip is longer than the remaining audio
            if (audio_duration - video_duration) < clip.duration:
                clip = clip.subclipped(0, (audio_duration - video_duration))
            # Only shorten clips if the calculated clip length (req_dur) is shorter than the actual clip to prevent still image
            elif req_dur < clip.duration:
                clip = clip.subclipped(0, req_dur)
            clip = clip.with_fps(30)

            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height

                if clip_ratio == video_ratio:
                    # Resize proportionally
                    clip = clip.resized((video_width, video_height))
                else:
                    # Resize proportionally
                    if clip_ratio > video_ratio:
                        # Resize proportionally based on the target width
                        scale_factor = video_width / clip_w
                    else:
                        # Resize proportionally based on the target height
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)
                    clip_resized = clip.resized(new_size=(new_width, new_height))

                    background = ColorClip(
                        size=(video_width, video_height), color=(0, 0, 0)
                    )
                    clip = CompositeVideoClip(
                        [
                            background.with_duration(clip.duration),
                            clip_resized.with_position("center"),
                        ]
                    )

                logger.info(
                    f"resizing video to {video_width} x {video_height}, clip size: {clip_w} x {clip_h}"
                )

            # 如果是第一个视频片段，不应用转场效果
            if is_first_clip:
                logger.info("First clip: no transition effect applied")
                # 不应用任何转场效果
                is_first_clip = False  # 更新标志，后续片段将应用转场效果
            else:
                # 对后续视频片段应用转场效果
                shuffle_side = random.choice(["left", "right", "top", "bottom"])
                logger.info(f"Using transition mode: {video_transition_mode}")
                if video_transition_mode.value == VideoTransitionMode.none.value:
                    clip = clip
                elif video_transition_mode.value == VideoTransitionMode.fade_in.value:
                    clip = video_effects.fadein_transition(clip, 1)
                elif video_transition_mode.value == VideoTransitionMode.fade_out.value:
                    clip = video_effects.fadeout_transition(clip, 1)
                elif video_transition_mode.value == VideoTransitionMode.slide_in.value:
                    clip = video_effects.slidein_transition(clip, 1, shuffle_side)
                elif video_transition_mode.value == VideoTransitionMode.slide_out.value:
                    clip = video_effects.slideout_transition(clip, 1, shuffle_side)
                elif video_transition_mode.value == VideoTransitionMode.shuffle.value:
                    transition_funcs = [
                        lambda c: video_effects.fadein_transition(c, 1),
                        lambda c: video_effects.fadeout_transition(c, 1),
                        lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                        lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                    ]
                    shuffle_transition = random.choice(transition_funcs)
                    clip = shuffle_transition(clip)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)

            clips.append(clip)
            video_duration += clip.duration
    clips = [CompositeVideoClip([clip]) for clip in clips]
    video_clip = concatenate_videoclips(clips)
    video_clip = video_clip.with_fps(30)
    logger.info("writing")
    # https://github.com/harry0703/MoneyPrinterTurbo/issues/111#issuecomment-2032354030
    video_clip.write_videofile(
        filename=combined_video_path,
        threads=threads,
        logger=None,
        temp_audiofile_path=output_dir,
        audio_codec="aac",
        fps=30,
    )
    video_clip.close()
    logger.success("completed")
    return combined_video_path


def create_title_sticker(text, font, font_size, style, background, background_color, border, border_color, size, background_enabled=True, text_color="#FFFFFF"):
    """
    创建标题贴纸

    :param text: 标题文本
    :param font: 字体路径
    :param font_size: 字体大小
    :param style: 标题样式（rainbow, neon, gradient, chinese_style等）
    :param background: 背景类型（none, rounded_rect, rect等）
    :param background_color: 背景颜色
    :param border: 是否有边框
    :param border_color: 边框颜色
    :param size: 视频尺寸
    :param background_enabled: 是否启用背景
    :param text_color: 文字颜色
    :return: ImageClip对象
    """
    if not text:
        return None

    video_width, video_height = size

    # 创建字体对象
    font_obj = ImageFont.truetype(font, font_size)

    # 计算文本尺寸
    left, top, right, bottom = font_obj.getbbox(text)
    text_width = right - left
    text_height = bottom - top

    # 设置贴纸尺寸（比文本略大）
    padding_x = int(text_width * 0.3)
    padding_y = int(text_height * 0.5)
    sticker_width = text_width + padding_x * 2
    sticker_height = text_height + padding_y * 2

    # 确保文本在背景中垂直居中
    text_y_position = (sticker_height - text_height) // 2

    # 创建透明背景图像
    img = Image.new('RGBA', (sticker_width, sticker_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 绘制背景（如果启用了背景）
    if background != "none" and background_enabled:
        # 确保背景颜色完全不透明
        if background_color.startswith('#') and len(background_color) == 7:
            bg_color = background_color + 'ff'  # 添加不透明度
        else:
            bg_color = background_color

        if background == "rounded_rect":
            # 绘制圆角矩形
            radius = int(sticker_height * 0.3)  # 圆角半径
            draw.rounded_rectangle(
                [(0, 0), (sticker_width, sticker_height)],
                radius=radius,
                fill=bg_color
            )
        elif background == "rect":
            # 绘制矩形
            draw.rectangle(
                [(0, 0), (sticker_width, sticker_height)],
                fill=bg_color
            )

    # 根据样式绘制文本
    if style == "chinese_style":
        # 中国风格效果：红色填充+黄色粗描边
        # 解析文字颜色
        try:
            if text_color.startswith('#'):
                hex_color = text_color.lstrip('#')
                r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                fill_color = (r, g, b, 255)
            else:
                fill_color = (255, 0, 0, 255)  # 默认红色
        except Exception:
            fill_color = (255, 0, 0, 255)  # 默认红色

        # 描边颜色（默认黄色）
        stroke_color = border_color if border else "#FFD700"

        # 绘制粗描边（多层描边增强效果）
        stroke_width = max(4, font_size // 15)  # 描边宽度
        for offset in range(stroke_width, 0, -1):
            for dx, dy in [(ox, oy) for ox in range(-offset, offset+1, max(1, offset//2)) for oy in range(-offset, offset+1, max(1, offset//2))]:
                draw.text((padding_x + dx, text_y_position + dy), text, font=font_obj, fill=stroke_color)

        # 绘制主文本（红色填充）
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=fill_color)

    elif style == "rainbow":
        # 彩虹渐变文字
        rainbow_colors = ["#FF0000", "#FF7F00", "#FFFF00", "#00FF00", "#0000FF", "#4B0082", "#9400D3"]
        # 创建渐变色文本
        gradient_img = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient_img)

        # 计算每个字符的颜色
        for i, char in enumerate(text):
            color_idx = i % len(rainbow_colors)
            char_width = font_obj.getbbox(char)[2] - font_obj.getbbox(char)[0]
            gradient_draw.text((left + i * char_width, 0), char, font=font_obj, fill=rainbow_colors[color_idx])

        # 添加白色描边
        if border:
            for offset_x, offset_y in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                draw.text((padding_x + offset_x, text_y_position + offset_y), text, font=font_obj, fill=border_color)

        # 将渐变文本粘贴到主图像
        img.paste(gradient_img, (padding_x, text_y_position), gradient_img)

    elif style == "neon":
        # 霓虹灯效果
        glow_color = "#FF4500"  # 橙红色
        outer_glow_color = "#FFFF00"  # 黄色外发光

        # 添加外发光效果
        for offset in range(3, 0, -1):
            alpha = 100 - offset * 30
            glow_alpha = max(0, alpha)
            glow_color_with_alpha = glow_color[0:7] + format(glow_alpha, '02x')
            for dx, dy in [(ox, oy) for ox in range(-offset, offset+1) for oy in range(-offset, offset+1)]:
                draw.text((padding_x + dx, text_y_position + dy), text, font=font_obj, fill=glow_color_with_alpha)

        # 添加内发光
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=outer_glow_color)

        # 添加主文本
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=glow_color)

        # 应用模糊效果增强霓虹感
        img = img.filter(ImageFilter.GaussianBlur(1))

    elif style == "gradient":
        # 渐变效果
        start_color = (255, 0, 0)  # 红色
        end_color = (0, 0, 255)  # 蓝色

        # 创建渐变色文本
        gradient_img = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient_img)

        # 绘制渐变背景
        for y in range(text_height):
            r = int(start_color[0] + (end_color[0] - start_color[0]) * y / text_height)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * y / text_height)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * y / text_height)
            gradient_draw.line([(0, y), (text_width, y)], fill=(r, g, b, 255))

        # 创建文本蒙版
        mask = Image.new('L', (text_width, text_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.text((0, 0), text, font=font_obj, fill=255)

        # 应用蒙版到渐变图像
        gradient_text = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
        gradient_text.paste(gradient_img, (0, 0), mask)

        # 添加描边
        if border:
            for offset_x, offset_y in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                draw.text((padding_x + offset_x, text_y_position + offset_y), text, font=font_obj, fill=border_color)

        # 将渐变文本粘贴到主图像
        img.paste(gradient_text, (padding_x, text_y_position), gradient_text)

    else:  # 默认样式
        # 添加描边
        if border:
            for offset_x, offset_y in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                draw.text((padding_x + offset_x, text_y_position + offset_y), text, font=font_obj, fill=border_color)

        # 绘制主文本
        draw.text((padding_x, text_y_position), text, font=font_obj, fill="#FFFFFF")

    # 保存为临时文件
    temp_img_path = os.path.join(utils.storage_dir("temp", create=True), f"title_sticker_{str(uuid.uuid4())}.png")
    img.save(temp_img_path, format="PNG")

    # 创建图像剪辑
    clip = ImageClip(temp_img_path)

    # 删除临时文件
    try:
        os.remove(temp_img_path)
    except Exception as e:
        logger.warning(f"Failed to remove temporary image file: {e}")

    return clip


def create_art_text_clip(text, font, font_size, color, art_font_type, art_font_background, size, text_align='center'):
    """
    创建艺术字体字幕

    :param text: 文本内容
    :param font: 字体路径
    :param font_size: 字体大小
    :param color: 字体颜色
    :param art_font_type: 艺术字体类型（normal, shadow, outline, 3d, neon, metallic）
    :param art_font_background: 背景颜色
    :param size: 字幕大小
    :param text_align: 文本对齐方式
    :return: TextClip对象
    """
    width, height = size[0], None

    # 创建一个透明背景的图像
    # 首先计算文本高度
    font_obj = ImageFont.truetype(font, font_size)
    lines = text.split('\n')
    total_height = 0
    for line in lines:
        left, top, right, bottom = font_obj.getbbox(line)
        line_height = bottom - top
        total_height += line_height + 10  # 添加行间距

    # 创建背景图像
    if art_font_background != "none" and art_font_background != "":
        # 如果是预定义颜色
        if art_font_background in ["red", "blue", "green", "yellow", "purple", "orange"]:
            bg_colors = {
                "red": (255, 0, 0, 180),
                "blue": (0, 0, 255, 180),
                "green": (0, 128, 0, 180),
                "yellow": (255, 255, 0, 180),
                "purple": (128, 0, 128, 180),
                "orange": (255, 165, 0, 180)
            }
            bg_color = bg_colors.get(art_font_background, (255, 0, 0, 180))
        else:
            # 如果是自定义颜色（如#FF0000）
            try:
                # 将十六进制颜色代码转换为RGBA
                hex_color = art_font_background.lstrip('#')
                r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                bg_color = (r, g, b, 180)  # 半透明
            except Exception:
                bg_color = (255, 0, 0, 180)  # 默认红色

        # 创建背景图像，比文本区域稍大一些
        bg_img = Image.new('RGBA', (width, total_height + 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bg_img)
        # 绘制圆角矩形背景
        draw.rounded_rectangle([(10, 5), (width-10, total_height+35)], radius=20, fill=bg_color)
    else:
        bg_img = Image.new('RGBA', (width, total_height + 40), (0, 0, 0, 0))

    # 创建文本图像
    txt_img = Image.new('RGBA', (width, total_height + 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_img)

    # 解析颜色
    try:
        if color.startswith('#'):
            hex_color = color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            text_color = (r, g, b, 255)
        else:
            text_color = (255, 255, 255, 255)  # 默认白色
    except Exception:
        text_color = (255, 255, 255, 255)  # 默认白色

    # 根据艺术字体类型应用不同的效果
    y_offset = 20  # 初始垂直偏移
    for line in lines:
        # 计算文本宽度以实现居中对齐
        left, top, right, bottom = font_obj.getbbox(line)
        text_width = right - left
        line_height = bottom - top

        if text_align == 'center':
            x_position = (width - text_width) // 2
        elif text_align == 'right':
            x_position = width - text_width - 20
        else:  # left
            x_position = 20

        if art_font_type == "shadow":
            # 阴影效果
            shadow_offset = max(2, font_size // 20)  # 阴影偏移量
            draw.text((x_position + shadow_offset, y_offset + shadow_offset), line, font=font_obj, fill=(0, 0, 0, 160))
            draw.text((x_position, y_offset), line, font=font_obj, fill=text_color)

        elif art_font_type == "outline":
            # 描边效果
            outline_size = max(2, font_size // 25)  # 描边大小
            # 绘制描边（四个方向）
            for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1), (-outline_size,0), (outline_size,0), (0,-outline_size), (0,outline_size)]:
                draw.text((x_position + dx, y_offset + dy), line, font=font_obj, fill=(0, 0, 0, 200))
            # 绘制主文本
            draw.text((x_position, y_offset), line, font=font_obj, fill=text_color)

        elif art_font_type == "3d":
            # 3D立体效果
            depth = max(3, font_size // 15)  # 3D深度
            for i in range(depth, 0, -1):
                alpha = 100 + (155 * i // depth)  # 渐变透明度
                shadow_color = (0, 0, 0, alpha)
                draw.text((x_position - i, y_offset + i), line, font=font_obj, fill=shadow_color)
            # 绘制主文本
            draw.text((x_position, y_offset), line, font=font_obj, fill=text_color)

        elif art_font_type == "neon":
            # 霓虹灯效果
            glow_iterations = 5
            glow_color = (0, 255, 255, 50)  # 青色荧光
            for i in range(glow_iterations, 0, -1):
                blur_radius = i * 2
                for dx, dy in [(j, k) for j in range(-1, 2) for k in range(-1, 2)]:
                    draw.text((x_position + dx * blur_radius, y_offset + dy * blur_radius),
                             line, font=font_obj, fill=(glow_color[0], glow_color[1], glow_color[2], glow_color[3] // i))
            # 绘制主文本
            draw.text((x_position, y_offset), line, font=font_obj, fill=text_color)

        elif art_font_type == "metallic":
            # 金属效果
            # 金属渐变色
            metallic_base = (212, 175, 55, 255)  # 金色基色
            metallic_highlight = (255, 223, 0, 255)  # 金色高光

            # 绘制金属效果的底色
            draw.text((x_position, y_offset), line, font=font_obj, fill=metallic_base)

            # 添加高光效果
            highlight_offset = max(1, font_size // 30)
            draw.text((x_position - highlight_offset, y_offset - highlight_offset),
                     line, font=font_obj, fill=(255, 255, 255, 100))

            # 添加阴影增强金属感
            shadow_offset = max(1, font_size // 25)
            draw.text((x_position + shadow_offset, y_offset + shadow_offset),
                     line, font=font_obj, fill=(100, 100, 100, 100))

        else:  # normal
            # 普通文本
            draw.text((x_position, y_offset), line, font=font_obj, fill=text_color)

        y_offset += line_height + 10  # 移动到下一行

    # 合并背景和文本图像
    final_img = Image.alpha_composite(bg_img, txt_img)

    # 如果是霓虹灯效果，添加模糊
    if art_font_type == "neon":
        final_img = final_img.filter(ImageFilter.GaussianBlur(1))

    # 将PIL图像转换为TextClip
    # 需要先保存为临时文件
    temp_img_path = os.path.join(utils.storage_dir("temp", create=True), f"art_text_{str(uuid.uuid4())}.png")
    final_img.save(temp_img_path, format="PNG")

    # 创建图像剪辑
    clip = ImageClip(temp_img_path)

    # 删除临时文件
    try:
        os.remove(temp_img_path)
    except Exception as e:
        logger.warning(f"Failed to remove temporary image file: {e}")

    return clip


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # Create ImageFont
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    # logger.warning(f"wrapping text, max_width: {max_width}, text_width: {width}, text: {text}")

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        # logger.warning(f"wrapped text: {result}")
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    # logger.warning(f"wrapped text: {result}")
    return result, height


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"start, video size: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"using font: {font_path}")

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )

        # 判断是否启用艺术字体
        if hasattr(params, 'art_font_enabled') and params.art_font_enabled:
            # 创建艺术字体
            _clip = create_art_text_clip(
                text=wrapped_txt,
                font=font_path,
                font_size=params.font_size,
                color=params.text_fore_color,
                art_font_type=params.art_font_type,
                art_font_background=params.art_font_background,
                size=(video_width, None),
                text_align='center'
            )
        else:
            # 使用普通字幕
            # 处理随机描边颜色
            stroke_color = params.stroke_color
            if stroke_color == "random":
                # 随机生成一个颜色
                random_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
                stroke_color = random_color
                logger.info(f"Using random stroke color: {stroke_color}")

            _clip = TextClip(
                text=wrapped_txt,
                font=font_path,
                font_size=params.font_size,
                color=params.text_fore_color,
                bg_color=params.text_background_color,
                stroke_color=stroke_color,
                stroke_width=params.stroke_width,
                size=(video_width, None),
                method='caption',
                text_align='center'
            )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.with_start(subtitle_item[0][0])
        _clip = _clip.with_end(subtitle_item[0][1])
        _clip = _clip.with_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.with_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.with_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # Ensure the subtitle is fully within the screen bounds
            margin = 10  # Additional margin, in pixels
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(
                min_y, min(custom_y, max_y)
            )  # Constrain the y value within the valid range
            _clip = _clip.with_position(("center", custom_y))
        else:  # center
            _clip = _clip.with_position(("center", "center"))
        return _clip

    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path).with_effects(
        [afx.MultiplyVolume(params.voice_volume)]
    )

    def make_textclip(text):
        # 判断是否启用艺术字体
        if hasattr(params, 'art_font_enabled') and params.art_font_enabled:
            # 创建艺术字体
            return create_art_text_clip(
                text=text,
                font=font_path,
                font_size=params.font_size,
                color=params.text_fore_color,
                art_font_type=params.art_font_type,
                art_font_background=params.art_font_background,
                size=(video_width, None),
                text_align='center'
            )
        else:
            # 使用普通字幕
            return TextClip(
                text=text,
                font=font_path,
                font_size=params.font_size,
                size=(video_width, None),
                method='caption',
                text_align='center'
            )

    # 创建所有视频元素的列表
    video_elements = [video_clip]

    # 添加标题贴纸
    if hasattr(params, 'title_sticker_enabled') and params.title_sticker_enabled and params.title_sticker_text:
        # 获取标题贴纸字体路径
        title_font_path = os.path.join(utils.font_dir(), params.title_sticker_font)
        if os.name == "nt":
            title_font_path = title_font_path.replace("\\", "/")

        # 创建标题贴纸
        title_sticker = create_title_sticker(
            text=params.title_sticker_text,
            font=title_font_path,
            font_size=params.title_sticker_font_size,
            style=params.title_sticker_style,
            background=params.title_sticker_background,
            background_color=params.title_sticker_background_color,
            border=params.title_sticker_border,
            border_color=params.title_sticker_border_color,
            size=(video_width, video_height),
            background_enabled=params.title_sticker_background_enabled,
            text_color=getattr(params, 'title_sticker_text_color', '#FF0000')
        )

        # 设置标题贴纸位置
        if title_sticker:
            # 根据用户选择的位置设置标题贴纸位置
            if params.title_sticker_position == "upper_middle":
                # 上方中间
                title_sticker = title_sticker.with_position(("center", video_height * 0.10))
            elif params.title_sticker_position == "middle":
                # 正中间
                title_sticker = title_sticker.with_position(("center", "center"))
            elif params.title_sticker_position == "lower_middle":
                # 下方中间
                title_sticker = title_sticker.with_position(("center", video_height * 0.80))
            elif params.title_sticker_position == "custom":
                # 自定义位置
                custom_y = video_height * (params.title_sticker_custom_position / 100)
                title_sticker = title_sticker.with_position(("center", custom_y))
            else:
                # 默认位置（上方中间）
                title_sticker = title_sticker.with_position(("center", video_height * 0.10))

            # 设置标题贴纸持续时间
            title_sticker = title_sticker.with_duration(video_clip.duration)

            # 应用动画效果
            if hasattr(params, 'title_sticker_animation') and params.title_sticker_animation != "none":
                # 获取动画速度
                animation_speed = getattr(params, 'title_sticker_animation_speed', 1.0)

                # 应用动画效果
                title_sticker = title_animations.apply_animation(
                    clip=title_sticker,
                    animation_type=params.title_sticker_animation,
                    duration=video_clip.duration,
                    speed=animation_speed
                )
                logger.info(f"Applied animation effect: {params.title_sticker_animation} with speed {animation_speed}")

            video_elements.append(title_sticker)
            logger.info(f"Added title sticker: {params.title_sticker_text} at position {params.title_sticker_position}")

    # 添加字幕
    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(
            subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
        )
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_elements.extend(text_clips)

    # 合成所有视频元素
    video_clip = CompositeVideoClip(video_elements)

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = AudioFileClip(bgm_file).with_effects(
                [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ]
            )
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")

    video_clip = video_clip.with_audio(audio_clip)
    video_clip.write_videofile(
        output_file,
        audio_codec="aac",
        temp_audiofile_path=output_dir,
        threads=params.n_threads or 2,
        logger=None,
        fps=30,
    )
    video_clip.close()
    del video_clip
    logger.success("completed")


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"video is too small, width: {width}, height: {height}")
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            # Create an image clip and set its duration to 3 seconds
            clip = (
                ImageClip(material.url)
                .with_duration(clip_duration)
                .with_position("center")
            )
            # Apply a zoom effect using the resize method.
            # A lambda function is used to make the zoom effect dynamic over time.
            # The zoom effect starts from the original size and gradually scales up to 120%.
            # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
            # Note: 1 represents 100% size, so 1.2 represents 120% size.
            zoom_clip = clip.resized(
                lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
            )

            # Optionally, create a composite video clip containing the zoomed clip.
            # This is useful when you want to add other elements to the video.
            final_clip = CompositeVideoClip([zoom_clip])

            # Output the video to a file.
            video_file = f"{material.url}.mp4"
            final_clip.write_videofile(video_file, fps=30, logger=None)
            final_clip.close()
            del final_clip
            material.url = video_file
            logger.success(f"completed: {video_file}")
    return materials


def create_preview_image(text, font_path, font_size, style, background_type, background_color, border, border_color, background_enabled=True, is_title=False, text_color="#FF0000"):
    """
    创建预览图像

    :param text: 文本内容
    :param font_path: 字体路径
    :param font_size: 字体大小
    :param style: 样式（normal, shadow, outline, 3d, neon, metallic, rainbow, gradient）
    :param background_type: 背景类型（none, rounded_rect, rect等）
    :param background_color: 背景颜色
    :param border: 是否有边框
    :param border_color: 边框颜色
    :param background_enabled: 是否启用背景
    :param is_title: 是否是标题（影响样式处理）
    :return: 临时图像文件路径
    """
    # 设置预览图像宽度
    preview_width = 400

    # 计算字体大小缩放比例
    # 实际视频宽度为1080或1920，预览宽度为400
    # 根据是否为标题使用不同的缩放比例
    if is_title:
        # 标题通常在竖屏视频中，宽度为1080
        scale_factor = preview_width / 1080
    else:
        # 字幕可能在横屏或竖屏，取一个中间值
        scale_factor = preview_width / 1500

    # 缩放字体大小
    scaled_font_size = int(font_size * scale_factor)

    # 确保字体大小不会太小
    scaled_font_size = max(scaled_font_size, 12)

    # 创建字体对象
    font_obj = ImageFont.truetype(font_path, scaled_font_size)

    # 计算文本尺寸
    left, top, right, bottom = font_obj.getbbox(text)
    text_width = right - left
    text_height = bottom - top

    # 设置图像尺寸（比文本略大）
    padding_x = int(text_width * 0.3)
    padding_y = int(text_height * 0.5)
    img_width = min(preview_width, text_width + padding_x * 2)
    img_height = text_height + padding_y * 2

    # 确保文本在背景中垂直居中
    text_y_position = (img_height - text_height) // 2

    # 创建透明背景图像
    img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 绘制背景（如果启用了背景）
    if background_type != "none" and background_enabled:
        # 确保背景颜色完全不透明
        if background_color.startswith('#') and len(background_color) == 7:
            bg_color = background_color + 'ff'  # 添加不透明度
        else:
            bg_color = background_color

        if background_type == "rounded_rect":
            # 绘制圆角矩形
            radius = int(img_height * 0.3)  # 圆角半径
            draw.rounded_rectangle(
                [(0, 0), (img_width, img_height)],
                radius=radius,
                fill=bg_color
            )
        elif background_type == "rect":
            # 绘制矩形
            draw.rectangle(
                [(0, 0), (img_width, img_height)],
                fill=bg_color
            )

    # 根据样式绘制文本
    if style == "chinese_style":
        # 中国风格效果：红色填充+黄色粗描边
        # 描边颜色（默认黄色）
        if border_color == "random":
            # 随机生成一个颜色
            stroke_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
        else:
            stroke_color = border_color if border else "#FFD700"

        # 绘制粗描边（多层描边增强效果）
        stroke_width = max(3, scaled_font_size // 10)  # 描边宽度
        for offset in range(stroke_width, 0, -1):
            for dx, dy in [(ox, oy) for ox in range(-offset, offset+1, max(1, offset//2)) for oy in range(-offset, offset+1, max(1, offset//2))]:
                draw.text((padding_x + dx, text_y_position + dy), text, font=font_obj, fill=stroke_color)

        # 绘制主文本（使用指定的文字颜色）
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=text_color)

    elif is_title and style == "rainbow":
        # 彩虹渐变文字
        rainbow_colors = ["#FF0000", "#FF7F00", "#FFFF00", "#00FF00", "#0000FF", "#4B0082", "#9400D3"]
        # 创建渐变色文本
        gradient_img = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient_img)

        # 计算每个字符的颜色
        for i, char in enumerate(text):
            color_idx = i % len(rainbow_colors)
            char_width = font_obj.getbbox(char)[2] - font_obj.getbbox(char)[0]
            gradient_draw.text((left + i * char_width, 0), char, font=font_obj, fill=rainbow_colors[color_idx])

        # 添加描边
        if border:
            # 处理随机描边颜色
            if border_color == "random":
                # 随机生成一个颜色
                stroke_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
            else:
                stroke_color = border_color

            for offset_x, offset_y in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                draw.text((padding_x + offset_x, text_y_position + offset_y), text, font=font_obj, fill=stroke_color)

        # 将渐变文本粘贴到主图像
        img.paste(gradient_img, (padding_x, text_y_position), gradient_img)

    elif is_title and style == "neon":
        # 霓虹灯效果
        glow_color = "#FF4500"  # 橙红色
        outer_glow_color = "#FFFF00"  # 黄色外发光

        # 添加外发光效果
        for offset in range(3, 0, -1):
            alpha = 100 - offset * 30
            glow_alpha = max(0, alpha)
            glow_color_with_alpha = glow_color[0:7] + format(glow_alpha, '02x')
            for dx, dy in [(ox, oy) for ox in range(-offset, offset+1) for oy in range(-offset, offset+1)]:
                draw.text((padding_x + dx, text_y_position + dy), text, font=font_obj, fill=glow_color_with_alpha)

        # 添加内发光
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=outer_glow_color)

        # 添加主文本
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=glow_color)

        # 应用模糊效果增强霓虹感
        img = img.filter(ImageFilter.GaussianBlur(1))

    elif is_title and style == "gradient":
        # 渐变效果
        start_color = (255, 0, 0)  # 红色
        end_color = (0, 0, 255)  # 蓝色

        # 创建渐变色文本
        gradient_img = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient_img)

        # 绘制渐变背景
        for y in range(text_height):
            r = int(start_color[0] + (end_color[0] - start_color[0]) * y / text_height)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * y / text_height)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * y / text_height)
            gradient_draw.line([(0, y), (text_width, y)], fill=(r, g, b, 255))

        # 创建文本蒙版
        mask = Image.new('L', (text_width, text_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.text((0, 0), text, font=font_obj, fill=255)

        # 应用蒙版到渐变图像
        gradient_text = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
        gradient_text.paste(gradient_img, (0, 0), mask)

        # 添加描边
        if border:
            # 处理随机描边颜色
            if border_color == "random":
                # 随机生成一个颜色
                stroke_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
            else:
                stroke_color = border_color

            for offset_x, offset_y in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                draw.text((padding_x + offset_x, text_y_position + offset_y), text, font=font_obj, fill=stroke_color)

        # 将渐变文本粘贴到主图像
        img.paste(gradient_text, (padding_x, text_y_position), gradient_text)

    elif style == "shadow":
        # 阴影效果
        shadow_offset = max(2, font_size // 20)  # 阴影偏移量
        draw.text((padding_x + shadow_offset, text_y_position + shadow_offset), text, font=font_obj, fill=(0, 0, 0, 160))
        draw.text((padding_x, text_y_position), text, font=font_obj, fill="#FFFFFF")

    elif style == "outline":
        # 描边效果
        outline_size = max(2, font_size // 25)  # 描边大小
        # 绘制描边（四个方向）
        for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1), (-outline_size,0), (outline_size,0), (0,-outline_size), (0,outline_size)]:
            draw.text((padding_x + dx, text_y_position + dy), text, font=font_obj, fill=(0, 0, 0, 200))
        # 绘制主文本
        draw.text((padding_x, text_y_position), text, font=font_obj, fill="#FFFFFF")

    elif style == "3d":
        # 3D立体效果
        depth = max(3, font_size // 15)  # 3D深度
        for i in range(depth, 0, -1):
            alpha = 100 + (155 * i // depth)  # 渐变透明度
            shadow_color = (0, 0, 0, alpha)
            draw.text((padding_x - i, text_y_position + i), text, font=font_obj, fill=shadow_color)
        # 绘制主文本
        draw.text((padding_x, text_y_position), text, font=font_obj, fill="#FFFFFF")

    elif style == "metallic":
        # 金属效果
        # 金属渐变色
        metallic_base = (212, 175, 55, 255)  # 金色基色

        # 绘制金属效果的底色
        draw.text((padding_x, text_y_position), text, font=font_obj, fill=metallic_base)

        # 添加高光效果
        highlight_offset = max(1, font_size // 30)
        draw.text((padding_x - highlight_offset, text_y_position - highlight_offset),
                 text, font=font_obj, fill=(255, 255, 255, 100))

        # 添加阴影增强金属感
        shadow_offset = max(1, font_size // 25)
        draw.text((padding_x + shadow_offset, text_y_position + shadow_offset),
                 text, font=font_obj, fill=(100, 100, 100, 100))

    else:  # normal
        # 添加描边
        if border:
            # 处理随机描边颜色
            if border_color == "random":
                # 随机生成一个颜色
                stroke_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
            else:
                stroke_color = border_color

            for offset_x, offset_y in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                draw.text((padding_x + offset_x, text_y_position + offset_y), text, font=font_obj, fill=stroke_color)

        # 绘制主文本
        draw.text((padding_x, text_y_position), text, font=font_obj, fill="#FFFFFF")

    # 保存为临时文件
    temp_img_path = os.path.join(utils.storage_dir("temp", create=True), f"preview_{str(uuid.uuid4())}.png")
    img.save(temp_img_path, format="PNG")

    return temp_img_path


def create_unified_preview(video_aspect, subtitle_params=None, title_params=None):
    """
    创建统一预览图像

    :param video_aspect: 视频宽高比
    :param subtitle_params: 字幕参数字典
    :param title_params: 标题参数字典
    :return: 临时图像文件路径
    """
    # 获取视频尺寸
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    # 计算预览区域的尺寸，保持原始宽高比
    preview_width = 400  # 固定宽度
    preview_height = int(preview_width * video_height / video_width)

    # 创建背景图像
    bg_img = Image.new('RGB', (preview_width, preview_height), (51, 51, 51))  # #333333 背景色

    # 如果有字幕参数，创建字幕预览
    if subtitle_params and subtitle_params.get("enabled", False):
        # 获取字幕参数
        text = subtitle_params.get("text", "字幕预览")
        font_path = subtitle_params.get("font_path")
        font_size = subtitle_params.get("font_size", 60)
        style = subtitle_params.get("style", "normal")
        background = subtitle_params.get("background", "none")
        background_color = subtitle_params.get("background_color", "#000000")
        border = subtitle_params.get("border", True)
        border_color = subtitle_params.get("border_color", "#FFFFFF")
        position = subtitle_params.get("position", "bottom")
        custom_position = subtitle_params.get("custom_position", 85.0)
        background_enabled = subtitle_params.get("background_enabled", True)

        # 创建字幕预览图像
        subtitle_img_path = create_preview_image(
            text=text,
            font_path=font_path,
            font_size=font_size,
            style=style,
            background_type=background,
            background_color=background_color,
            border=border,
            border_color=border_color,
            background_enabled=background_enabled,
            is_title=False
        )

        # 加载字幕图像
        subtitle_img = Image.open(subtitle_img_path)

        # 计算字幕位置
        if position == "top":
            subtitle_y = int(preview_height * 0.05)
        elif position == "center":
            subtitle_y = int(preview_height * 0.5 - subtitle_img.height / 2)
        elif position == "bottom":
            subtitle_y = int(preview_height * 0.95 - subtitle_img.height)
        elif position == "custom":
            subtitle_y = int(preview_height * custom_position / 100 - subtitle_img.height / 2)
        else:
            subtitle_y = int(preview_height * 0.95 - subtitle_img.height)

        # 计算水平居中位置
        subtitle_x = int(preview_width / 2 - subtitle_img.width / 2)

        # 将字幕图像粘贴到背景图像上
        bg_img.paste(subtitle_img, (subtitle_x, subtitle_y), subtitle_img)

        # 删除临时文件
        try:
            os.remove(subtitle_img_path)
        except Exception as e:
            logger.warning(f"Failed to remove temporary subtitle image file: {e}")

    # 如果有标题参数，创建标题预览
    if title_params and title_params.get("enabled", False):
        # 获取标题参数
        text = title_params.get("text", "标题预览")
        font_path = title_params.get("font_path")
        font_size = title_params.get("font_size", 80)
        style = title_params.get("style", "rainbow")
        background = title_params.get("background", "rounded_rect")
        background_color = title_params.get("background_color", "#000000")
        border = title_params.get("border", True)
        border_color = title_params.get("border_color", "#FFFFFF")
        position = title_params.get("position", "upper_middle")
        custom_position = title_params.get("custom_position", 15.0)
        background_enabled = title_params.get("background_enabled", True)
        animation = title_params.get("animation", "none")

        # 如果有动画效果，在文本中添加提示
        if animation != "none":
            text = f"{text} [动画: {animation}]"

        # 获取文字颜色
        text_color = title_params.get("text_color", "#FF0000")

        # 创建标题预览图像
        title_img_path = create_preview_image(
            text=text,
            font_path=font_path,
            font_size=font_size,
            style=style,
            background_type=background,
            background_color=background_color,
            border=border,
            border_color=border_color,
            background_enabled=background_enabled,
            is_title=True,
            text_color=text_color
        )

        # 加载标题图像
        title_img = Image.open(title_img_path)

        # 计算标题位置
        if position == "upper_middle":
            title_y = int(preview_height * 0.10 - title_img.height / 2)
        elif position == "middle":
            title_y = int(preview_height * 0.5 - title_img.height / 2)
        elif position == "lower_middle":
            title_y = int(preview_height * 0.80 - title_img.height / 2)
        elif position == "custom":
            title_y = int(preview_height * custom_position / 100 - title_img.height / 2)
        else:
            title_y = int(preview_height * 0.10 - title_img.height / 2)

        # 计算水平居中位置
        title_x = int(preview_width / 2 - title_img.width / 2)

        # 将标题图像粘贴到背景图像上
        bg_img.paste(title_img, (title_x, title_y), title_img)

        # 删除临时文件
        try:
            os.remove(title_img_path)
        except Exception as e:
            logger.warning(f"Failed to remove temporary title image file: {e}")

    # 保存最终预览图像
    preview_img_path = os.path.join(utils.storage_dir("temp", create=True), f"unified_preview_{str(uuid.uuid4())}.png")
    bg_img.save(preview_img_path, format="PNG")

    return preview_img_path


if __name__ == "__main__":
    m = MaterialInfo()
    m.url = "/Users/harry/Downloads/IMG_2915.JPG"
    m.provider = "local"
    materials = preprocess_video([m], clip_duration=4)
    print(materials)

    # txt_en = "Here's your guide to travel hacks for budget-friendly adventures"
    # txt_zh = "测试长字段这是您的旅行技巧指南帮助您进行预算友好的冒险"
    # font = utils.resource_dir() + "/fonts/STHeitiMedium.ttc"
    # for txt in [txt_en, txt_zh]:
    #     t, h = wrap_text(text=txt, max_width=1000, font=font, fontsize=60)
    #     print(t)
    #
    # task_id = "aa563149-a7ea-49c2-b39f-8c32cc225baf"
    # task_dir = utils.task_dir(task_id)
    # video_file = f"{task_dir}/combined-1.mp4"
    # audio_file = f"{task_dir}/audio.mp3"
    # subtitle_file = f"{task_dir}/subtitle.srt"
    # output_file = f"{task_dir}/final.mp4"
    #
    # # video_paths = []
    # # for file in os.listdir(utils.storage_dir("test")):
    # #     if file.endswith(".mp4"):
    # #         video_paths.append(os.path.join(utils.storage_dir("test"), file))
    # #
    # # combine_videos(combined_video_path=video_file,
    # #                audio_file=audio_file,
    # #                video_paths=video_paths,
    # #                video_aspect=VideoAspect.portrait,
    # #                video_concat_mode=VideoConcatMode.random,
    # #                max_clip_duration=5,
    # #                threads=2)
    #
    # cfg = VideoParams()
    # cfg.video_aspect = VideoAspect.portrait
    # cfg.font_name = "STHeitiMedium.ttc"
    # cfg.font_size = 60
    # cfg.stroke_color = "#000000"
    # cfg.stroke_width = 1.5
    # cfg.text_fore_color = "#FFFFFF"
    # cfg.text_background_color = "transparent"
    # cfg.bgm_type = "random"
    # cfg.bgm_file = ""
    # cfg.bgm_volume = 1.0
    # cfg.subtitle_enabled = True
    # cfg.subtitle_position = "bottom"
    # cfg.n_threads = 2
    # cfg.paragraph_number = 1
    #
    # cfg.voice_volume = 1.0
    #
    # generate_video(video_path=video_file,
    #                audio_path=audio_file,
    #                subtitle_path=subtitle_file,
    #                output_file=output_file,
    #                params=cfg
    #                )
