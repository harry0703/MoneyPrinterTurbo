"""Facial expressions layered on top of an animation pose."""

from __future__ import annotations

from app.services.cartoon_animation.models import AnimationError, Pose

# Channel offsets applied on top of whatever the animation produced. Values are
# intentionally small: expressions are accents, not separate animations.
EXPRESSIONS: dict[str, dict[str, float]] = {
    "neutral": {},
    "happy": {
        "mouth_width": 0.3,
        "mouth_open": 0.25,
        "brow_raise": 0.35,
        "eye_open": -0.15,
        "blush": 0.5,
    },
    "surprised": {
        "eye_open": 0.35,
        "mouth_open": 0.55,
        "mouth_width": -0.1,
        "brow_raise": 0.8,
        "head_rotation": -4.0,
        "antenna_rotation": 12.0,
    },
    "curious": {
        "head_rotation": 9.0,
        "brow_raise": 0.4,
        "eye_open": 0.15,
        "pupil_x": 0.35,
        "mouth_width": -0.05,
    },
    "sad": {
        "brow_raise": -0.4,
        "brow_angle": -0.6,
        "mouth_width": -0.25,
        "head_rotation": 5.0,
        "eye_open": -0.2,
    },
    "determined": {
        "brow_angle": 0.7,
        "eye_open": -0.1,
        "mouth_width": -0.1,
        "body_rotation": -2.0,
    },
}


def expression_names() -> tuple[str, ...]:
    return tuple(sorted(EXPRESSIONS))


def apply_expression(pose: Pose, name: str, weight: float = 1.0) -> Pose:
    try:
        offsets = EXPRESSIONS[name]
    except KeyError as exc:
        choices = ", ".join(expression_names())
        raise AnimationError(f"expression must be one of {choices}") from exc
    if not 0.0 <= weight <= 1.0:
        raise AnimationError("expression weight must be between 0 and 1")
    if not offsets:
        return pose
    return pose.adjusted(offsets, weight)


def mouth_state(openness: float) -> str:
    """Map a 0..1 mouth opening to a stable named state."""
    if openness <= 0.08:
        return "closed"
    if openness <= 0.33:
        return "slightly_open"
    if openness <= 0.66:
        return "half_open"
    return "open"
