"""Scene timeline primitives.

Clips, priorities and blending live with the keyframe sampler in
:mod:`app.services.cartoon_animation.keyframes`; this module is the stable
import path for timeline consumers.
"""

from app.services.cartoon_animation.keyframes import (
    AnimationClip,
    merged_animation,
    sample_clips,
)

__all__ = ["AnimationClip", "merged_animation", "sample_clips"]
