"""Scene composition: background, props and articulated actors per frame.

The compositor owns the timeline-to-image step. It renders frames lazily so a
long scene never keeps more than one frame in memory, and it hands each frame
to the encoder immediately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterator

from PIL import Image, ImageDraw

from app.services.cartoon_animation import assets
from app.services.cartoon_animation.expressions import apply_expression
from app.services.cartoon_animation.keyframes import AnimationClip, sample_clips
from app.services.cartoon_animation.models import (
    AnimationError,
    Character,
    Pose,
    RenderSettings,
)


@dataclass(frozen=True)
class Prop:
    """A procedurally drawn object in the scene.

    ``growth`` animates the flower opening between ``appear`` and
    ``appear + grow_duration``; other props ignore it.
    """

    name: str
    x: float
    y: float
    scale: float = 1.0
    appear: float = 0.0
    growth_from: float = 0.0
    growth_to: float = 1.0
    grow_duration: float = 2.0
    base_y: float | None = None

    def __post_init__(self) -> None:
        if self.name not in assets.PROP_NAMES:
            choices = ", ".join(sorted(assets.PROP_NAMES))
            raise AnimationError(f"prop must be one of {choices}")
        if self.scale <= 0:
            raise AnimationError("prop scale must be positive")
        if self.appear < 0:
            raise AnimationError("prop appear time must not be negative")
        if self.grow_duration < 0:
            raise AnimationError("prop grow duration must not be negative")
        for value in (self.x, self.y, self.growth_from, self.growth_to):
            if not math.isfinite(value):
                raise AnimationError("prop values must be finite")

    def growth_at(self, time: float) -> float:
        if time < self.appear:
            return self.growth_from
        if self.grow_duration <= 0:
            return self.growth_to
        ratio = min(1.0, (time - self.appear) / self.grow_duration)
        return self.growth_from + (self.growth_to - self.growth_from) * ratio

    def visible(self, time: float) -> bool:
        return time >= self.appear


@dataclass(frozen=True)
class Actor:
    """A character placed in a scene with its own animation clips."""

    character: Character
    x: float
    y: float
    scale: float = 1.0
    clips: tuple[AnimationClip, ...] = ()
    expression: str = "neutral"
    expression_weight: float = 1.0
    mouth_track: tuple[float, ...] = ()
    appear: float = 0.0
    fade_in: float = 0.25
    travel_to_x: float | None = None
    travel_start: float = 0.0
    travel_duration: float = 1.0

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise AnimationError("actor scale must be positive")
        if self.appear < 0:
            raise AnimationError("actor appear time must not be negative")
        if self.fade_in < 0:
            raise AnimationError("actor fade-in must not be negative")
        if self.travel_duration <= 0:
            raise AnimationError("actor travel duration must be positive")
        for value in self.mouth_track:
            if not 0.0 <= value <= 1.0:
                raise AnimationError("mouth track values must be between 0 and 1")

    def pose_at(self, time: float, fps: int) -> Pose:
        pose = sample_clips(self.clips, time)
        pose = apply_expression(pose, self.expression, self.expression_weight)
        if self.mouth_track and time >= self.appear:
            index = min(len(self.mouth_track) - 1, max(0, int(time * fps)))
            pose = pose.updated(mouth_open=self.mouth_track[index])
        return pose

    def x_at(self, time: float) -> float:
        """Actor x at ``time``, including a smooth scene-level travel path."""
        if self.travel_to_x is None or time <= self.travel_start:
            return self.x
        progress = min(1.0, (time - self.travel_start) / self.travel_duration)
        eased = progress * progress * (3.0 - 2.0 * progress)
        return self.x + (self.travel_to_x - self.x) * eased

    def opacity_at(self, time: float) -> float:
        if time < self.appear:
            return 0.0
        if self.fade_in <= 0:
            return 1.0
        return min(1.0, (time - self.appear) / self.fade_in)


@dataclass(frozen=True)
class ScenePlan:
    """Everything needed to render one animated scene."""

    background: str
    duration: float
    settings: RenderSettings = RenderSettings()
    actors: tuple[Actor, ...] = ()
    props: tuple[Prop, ...] = ()

    def __post_init__(self) -> None:
        if self.background not in assets.BACKGROUNDS:
            choices = ", ".join(assets.background_names())
            raise AnimationError(f"background must be one of {choices}")
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise AnimationError("scene duration must be positive")

    @property
    def frame_count(self) -> int:
        return max(1, int(round(self.duration * self.settings.fps)))


def build_plan(
    spec,
    characters: dict[str, Character],
    duration: float,
    settings: RenderSettings,
    *,
    mouth_track: tuple[float, ...] = (),
) -> ScenePlan:
    """Turn a validated scene animation into a renderable plan."""
    from app.services.cartoon_animation import presets

    actors: list[Actor] = []
    if spec.character:
        try:
            character = characters[spec.character]
        except KeyError as exc:
            raise AnimationError(
                f"scene references an undeclared character: {spec.character}"
            ) from exc
        clips = [AnimationClip(presets.get_animation("idle"), start=0.0)]
        for action in spec.actions:
            clips.append(
                AnimationClip(
                    presets.get_animation(action.animation),
                    start=action.at,
                    speed=action.speed,
                    weight=action.weight,
                )
            )
        actors.append(
            Actor(
                character=character,
                x=spec.x * settings.width,
                y=spec.y * settings.height,
                scale=spec.scale,
                clips=tuple(clips),
                expression=spec.expression,
                mouth_track=mouth_track if spec.lip_sync else (),
                travel_to_x=(
                    spec.travel.to_x * settings.width
                    if spec.travel is not None
                    else None
                ),
                travel_start=spec.travel.start if spec.travel is not None else 0.0,
                travel_duration=(
                    spec.travel.duration if spec.travel is not None else 1.0
                ),
            )
        )

    unit = settings.height / 1280.0
    props = tuple(
        Prop(
            name=prop.name,
            x=prop.x * settings.width,
            y=prop.y * settings.height,
            scale=prop.scale * unit,
            appear=prop.appear,
            growth_from=prop.growth_from,
            growth_to=prop.growth_to,
            grow_duration=prop.grow_duration,
            base_y=(
                prop.base_y * settings.height if prop.base_y is not None else None
            ),
        )
        for prop in spec.props
    )
    return ScenePlan(
        background=spec.background,
        duration=duration,
        settings=settings,
        actors=tuple(actors),
        props=props,
    )


def render_frame(plan: ScenePlan, time: float) -> Image.Image:
    """Render one RGB frame at ``time`` seconds (deterministic)."""
    from app.services.cartoon_animation.renderer import render_character

    width, height = plan.settings.width, plan.settings.height
    frame = assets.background(plan.background, (width, height))
    draw = ImageDraw.Draw(frame)

    base_y = height * 0.74
    for prop in plan.props:
        if not prop.visible(time):
            continue
        assets.draw_prop(
            draw,
            prop.name,
            prop.x,
            prop.y,
            prop.scale,
            growth=prop.growth_at(time),
            base_y=prop.base_y if prop.base_y is not None else base_y,
        )

    for actor in plan.actors:
        opacity = actor.opacity_at(time)
        if opacity <= 0:
            continue
        pose = actor.pose_at(time, plan.settings.fps)
        sprite = render_character(actor.character, pose)
        if actor.scale != 1.0:
            sprite = sprite.resize(
                (
                    max(1, int(round(sprite.width * actor.scale))),
                    max(1, int(round(sprite.height * actor.scale))),
                ),
                Image.LANCZOS,
            )
        if opacity < 1.0:
            alpha = sprite.getchannel("A").point(lambda value: int(value * opacity))
            sprite.putalpha(alpha)
        origin_x = actor.character.origin[0] * actor.scale
        origin_y = actor.character.origin[1] * actor.scale
        _composite(
            frame,
            sprite,
            int(round(actor.x_at(time) - origin_x)),
            int(round(actor.y - origin_y)),
        )
    return frame


def _composite(destination: Image.Image, source: Image.Image, x: int, y: int) -> None:
    """Alpha-composite ``source`` onto ``destination`` clipping at the edges."""
    left = max(0, x)
    top = max(0, y)
    right = min(destination.width, x + source.width)
    bottom = min(destination.height, y + source.height)
    if right <= left or bottom <= top:
        return
    crop = source.crop((left - x, top - y, right - x, bottom - y))
    region = destination.crop((left, top, right, bottom))
    destination.paste(Image.alpha_composite(region.convert("RGBA"), crop).convert("RGB"), (left, top))


def iter_frames(plan: ScenePlan) -> Iterator[tuple[float, Image.Image]]:
    """Yield ``(time, frame)`` progressively without buffering the scene."""
    fps = plan.settings.fps
    for index in range(plan.frame_count):
        time = index / fps
        yield time, render_frame(plan, time)


def render_scene_video(
    plan: ScenePlan,
    output_path: str,
    *,
    progress: Callable[[float], None] | None = None,
    ffmpeg_binary: str | None = None,
    cancel: Callable[[], bool] | None = None,
) -> str:
    """Encode a scene to H.264 MP4 by streaming raw frames to FFmpeg."""
    from app.services.cartoon_animation.renderer import encode_frames

    return encode_frames(
        iter_frames(plan),
        output_path,
        plan.settings,
        progress=progress,
        ffmpeg_binary=ffmpeg_binary,
        cancel=cancel,
    )
