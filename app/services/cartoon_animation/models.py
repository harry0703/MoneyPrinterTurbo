"""Data model for the procedural 2D cartoon animation engine.

The engine is deliberately independent from Cartoon Studio and from FFmpeg:
a character is a small component tree, a pose is a flat set of named numeric
channels, and an animation is a set of keyframe tracks over those channels.
Everything else (rendering, compositing, lip sync) consumes these types.

Coordinates are pixels in the internal render canvas, with ``+x`` to the right
and ``+y`` downwards. Rotations are degrees, clockwise for a positive value
because Pillow rotates clockwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


class AnimationError(ValueError):
    """Raised when an animation, character or scene definition is invalid."""


# name -> (minimum, maximum, neutral value)
CHANNELS: dict[str, tuple[float, float, float]] = {
    "root_x": (-500.0, 500.0, 0.0),
    "root_y": (-800.0, 800.0, 0.0),
    "scale": (0.2, 3.0, 1.0),
    "opacity": (0.0, 1.0, 1.0),
    "body_rotation": (-25.0, 25.0, 0.0),
    "head_rotation": (-30.0, 30.0, 0.0),
    "head_x": (-40.0, 40.0, 0.0),
    "head_y": (-40.0, 40.0, 0.0),
    "left_arm_rotation": (-170.0, 170.0, 0.0),
    "right_arm_rotation": (-170.0, 170.0, 0.0),
    "left_leg_rotation": (-60.0, 60.0, 0.0),
    "right_leg_rotation": (-60.0, 60.0, 0.0),
    "antenna_rotation": (-40.0, 40.0, 0.0),
    "eye_open": (0.0, 1.0, 1.0),
    "pupil_x": (-1.0, 1.0, 0.0),
    "pupil_y": (-1.0, 1.0, 0.0),
    "mouth_open": (0.0, 1.0, 0.0),
    "mouth_width": (0.0, 1.0, 0.4),
    "brow_raise": (-1.0, 1.0, 0.0),
    "brow_angle": (-1.0, 1.0, 0.0),
    "blush": (0.0, 1.0, 0.0),
}

SHAPE_KINDS = frozenset({"ellipse", "rounded_rect", "capsule", "polygon"})
DYNAMIC_PARTS = frozenset({"eye", "pupil", "mouth", "brow", "blush"})

# Rendering presets for the final delivery. Keeping these values together
# makes it possible to change quality without touching any animation code.
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280
DEFAULT_FPS = 24
DEFAULT_OUTPUT_WIDTH = 1080
DEFAULT_OUTPUT_HEIGHT = 1920


def clamp(value: float, minimum: float, maximum: float) -> float:
    return minimum if value < minimum else maximum if value > maximum else value


def channel_default(name: str) -> float:
    if name not in CHANNELS:
        raise AnimationError(f"unknown animation channel: {name}")
    return CHANNELS[name][2]


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnimationError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise AnimationError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True)
class Pose:
    """A snapshot of every animation channel for one character.

    Unknown channels, non-finite values and out-of-range values are rejected
    when the pose is built. ``value`` also clamps, so interpolated poses can
    never push a rotation past its joint limit.
    """

    channels: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in self.channels.items():
            if name not in CHANNELS:
                raise AnimationError(f"unknown animation channel: {name}")
            _finite(value, f"pose.{name}")

    def value(self, name: str) -> float:
        minimum, maximum, default = CHANNELS[name]
        return clamp(float(self.channels.get(name, default)), minimum, maximum)

    def updated(self, **values: float) -> "Pose":
        merged = dict(self.channels)
        merged.update(values)
        return Pose(merged)

    def merged(self, values: Mapping[str, float]) -> "Pose":
        merged = dict(self.channels)
        merged.update(values)
        return Pose(merged)

    def adjusted(self, deltas: Mapping[str, float], weight: float = 1.0) -> "Pose":
        merged = dict(self.channels)
        for name, delta in deltas.items():
            merged[name] = merged.get(name, channel_default(name)) + delta * weight
        return Pose(merged)

    def as_dict(self) -> dict[str, float]:
        return {name: self.value(name) for name in CHANNELS}


@dataclass(frozen=True)
class Shape:
    """A drawable primitive in a part's local space.

    ``offset`` positions the shape centre relative to the part joint, so a
    limb can rotate around its shoulder instead of its centre.
    """

    kind: str
    width: float
    height: float
    color: str
    outline: str = ""
    outline_width: float = 0.0
    radius: float = 0.0
    points: tuple[tuple[float, float], ...] = ()
    offset: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        if self.kind not in SHAPE_KINDS:
            choices = ", ".join(sorted(SHAPE_KINDS))
            raise AnimationError(f"shape kind must be one of {choices}")
        if _finite(self.width, "shape.width") <= 0 or _finite(
            self.height, "shape.height"
        ) <= 0:
            raise AnimationError("shape width and height must be positive")
        if not isinstance(self.color, str) or not self.color:
            raise AnimationError("shape color must be a palette key")
        if self.kind == "polygon" and len(self.points) < 3:
            raise AnimationError("polygon shapes need at least three points")
        for x, y in self.points:
            _finite(x, "shape.points.x")
            _finite(y, "shape.points.y")
        _finite(self.offset[0], "shape.offset.x")
        _finite(self.offset[1], "shape.offset.y")
        if _finite(self.outline_width, "shape.outline_width") < 0:
            raise AnimationError("shape outline width must not be negative")


@dataclass(frozen=True)
class Part:
    """One component of a character, optionally attached to a parent joint."""

    name: str
    shape: Shape
    parent: str | None = None
    anchor: tuple[float, float] = (0.0, 0.0)
    layer: int = 0
    rotation_channel: str | None = None
    translation_channels: tuple[str, str] | None = None
    dynamic: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise AnimationError("part name must be a non-empty string")
        if self.layer < 0:
            raise AnimationError(f"part {self.name} has a negative layer")
        if self.rotation_channel is not None and self.rotation_channel not in CHANNELS:
            raise AnimationError(
                f"part {self.name} uses unknown rotation channel {self.rotation_channel}"
            )
        if self.translation_channels is not None:
            for channel in self.translation_channels:
                if channel not in CHANNELS:
                    raise AnimationError(
                        f"part {self.name} uses unknown translation channel {channel}"
                    )
        if self.dynamic is not None and self.dynamic not in DYNAMIC_PARTS:
            raise AnimationError(
                f"part {self.name} has unknown dynamic kind {self.dynamic}"
            )
        _finite(self.anchor[0], f"part.{self.name}.anchor.x")
        _finite(self.anchor[1], f"part.{self.name}.anchor.y")


@dataclass(frozen=True)
class Character:
    """A reusable articulated 2D character."""

    id: str
    name: str
    palette: Mapping[str, str]
    parts: tuple[Part, ...]
    canvas: tuple[float, float] = (480.0, 660.0)
    origin: tuple[float, float] = (240.0, 500.0)

    def __post_init__(self) -> None:
        if not self.id:
            raise AnimationError("character id must not be empty")
        if not self.parts:
            raise AnimationError(f"character {self.id} has no parts")
        names: set[str] = set()
        for part in self.parts:
            if part.name in names:
                raise AnimationError(f"character {self.id} repeats part {part.name}")
            names.add(part.name)
        for part in self.parts:
            if part.parent is not None and part.parent not in names:
                raise AnimationError(
                    f"part {part.name} references unknown parent {part.parent}"
                )
            for key in self._color_keys(part.shape):
                if key not in self.palette:
                    raise AnimationError(
                        f"part {part.name} uses missing palette key {key}"
                    )
        for value in (self.canvas[0], self.canvas[1], self.origin[0], self.origin[1]):
            _finite(value, "character.canvas")
        self._check_cycles()

    @staticmethod
    def _color_keys(shape: Shape) -> Iterable[str]:
        if shape.color:
            yield shape.color
        if shape.outline:
            yield shape.outline

    def _check_cycles(self) -> None:
        parents = {part.name: part.parent for part in self.parts}
        for part in self.parts:
            seen = {part.name}
            parent = part.parent
            while parent is not None:
                if parent in seen:
                    raise AnimationError(
                        f"character {self.id} has a cycle at part {part.name}"
                    )
                seen.add(parent)
                parent = parents[parent]

    def part(self, name: str) -> Part:
        for part in self.parts:
            if part.name == name:
                return part
        raise AnimationError(f"character {self.id} has no part {name}")

    def layered(self) -> tuple[Part, ...]:
        """Parts in draw order: stable for equal layers."""
        return tuple(sorted(self.parts, key=lambda item: (item.layer, item.name)))


@dataclass(frozen=True)
class Keyframe:
    time: float
    value: float
    easing: str = "ease-in-out"

    def __post_init__(self) -> None:
        if _finite(self.time, "keyframe.time") < 0:
            raise AnimationError("keyframe time must not be negative")
        _finite(self.value, "keyframe.value")
        from app.services.cartoon_animation.interpolation import EASINGS

        if self.easing not in EASINGS:
            choices = ", ".join(sorted(EASINGS))
            raise AnimationError(f"keyframe easing must be one of {choices}")


@dataclass(frozen=True)
class Animation:
    """Keyframe tracks evaluated over a fixed duration.

    ``additive`` animations add their offset to the pose instead of replacing
    the channel, and a higher ``priority`` wins when two clips animate the same
    channel.
    """

    name: str
    duration: float
    tracks: Mapping[str, tuple[Keyframe, ...]]
    loop: bool = False
    priority: int = 0
    additive: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise AnimationError("animation name must not be empty")
        if _finite(self.duration, f"animation.{self.name}.duration") <= 0:
            raise AnimationError(f"animation {self.name} must have a duration")
        if not self.tracks:
            raise AnimationError(f"animation {self.name} has no tracks")
        for channel, frames in self.tracks.items():
            if channel not in CHANNELS:
                raise AnimationError(
                    f"animation {self.name} uses unknown channel {channel}"
                )
            if not frames:
                raise AnimationError(
                    f"animation {self.name} has an empty track for {channel}"
                )
            last = -1.0
            for frame in frames:
                if not isinstance(frame, Keyframe):
                    raise AnimationError(
                        f"animation {self.name} tracks must contain keyframes"
                    )
                if frame.time < last:
                    raise AnimationError(
                        f"animation {self.name} track {channel} is not sorted"
                    )
                if frame.time > self.duration + 1e-9:
                    raise AnimationError(
                        f"animation {self.name} track {channel} exceeds its duration"
                    )
                last = frame.time


@dataclass(frozen=True)
class RenderSettings:
    """Internal and delivery resolution for one scene render."""

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    output_width: int = DEFAULT_OUTPUT_WIDTH
    output_height: int = DEFAULT_OUTPUT_HEIGHT
    crf: int = 20
    preset: str = "medium"

    def __post_init__(self) -> None:
        for name in ("width", "height", "fps", "output_width", "output_height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise AnimationError(f"render {name} must be a positive integer")
        if not 1 <= self.fps <= 60:
            raise AnimationError("render fps must be between 1 and 60")
        if not 0 <= self.crf <= 51:
            raise AnimationError("render crf must be between 0 and 51")
        if not isinstance(self.preset, str) or not self.preset:
            raise AnimationError("render preset must be a non-empty string")
