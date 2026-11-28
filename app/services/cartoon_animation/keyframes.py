"""Keyframe sampling and animation mixing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.services.cartoon_animation.interpolation import apply_easing
from app.services.cartoon_animation.models import (
    Animation,
    AnimationError,
    CHANNELS,
    Pose,
    channel_default,
)


def _bracketing(frames, time: float):
    """Return the two keyframes surrounding ``time`` (or a single hold)."""
    if time <= frames[0].time:
        return frames[0], frames[0], 0.0
    if time >= frames[-1].time:
        return frames[-1], frames[-1], 0.0
    previous = frames[0]
    for frame in frames[1:]:
        if time <= frame.time:
            span = frame.time - previous.time
            fraction = 0.0 if span <= 0 else (time - previous.time) / span
            return previous, frame, fraction
        previous = frame
    return frames[-1], frames[-1], 0.0


def sample_track(frames, time: float) -> float:
    """Sample one keyframe track; the target keyframe selects the easing."""
    if not frames:
        raise AnimationError("cannot sample an empty keyframe track")
    previous, following, fraction = _bracketing(frames, time)
    if previous is following:
        return previous.value
    eased = apply_easing(following.easing, fraction)
    return previous.value + (following.value - previous.value) * eased


def local_time(animation: Animation, time: float) -> float | None:
    """Map scene time to animation-local time, honouring loops and duration."""
    if time < 0:
        return None
    if animation.loop:
        return time % animation.duration
    if time > animation.duration:
        return None
    return time


def sample_animation(animation: Animation, time: float) -> dict[str, float]:
    """Return the channel values an animation contributes at ``time``."""
    local = local_time(animation, time)
    if local is None:
        return {}
    return {
        channel: sample_track(frames, local)
        for channel, frames in animation.tracks.items()
    }


@dataclass(frozen=True)
class AnimationClip:
    """One animation placed on a scene timeline."""

    animation: Animation
    start: float = 0.0
    speed: float = 1.0
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.start < 0:
            raise AnimationError("animation clip start must not be negative")
        if self.speed <= 0:
            raise AnimationError("animation clip speed must be positive")
        if not 0.0 <= self.weight <= 1.0:
            raise AnimationError("animation clip weight must be between 0 and 1")

    def covers(self, time: float) -> bool:
        if time < self.start:
            return False
        elapsed = (time - self.start) * self.speed
        return self.animation.loop or elapsed <= self.animation.duration

    def sample(self, time: float) -> dict[str, float]:
        if not self.covers(time):
            return {}
        return sample_animation(self.animation, (time - self.start) * self.speed)


def sample_clips(clips: Iterable[AnimationClip], time: float) -> Pose:
    """Merge the active clips at ``time`` into a pose.

    Overrides blend towards the sampled value by clip weight; additive clips
    add their offset from the channel's neutral value. Higher priorities are
    applied later, so they win on conflicts.
    """
    contributions = [
        clip
        for clip in clips
        if clip.covers(time)
    ]
    contributions.sort(key=lambda clip: (clip.animation.priority, clip.start))
    values: dict[str, float] = {}
    for clip in contributions:
        sampled = clip.sample(time)
        for channel, value in sampled.items():
            if channel not in CHANNELS:
                raise AnimationError(f"unknown animation channel: {channel}")
            current = values.get(channel, channel_default(channel))
            if clip.animation.additive:
                values[channel] = current + (
                    value - channel_default(channel)
                ) * clip.weight
            else:
                values[channel] = current + (value - current) * clip.weight
    return Pose(values)


def merged_animation(name: str, animations: Iterable[Animation]) -> Animation:
    """Combine compatible animations into one by unioning their tracks.

    This is a convenience for tools and tests; the timeline mixer is the
    authoritative way to combine animations at render time.
    """
    items = list(animations)
    if not items:
        raise AnimationError("cannot merge an empty animation list")
    tracks: dict[str, tuple] = {}
    for animation in items:
        for channel, frames in animation.tracks.items():
            if channel in tracks:
                raise AnimationError(
                    f"animations conflict on channel {channel}; use the timeline mixer"
                )
            tracks[channel] = frames
    return Animation(
        name=name,
        duration=max(animation.duration for animation in items),
        tracks=tracks,
        loop=all(animation.loop for animation in items),
        priority=max(animation.priority for animation in items),
        additive=all(animation.additive for animation in items),
    )
