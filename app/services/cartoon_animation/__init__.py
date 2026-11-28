"""Procedural 2D animation engine for Cartoon Studio.

Public entry points::

    from app.services.cartoon_animation import (
        Character, Pose, RenderSettings, ScenePlan,
        get_character, get_animation, build_plan, render_scene_video,
    )

The engine is offline and CPU-only. It depends on Pillow for drawing, Pillow
plus FFmpeg for encoding, and on the existing FFmpeg helper for the binary
path. Narration and manifest handling stay in ``cartoon_studio``.
"""

from app.services.cartoon_animation.characters import (
    CHARACTER_PRESETS,
    TIKO_PALETTE,
    get_character,
    tiko,
)
from app.services.cartoon_animation.compositor import (
    Actor,
    Prop,
    ScenePlan,
    build_plan,
    iter_frames,
    render_frame,
    render_scene_video,
)
from app.services.cartoon_animation.expressions import (
    EXPRESSIONS,
    apply_expression,
    expression_names,
    mouth_state,
)
from app.services.cartoon_animation.interpolation import EASINGS, apply_easing
from app.services.cartoon_animation.keyframes import (
    AnimationClip,
    merged_animation,
    sample_animation,
    sample_clips,
    sample_track,
)
from app.services.cartoon_animation.models import (
    Animation,
    AnimationError,
    CHANNELS,
    Character,
    Keyframe,
    Part,
    Pose,
    RenderSettings,
    Shape,
)
from app.services.cartoon_animation.presets import (
    ANIMATIONS,
    animation_names,
    clip,
    get_animation,
)
from app.services.cartoon_animation.renderer import (
    encode_frames,
    render_character,
    render_still,
)
from app.services.cartoon_animation.validation import (
    ProjectAnimation,
    SceneAnimation,
    parse_animation,
    parse_project_animation,
    parse_scene_animation,
)

__all__ = [
    "Actor",
    "ANIMATIONS",
    "Animation",
    "AnimationClip",
    "AnimationError",
    "CHANNELS",
    "CHARACTER_PRESETS",
    "Character",
    "EASINGS",
    "EXPRESSIONS",
    "Keyframe",
    "Part",
    "Pose",
    "ProjectAnimation",
    "Prop",
    "RenderSettings",
    "SceneAnimation",
    "ScenePlan",
    "Shape",
    "TIKO_PALETTE",
    "animation_names",
    "apply_easing",
    "apply_expression",
    "build_plan",
    "clip",
    "encode_frames",
    "expression_names",
    "get_animation",
    "get_character",
    "iter_frames",
    "merged_animation",
    "mouth_state",
    "parse_animation",
    "parse_project_animation",
    "parse_scene_animation",
    "render_character",
    "render_frame",
    "render_scene_video",
    "render_still",
    "sample_animation",
    "sample_clips",
    "sample_track",
    "tiko",
]
