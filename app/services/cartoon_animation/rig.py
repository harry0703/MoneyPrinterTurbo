"""Joint hierarchy resolution for articulated characters.

Each part is a joint: it has an anchor in its parent's local space, an
accumulated rotation and a scale. Resolving a pose walks the tree once and
returns world-space joints, which the renderer draws in layer order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.cartoon_animation.models import (
    AnimationError,
    Character,
    Part,
    Pose,
)


@dataclass(frozen=True)
class Joint:
    name: str
    x: float
    y: float
    angle: float
    scale: float


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    if not degrees:
        return x, y
    radians = math.radians(degrees)
    cos = math.cos(radians)
    sin = math.sin(radians)
    return x * cos - y * sin, x * sin + y * cos


def _ordered_parts(character: Character) -> list[Part]:
    """Parents before children, preserving the declared order otherwise."""
    pending = list(character.parts)
    resolved: dict[str, Joint] = {}
    ordered: list[Part] = []
    while pending:
        progressed = False
        remaining: list[Part] = []
        for part in pending:
            if part.parent is None or part.parent in resolved:
                ordered.append(part)
                resolved[part.name] = Joint(part.name, 0.0, 0.0, 0.0, 1.0)
                progressed = True
            else:
                remaining.append(part)
        if not progressed:
            raise AnimationError(f"character {character.id} has an unresolved hierarchy")
        pending = remaining
    return ordered


def resolve_joints(character: Character, pose: Pose) -> dict[str, Joint]:
    scale = pose.value("scale")
    root_x = pose.value("root_x")
    root_y = pose.value("root_y")
    origin_x, origin_y = character.origin
    joints: dict[str, Joint] = {}

    for part in _ordered_parts(character):
        rotation = pose.value(part.rotation_channel) if part.rotation_channel else 0.0
        if part.parent is None:
            offset_x, offset_y = _rotate(
                part.anchor[0] * scale, part.anchor[1] * scale, 0.0
            )
            x = origin_x + offset_x + root_x
            y = origin_y + offset_y + root_y
            angle = rotation
        else:
            parent = joints[part.parent]
            offset_x, offset_y = _rotate(
                part.anchor[0] * parent.scale,
                part.anchor[1] * parent.scale,
                parent.angle,
            )
            x = parent.x + offset_x
            y = parent.y + offset_y
            angle = parent.angle + rotation
        if part.translation_channels:
            x += pose.value(part.translation_channels[0]) * scale
            y += pose.value(part.translation_channels[1]) * scale
        joints[part.name] = Joint(part.name, x, y, angle, scale)
    return joints


def part_world_bounds(
    character: Character, pose: Pose
) -> tuple[float, float, float, float]:
    """Approximate sprite bounds in canvas space, used for tests and layout."""
    joints = resolve_joints(character, pose)
    scale = pose.value("scale")
    left = right = character.origin[0]
    top = bottom = character.origin[1]
    for part in character.parts:
        joint = joints[part.name]
        centre_x = joint.x + part.shape.offset[0] * scale
        centre_y = joint.y + part.shape.offset[1] * scale
        half_w = part.shape.width * scale / 2
        half_h = part.shape.height * scale / 2
        reach = math.hypot(half_w, half_h)
        left = min(left, centre_x - reach)
        right = max(right, centre_x + reach)
        top = min(top, centre_y - reach)
        bottom = max(bottom, centre_y + reach)
    return left, top, right, bottom
