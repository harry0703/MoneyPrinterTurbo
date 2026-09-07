import hashlib
import os
import textwrap
from typing import List

from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.models.schema import VideoAspect, VideoParams
from app.utils import utils


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}


def generate_cover_image(
    task_id: str,
    params: VideoParams,
    video_script: str,
    video_terms,
    material_paths: List[str],
) -> str:
    cover_path = os.path.join(utils.task_dir(task_id), "cover.png")
    width, height = VideoAspect(params.video_aspect).to_resolution()
    background = _load_background_image(material_paths, width, height)
    if background is None:
        background = _build_fallback_background(width, height, params, video_terms)

    cover = _compose_cover(background, width, height, params, video_script, video_terms)
    cover.save(cover_path, format="PNG")
    return cover_path


def _load_background_image(material_paths: List[str], width: int, height: int):
    for material_path in material_paths or []:
        if not material_path or not os.path.exists(material_path):
            continue

        extension = os.path.splitext(material_path)[1].lower()
        try:
            if extension in IMAGE_EXTENSIONS:
                with Image.open(material_path) as image:
                    return _fit_background(image.convert("RGB"), width, height)

            if extension in VIDEO_EXTENSIONS:
                clip = None
                try:
                    clip = VideoFileClip(material_path, audio=False)
                    timestamp = min(max(0.3, clip.duration * 0.25), max(0.3, clip.duration - 0.1))
                    frame = clip.get_frame(timestamp)
                    image = Image.fromarray(frame).convert("RGB")
                    return _fit_background(image, width, height)
                finally:
                    if clip is not None:
                        clip.close()
        except Exception as exc:
            logger.warning(f"failed to build cover background from material {material_path}: {str(exc)}")

    return None


def _fit_background(image: Image.Image, width: int, height: int) -> Image.Image:
    source_ratio = image.width / max(image.height, 1)
    target_ratio = width / max(height, 1)

    if source_ratio > target_ratio:
        resized_height = height
        resized_width = int(resized_height * source_ratio)
    else:
        resized_width = width
        resized_height = int(resized_width / max(source_ratio, 0.001))

    resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
    left = max(0, (resized_width - width) // 2)
    top = max(0, (resized_height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _build_fallback_background(width: int, height: int, params: VideoParams, video_terms) -> Image.Image:
    seed_text = f"{params.video_subject}|{params.video_script}|{video_terms}"
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    start = tuple(int(digest[index:index + 2], 16) // 2 + 40 for index in (0, 2, 4))
    end = tuple(int(digest[index:index + 2], 16) // 2 + 20 for index in (6, 8, 10))

    image = Image.new("RGB", (width, height), start)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(start[channel] * (1 - ratio) + end[channel] * ratio) for channel in range(3))
        draw.line([(0, y), (width, y)], fill=color)

    glow_color = tuple(min(255, component + 35) for component in end)
    ellipse_box = (
        int(width * 0.1),
        int(height * 0.08),
        int(width * 0.9),
        int(height * 0.72),
    )
    draw.ellipse(ellipse_box, fill=glow_color)
    return image.filter(ImageFilter.GaussianBlur(radius=max(width, height) // 18))


def _compose_cover(
    background: Image.Image,
    width: int,
    height: int,
    params: VideoParams,
    video_script: str,
    video_terms,
) -> Image.Image:
    canvas = background.filter(ImageFilter.GaussianBlur(radius=8))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    top_fade_height = max(220, height // 4)
    bottom_fade_top = height - max(320, height // 3)
    for y in range(height):
        alpha = 0
        if y < top_fade_height:
            alpha = int(170 * (1 - (y / max(top_fade_height, 1))))
        elif y > bottom_fade_top:
            alpha = int(210 * ((y - bottom_fade_top) / max(height - bottom_fade_top, 1)))
        overlay_draw.line([(0, y), (width, y)], fill=(10, 10, 10, max(alpha, 45)))

    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)

    title = _build_cover_title(params.video_subject, video_script)
    subtitle = _build_cover_subtitle(video_terms)
    font_path = _resolve_font_path(params.font_name)
    title_font = _load_font(font_path, max(48, width // 14))
    subtitle_font = _load_font(font_path, max(24, width // 34))

    margin_x = int(width * 0.08)
    title_y = int(height * 0.54)
    wrap_width = 18 if width < height else 28
    title_lines = textwrap.wrap(title, width=wrap_width)[:4] or [title]
    subtitle_lines = textwrap.wrap(subtitle, width=wrap_width + 8)[:2] if subtitle else []

    current_y = title_y
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font, stroke_width=3)
        line_height = bbox[3] - bbox[1]
        draw.text(
            (margin_x, current_y),
            line,
            font=title_font,
            fill=(255, 255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 180),
        )
        current_y += line_height + 18

    for line in subtitle_lines:
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        line_height = bbox[3] - bbox[1]
        draw.text(
            (margin_x, current_y + 10),
            line,
            font=subtitle_font,
            fill=(228, 228, 228, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 180),
        )
        current_y += line_height + 10

    return canvas.convert("RGB")


def _build_cover_title(video_subject: str, video_script: str) -> str:
    if video_subject and video_subject.strip():
        return video_subject.strip()

    script_lines = utils.split_string_by_punctuations(video_script or "")
    if script_lines:
        return script_lines[0].strip()[:120]
    return "Generated Story"


def _build_cover_subtitle(video_terms) -> str:
    if isinstance(video_terms, str):
        terms = [item.strip() for item in video_terms.split(",") if item.strip()]
    elif isinstance(video_terms, list):
        terms = [str(item).strip() for item in video_terms if str(item).strip()]
    else:
        terms = []

    if not terms:
        return ""
    return " • ".join(terms[:4])


def _resolve_font_path(font_name: str) -> str:
    if font_name:
        candidate = utils.font_dir(font_name)
        if os.path.exists(candidate):
            return candidate
    return ""


def _load_font(font_path: str, size: int):
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception as exc:
            logger.warning(f"failed to load cover font {font_path}: {str(exc)}")
    return ImageFont.load_default()