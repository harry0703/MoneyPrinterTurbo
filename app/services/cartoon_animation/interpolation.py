"""Deterministic easing functions for keyframe interpolation."""

from __future__ import annotations

import math

from app.services.cartoon_animation.models import AnimationError


def linear(t: float) -> float:
    return t


def step(t: float) -> float:
    """Hold the previous value until the next keyframe."""
    return 0.0 if t < 1.0 else 1.0


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def smoothstep(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


EASINGS = {
    "linear": linear,
    "step": step,
    "ease-in": ease_in,
    "ease-out": ease_out,
    "ease-in-out": ease_in_out,
    "smoothstep": smoothstep,
}


def parse_easing(name: str) -> str:
    if name not in EASINGS:
        choices = ", ".join(sorted(EASINGS))
        raise AnimationError(f"easing must be one of {choices}")
    return name


def apply_easing(name: str, fraction: float) -> float:
    """Ease ``fraction`` with a named function, clamped to [0, 1]."""
    try:
        easing = EASINGS[name]
    except KeyError as exc:
        choices = ", ".join(sorted(EASINGS))
        raise AnimationError(f"easing must be one of {choices}") from exc
    if not math.isfinite(fraction):
        raise AnimationError("interpolation fraction must be finite")
    return easing(min(1.0, max(0.0, fraction)))
