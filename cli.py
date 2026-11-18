from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import sys
from typing import TYPE_CHECKING, Any, Sequence
from uuid import UUID, uuid4

from loguru import logger

if TYPE_CHECKING:
    from app.models.schema import MaterialInfo, VideoParams


DEFAULT_VOICE_NAME = "zh-CN-XiaoxiaoNeural-Female"
# Corresponds to VOICE_MODE_NONE and VOICE_MODE_UPLOAD in webui/Main.py. The two sides don't currently
# share these constants, so the literal values are kept here with their source noted.
UI_VOICE_MODE_NONE = "none"
# Built-in default for subtitle position. VideoParams has a same-named default, but it's a Pydantic field
# default that reads config.ui only once at module import: an invalid value in config.toml at that point would be
# frozen into the model directly, neither validated nor replaceable in tests. So the CLI keeps its own copy,
# guaranteeing that "invalid saved values fall back to the default" always holds on the command line.
DEFAULT_SUBTITLE_POSITION = "bottom"
DEFAULT_CUSTOM_POSITION = 70.0
UI_VOICE_MODE_UPLOAD = "upload"
# Both of these saved voice-over modes mean no automatic voice-over.
UI_VOICE_MODES_WITHOUT_TTS = frozenset({UI_VOICE_MODE_NONE, UI_VOICE_MODE_UPLOAD})
_PIPELINE_STAGES = ("script", "terms", "audio", "subtitle", "materials", "video")
_CUSTOM_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_BATCH_FILE_MAX_BYTES = 1024 * 1024
_BATCH_TASK_MAX_COUNT = 100
# Single-task argparse and the batch manifest must share the same set of sources. They used to be maintained by hand in two places, so
# openai_image was only available in the single-task entry; with one definition, new Providers won't be missed again in
# batch validation. Only sources the CLI publicly supports are included here; WebUI-only flows aren't forced in.
_CLI_VIDEO_SOURCES = (
    "pexels",
    "pixabay",
    "coverr",
    "wavespeed",
    "volcengine_seedance",
    "ofox",
    "infistar",
    "jalapeno",
    "metaso_minimax",
    "muapi",
    "useapi",
    "openai_image",
    "codex_image",
    "useapi_image",
    "local",
)


class _CliHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """Show meaningful defaults automatically while keeping multi-line example formatting."""

    def _get_help_string(self, action):
        help_text = action.help or ""
        if (
            "%(default)" not in help_text
            and action.default not in (None, "", argparse.SUPPRESS)
            and action.option_strings
            and "default:" not in help_text.lower()
        ):
            help_text += " (default: %(default)s)"
        return help_text


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"value must be >= 1, got {parsed}")
    return parsed


def _paragraph_count(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 10:
        raise argparse.ArgumentTypeError(
            f"paragraph-number must be between 1 and 10, got {parsed}"
        )
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(f"value must be a finite number >= 0, got {value!r}")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"value must be a finite number > 0, got {value!r}")
    return parsed


# Value range for clip playback speed. normalize_clip_speed() in app/utils/utils.py clamps with the same
# range, and the slider in webui/Main.py also uses 0.5~2.0. With one definition, single-task arguments,
# batch manifest validation and [ui] saved values won't diverge again.
_CLIP_SPEED_MIN = 0.5
_CLIP_SPEED_MAX = 2.0


def _clip_speed(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not _CLIP_SPEED_MIN <= parsed <= _CLIP_SPEED_MAX:
        raise argparse.ArgumentTypeError(
            "video-clip-speed must be a finite number between "
            f"{_CLIP_SPEED_MIN} and {_CLIP_SPEED_MAX}, got {value!r}"
        )
    return parsed


def _percent_position(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or parsed > 100:
        raise argparse.ArgumentTypeError(
            f"custom-position must be a finite number between 0 and 100, got {value!r}"
        )
    return parsed


def _hex_color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError(
            f"color must use #RRGGBB format, got {value!r}"
        )
    return value


def _subtitle_position(value: str) -> str:
    """Validate the saved subtitle position, with the same value range as the command-line argument."""
    if value not in _SUBTITLE_POSITION_VALUES:
        raise argparse.ArgumentTypeError(
            "subtitle-position must be one of: "
            f"{', '.join(_SUBTITLE_POSITION_VALUES)}, got {value!r}"
        )
    return value


def _subtitle_display_mode(value: str) -> str:
    """Validate the saved subtitle display mode, with the same value range as the command-line argument."""
    if value not in _SUBTITLE_DISPLAY_MODE_VALUES:
        raise argparse.ArgumentTypeError(
            "subtitle-display-mode must be one of: "
            f"{', '.join(_SUBTITLE_DISPLAY_MODE_VALUES)}, got {value!r}"
        )
    return value


def _subtitle_animation(value: str) -> str:
    """Validate the saved subtitle animation, with the same value range as the command-line argument."""
    if value not in _SUBTITLE_ANIMATION_VALUES:
        raise argparse.ArgumentTypeError(
            "subtitle-animation must be one of: "
            f"{', '.join(_SUBTITLE_ANIMATION_VALUES)}, got {value!r}"
        )
    return value


def _task_id(value: str) -> str:
    """The CLI custom task identifier only accepts UUIDs, so the value can't be interpreted as a file system path."""
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"task-id must be a valid UUID, got {value!r}"
        ) from exc


_TRANSITION_MODE_VALUES = {
    "none": None,
    "shuffle": "Shuffle",
    "fade-in": "FadeIn",
    "fade-out": "FadeOut",
    "slide-in": "SlideIn",
    "slide-out": "SlideOut",
    "zoom-in": "ZoomIn",
    "zoom-out": "ZoomOut",
}

# Single-task argparse and the batch manifest must share the same subtitle position values, so the gap of
# "the WebUI can save it but the CLI rejects it" doesn't happen again. Values must match the render branches in app/services/video.py
# and the dropdown in webui/Main.py.
_SUBTITLE_POSITION_VALUES = (
    "top",
    "center",
    "bottom",
    "two_thirds_bottom",
    "custom",
)

# The subtitle display mode and entrance animation are saved into [ui] by the WebUI. When "word-level subtitles + bounce animation"
# were added, only the WebUI and model field defaults changed, and the command line never got switches. Values must match
# _SUBTITLE_DISPLAY_MODES / _SUBTITLE_ANIMATIONS in app/models/schema.py.
_SUBTITLE_DISPLAY_MODE_VALUES = ("sentence", "word_by_word")
_SUBTITLE_ANIMATION_VALUES = ("none", "pop_spring")


def _transition_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized not in _TRANSITION_MODE_VALUES:
        allowed = ", ".join(_TRANSITION_MODE_VALUES)
        raise argparse.ArgumentTypeError(
            f"video-transition-mode must be one of: {allowed}"
        )
    return _TRANSITION_MODE_VALUES[normalized]


def _video_fit_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"cover", "contain"}:
        raise argparse.ArgumentTypeError(
            "video-fit-mode must be one of: cover, contain"
        )
    return normalized


def _image_motion(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"static", "zoom"}:
        raise argparse.ArgumentTypeError("image-motion must be one of: static, zoom")
    return normalized


# Only these values request an external music generation service, so only they consume the music prompt. Values must match
# _VIDEO_MUSIC_PROVIDERS in app/services/task.py; with one definition, new
# music providers won't be missed again in --bgm-type validation, batch validation and prompt arguments.
_CLI_MUSIC_BGM_TYPES = ("sonilo", "elevenlabs")
_BGM_TYPE_CHOICES_TEXT = "none, random, custom, " + ", ".join(_CLI_MUSIC_BGM_TYPES)
_BGM_TYPE_METAVAR = "{none,random,custom," + ",".join(_CLI_MUSIC_BGM_TYPES) + "}"


def _bgm_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "none":
        return ""
    if normalized in {"", "random", "custom", *_CLI_MUSIC_BGM_TYPES}:
        return normalized
    raise argparse.ArgumentTypeError(
        f"bgm-type must be one of: {_BGM_TYPE_CHOICES_TEXT}"
    )


def _useapi_image_needs_confirmation() -> bool:
    """Kling image models spend Kling credits; Nano Banana models do not."""
    from app.services import useapi

    return useapi.image_requires_confirmation()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    command = "mpt cli" if __name__ == "app.cli" else "uv run python cli.py"
    parser = argparse.ArgumentParser(
        prog="mpt cli" if __name__ == "app.cli" else None,
        description=(
            "Generate MoneyPrinterTurbo videos without the WebUI.\n\n"
            "Provider settings and credentials are read from config.toml.\n"
            "Default full-video generation requires a configured LLM and Pexels API key.\n"
            "The default Edge TTS voice requires no API key."
        ),
        epilog="""
Examples:
  Generate a complete video with the default Edge TTS voice:
    uv run python cli.py --video-subject "How AI is changing everyday life"

  Generate from local files. Relative paths use the current working directory;
  absolute paths are also accepted:
    uv run python cli.py --video-subject "How AI is changing everyday life" \\
      --video-source local --video-materials "./1.mp4,./2.mp4"

  Generate with a prepared script and no voiceover:
    uv run python cli.py --video-script "Your complete script" \\
      --voice-name no-voice --stop-at video

  Stop after script generation:
    uv run python cli.py --video-subject "How AI is changing everyday life" --stop-at script

  Run a JSON array or JSONL manifest. CLI options provide defaults and each object
  overrides VideoParams fields for one task:
    uv run python cli.py --batch-file ./tasks.jsonl --stop-at script

Pipeline stages:
  script     Generate or return the script.
  terms      Generate material search terms; unavailable with local materials.
  audio      Generate TTS, silent audio, or use --custom-audio-file.
  subtitle   Generate subtitles when enabled.
  materials  Download online materials or preprocess local files.
  video      Generate the final video and run configured cross-posting.
  The command stops immediately after the selected stage and prints that stage's result.

Output and exit status:
  Task files are written to storage/tasks/<task-id>/. A successful command prints one
  JSON object to stdout and exits with 0. Batch mode prints one JSON summary after all
  tasks finish. Task failures exit with 1; argument or manifest errors exit with 2
  before any batch task starts. Runtime logs are written to stderr.

Batch manifests:
  --batch-file accepts a UTF-8 JSON array or JSONL file with one object per non-empty
  line (up to 100 tasks and 1 MiB). Objects may override VideoParams fields; unknown
  fields are rejected. Every merged task needs video_subject or video_script.
  The manifest path is relative to the current working directory. Relative
  custom_audio_file and local video_materials[].url values declared in a manifest are
  relative to the manifest directory. Relative paths supplied by CLI options remain
  relative to the current working directory. bgm_file and font_name keep their managed
  storage/resource lookup rules. --stop-at is a batch-wide CLI option. The summary has
  total, succeeded, failed, and tasks keys; every task entry has index, task_id,
  status, result, failed_stage, and error.
""".replace("uv run python cli.py", command),
        formatter_class=_CliHelpFormatter,
    )

    content_group = parser.add_argument_group("script and content")
    content_group.add_argument(
        "--video-subject",
        default="",
        help="video topic; required unless --video-script is provided",
    )
    content_group.add_argument(
        "--video-script",
        default="",
        help="complete script; skips LLM script generation when provided",
    )
    content_group.add_argument(
        "--video-terms",
        default=None,
        help="comma-separated material search terms; generated automatically when omitted",
    )
    content_group.add_argument(
        "--video-language",
        default=None,
        help=(
            "script language code, such as zh-CN or en-US (default: auto-detect)"
        ),
    )
    content_group.add_argument(
        "--paragraph-number",
        type=_paragraph_count,
        default=None,
        help="number of generated script paragraphs, from 1 to 10 (default: 1)",
    )
    content_group.add_argument(
        "--video-script-prompt",
        default=None,
        help="additional requirements for LLM script generation",
    )
    content_group.add_argument(
        "--custom-system-prompt",
        default=None,
        help="replace the default LLM system prompt for script generation",
    )

    material_group = parser.add_argument_group("materials and pipeline")
    material_group.add_argument(
        "--video-source",
        default="pexels",
        choices=_CLI_VIDEO_SOURCES,
        help="video material provider; online providers require matching API keys in config.toml",
    )
    material_group.add_argument(
        "--video-materials",
        default="",
        metavar="PATH[,PATH...]",
        help=(
            "comma-separated local image/video paths for --video-source local; relative "
            "paths use the current working directory, then storage/local_videos as a "
            "compatibility fallback; absolute paths are accepted"
        ),
    )
    material_group.add_argument(
        "--stop-at",
        default="video",
        choices=_PIPELINE_STAGES,
        help="stop after this pipeline stage; see the stage order below",
    )
    material_group.add_argument(
        "--confirm-wavespeed-charge",
        action="store_true",
        help=(
            "confirm that WaveSpeed video generation creates paid tasks; required "
            "with --video-source wavespeed for materials or video output"
        ),
    )
    material_group.add_argument(
        "--confirm-seedance-charge",
        action="store_true",
        help=(
            "confirm that Volcano Engine Seedance creates paid Ark tasks; required "
            "with --video-source volcengine_seedance for materials or video output"
        ),
    )
    material_group.add_argument(
        "--confirm-jalapeno-charge", action="store_true",
        help="confirm paid Jalapeno Cloud video generation for materials or video output",
    )
    material_group.add_argument(
        "--confirm-infistar-charge", action="store_true",
        help="confirm paid Infistar video generation for materials or video output",
    )
    material_group.add_argument(
        "--confirm-ofox-charge",
        action="store_true",
        help=(
            "confirm that OFox video generation creates paid tasks; required "
            "with --video-source ofox for materials or video output"
        ),
    )
    material_group.add_argument(
        "--confirm-metaso-minimax-charge",
        action="store_true",
        help=(
            "confirm that Metaso MiniMax H3 creates paid video tasks; required "
            "with --video-source metaso_minimax for materials or video output"
        ),
    )
    material_group.add_argument(
        "--confirm-muapi-charge",
        action="store_true",
        help=(
            "confirm that MuAPI video generation creates paid tasks; required "
            "with --video-source muapi for materials or video output"
        ),
    )
    material_group.add_argument(
        "--confirm-useapi-charge",
        action="store_true",
        help=(
            "confirm that useapi.net videos and Kling images spend credits on "
            "your own Google AI plan, Kling AI account or Dreamina account; "
            "required with --video-source useapi, and with useapi_image when "
            "useapi_image_model is a Kling model, for materials or video output"
        ),
    )

    video_group = parser.add_argument_group("video output")
    video_group.add_argument(
        "--video-count",
        type=_positive_int,
        default=1,
        help="number of output videos, at least 1",
    )
    video_group.add_argument(
        "--video-aspect",
        choices=["9:16", "16:9", "1:1"],
        default="9:16",
        help="output aspect ratio: portrait, landscape, or square",
    )
    video_group.add_argument(
        "--video-fit-mode",
        type=_video_fit_mode,
        choices=["cover", "contain"],
        default=None,
        help=(
            "fit mismatched source clips by filling and center-cropping (cover) "
            "or preserving the full frame with black bars (contain); default: cover"
        ),
    )
    video_group.add_argument(
        "--video-concat-mode",
        choices=["random", "sequential"],
        default=None,
        help="source clip concatenation order (default: random)",
    )
    video_group.add_argument(
        "--image-motion",
        type=_image_motion,
        choices=["static", "zoom"],
        default=None,
        help="motion for local or AI-generated images (default: zoom)",
    )
    video_group.add_argument(
        "--video-transition-mode",
        type=_transition_mode,
        default=None,
        metavar="{none,shuffle,fade-in,fade-out,slide-in,slide-out,zoom-in,zoom-out}",
        help="transition applied between source clips (default: none)",
    )
    video_group.add_argument(
        "--video-clip-duration",
        type=_positive_int,
        default=None,
        help=(
            "maximum duration of each source clip in seconds, at least 1 (default: 5)"
        ),
    )
    video_group.add_argument(
        "--video-clip-speed",
        type=_clip_speed,
        default=None,
        help=(
            "playback speed multiplier applied to every source clip, between "
            "0.5 and 2.0 (default: 1.0)"
        ),
    )
    video_group.add_argument(
        "--match-materials-to-script",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "preserve script keyword order while selecting and concatenating materials "
            "(default: disabled)"
        ),
    )
    video_group.add_argument(
        "--n-threads",
        type=_positive_int,
        default=None,
        help="FFmpeg worker thread count, at least 1 (default: 2)",
    )

    audio_group = parser.add_argument_group("voiceover and background music")
    audio_group.add_argument(
        "--voice-name",
        default=None,
        help=(
            f"TTS voice identifier. Defaults to [ui].voice_name from "
            f"config.toml, otherwise {DEFAULT_VOICE_NAME}. A saved "
            "[ui].voice_mode of 'none' or 'upload' resolves to no-voice "
            "instead, unless this option is given. "
            "Use 'no-voice' for silent output. Provider-specific identifiers "
            "use prefixes such as gemini:, mimo:, elevenlabs:, chatterbox:, "
            "kokoro:, and voxcpm:"
        ),
    )
    audio_group.add_argument(
        "--voice-volume",
        type=_non_negative_float,
        default=None,
        help=(
            "final voiceover volume multiplier, a finite number >= 0 (default: "
            "[ui].voice_volume from config.toml; 1.0 when unset)"
        ),
    )
    audio_group.add_argument(
        "--voice-rate",
        type=_positive_float,
        default=None,
        help=(
            "speech rate multiplier, a finite number > 0 (default: "
            "[ui].voice_rate from config.toml; 1.0 when unset)"
        ),
    )
    audio_group.add_argument(
        "--custom-audio-file",
        default=None,
        metavar="PATH",
        help=(
            "existing MP3/WAV/M4A/AAC/FLAC/OGG voiceover; relative paths use the "
            "current working directory. This skips TTS; set subtitle_provider=whisper "
            "to transcribe it"
        ),
    )
    audio_group.add_argument(
        "--bgm-type",
        type=_bgm_type,
        default=None,
        metavar=_BGM_TYPE_METAVAR,
        help=(
            "background music mode; Sonilo reads its API key from config.toml or "
            "SONILO_API_KEY, ElevenLabs from config.toml or ELEVENLABS_API_KEY; "
            "--bgm-file implies custom when omitted (default: random)"
        ),
    )
    audio_group.add_argument(
        "--sonilo-bgm-prompt",
        default=None,
        help="optional music style prompt for Sonilo, up to 2000 characters",
    )
    audio_group.add_argument(
        "--video-music-prompt",
        default=None,
        help=(
            "optional music style prompt for the selected AI background music "
            "provider (sonilo or elevenlabs); the provider's own length limit "
            "is enforced before generation"
        ),
    )
    audio_group.add_argument(
        "--bgm-file",
        default=None,
        metavar="PATH",
        help=(
            "custom supported audio file inside storage/bgm or resource/songs; "
            "accepts a filename or an allowed managed path"
        ),
    )
    audio_group.add_argument(
        "--bgm-volume",
        type=_non_negative_float,
        default=None,
        help=(
            "background music volume multiplier, a finite number >= 0 (default: 0.2)"
        ),
    )

    subtitle_group = parser.add_argument_group("subtitles")
    subtitle_group.add_argument(
        "--subtitle-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "enable subtitles; use --no-subtitle-enabled to disable "
            "(default: [ui].subtitle_enabled from config.toml; enabled when "
            "unset)"
        ),
    )
    subtitle_group.add_argument(
        "--font-name",
        default=None,
        help=(
            "subtitle font filename inside resource/fonts "
            "(default: [ui].font_name from config.toml; "
            "STHeitiMedium.ttc when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-position",
        choices=_SUBTITLE_POSITION_VALUES,
        default=None,
        help=(
            "subtitle vertical position (default: [ui].subtitle_position from "
            "config.toml; bottom when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-display-mode",
        choices=_SUBTITLE_DISPLAY_MODE_VALUES,
        default=None,
        help=(
            "subtitle timing: sentence by sentence, or one word at a time "
            "(default: [ui].subtitle_display_mode from config.toml; sentence)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-animation",
        choices=_SUBTITLE_ANIMATION_VALUES,
        default=None,
        help=(
            "subtitle entrance animation (default: [ui].subtitle_animation from "
            "config.toml; none when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--custom-position",
        type=_percent_position,
        default=None,
        help=(
            "custom position as percent from top, 0-100; requires "
            "--subtitle-position custom (default: [ui].custom_position from "
            "config.toml; 70 when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--text-fore-color",
        type=_hex_color,
        default=None,
        help=(
            "subtitle text color in #RRGGBB format; quote the value in shells "
            "that treat # as a comment (default: [ui].text_fore_color from "
            "config.toml; #FFFFFF when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--font-size",
        type=_positive_int,
        default=None,
        help=(
            "subtitle font size (default: [ui].font_size from config.toml; "
            "60 when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--stroke-color",
        type=_hex_color,
        default=None,
        help=(
            "subtitle outline color in #RRGGBB format (default: "
            "[ui].stroke_color from config.toml; #000000 when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--stroke-width",
        type=_non_negative_float,
        default=None,
        help=(
            "subtitle outline width, a finite number >= 0 (default: "
            "[ui].stroke_width from config.toml; 1.5 when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-background-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "enable subtitle background; use --no-subtitle-background-enabled to "
            "disable (default: [ui].subtitle_background_enabled from "
            "config.toml; disabled when unset)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-background-color",
        type=_hex_color,
        default=None,
        help=(
            "subtitle background color in #RRGGBB format (default: "
            "[ui].subtitle_background_color from config.toml)"
        ),
    )
    subtitle_group.add_argument(
        "--rounded-subtitle-background",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "use a rounded subtitle background (default: "
            "[ui].rounded_subtitle_background from config.toml; "
            "disabled when unset)"
        ),
    )

    execution_group = parser.add_argument_group("execution")
    execution_mode = execution_group.add_mutually_exclusive_group()
    execution_mode.add_argument(
        "--task-id",
        type=_task_id,
        default=None,
        help="custom UUID used for storage/tasks/<task-id>; generated automatically when omitted",
    )
    execution_mode.add_argument(
        "--batch-file",
        default=None,
        metavar="PATH",
        help=(
            "UTF-8 JSON array or JSONL task manifest; conflicts with --task-id and "
            "generates a UUID for every task"
        ),
    )
    args = parser.parse_args(argv)

    if (
        not args.batch_file
        and not args.video_subject.strip()
        and not args.video_script.strip()
    ):
        parser.error("one of --video-subject or --video-script is required")

    if not args.batch_file and args.video_source == "local" and args.stop_at == "terms":
        parser.error(
            "--stop-at terms has no effect with --video-source local "
            "(search terms are not generated for local sources)"
        )

    stage_requires_materials = args.stop_at in {"materials", "video"}
    has_video_materials = bool((args.video_materials or "").strip())
    if (
        not args.batch_file
        and args.video_source == "local"
        and stage_requires_materials
        and not has_video_materials
    ):
        parser.error(
            "--video-materials is required with --video-source local when "
            "--stop-at is materials or video"
        )
    if not args.batch_file and args.video_source != "local" and has_video_materials:
        parser.error("--video-materials can only be used with --video-source local")
    if (
        not args.batch_file
        and args.video_source == "wavespeed"
        and stage_requires_materials
        and not args.confirm_wavespeed_charge
    ):
        parser.error(
            "--confirm-wavespeed-charge is required with "
            "--video-source wavespeed"
        )
    if (
        not args.batch_file
        and args.video_source == "volcengine_seedance"
        and stage_requires_materials
        and not args.confirm_seedance_charge
    ):
        parser.error(
            "--confirm-seedance-charge is required with "
            "--video-source volcengine_seedance"
        )
    if (
        not args.batch_file
        and args.video_source == "ofox"
        and stage_requires_materials
        and not args.confirm_ofox_charge
    ):
        parser.error(
            "--confirm-ofox-charge is required with --video-source ofox"
        )
    if (
        not args.batch_file
        and args.video_source == "metaso_minimax"
        and stage_requires_materials
        and not args.confirm_metaso_minimax_charge
    ):
        parser.error(
            "--confirm-metaso-minimax-charge is required with "
            "--video-source metaso_minimax"
        )
    if (
        not args.batch_file
        and args.video_source == "muapi"
        and stage_requires_materials
        and not args.confirm_muapi_charge
    ):
        parser.error(
            "--confirm-muapi-charge is required with --video-source muapi"
        )
    if (
        not args.batch_file
        and args.video_source == "useapi"
        and stage_requires_materials
        and not args.confirm_useapi_charge
    ):
        parser.error(
            "--confirm-useapi-charge is required with --video-source useapi"
        )
    if (
        not args.batch_file
        and args.video_source == "useapi_image"
        and stage_requires_materials
        and not args.confirm_useapi_charge
        and _useapi_image_needs_confirmation()
    ):
        parser.error(
            "--confirm-useapi-charge is required with --video-source "
            "useapi_image when useapi_image_model is a Kling model"
        )

    if (not args.batch_file and args.video_source == "infistar"
            and stage_requires_materials and not args.confirm_infistar_charge):
        parser.error("--confirm-infistar-charge is required with --video-source infistar")
    if (not args.batch_file and args.video_source == "jalapeno"
            and stage_requires_materials and not args.confirm_jalapeno_charge):
        parser.error("--confirm-jalapeno-charge is required with --video-source jalapeno")

    if args.bgm_file:
        if args.bgm_type in (None, "custom"):
            args.bgm_type = "custom"
        elif not args.batch_file:
            parser.error("--bgm-file can only be combined with --bgm-type custom")

    if args.sonilo_bgm_prompt:
        if args.bgm_type in (None, "sonilo"):
            args.bgm_type = "sonilo"
        elif not args.batch_file:
            parser.error(
                "--sonilo-bgm-prompt can only be combined with --bgm-type sonilo"
            )

    # The prompt field itself is provider-agnostic, so bgm_type isn't inferred as with the Sonilo-specific arguments:
    # the inferred provider might not be the one the user wants. An AI music provider must be chosen explicitly,
    # otherwise the prompt would be silently dropped. Batch manifests can still set this field per task.
    if (
        not args.batch_file
        and args.video_music_prompt
        and args.bgm_type not in _CLI_MUSIC_BGM_TYPES
    ):
        parser.error(
            "--video-music-prompt requires --bgm-type sonilo or elevenlabs"
        )

    if (
        not args.batch_file
        and args.custom_position is not None
        and args.subtitle_position != "custom"
    ):
        parser.error("--custom-position requires --subtitle-position custom")
    # Only an explicit --no-subtitle-enabled counts as a conflict. The default is now None, and
    # a saved off state is handled in build_video_params, so it shouldn't raise an argument error here.
    if (
        not args.batch_file
        and args.stop_at == "subtitle"
        and args.subtitle_enabled is False
    ):
        parser.error("--stop-at subtitle cannot be combined with --no-subtitle-enabled")
    if not args.batch_file and args.subtitle_background_enabled is False and (
        args.subtitle_background_color is not None
        or args.rounded_subtitle_background is True
    ):
        parser.error(
            "subtitle background color or rounding cannot be enabled together with "
            "--no-subtitle-background-enabled"
        )

    return args


def _ui_config_value(ui_config, key: str, expected_type, checker=None):
    """
    Read WebUI settings saved in ``[ui]``, returning ``None`` when no usable value is available.

    This config section may also be hand-edited, so unusable entries are dropped here, letting the caller fall back to
    built-in defaults, instead of passing dirty data along and triggering a traceback or ``VideoParams``
    validation errors.

    ``checker`` reuses the same type functions used by the command line (such as ``_hex_color``), so saved
    values and command-line arguments follow exactly the same value rules, e.g. volume can't be negative and colors must be
    ``#RRGGBB``.
    """
    value = ui_config.get(key)
    if value is None:
        return None
    # ``isinstance(True, int)`` is true, so bool must be excluded explicitly when expecting a number.
    if isinstance(value, bool) != (expected_type is bool):
        return None
    # ``1`` in TOML is an integer, but it's also a valid value for fields like volume and speech rate.
    if expected_type is float and isinstance(value, int):
        value = float(value)
    if not isinstance(value, expected_type):
        return None
    if expected_type is str and not value.strip():
        return None
    if checker is not None:
        try:
            return checker(str(value))
        except argparse.ArgumentTypeError:
            return None
    return value


def _resolve_subtitle_enabled(args: argparse.Namespace, ui_config) -> bool:
    """
    Resolve the subtitle switch by priority: command line > WebUI saved value > enabled by default.

    ``--stop-at subtitle`` explicitly asks for subtitles, so a saved off state must not turn that stage
    into a no-op; the combination of an explicit --no-subtitle-enabled with that stage is already rejected in argument validation,
    so only the saved value needs handling here.
    """
    if args.subtitle_enabled is not None:
        return args.subtitle_enabled
    if args.stop_at == "subtitle":
        return True
    saved = _ui_config_value(ui_config, "subtitle_enabled", bool)
    return True if saved is None else saved


def _resolve_voice_name(args: argparse.Namespace, ui_config) -> str:
    """
    Resolve the voice by priority: command line > WebUI saved voice-over mode and voice > built-in default.

    The WebUI saves "no voice-over" as a separate voice_mode while keeping the voice the user last really chose,
    so it can be restored after switching back to auto voice-over. So voice_name alone can't be read here, otherwise the saved
    no-voice-over state would be ignored and might trigger paid provider requests again.
    """
    from app.services.voice import NO_VOICE_NAME

    if args.voice_name:
        return args.voice_name
    # Both no voice-over and uploading your own audio mean the user doesn't want automatic voice-over. The upload mode's file path isn't
    # written to [ui], so the CLI can't reproduce that upload; reusing the saved voice then would silently trigger paid TTS
    # requests, so both modes map to no-voice, and --voice-name must be passed explicitly when voice-over is wanted.
    if _ui_config_value(ui_config, "voice_mode", str) in UI_VOICE_MODES_WITHOUT_TTS:
        return NO_VOICE_NAME
    return _ui_config_value(ui_config, "voice_name", str) or DEFAULT_VOICE_NAME


def build_video_params(args: argparse.Namespace) -> VideoParams:
    # Argument help and validation don't need app config loaded. The model is imported only when actually building task parameters,
    # so running ``cli.py -h`` doesn't produce config initialization logs.
    from app.config import config
    from app.models.schema import MaterialInfo, VideoParams

    ui_config = config.ui

    video_terms = args.video_terms
    if video_terms:
        video_terms = [
            term.strip() for term in re.split(r"[,，]", video_terms) if term.strip()
        ]

    video_materials = None
    materials_arg = args.video_materials or ""
    if materials_arg.strip():
        video_materials = [
            # Actual duration will be detected during video processing; use 0 as placeholder.
            MaterialInfo(provider="local", url=item.strip(), duration=0)
            for item in materials_arg.split(",")
            if item.strip()
        ]

    params_kwargs = {
        "video_subject": args.video_subject.strip(),
        "video_script": args.video_script,
        "video_terms": video_terms,
        "video_source": args.video_source,
        "video_materials": video_materials,
        "video_count": args.video_count,
        "video_aspect": args.video_aspect,
        "voice_name": _resolve_voice_name(args, ui_config),
        "subtitle_enabled": _resolve_subtitle_enabled(args, ui_config),
    }

    optional_arg_names = [
        "video_language",
        "paragraph_number",
        "video_script_prompt",
        "custom_system_prompt",
        "video_fit_mode",
        "image_motion",
        "video_concat_mode",
        "video_transition_mode",
        "video_clip_duration",
        "video_clip_speed",
        "match_materials_to_script",
        "n_threads",
        "voice_volume",
        "voice_rate",
        "custom_audio_file",
        "bgm_type",
        "bgm_file",
        "bgm_volume",
        "sonilo_bgm_prompt",
        "video_music_prompt",
        "font_name",
        "subtitle_position",
        "subtitle_display_mode",
        "subtitle_animation",
        "custom_position",
        "text_fore_color",
        "font_size",
        "stroke_color",
        "stroke_width",
        "rounded_subtitle_background",
    ]
    for name in optional_arg_names:
        value = getattr(args, name)
        if value is not None:
            params_kwargs[name] = value

    # When no command-line argument is passed explicitly, use the values saved by the WebUI. Only fill in fields not yet
    # set by the command line above; if the saved value is missing, keep using the VideoParams default.
    # Most savable fields in VideoParams (subtitle_position, custom_position, etc.) read config.ui
    # at model import, but video_clip_speed is hardcoded to 1.0, so it must be
    # filled in explicitly here, otherwise the speed saved by the WebUI would be silently dropped on the command line.
    ui_defaults = (
        ("video_clip_speed", float, _clip_speed),
        ("video_fit_mode", str, _video_fit_mode),
        ("image_motion", str, _image_motion),
        ("font_name", str, None),
        ("subtitle_display_mode", str, _subtitle_display_mode),
        ("subtitle_animation", str, _subtitle_animation),
        ("text_fore_color", str, _hex_color),
        ("font_size", int, _positive_int),
        ("rounded_subtitle_background", bool, None),
        ("voice_volume", float, _non_negative_float),
        ("voice_rate", float, _positive_float),
        ("stroke_color", str, _hex_color),
        ("stroke_width", float, _non_negative_float),
    )
    for name, expected_type, checker in ui_defaults:
        if name in params_kwargs:
            continue
        value = _ui_config_value(ui_config, name, expected_type, checker)
        if value is not None:
            params_kwargs[name] = value

    # The subtitle position must be given a definite value by the CLI, not left to the import-time field default described above.
    if "subtitle_position" not in params_kwargs:
        params_kwargs["subtitle_position"] = (
            _ui_config_value(ui_config, "subtitle_position", str, _subtitle_position)
            or DEFAULT_SUBTITLE_POSITION
        )
    if "custom_position" not in params_kwargs:
        saved_custom_position = _ui_config_value(
            ui_config, "custom_position", float, _percent_position
        )
        params_kwargs["custom_position"] = (
            DEFAULT_CUSTOM_POSITION
            if saved_custom_position is None
            else saved_custom_position
        )

    if args.subtitle_background_enabled is False:
        params_kwargs["text_background_color"] = False
        params_kwargs["rounded_subtitle_background"] = False
    elif args.subtitle_background_color is not None:
        params_kwargs["text_background_color"] = args.subtitle_background_color
    elif args.subtitle_background_enabled is True:
        # The user only enabled the background without overriding the color, so prefer the color saved by the WebUI,
        # falling back to the default background only when no usable saved value exists.
        params_kwargs["text_background_color"] = (
            _ui_config_value(
                ui_config, "subtitle_background_color", str, _hex_color
            )
            or True
        )
    else:
        # "Background off" plus a color as a command-line combination is an argument error; but as a saved setting,
        # the same combination shouldn't stop the run and simply means the background is disabled.
        ui_enabled = _ui_config_value(
            ui_config, "subtitle_background_enabled", bool
        )
        ui_color = _ui_config_value(
            ui_config, "subtitle_background_color", str, _hex_color
        )
        if ui_enabled is False:
            params_kwargs["text_background_color"] = False
            if args.rounded_subtitle_background is None:
                params_kwargs["rounded_subtitle_background"] = False
        elif ui_color is not None:
            params_kwargs["text_background_color"] = ui_color
        elif ui_enabled is True:
            params_kwargs["text_background_color"] = True

    return VideoParams(**params_kwargs)


def _load_batch_manifest(raw_path: str) -> tuple[str, list[dict[str, Any]]]:
    expanded_path = os.path.expanduser(raw_path.strip())
    if not expanded_path:
        raise ValueError("--batch-file path cannot be empty")

    candidate = (
        expanded_path
        if os.path.isabs(expanded_path)
        else os.path.join(os.getcwd(), expanded_path)
    )
    manifest_path = os.path.realpath(candidate)
    if not os.path.isfile(manifest_path):
        raise ValueError(f"batch manifest does not exist or is not a file: {raw_path}")

    with open(manifest_path, "rb") as manifest_file:
        payload = manifest_file.read(_BATCH_FILE_MAX_BYTES + 1)
    if len(payload) > _BATCH_FILE_MAX_BYTES:
        raise ValueError("batch manifest exceeds the 1 MiB limit")

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("batch manifest must be UTF-8 encoded") from exc
    if not text.strip():
        raise ValueError("batch manifest must contain at least one task")

    if text.lstrip().startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSON array in batch manifest: {exc.msg}"
            ) from exc
        if not isinstance(parsed, list):
            raise ValueError("batch manifest JSON must be an array")
        entries = parsed
    else:
        entries = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL in batch manifest at line {line_number}: {exc.msg}"
                ) from exc

    if not entries:
        raise ValueError("batch manifest must contain at least one task")
    if len(entries) > _BATCH_TASK_MAX_COUNT:
        raise ValueError(
            f"batch manifest contains {len(entries)} tasks; "
            f"the limit is {_BATCH_TASK_MAX_COUNT}"
        )

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"batch task {index} must be a JSON object")
    return manifest_path, entries


def _validate_batch_entry_fields(
    entry: dict[str, Any],
    *,
    index: int,
    allowed_fields: set[str],
) -> None:
    unknown_fields = sorted(set(entry) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            f"batch task {index} contains unknown VideoParams fields: "
            f"{', '.join(unknown_fields)}"
        )

    materials = entry.get("video_materials")
    if not isinstance(materials, list):
        return
    allowed_material_fields = {"provider", "url", "duration", "source_info"}
    for material_index, material in enumerate(materials, start=1):
        if not isinstance(material, dict):
            continue
        unknown_material_fields = sorted(set(material) - allowed_material_fields)
        if unknown_material_fields:
            raise ValueError(
                f"batch task {index} material {material_index} contains unknown "
                f"MaterialInfo fields: {', '.join(unknown_material_fields)}"
            )


def _manifest_relative_path(raw_path: str, manifest_directory: str) -> str:
    expanded_path = os.path.expanduser(raw_path.strip())
    if not expanded_path or os.path.isabs(expanded_path):
        return expanded_path
    return os.path.realpath(os.path.join(manifest_directory, expanded_path))


def _resolve_batch_entry_paths(
    params: VideoParams,
    *,
    override_fields: set[str],
    manifest_directory: str,
) -> None:
    if "custom_audio_file" in override_fields and params.custom_audio_file:
        params.custom_audio_file = _manifest_relative_path(
            params.custom_audio_file,
            manifest_directory,
        )

    if (
        "video_materials" in override_fields
        and params.video_source == "local"
        and params.video_materials
    ):
        for material in params.video_materials:
            material.url = _manifest_relative_path(
                material.url,
                manifest_directory,
            )


def _validate_batch_task_params(
    params: VideoParams,
    *,
    stop_at: str,
    custom_position_is_explicit: bool,
    wavespeed_charge_confirmed: bool,
    seedance_charge_confirmed: bool,
    ofox_charge_confirmed: bool,
    metaso_minimax_charge_confirmed: bool,
    muapi_charge_confirmed: bool,
    infistar_charge_confirmed: bool = False,
    jalapeno_charge_confirmed: bool = False,
    useapi_charge_confirmed: bool = False,
) -> None:
    if not params.video_subject.strip() and not params.video_script.strip():
        raise ValueError("one of video_subject or video_script is required")

    if params.video_source not in _CLI_VIDEO_SOURCES:
        raise ValueError(
            "video_source must be one of: " + ", ".join(_CLI_VIDEO_SOURCES)
        )
    for field_name, value in (
        ("video_aspect", params.video_aspect),
        ("video_concat_mode", params.video_concat_mode),
    ):
        # These schema fields remain Optional for compatibility with historical
        # API payloads, but the video pipeline always dereferences their enum
        # values. A manifest's explicit null must fail before any batch task starts.
        if value is None:
            raise ValueError(f"{field_name} cannot be null")
    if params.video_source == "local" and stop_at == "terms":
        raise ValueError(
            "stop_at=terms has no effect with video_source=local"
        )
    if (
        params.video_source == "local"
        and stop_at in {"materials", "video"}
        and not params.video_materials
    ):
        raise ValueError(
            "video_materials is required with video_source=local when "
            "stop_at is materials or video"
        )
    if params.video_source != "local" and params.video_materials:
        raise ValueError("video_materials can only be used with video_source=local")
    if (
        params.video_source == "wavespeed"
        and stop_at in {"materials", "video"}
        and not wavespeed_charge_confirmed
    ):
        raise ValueError(
            "--confirm-wavespeed-charge is required for WaveSpeed video generation"
        )
    if (
        params.video_source == "volcengine_seedance"
        and stop_at in {"materials", "video"}
        and not seedance_charge_confirmed
    ):
        raise ValueError(
            "--confirm-seedance-charge is required for Volcano Engine Seedance"
        )
    if (
        params.video_source == "ofox"
        and stop_at in {"materials", "video"}
        and not ofox_charge_confirmed
    ):
        raise ValueError("--confirm-ofox-charge is required for OFox video generation")
    if (
        params.video_source == "metaso_minimax"
        and stop_at in {"materials", "video"}
        and not metaso_minimax_charge_confirmed
    ):
        raise ValueError(
            "--confirm-metaso-minimax-charge is required for Metaso MiniMax H3"
        )
    if (
        params.video_source == "muapi"
        and stop_at in {"materials", "video"}
        and not muapi_charge_confirmed
    ):
        raise ValueError("--confirm-muapi-charge is required for MuAPI video generation")
    if (
        params.video_source == "useapi"
        and stop_at in {"materials", "video"}
        and not useapi_charge_confirmed
    ):
        raise ValueError(
            "--confirm-useapi-charge is required for useapi.net video generation"
        )
    if (
        params.video_source == "useapi_image"
        and stop_at in {"materials", "video"}
        and not useapi_charge_confirmed
        and _useapi_image_needs_confirmation()
    ):
        raise ValueError(
            "--confirm-useapi-charge is required for useapi.net Kling images"
        )

    if (params.video_source == "infistar" and stop_at in {"materials", "video"}
            and not infistar_charge_confirmed):
        raise ValueError("--confirm-infistar-charge is required for Infistar video generation")
    if (params.video_source == "jalapeno" and stop_at in {"materials", "video"}
            and not jalapeno_charge_confirmed):
        raise ValueError("--confirm-jalapeno-charge is required for Jalapeno Cloud video generation")

    if stop_at == "subtitle" and not params.subtitle_enabled:
        raise ValueError("stop_at=subtitle cannot be combined with disabled subtitles")
    if params.subtitle_position not in _SUBTITLE_POSITION_VALUES:
        raise ValueError(
            "subtitle_position must be one of: "
            + ", ".join(_SUBTITLE_POSITION_VALUES)
        )
    if custom_position_is_explicit and params.subtitle_position != "custom":
        raise ValueError("custom_position requires subtitle_position=custom")
    if not math.isfinite(params.custom_position) or not 0 <= params.custom_position <= 100:
        raise ValueError("custom_position must be a finite number between 0 and 100")
    if params.video_clip_speed is not None and (
        not math.isfinite(params.video_clip_speed)
        or not _CLIP_SPEED_MIN <= params.video_clip_speed <= _CLIP_SPEED_MAX
    ):
        raise ValueError(
            "video_clip_speed must be a finite number between "
            f"{_CLIP_SPEED_MIN} and {_CLIP_SPEED_MAX}"
        )
    if params.text_background_color is False and params.rounded_subtitle_background:
        raise ValueError(
            "rounded_subtitle_background requires an enabled subtitle background"
        )

    color_values = {
        "text_fore_color": params.text_fore_color,
        "stroke_color": params.stroke_color,
        "text_background_color": (
            params.text_background_color
            if isinstance(params.text_background_color, str)
            else None
        ),
    }
    for name, value in color_values.items():
        if value is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"{name} must use #RRGGBB format")

    numeric_constraints = (
        ("voice_volume", params.voice_volume, 0, False),
        ("voice_rate", params.voice_rate, 0, True),
        ("bgm_volume", params.bgm_volume, 0, False),
        ("stroke_width", params.stroke_width, 0, False),
    )
    for name, value, minimum, exclusive in numeric_constraints:
        if value is None:
            continue
        if not math.isfinite(value) or (
            value <= minimum if exclusive else value < minimum
        ):
            comparison = ">" if exclusive else ">="
            raise ValueError(f"{name} must be a finite number {comparison} {minimum}")

    for name, value in (
        ("n_threads", params.n_threads),
        ("font_size", params.font_size),
    ):
        if value is not None and value < 1:
            raise ValueError(f"{name} must be >= 1")

    if params.bgm_type not in {"", "random", "custom", *_CLI_MUSIC_BGM_TYPES}:
        raise ValueError(f"bgm_type must be one of: {_BGM_TYPE_CHOICES_TEXT}")
    if params.bgm_file and params.bgm_type != "custom":
        raise ValueError("bgm_file requires bgm_type=custom")
    if params.sonilo_bgm_prompt and params.bgm_type != "sonilo":
        raise ValueError("sonilo_bgm_prompt requires bgm_type=sonilo")
    if params.video_music_prompt and params.bgm_type not in _CLI_MUSIC_BGM_TYPES:
        raise ValueError(
            "video_music_prompt requires bgm_type=sonilo or elevenlabs"
        )


def _build_batch_tasks(args: argparse.Namespace) -> list[VideoParams]:
    from app.models.schema import VideoParams

    manifest_path, entries = _load_batch_manifest(args.batch_file)
    manifest_directory = os.path.dirname(manifest_path)
    base_params = build_video_params(args)
    allowed_fields = set(VideoParams.model_fields)
    base_values = {
        field_name: getattr(base_params, field_name) for field_name in allowed_fields
    }
    tasks: list[VideoParams] = []

    for index, entry in enumerate(entries, start=1):
        _validate_batch_entry_fields(
            entry,
            index=index,
            allowed_fields=allowed_fields,
        )
        try:
            params = VideoParams.model_validate(
                {**copy.deepcopy(base_values), **entry}
            )
            override_fields = set(entry)
            _resolve_batch_entry_paths(
                params,
                override_fields=override_fields,
                manifest_directory=manifest_directory,
            )
            _validate_batch_task_params(
                params,
                stop_at=args.stop_at,
                custom_position_is_explicit=(
                    args.custom_position is not None
                    or "custom_position" in override_fields
                ),
                seedance_charge_confirmed=args.confirm_seedance_charge,
                wavespeed_charge_confirmed=args.confirm_wavespeed_charge,
                ofox_charge_confirmed=args.confirm_ofox_charge,
                metaso_minimax_charge_confirmed=(
                    args.confirm_metaso_minimax_charge
                ),
                muapi_charge_confirmed=args.confirm_muapi_charge,
                infistar_charge_confirmed=args.confirm_infistar_charge,
                jalapeno_charge_confirmed=args.confirm_jalapeno_charge,
                useapi_charge_confirmed=args.confirm_useapi_charge,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid batch task {index}: {exc}") from exc
        tasks.append(params)

    validation_plans = []
    for index, params in enumerate(tasks, start=1):
        try:
            validation_plans.append(_validate_cli_files(params, stop_at=args.stop_at))
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid batch task {index}: {exc}") from exc

    prepared_paths: dict[str, str] = {}
    created_paths: list[str] = []
    try:
        for index, (local_videos_dir, resolved_materials) in enumerate(
            validation_plans, start=1
        ):
            try:
                _prepare_cli_materials(
                    local_videos_dir,
                    resolved_materials,
                    prepared_paths=prepared_paths,
                    created_paths=created_paths,
                )
            except OSError as exc:
                raise ValueError(f"invalid batch task {index}: {exc}") from exc
    except Exception:
        _remove_cli_material_copies(created_paths)
        raise
    return tasks


def _resolve_cli_file(
    raw_path: str,
    *,
    description: str,
    fallback_dir: str | None = None,
) -> str:
    """
    Resolve CLI file arguments into absolute paths relative to the current working directory,
    and confirm they exist before the task starts.

    Older versions always resolved local materials relative to ``storage/local_videos``. For compatibility with existing scripts,
    falling back to that directory is allowed when a relative path isn't found in the current directory; absolute paths are always
    resolved exactly as the user entered them.
    """
    expanded_path = os.path.expanduser(raw_path.strip())
    if not expanded_path:
        raise ValueError(f"{description} path cannot be empty")

    candidate = (
        expanded_path
        if os.path.isabs(expanded_path)
        else os.path.join(os.getcwd(), expanded_path)
    )
    resolved_path = os.path.realpath(candidate)
    if not os.path.isfile(resolved_path) and fallback_dir and not os.path.isabs(expanded_path):
        resolved_path = os.path.realpath(os.path.join(fallback_dir, expanded_path))

    if not os.path.isfile(resolved_path):
        raise ValueError(f"{description} file does not exist: {raw_path}")
    return resolved_path


def _path_is_within_directory(file_path: str, directory: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.realpath(directory), os.path.realpath(file_path)]
        ) == os.path.realpath(directory)
    except ValueError:
        # commonpath can't be computed across different drive letters on Windows, in which case the file is clearly not inside the target directory.
        return False


def _resolve_managed_resource_file(
    raw_path: str,
    *,
    resource_dir: str,
    description: str,
) -> str:
    """Resolve a project resource file, making sure an absolute path still lies within the corresponding resource directory."""
    from app.utils import utils

    expanded_path = os.path.expanduser(raw_path.strip())
    candidates = (
        [expanded_path]
        if os.path.isabs(expanded_path)
        else [
            os.path.join(resource_dir, expanded_path),
            os.path.join(utils.root_dir(), expanded_path),
        ]
    )
    for candidate in candidates:
        resolved_path = os.path.realpath(candidate)
        if os.path.isfile(resolved_path) and _path_is_within_directory(
            resolved_path, resource_dir
        ):
            return resolved_path
    raise ValueError(
        f"{description} file must exist inside {resource_dir}: {raw_path}"
    )


def _validate_cli_files(
    params: VideoParams, stop_at: str
) -> tuple[str, list[tuple[MaterialInfo, str, str]]]:
    """
    Resolve and validate CLI files without side effects, so batch preflight doesn't leave material copies behind.

    Custom audio, BGM and fonts are normalized into paths or names the service layer can use; local materials
    only have their source and extension resolved, and the actual copying is done by ``_prepare_cli_materials`` once all batch entries
    have passed validation.
    """
    from app.models import const
    from app.services import bgm as bgm_service
    from app.utils import utils

    # FFmpeg probing has moved into the shared task pipeline in app/services/task.py (task.start)
    # as a hard check: a probe failure ends the task as a preflight-stage failure, and run_cli()
    # returns a non-zero exit code accordingly. The non-blocking check is no longer repeated here, so it can't disagree
    # with the pipeline's result.

    local_material_extensions = {
        *(f".{extension}" for extension in const.FILE_TYPE_VIDEOS),
        *(f".{extension}" for extension in const.FILE_TYPE_IMAGES),
        ".avi",
        ".flv",
    }

    if params.custom_audio_file and stop_at not in {"script", "terms"}:
        params.custom_audio_file = _resolve_cli_file(
            params.custom_audio_file,
            description="custom audio",
        )
        audio_extension = os.path.splitext(params.custom_audio_file)[1].lower()
        if audio_extension not in _CUSTOM_AUDIO_EXTENSIONS:
            allowed = ", ".join(sorted(_CUSTOM_AUDIO_EXTENSIONS))
            raise ValueError(
                f"unsupported custom audio type {audio_extension or '<none>'}; "
                f"allowed extensions: {allowed}"
            )

    if params.bgm_type == "custom" and stop_at == "video":
        if not bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume):
            # At 0 volume, all BGM is skipped downstream. Also clear the file argument here, so
            # the CLI doesn't resolve paths, check existence or validate the format
            # for a file that will never be read.
            params.bgm_file = ""
        elif not params.bgm_file:
            # Whether a missing file is an error depends on the generic BGM switch, so it can't be blocked
            # unconditionally at the argparse stage, otherwise ``custom + 0%`` would behave differently from the WebUI and service layer.
            raise ValueError("--bgm-file is required when --bgm-type is custom")
        else:
            try:
                # The CLI, WebUI and task service must share the same BGM file boundary. Reuse
                # the service layer's resolution directly here, which supports both the user upload directory and the built-in songs directory, and
                # automatically inherits new audio formats and path safety rules, so multiple entry points don't each
                # maintain an allowlist.
                params.bgm_file = bgm_service.resolve_bgm_file(params.bgm_file)
            except ValueError as exc:
                supported_extensions = ", ".join(
                    bgm_service.SUPPORTED_BGM_EXTENSIONS
                )
                raise ValueError(
                    "background music must be a supported audio file inside "
                    f"storage/bgm or resource/songs ({supported_extensions}): "
                    f"{params.bgm_file}"
                ) from exc

    if params.subtitle_enabled and params.font_name and stop_at == "video":
        font_path = _resolve_managed_resource_file(
            params.font_name,
            resource_dir=utils.font_dir(),
            description="subtitle font",
        )
        if not font_path.lower().endswith((".ttf", ".ttc")):
            raise ValueError("subtitle font must use the .ttf or .ttc extension")
        # Downstream builds the path from the filename inside resource/fonts, so a plain filename is kept.
        params.font_name = os.path.basename(font_path)

    if params.video_source != "local" or stop_at not in {"materials", "video"}:
        return "", []

    local_videos_dir = utils.storage_dir("local_videos")
    resolved_materials: list[tuple[MaterialInfo, str, str]] = []
    for material in params.video_materials or []:
        source_path = _resolve_cli_file(
            material.url,
            description="local material",
            fallback_dir=local_videos_dir,
        )
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in local_material_extensions:
            allowed = ", ".join(sorted(local_material_extensions))
            raise ValueError(
                f"unsupported local material type {extension or '<none>'}: "
                f"{material.url}; allowed extensions: {allowed}"
            )
        resolved_materials.append((material, source_path, extension))

    return local_videos_dir, resolved_materials


def _remove_cli_material_copies(created_paths: Sequence[str]) -> None:
    """Best-effort cleanup for managed copies created by one CLI preparation."""
    for file_path in reversed(created_paths):
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except OSError as exc:
            logger.warning(
                f"failed to remove prepared CLI material: path={file_path}, "
                f"error={exc}"
            )


def _prepare_cli_materials(
    local_videos_dir: str,
    resolved_materials: Sequence[tuple[MaterialInfo, str, str]],
    *,
    prepared_paths: dict[str, str] | None = None,
    created_paths: list[str] | None = None,
) -> None:
    """Copy validated local materials once and update every matching reference."""
    if not resolved_materials:
        return

    os.makedirs(local_videos_dir, exist_ok=True)
    if prepared_paths is None:
        prepared_paths = {}
    if created_paths is None:
        created_paths = []

    for material, source_path, extension in resolved_materials:
        prepared_path = prepared_paths.get(source_path)
        if prepared_path is None:
            if _path_is_within_directory(source_path, local_videos_dir):
                prepared_path = source_path
            else:
                prepared_path = os.path.join(
                    local_videos_dir,
                    f"cli-material-{uuid4().hex}{extension}",
                )
                try:
                    shutil.copy2(source_path, prepared_path)
                except OSError:
                    try:
                        if os.path.exists(prepared_path):
                            os.remove(prepared_path)
                    except OSError:
                        pass
                    raise
                created_paths.append(prepared_path)
                logger.info(
                    "copied CLI local material into managed storage: "
                    f"source={source_path}, target={prepared_path}"
                )
            prepared_paths[source_path] = prepared_path

        material.url = prepared_path


def prepare_cli_files(params: VideoParams, stop_at: str) -> None:
    """Validate and prepare files for one trusted local CLI task."""
    local_videos_dir, resolved_materials = _validate_cli_files(params, stop_at)
    created_paths: list[str] = []
    try:
        _prepare_cli_materials(
            local_videos_dir,
            resolved_materials,
            created_paths=created_paths,
        )
    except Exception:
        _remove_cli_material_copies(created_paths)
        raise


def _run_batch_tasks(args: argparse.Namespace, tasks: list[VideoParams]) -> int:
    from app.services import task as tm
    from app.utils import utils

    task_summaries: list[dict[str, Any]] = []
    used_task_ids: set[str] = set()
    failed_count = 0

    for index, params in enumerate(tasks, start=1):
        task_id = utils.get_uuid()
        if task_id in used_task_ids:
            task_id = str(uuid4())
        used_task_ids.add(task_id)
        logger.info(
            f"start CLI batch task: index={index}, task_id={task_id}, "
            f"stop_at={args.stop_at}"
        )

        result = None
        failed_stage = None
        error = None
        try:
            result = tm.start(
                task_id=task_id,
                params=params,
                stop_at=args.stop_at,
                allow_server_file_input=True,
            )
        except Exception as exc:
            failed_stage = "runtime"
            error = str(exc)
            logger.exception(
                "CLI batch task failed with an unexpected error: "
                f"index={index}, task_id={task_id}, error={exc}"
            )
        else:
            if not isinstance(result, dict) or not result:
                failed_stage = "unknown"
                error = "empty or invalid task result"
            elif result.get("state") == tm.const.TASK_STATE_FAILED:
                failed_stage = result.get("failed_stage") or "unknown"
                error = result.get("error") or "unknown task error"

            if error is not None:
                logger.error(
                    f"CLI batch task failed: index={index}, task_id={task_id}, "
                    f"stop_at={args.stop_at}, stage={failed_stage}, error={error}"
                )

        status = "failed" if error is not None else "succeeded"
        if status == "failed":
            failed_count += 1
        task_summaries.append(
            {
                "index": index,
                "task_id": task_id,
                "status": status,
                "result": result,
                "failed_stage": failed_stage,
                "error": error,
            }
        )

    print(
        json.dumps(
            {
                "total": len(task_summaries),
                "succeeded": len(task_summaries) - failed_count,
                "failed": failed_count,
                "tasks": task_summaries,
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed_count else 0


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    import app.config  # noqa: F401 -- initialize config and process logging setup.
    from app.utils.logging_utils import configure_terminal_logger, get_logging_options

    # The config module sends terminal logs to stdout by default. The CLI's stdout is machine-readable JSON,
    # so it must switch to stderr before steps like material preprocessing start; help and argument errors still keep the deferred import.
    configure_terminal_logger(sys.stderr, level=get_logging_options()[0], colorize=False)
    if args.batch_file:
        try:
            tasks = _build_batch_tasks(args)
        except (ValueError, OSError) as exc:
            logger.error(f"invalid CLI batch input: {exc}")
            return 2
        return _run_batch_tasks(args, tasks)

    try:
        params = build_video_params(args)
        prepare_cli_files(params, stop_at=args.stop_at)
    except (ValueError, OSError) as exc:
        logger.error(f"invalid CLI input: {exc}")
        return 2

    # Help arguments exit directly inside parse_args. Deferring business service imports until here
    # keeps -h/--help output clean without changing the actual task initialization flow.
    from app.services import task as tm
    from app.utils import utils

    task_id = args.task_id or utils.get_uuid()
    logger.info(f"start CLI task: task_id={task_id}, stop_at={args.stop_at}")
    try:
        result = tm.start(
            task_id=task_id,
            params=params,
            stop_at=args.stop_at,
            # CLI inputs come from the local operator rather than an HTTP client.
            # Preserve support for arbitrary local audio paths without weakening the
            # task service's secure default for API and WebUI callers.
            allow_server_file_input=True,
        )
    except Exception as exc:
        logger.exception(
            f"CLI task failed with an unexpected error: task_id={task_id}, error={exc}"
        )
        return 1
    if not result or result.get("state") == tm.const.TASK_STATE_FAILED:
        failed_stage = result.get("failed_stage", "unknown") if result else "unknown"
        error = result.get("error", "unknown task error") if result else "empty result"
        logger.error(
            f"CLI task failed: task_id={task_id}, stop_at={args.stop_at}, "
            f"stage={failed_stage}, error={error}"
        )
        if result and result.get("videos"):
            print(json.dumps({"task_id": task_id, "result": result}, ensure_ascii=False))
        return 1

    print(json.dumps({"task_id": task_id, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from app.utils.logging_utils import force_utf8_console

    force_utf8_console()
    raise SystemExit(run_cli())
