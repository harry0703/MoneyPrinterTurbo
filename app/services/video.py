

# Backward compatibility layer: re-export everything from modules
# This ensures existing imports like video.VideoFileClip still work

# First, load the exception/cleanup patches
from app.services.video_patches import *

# Re-export video utils (contains many video utility functions and get_bgm_file)
from app.services.video_utils import (
    get_video_codec,
    get_video_encoding_params,
    memory_safe_wait,
    memory_safe_operation,
    close_clip,
    delete_files,
    get_bgm_file,
    preprocess_video,
    match_local_videos_by_keywords,
    copy_local_materials_to_task,
    fit_intro_video_to_target,
    crop_clip_to_target,
    wrap_text,
    analyze_video_params,
    SubClippedVideoClip,
    audio_codec,
    fps,
    video_codec,
    video_encoding_params,
)

# Re-export moviepy components that were previously in this module
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    vfx,
    concatenate_videoclips,
)

# Re-export scene-related functions
from app.services.video_scene import (
    process_scene_videos,
    combine_scene_clips,
    combine_early_scenes,
    build_scene_video,
)

# Re-export video target functions
from app.services.video_target import (
    finalize_video,
    generate_video,
    process_final_video,
)

# Re-export video synthesis functions
from app.services.video_synthesis import (
    scan_task_files,
    recover_video_synthesis,
)

# Re-export video effects
from app.services.utils import video_effects

# Re-export LLM functions
from app.services.llm import add_english_translations

# Re-export other utilities
from app.utils import utils

# Re-export models and schema
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)

# Re-export config
from app.config import config
from app.config.config import load_config

# Re-export subtitle utilities
from app.services.subtitle import (
    file_to_subtitles,
    _srt_time_to_seconds,
    _seconds_to_srt_time,
    merge_scene_subtitles,
)
