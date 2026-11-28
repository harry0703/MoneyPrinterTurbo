"""Validation for the optional animation section of a cartoon manifest.

The classic manifest remains untouched. Animation is opt-in:

* a top-level ``animation.characters`` list declares which articulated
  characters a scene may use;
* each scene may add an ``animation`` object that places one character, picks
  a background, props and timed action clips.

Unknown fields are rejected so typos fail loudly instead of rendering a
silently different episode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.cartoon_animation import assets, presets
from app.services.cartoon_animation.characters import get_character
from app.services.cartoon_animation.expressions import expression_names
from app.services.cartoon_animation.models import AnimationError, Character

_PROJECT_FIELDS = {"characters"}
_CHARACTER_FIELDS = {"id", "preset", "palette"}
_SCENE_FIELDS = {
    "background",
    "character",
    "x",
    "y",
    "scale",
    "expression",
    "actions",
    "props",
    "lip_sync",
    "travel",
}
_TRAVEL_FIELDS = {"to_x", "start", "duration"}
_ACTION_FIELDS = {"animation", "at", "weight", "speed"}
_PROP_FIELDS = {
    "name",
    "x",
    "y",
    "scale",
    "appear",
    "growth_from",
    "growth_to",
    "grow_duration",
    "base_y",
}
_ID_LIMIT = 64


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnimationError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise AnimationError(f"{field} must be finite")
    return result


def _fraction(value: Any, field: str) -> float:
    result = _number(value, field)
    if not 0.0 <= result <= 1.0:
        raise AnimationError(f"{field} must be between 0 and 1")
    return result


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnimationError(f"{field} must be an object")
    return value


def _check_fields(data: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise AnimationError(f"unknown fields in {field}: {', '.join(sorted(unknown))}")


@dataclass(frozen=True)
class ActionSpec:
    animation: str
    at: float = 0.0
    weight: float = 1.0
    speed: float = 1.0


@dataclass(frozen=True)
class PropSpec:
    name: str
    x: float
    y: float
    scale: float = 1.0
    appear: float = 0.0
    growth_from: float = 0.0
    growth_to: float = 1.0
    grow_duration: float = 2.0
    base_y: float | None = None


@dataclass(frozen=True)
class TravelSpec:
    """Smooth horizontal displacement of the actor during the scene."""

    to_x: float
    start: float = 0.0
    duration: float = 1.0


@dataclass(frozen=True)
class SceneAnimation:
    background: str
    character: str | None
    x: float = 0.5
    y: float = 0.7
    scale: float = 1.0
    expression: str = "neutral"
    actions: tuple[ActionSpec, ...] = ()
    props: tuple[PropSpec, ...] = ()
    lip_sync: bool = True
    travel: TravelSpec | None = None


@dataclass(frozen=True)
class ProjectAnimation:
    characters: Mapping[str, Character]


def _parse_action(raw: Any, index: int) -> ActionSpec:
    data = _object(raw, f"animation.actions[{index}]")
    _check_fields(data, _ACTION_FIELDS, f"animation.actions[{index}]")
    name = data.get("animation")
    if not isinstance(name, str):
        raise AnimationError(f"animation.actions[{index}].animation must be text")
    presets.get_animation(name)
    at = _number(data.get("at", 0), f"animation.actions[{index}].at")
    if at < 0:
        raise AnimationError(f"animation.actions[{index}].at must not be negative")
    return ActionSpec(
        animation=name,
        at=at,
        weight=_fraction(data.get("weight", 1.0), f"animation.actions[{index}].weight"),
        speed=_number(data.get("speed", 1.0), f"animation.actions[{index}].speed"),
    )


def _parse_prop(raw: Any, index: int) -> PropSpec:
    data = _object(raw, f"animation.props[{index}]")
    _check_fields(data, _PROP_FIELDS, f"animation.props[{index}]")
    name = data.get("name")
    if name not in assets.PROP_NAMES:
        choices = ", ".join(sorted(assets.PROP_NAMES))
        raise AnimationError(f"animation.props[{index}].name must be one of {choices}")
    return PropSpec(
        name=name,
        x=_fraction(data.get("x", 0.5), f"animation.props[{index}].x"),
        y=_fraction(data.get("y", 0.75), f"animation.props[{index}].y"),
        scale=_number(data.get("scale", 1.0), f"animation.props[{index}].scale"),
        appear=_number(data.get("appear", 0.0), f"animation.props[{index}].appear"),
        growth_from=_fraction(
            data.get("growth_from", 0.0), f"animation.props[{index}].growth_from"
        ),
        growth_to=_fraction(
            data.get("growth_to", 1.0), f"animation.props[{index}].growth_to"
        ),
        grow_duration=_number(
            data.get("grow_duration", 2.0), f"animation.props[{index}].grow_duration"
        ),
        base_y=(
            _fraction(data["base_y"], f"animation.props[{index}].base_y")
            if data.get("base_y") is not None
            else None
        ),
    )


def parse_project_animation(data: Any) -> ProjectAnimation:
    if data is None:
        return ProjectAnimation({})
    root = _object(data, "animation")
    _check_fields(root, _PROJECT_FIELDS, "animation")
    raw_characters = root.get("characters", [])
    if not isinstance(raw_characters, list):
        raise AnimationError("animation.characters must be a list")
    characters: dict[str, Character] = {}
    for index, raw in enumerate(raw_characters):
        _check_fields(
            _object(raw, f"animation.characters[{index}]"),
            _CHARACTER_FIELDS,
            f"animation.characters[{index}]",
        )
        entry = _object(raw, f"animation.characters[{index}]")
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise AnimationError(f"animation.characters[{index}].id must be text")
        identifier = identifier.strip()
        if len(identifier) > _ID_LIMIT:
            raise AnimationError(
                f"animation.characters[{index}].id must be under {_ID_LIMIT} characters"
            )
        if identifier in characters:
            raise AnimationError(f"duplicate animation character: {identifier}")
        preset = entry.get("preset", identifier)
        if not isinstance(preset, str):
            raise AnimationError(
                f"animation.characters[{index}].preset must be text"
            )
        palette = entry.get("palette")
        if palette is not None:
            palette = dict(_object(palette, f"animation.characters[{index}].palette"))
            for key, value in palette.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise AnimationError(
                        f"animation.characters[{index}].palette must map names to colours"
                    )
        character = get_character(preset, palette)
        characters[identifier] = character
    if len(characters) > 20:
        raise AnimationError("animation supports at most 20 characters")
    return ProjectAnimation(characters)


def parse_scene_animation(
    data: Any, project: ProjectAnimation, *, field: str = "animation"
) -> SceneAnimation:
    root = _object(data, field)
    _check_fields(root, _SCENE_FIELDS, field)
    background = root.get("background", "garden")
    if background not in assets.BACKGROUNDS:
        choices = ", ".join(assets.background_names())
        raise AnimationError(f"{field}.background must be one of {choices}")
    character_name = root.get("character")
    if character_name is not None:
        if not isinstance(character_name, str):
            raise AnimationError(f"{field}.character must be text")
        if character_name not in project.characters:
            raise AnimationError(
                f"{field}.character references an undeclared character: {character_name}"
            )
    expression = root.get("expression", "neutral")
    if expression not in expression_names():
        choices = ", ".join(expression_names())
        raise AnimationError(f"{field}.expression must be one of {choices}")
    scale = _number(root.get("scale", 1.0), f"{field}.scale")
    if not 0.1 <= scale <= 3.0:
        raise AnimationError(f"{field}.scale must be between 0.1 and 3")
    raw_actions = root.get("actions", [])
    if not isinstance(raw_actions, list):
        raise AnimationError(f"{field}.actions must be a list")
    raw_props = root.get("props", [])
    if not isinstance(raw_props, list):
        raise AnimationError(f"{field}.props must be a list")
    lip_sync = root.get("lip_sync", True)
    if not isinstance(lip_sync, bool):
        raise AnimationError(f"{field}.lip_sync must be true or false")
    travel = None
    if root.get("travel") is not None:
        raw_travel = _object(root["travel"], f"{field}.travel")
        _check_fields(raw_travel, _TRAVEL_FIELDS, f"{field}.travel")
        travel = TravelSpec(
            to_x=_fraction(raw_travel.get("to_x"), f"{field}.travel.to_x"),
            start=_number(raw_travel.get("start", 0.0), f"{field}.travel.start"),
            duration=_number(
                raw_travel.get("duration", 1.0), f"{field}.travel.duration"
            ),
        )
        if travel.start < 0:
            raise AnimationError(f"{field}.travel.start must not be negative")
        if travel.duration <= 0:
            raise AnimationError(f"{field}.travel.duration must be positive")
    return SceneAnimation(
        background=background,
        character=character_name,
        x=_fraction(root.get("x", 0.5), f"{field}.x"),
        y=_fraction(root.get("y", 0.7), f"{field}.y"),
        scale=scale,
        expression=expression,
        actions=tuple(_parse_action(raw, index) for index, raw in enumerate(raw_actions)),
        props=tuple(_parse_prop(raw, index) for index, raw in enumerate(raw_props)),
        lip_sync=lip_sync,
        travel=travel,
    )


def parse_animation(
    manifest_animation: Any, scenes: list[Any]
) -> tuple[ProjectAnimation, dict[str, SceneAnimation]]:
    """Validate the whole animation section and return parsed scene specs."""
    project = parse_project_animation(manifest_animation)
    parsed: dict[str, SceneAnimation] = {}
    for scene in scenes:
        scene_animation = scene.get("animation")
        if scene_animation is None:
            continue
        scene_id = scene.get("id")
        if not isinstance(scene_id, str):
            raise AnimationError("every animated scene needs an id")
        parsed[scene_id] = parse_scene_animation(
            scene_animation, project, field=f"scenes[{scene_id}].animation"
        )
    return project, parsed


def document(spec: SceneAnimation) -> dict:
    """Serialise a validated scene animation back to manifest shape."""
    return {
        "background": spec.background,
        "character": spec.character,
        "x": spec.x,
        "y": spec.y,
        "scale": spec.scale,
        "expression": spec.expression,
        "lip_sync": spec.lip_sync,
        "travel": (
            {
                "to_x": spec.travel.to_x,
                "start": spec.travel.start,
                "duration": spec.travel.duration,
            }
            if spec.travel is not None
            else None
        ),
        "actions": [
            {
                "animation": action.animation,
                "at": action.at,
                "weight": action.weight,
                "speed": action.speed,
            }
            for action in spec.actions
        ],
        "props": [
            {
                "name": prop.name,
                "x": prop.x,
                "y": prop.y,
                "scale": prop.scale,
                "appear": prop.appear,
                "growth_from": prop.growth_from,
                "growth_to": prop.growth_to,
                "grow_duration": prop.grow_duration,
                "base_y": prop.base_y,
            }
            for prop in spec.props
        ],
    }
