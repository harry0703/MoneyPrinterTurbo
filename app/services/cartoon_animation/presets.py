"""Built-in animation presets.

Presets are plain :class:`Animation` values, so a project can reference them
by name while custom animations can be built with the same primitives.
Priorities are chosen so that a one-shot action (wave, jump) overrides an
ambient loop (idle) on the channels they share.
"""

from __future__ import annotations

from app.services.cartoon_animation.keyframes import AnimationClip
from app.services.cartoon_animation.models import Animation, AnimationError, Keyframe


def _frames(*pairs) -> tuple[Keyframe, ...]:
    """Build keyframes from ``(time, value)`` or ``(time, value, easing)``."""
    result = []
    for pair in pairs:
        time, value = pair[0], pair[1]
        easing = pair[2] if len(pair) > 2 else "ease-in-out"
        result.append(Keyframe(float(time), float(value), easing))
    return tuple(result)


def _animation(name, duration, tracks, *, loop=False, priority=0, additive=False):
    return Animation(
        name=name,
        duration=duration,
        tracks=tracks,
        loop=loop,
        priority=priority,
        additive=additive,
    )


def _build() -> dict[str, Animation]:
    animations: dict[str, Animation] = {}

    animations["idle"] = _animation(
        "idle",
        3.0,
        {
            "root_y": _frames((0, 0), (1.5, -4), (3.0, 0)),
            "body_rotation": _frames((0, 0), (0.75, 1.2), (2.25, -1.2), (3.0, 0)),
            "head_rotation": _frames((0, 0), (1.0, 1.0), (2.0, -1.5), (3.0, 0)),
            "antenna_rotation": _frames((0, 0), (1.0, 3.0), (2.0, -3.0), (3.0, 0)),
            "mouth_width": _frames((0, 0.4), (3.0, 0.4, "linear")),
        },
        loop=True,
        priority=0,
    )

    animations["blink"] = _animation(
        "blink",
        0.22,
        {
            "eye_open": _frames(
                (0.0, 1.0, "linear"), (0.07, 0.0, "ease-out"), (0.16, 0.0, "ease-in"), (0.22, 1.0)
            )
        },
        priority=50,
    )

    for name, direction in (("look_left", -1.0), ("look_right", 1.0)):
        animations[name] = _animation(
            name,
            1.1,
            {
                "pupil_x": _frames((0, 0), (0.18, direction), (0.8, direction), (1.1, 0)),
                "head_rotation": _frames(
                    (0, 0), (0.2, direction * 5.0), (0.8, direction * 5.0), (1.1, 0)
                ),
            },
            priority=20,
        )

    animations["talk"] = _animation(
        "talk",
        0.42,
        {
            "mouth_open": _frames(
                (0.0, 0.05, "linear"),
                (0.12, 0.75, "ease-out"),
                (0.26, 0.2, "ease-in"),
                (0.42, 0.6, "ease-in-out"),
            ),
            "mouth_width": _frames((0, 0.4), (0.2, 0.55), (0.42, 0.4)),
            "head_rotation": _frames((0, 0), (0.21, 1.5), (0.42, 0)),
        },
        loop=True,
        priority=30,
    )

    animations["wave"] = _animation(
        "wave",
        1.7,
        {
            "right_arm_rotation": _frames(
                (0.0, 0.0),
                (0.25, -150.0, "ease-out"),
                (0.55, -120.0),
                (0.85, -158.0),
                (1.15, -120.0),
                (1.45, -150.0),
                (1.7, 0.0, "ease-in"),
            ),
            "body_rotation": _frames((0, 0), (0.3, -3), (1.4, -3), (1.7, 0)),
            "head_rotation": _frames((0, 0), (0.3, 4), (1.4, 4), (1.7, 0)),
        },
        priority=40,
    )

    animations["walk"] = _animation(
        "walk",
        2.0,
        {
            "left_leg_rotation": _frames(
                (0, 0), (0.5, 28), (1.0, 0), (1.5, -28), (2.0, 0)
            ),
            "right_leg_rotation": _frames(
                (0, 0), (0.5, -28), (1.0, 0), (1.5, 28), (2.0, 0)
            ),
            "left_arm_rotation": _frames(
                (0, 0), (0.5, -18), (1.0, 0), (1.5, 18), (2.0, 0)
            ),
            "right_arm_rotation": _frames(
                (0, 0), (0.5, 18), (1.0, 0), (1.5, -18), (2.0, 0)
            ),
            "root_y": _frames((0, 0), (0.5, -6), (1.0, 0), (1.5, -6), (2.0, 0)),
        },
        priority=10,
    )

    animations["jump"] = _animation(
        "jump",
        0.95,
        {
            "root_y": _frames(
                (0.0, 0.0, "ease-in"),
                (0.18, 18.0, "ease-out"),
                (0.45, -105.0, "ease-in"),
                (0.7, 10.0, "ease-out"),
                (0.95, 0.0),
            ),
            "left_leg_rotation": _frames((0, 0), (0.18, -12), (0.5, 20), (0.95, 0)),
            "right_leg_rotation": _frames((0, 0), (0.18, 12), (0.5, -20), (0.95, 0)),
            "left_arm_rotation": _frames((0, 0), (0.2, 120), (0.5, 150), (0.95, 0)),
            "right_arm_rotation": _frames((0, 0), (0.2, -120), (0.5, -150), (0.95, 0)),
            "antenna_rotation": _frames((0, 0), (0.45, -18), (0.7, 12), (0.95, 0)),
        },
        priority=45,
    )

    animations["happy"] = _animation(
        "happy",
        1.4,
        {
            "root_y": _frames((0, 0), (0.25, -22), (0.5, 0), (0.75, -16), (1.0, 0), (1.4, 0)),
            "left_arm_rotation": _frames((0, 0), (0.3, 140), (1.0, 140), (1.4, 0)),
            "right_arm_rotation": _frames((0, 0), (0.3, -140), (1.0, -140), (1.4, 0)),
            "head_rotation": _frames((0, 0), (0.35, -8), (0.8, 8), (1.4, 0)),
            "mouth_open": _frames((0, 0), (0.3, 0.5), (1.1, 0.5), (1.4, 0)),
            "antenna_rotation": _frames((0, 0), (0.4, 14), (0.9, -10), (1.4, 0)),
        },
        priority=40,
    )

    animations["surprised"] = _animation(
        "surprised",
        0.9,
        {
            "mouth_open": _frames((0, 0), (0.15, 0.85), (0.75, 0.85), (0.9, 0)),
            "mouth_width": _frames((0, 0.4), (0.15, 0.3), (0.75, 0.3), (0.9, 0.4)),
            "brow_raise": _frames((0, 0), (0.15, 1.0), (0.75, 1.0), (0.9, 0)),
            "head_rotation": _frames((0, 0), (0.2, -6), (0.6, -6), (0.9, 0)),
            "root_y": _frames((0, 0), (0.2, -12), (0.5, 0), (0.9, 0)),
            "antenna_rotation": _frames((0, 0), (0.2, 22), (0.45, -16), (0.9, 0)),
        },
        priority=35,
    )

    animations["head_tilt"] = _animation(
        "head_tilt",
        1.2,
        {
            "head_rotation": _frames((0, 0), (0.35, 16), (0.8, 16), (1.2, 0)),
            "antenna_rotation": _frames((0, 0), (0.35, -12), (0.8, -12), (1.2, 0)),
        },
        priority=15,
    )

    animations["pick_up"] = _animation(
        "pick_up",
        1.55,
        {
            "right_arm_rotation": _frames(
                (0, 0), (0.35, -55), (0.8, -78), (1.2, -30), (1.55, 0)
            ),
            "body_rotation": _frames((0, 0), (0.4, 10), (1.15, 8), (1.55, 0)),
            "head_rotation": _frames((0, 0), (0.4, 18), (1.15, 14), (1.55, 0)),
            "root_y": _frames((0, 0), (0.4, 14), (1.15, 10), (1.55, 0)),
            "left_arm_rotation": _frames((0, 0), (0.6, -20), (1.2, -20), (1.55, 0)),
        },
        priority=40,
    )

    animations["point"] = _animation(
        "point",
        1.5,
        {
            "right_arm_rotation": _frames(
                (0, 0), (0.25, -105), (0.9, -95), (1.5, 0)
            ),
            "left_arm_rotation": _frames((0, 0), (0.3, 15), (1.2, 15), (1.5, 0)),
            "head_rotation": _frames((0, 0), (0.3, 10), (1.2, 10), (1.5, 0)),
            "body_rotation": _frames((0, 0), (0.3, -4), (1.2, -4), (1.5, 0)),
        },
        priority=40,
    )

    animations["water_plant"] = _animation(
        "water_plant",
        2.1,
        {
            "right_arm_rotation": _frames(
                (0, 0), (0.4, -95), (0.9, -70), (1.5, -80), (2.1, 0)
            ),
            "left_arm_rotation": _frames((0, 0), (0.4, -25), (1.5, -15), (2.1, 0)),
            "body_rotation": _frames((0, 0), (0.4, -5), (1.6, -5), (2.1, 0)),
            "head_rotation": _frames((0, 0), (0.4, 12), (1.5, 10), (2.1, 0)),
            "root_y": _frames((0, 0), (0.4, 6), (1.5, 4), (2.1, 0)),
        },
        priority=40,
    )

    animations["celebrate"] = _animation(
        "celebrate",
        2.0,
        {
            "left_arm_rotation": _frames(
                (0, 0), (0.3, 150), (0.6, 110), (0.9, 150), (1.5, 150), (2.0, 0)
            ),
            "right_arm_rotation": _frames(
                (0, 0), (0.3, -150), (0.6, -110), (0.9, -150), (1.5, -150), (2.0, 0)
            ),
            "root_y": _frames((0, 0), (0.25, -20), (0.5, 0), (0.75, -18), (1.0, 0), (2.0, 0)),
            "mouth_open": _frames((0, 0), (0.3, 0.55), (1.4, 0.55), (2.0, 0)),
            "head_rotation": _frames((0, 0), (0.4, -7), (1.0, 7), (2.0, 0)),
            "antenna_rotation": _frames((0, 0), (0.35, 18), (0.8, -14), (1.2, 12), (2.0, 0)),
        },
        priority=42,
    )

    return animations


ANIMATIONS: dict[str, Animation] = _build()


def animation_names() -> tuple[str, ...]:
    return tuple(sorted(ANIMATIONS))


def get_animation(name: str) -> Animation:
    try:
        return ANIMATIONS[name]
    except KeyError as exc:
        choices = ", ".join(animation_names())
        raise AnimationError(f"animation must be one of {choices}") from exc


def clip(name: str, at: float = 0.0, weight: float = 1.0, speed: float = 1.0) -> AnimationClip:
    return AnimationClip(get_animation(name), start=at, speed=speed, weight=weight)
