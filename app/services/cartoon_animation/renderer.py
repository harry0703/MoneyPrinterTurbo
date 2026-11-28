"""Pillow renderer for articulated characters and FFmpeg frame encoding.

Frames are drawn at the internal resolution (720x1280 by default), streamed
as raw RGB to FFmpeg and scaled to the delivery resolution there. Temporary
PNG files are never created for frames.
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
from typing import Callable, Iterable

from PIL import Image, ImageDraw

from app.services.cartoon_animation.models import (
    AnimationError,
    Character,
    Part,
    Pose,
    RenderSettings,
)
from app.services.cartoon_animation.rig import Joint, resolve_joints

_SUPERSAMPLE = 2


def _shape_color(character: Character, key: str) -> tuple[int, int, int, int]:
    value = character.palette[key]
    value = value.lstrip("#")
    if len(value) == 6:
        value += "ff"
    if len(value) != 8:
        raise AnimationError(f"palette colour {key} must be #RRGGBB or #RRGGBBAA")
    try:
        return tuple(int(value[index : index + 2], 16) for index in range(0, 8, 2))
    except ValueError as exc:
        raise AnimationError(f"palette colour {key} is not valid hex") from exc


def _dynamic_geometry(part: Part, pose: Pose) -> tuple[float, float, float, float, float]:
    """Return width, height, offset x/y and an extra rotation for a part."""
    width = part.shape.width
    height = part.shape.height
    offset_x, offset_y = part.shape.offset
    extra_angle = 0.0
    if part.dynamic == "eye":
        height = max(2.0, height * pose.value("eye_open"))
    elif part.dynamic == "pupil":
        offset_x += pose.value("pupil_x") * 14.0
        offset_y += pose.value("pupil_y") * 10.0
    elif part.dynamic == "mouth":
        width = part.shape.width * (0.72 + 0.5 * pose.value("mouth_width"))
        height = 6.0 + part.shape.height * pose.value("mouth_open")
    elif part.dynamic == "brow":
        offset_y -= pose.value("brow_raise") * 10.0
        extra_angle = pose.value("brow_angle") * 16.0
    return width, height, offset_x, offset_y, extra_angle


def _draw_shape(
    draw: ImageDraw.ImageDraw,
    shape,
    character: Character,
    box: tuple[float, float, float, float],
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None,
    outline_width: int,
) -> None:
    left, top, right, bottom = box
    if shape.kind == "ellipse":
        draw.ellipse(box, fill=fill, outline=outline, width=outline_width)
    elif shape.kind in ("rounded_rect", "capsule"):
        radius = shape.radius
        if shape.kind == "capsule":
            radius = min(right - left, bottom - top) / 2
        draw.rounded_rectangle(
            box,
            radius=max(0.0, radius),
            fill=fill,
            outline=outline,
            width=outline_width,
        )
    elif shape.kind == "polygon":
        points = [(left + x, top + y) for x, y in shape.points]
        draw.polygon(points, fill=fill)
        if outline and outline_width:
            draw.line(points + [points[0]], fill=outline, width=outline_width)


def _render_part(character: Character, part: Part, joint: Joint, pose: Pose) -> Image.Image | None:
    if part.dynamic == "pupil" and pose.value("eye_open") < 0.15:
        return None
    alpha_factor = 1.0
    if part.dynamic == "blush":
        alpha_factor = pose.value("blush")
        if alpha_factor <= 0.01:
            return None
    opacity = pose.value("opacity") * alpha_factor
    if opacity <= 0:
        return None

    width, height, offset_x, offset_y, extra_angle = _dynamic_geometry(part, pose)
    scale = joint.scale
    outline_width = part.shape.outline_width * scale
    reach_x = abs(offset_x) * scale + width * scale / 2
    reach_y = abs(offset_y) * scale + height * scale / 2
    reach = max(reach_x, reach_y) + outline_width + 6 * scale
    side = int(math.ceil(reach * 2)) + 2
    if side <= 0:
        return None

    # Draw at twice the target size, rotate, then downscale: edges stay smooth
    # without needing any dependency beyond Pillow.
    big = side * _SUPERSAMPLE
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    centre = big / 2
    unit = scale * _SUPERSAMPLE
    box = (
        centre + offset_x * unit - width * unit / 2,
        centre + offset_y * unit - height * unit / 2,
        centre + offset_x * unit + width * unit / 2,
        centre + offset_y * unit + height * unit / 2,
    )
    fill = _shape_color(character, part.shape.color)
    if opacity < 1.0:
        fill = fill[:3] + (int(fill[3] * opacity),)
    outline = _shape_color(character, part.shape.outline) if part.shape.outline else None
    if outline is not None and opacity < 1.0:
        outline = outline[:3] + (int(outline[3] * opacity),)
    _draw_shape(
        draw,
        part.shape,
        character,
        box,
        fill,
        outline,
        max(1, int(round(outline_width * _SUPERSAMPLE))) if outline else 0,
    )

    angle = -(joint.angle + extra_angle)
    # Sub-degree rotations are invisible but force an expensive resample of
    # every inherited part. Treat them as straight, which keeps idle scenes
    # fast on CPU while actions still rotate normally.
    if abs(angle) >= 0.75:
        canvas = canvas.rotate(angle, resample=Image.BICUBIC, expand=True)
    return canvas.resize(
        (max(1, canvas.width // _SUPERSAMPLE), max(1, canvas.height // _SUPERSAMPLE)),
        Image.LANCZOS,
    )


def _paste_alpha(destination: Image.Image, source: Image.Image, x: int, y: int) -> None:
    left = max(0, x)
    top = max(0, y)
    right = min(destination.width, x + source.width)
    bottom = min(destination.height, y + source.height)
    if right <= left or bottom <= top:
        return
    crop = source.crop((left - x, top - y, right - x, bottom - y))
    destination.alpha_composite(crop, (left, top))


def render_character(character: Character, pose: Pose) -> Image.Image:
    """Render one character sprite in local canvas coordinates (RGBA)."""
    joints = resolve_joints(character, pose)
    width, height = int(character.canvas[0]), int(character.canvas[1])
    sprite = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for part in character.layered():
        joint = joints[part.name]
        layer = _render_part(character, part, joint, pose)
        if layer is None:
            continue
        _paste_alpha(
            sprite,
            layer,
            int(round(joint.x - layer.width / 2)),
            int(round(joint.y - layer.height / 2)),
        )
    return sprite


def render_still(plan, time: float, path: str) -> str:
    """Save a single composed frame as PNG."""
    from app.services.cartoon_animation.compositor import render_frame

    frame = render_frame(plan, time)
    target = os.path.abspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".still-", suffix=".png", dir=os.path.dirname(target) or ".")
    os.close(fd)
    try:
        frame.save(temporary, format="PNG")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def _ffmpeg_binary() -> str:
    from app.utils import utils

    return utils.get_ffmpeg_binary()


def encode_frames(
    frames: Iterable[tuple[float, Image.Image]],
    output_path: str,
    settings: RenderSettings,
    *,
    progress: Callable[[float], None] | None = None,
    ffmpeg_binary: str | None = None,
    cancel: Callable[[], bool] | None = None,
) -> str:
    """Encode progressive frames to H.264 using one persistent FFmpeg pipe.

    ``cancel`` is polled once per frame so the web panel can stop a render and
    terminate FFmpeg without leaving an orphan process behind.
    """
    target = os.path.abspath(output_path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    binary = ffmpeg_binary or _ffmpeg_binary()
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{settings.width}x{settings.height}",
        "-r",
        str(settings.fps),
        "-i",
        "-",
        "-an",
        "-vf",
        f"scale={settings.output_width}:{settings.output_height}:flags=lanczos",
        "-c:v",
        "libx264",
        "-preset",
        settings.preset,
        "-crf",
        str(settings.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-y",
        target,
    ]
    fd, temporary = tempfile.mkstemp(prefix=".frames-", suffix=".mp4", dir=directory)
    os.close(fd)
    command[-1] = temporary
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    rendered = 0
    assert process.stdin is not None
    try:
        for _, frame in frames:
            if cancel is not None and cancel():
                raise AnimationError("render cancelled")
            if frame.size != (settings.width, settings.height):
                frame = frame.resize((settings.width, settings.height), Image.LANCZOS)
            process.stdin.write(frame.convert("RGB").tobytes())
            rendered += 1
            if progress is not None and rendered % settings.fps == 0:
                progress(rendered / settings.fps)
        if rendered == 0:
            process.stdin.close()
            process.kill()
            process.wait()
            os.unlink(temporary)
            raise AnimationError("no frames were rendered")
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        status = process.wait()
    except BrokenPipeError as exc:
        process.kill()
        process.wait()
        raise AnimationError("FFmpeg stopped while encoding the animated scene") from exc
    except AnimationError:
        # Cancellation (and any rendering error) must not leave FFmpeg or the
        # temporary file behind.
        process.kill()
        process.wait()
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
    if status != 0:
        message = stderr.decode("utf-8", "replace").strip()
        os.unlink(temporary)
        raise AnimationError(f"FFmpeg failed to encode the scene: {message or status}")
    os.replace(temporary, target)
    return target
