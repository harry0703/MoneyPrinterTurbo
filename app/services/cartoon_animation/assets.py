"""Procedural, offline backgrounds and props drawn with Pillow.

Nothing here downloads art: every scene is generated deterministically from
the requested canvas size, which keeps the engine usable without a network or
a GPU. New backgrounds are added to ``BACKGROUNDS``.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw

from app.services.cartoon_animation.models import AnimationError


def _gradient(size, top, bottom) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(
            int(top[index] + (bottom[index] - top[index]) * ratio) for index in range(3)
        )
        draw.line([(0, y), (width, y)], fill=color)
    return image


def _hill(draw, width, height, base_y, amplitude, color, phase=0.0):
    points = []
    for x in range(0, width + 8, 8):
        y = base_y + math.sin(x / width * math.pi * 2 + phase) * amplitude
        points.append((x, y))
    points += [(width, height), (0, height)]
    draw.polygon(points, fill=color)


def _cloud(draw, x, y, scale, color):
    radius = 26 * scale
    for dx, dy, factor in ((0, 0, 1.0), (radius * 0.9, -radius * 0.25, 0.8), (-radius * 0.9, -radius * 0.15, 0.75)):
        draw.ellipse(
            [
                x + dx - radius * factor,
                y + dy - radius * factor * 0.7,
                x + dx + radius * factor,
                y + dy + radius * factor * 0.7,
            ],
            fill=color,
        )


@lru_cache(maxsize=8)
def garden(size: tuple[int, int] = (720, 1280)) -> Image.Image:
    width, height = size
    image = _gradient(size, (154, 214, 245), (233, 246, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [width * 0.72, height * 0.05, width * 0.72 + 110, height * 0.05 + 110],
        fill=(255, 219, 122),
    )
    _cloud(draw, width * 0.22, height * 0.12, 1.1, (255, 255, 255))
    _cloud(draw, width * 0.66, height * 0.19, 0.8, (255, 255, 255))
    _hill(draw, width, height, height * 0.62, 26, (168, 213, 148))
    _hill(draw, width, height, height * 0.7, 18, (126, 191, 118), phase=1.9)
    draw.rectangle([0, height * 0.74, width, height], fill=(104, 176, 100))
    for index in range(16):
        x = (index * 137 + 41) % width
        y = height * 0.77 + (index * 83 % int(height * 0.2))
        color = (255, 255, 255) if index % 3 else (255, 214, 90)
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=color)
    return image


@lru_cache(maxsize=8)
def meadow(size: tuple[int, int] = (720, 1280)) -> Image.Image:
    width, height = size
    image = _gradient(size, (196, 229, 246), (255, 248, 227))
    draw = ImageDraw.Draw(image)
    _hill(draw, width, height, height * 0.66, 34, (183, 214, 156), phase=0.6)
    draw.rectangle([0, height * 0.78, width, height], fill=(121, 182, 111))
    return image


@lru_cache(maxsize=8)
def night(size: tuple[int, int] = (720, 1280)) -> Image.Image:
    width, height = size
    image = _gradient(size, (18, 30, 61), (52, 73, 120))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [width * 0.68, height * 0.07, width * 0.68 + 96, height * 0.07 + 96],
        fill=(245, 240, 208),
    )
    for index in range(40):
        x = (index * 89 + 17) % width
        y = (index * 137 + 61) % int(height * 0.6)
        radius = 2 if index % 4 else 3
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(255, 255, 255))
    draw.rectangle([0, height * 0.8, width, height], fill=(27, 53, 71))
    return image


@lru_cache(maxsize=8)
def studio(size: tuple[int, int] = (720, 1280)) -> Image.Image:
    width, height = size
    image = _gradient(size, (255, 246, 231), (238, 224, 207))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [-width * 0.25, height * 0.55, width * 1.25, height * 1.35],
        fill=(226, 205, 182),
    )
    return image


BACKGROUNDS = {
    "garden": garden,
    "meadow": meadow,
    "night": night,
    "studio": studio,
}


def background_names() -> tuple[str, ...]:
    return tuple(sorted(BACKGROUNDS))


def background(name: str, size: tuple[int, int]) -> Image.Image:
    try:
        factory = BACKGROUNDS[name]
    except KeyError as exc:
        choices = ", ".join(background_names())
        raise AnimationError(f"background must be one of {choices}") from exc
    image = factory(size).convert("RGB")
    return image.copy()


def draw_seed(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float) -> None:
    draw.ellipse(
        [x - 12 * scale, y - 16 * scale, x + 12 * scale, y + 16 * scale],
        fill=(150, 98, 56),
        outline=(96, 60, 32),
        width=max(1, int(2 * scale)),
    )
    draw.arc(
        [x - 8 * scale, y - 11 * scale, x + 8 * scale, y + 11 * scale],
        200,
        340,
        fill=(206, 158, 106),
        width=max(1, int(3 * scale)),
    )


def draw_pot(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float) -> None:
    top = y - 120 * scale
    draw.polygon(
        [
            (x - 78 * scale, top + 16 * scale),
            (x + 78 * scale, top + 16 * scale),
            (x + 58 * scale, y),
            (x - 58 * scale, y),
        ],
        fill=(196, 100, 70),
        outline=(120, 58, 40),
        width=max(1, int(3 * scale)),
    )
    draw.rectangle(
        [x - 88 * scale, top, x + 88 * scale, top + 26 * scale],
        fill=(214, 118, 86),
        outline=(120, 58, 40),
        width=max(1, int(3 * scale)),
    )
    draw.ellipse(
        [x - 74 * scale, top + 6 * scale, x + 74 * scale, top + 36 * scale],
        fill=(88, 58, 38),
    )


def draw_watering_can(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float) -> None:
    draw.rounded_rectangle(
        [x - 44 * scale, y - 70 * scale, x + 34 * scale, y],
        radius=14 * scale,
        fill=(94, 156, 178),
        outline=(48, 92, 110),
        width=max(1, int(3 * scale)),
    )
    draw.line(
        [
            (x + 34 * scale, y - 40 * scale),
            (x + 86 * scale, y - 74 * scale),
        ],
        fill=(48, 92, 110),
        width=max(2, int(9 * scale)),
    )
    draw.ellipse(
        [x + 78 * scale, y - 86 * scale, x + 100 * scale, y - 64 * scale],
        fill=(94, 156, 178),
        outline=(48, 92, 110),
        width=max(1, int(2 * scale)),
    )
    draw.arc(
        [x - 60 * scale, y - 96 * scale, x + 4 * scale, y - 40 * scale],
        180,
        330,
        fill=(48, 92, 110),
        width=max(2, int(5 * scale)),
    )


def draw_flower(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    scale: float,
    growth: float,
    base_y: float | None = None,
) -> None:
    """Draw a flower growing from ``base_y`` to ``y`` by ``growth`` (0..1)."""
    growth = max(0.0, min(1.0, growth))
    if growth <= 0:
        return
    ground = base_y if base_y is not None else y
    stem_height = (ground - y) * growth
    top_y = ground - stem_height
    draw.line(
        [(x, ground), (x, top_y)],
        fill=(72, 140, 74),
        width=max(2, int(7 * scale)),
    )
    leaf_y = ground - stem_height * 0.45
    if growth > 0.35:
        leaf = 22 * scale * min(1.0, (growth - 0.35) / 0.4)
        draw.ellipse(
            [x + 2 * scale, leaf_y - leaf * 0.4, x + 2 * scale + leaf, leaf_y + leaf * 0.4],
            fill=(94, 170, 92),
        )
        draw.ellipse(
            [x - 2 * scale - leaf, leaf_y - leaf * 0.4, x - 2 * scale, leaf_y + leaf * 0.4],
            fill=(94, 170, 92),
        )
    if growth > 0.6:
        petal = 26 * scale * min(1.0, (growth - 0.6) / 0.4)
        for angle in range(0, 360, 60):
            radians = math.radians(angle)
            px = x + math.cos(radians) * petal
            py = top_y + math.sin(radians) * petal
            draw.ellipse(
                [px - petal, py - petal * 0.7, px + petal, py + petal * 0.7],
                fill=(255, 178, 196),
            )
        draw.ellipse(
            [x - 17 * scale, top_y - 17 * scale, x + 17 * scale, top_y + 17 * scale],
            fill=(255, 214, 90),
        )


def draw_prop(
    draw: ImageDraw.ImageDraw,
    name: str,
    x: float,
    y: float,
    scale: float = 1.0,
    *,
    growth: float = 1.0,
    base_y: float | None = None,
) -> None:
    if name == "seed":
        draw_seed(draw, x, y, scale)
    elif name == "pot":
        draw_pot(draw, x, y, scale)
    elif name == "watering_can":
        draw_watering_can(draw, x, y, scale)
    elif name == "flower":
        draw_flower(draw, x, y, scale, growth, base_y)
    else:
        choices = ", ".join(sorted(PROP_NAMES))
        raise AnimationError(f"prop must be one of {choices}")


PROP_NAMES = frozenset({"seed", "pot", "watering_can", "flower"})
