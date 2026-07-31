from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
from typing import TYPE_CHECKING, Sequence
from uuid import UUID, uuid4

from loguru import logger

if TYPE_CHECKING:
    from app.models.schema import MaterialInfo, VideoParams


DEFAULT_VOICE_NAME = "zh-CN-XiaoxiaoNeural-Female"
_PIPELINE_STAGES = ("script", "terms", "audio", "subtitle", "materials", "video")
_CUSTOM_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class _CliHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """여러 줄 예시의 배치를 유지하면서, 의미 있는 기본값을 자동으로 보여 준다."""

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


def _task_id(value: str) -> str:
    """CLI 의 사용자 지정 작업 식별자는 UUID 만 받는다. 이 값이 파일 시스템 경로로 해석되지 않게 하기 위해서다."""
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
}


def _transition_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized not in _TRANSITION_MODE_VALUES:
        allowed = ", ".join(_TRANSITION_MODE_VALUES)
        raise argparse.ArgumentTypeError(
            f"video-transition-mode must be one of: {allowed}"
        )
    return _TRANSITION_MODE_VALUES[normalized]


def _bgm_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "none":
        return ""
    if normalized in {"", "random", "custom", "sonilo"}:
        return normalized
    raise argparse.ArgumentTypeError(
        "bgm-type must be one of: none, random, custom, sonilo"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
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
  JSON object to stdout and exits with 0. Task failures exit with 1; argument errors
  exit with 2. Runtime logs are written to stderr.
""",
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
        choices=["pexels", "pixabay", "coverr", "local"],
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
        "--video-concat-mode",
        choices=["random", "sequential"],
        default=None,
        help="source clip concatenation order (default: random)",
    )
    video_group.add_argument(
        "--video-transition-mode",
        type=_transition_mode,
        default=None,
        metavar="{none,shuffle,fade-in,fade-out,slide-in,slide-out}",
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
        default=DEFAULT_VOICE_NAME,
        help=(
            "TTS voice identifier; use 'no-voice' for silent output. Provider-specific "
            "identifiers use prefixes such as gemini:, mimo:, elevenlabs:, and chatterbox:"
        ),
    )
    audio_group.add_argument(
        "--voice-volume",
        type=_non_negative_float,
        default=None,
        help=(
            "final voiceover volume multiplier, a finite number >= 0 (default: 1.0)"
        ),
    )
    audio_group.add_argument(
        "--voice-rate",
        type=_positive_float,
        default=None,
        help=(
            "speech rate multiplier, a finite number > 0 (default: 1.0)"
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
        metavar="{none,random,custom,sonilo}",
        help=(
            "background music mode; Sonilo reads its API key from config.toml or "
            "SONILO_API_KEY; --bgm-file implies custom when omitted "
            "(default: random)"
        ),
    )
    audio_group.add_argument(
        "--sonilo-bgm-prompt",
        default=None,
        help="optional music style prompt for Sonilo, up to 2000 characters",
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
        default=True,
        action=argparse.BooleanOptionalAction,
        help=(
            "enable subtitles; use --no-subtitle-enabled to disable "
            "(default: enabled)"
        ),
    )
    subtitle_group.add_argument(
        "--font-name",
        default=None,
        help=(
            "subtitle font filename inside resource/fonts "
            "(default: STHeitiMedium.ttc)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-position",
        choices=["top", "center", "bottom", "custom"],
        default=None,
        help=(
            "subtitle vertical position (default: [ui].subtitle_position from "
            "config.toml; bottom when unset)"
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
            "that treat # as a comment (default: #FFFFFF)"
        ),
    )
    subtitle_group.add_argument(
        "--font-size",
        type=_positive_int,
        default=None,
        help="subtitle font size (default: 60)",
    )
    subtitle_group.add_argument(
        "--stroke-color",
        type=_hex_color,
        default=None,
        help="subtitle outline color in #RRGGBB format (default: #000000)",
    )
    subtitle_group.add_argument(
        "--stroke-width",
        type=_non_negative_float,
        default=None,
        help=(
            "subtitle outline width, a finite number >= 0 (default: 1.5)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-background-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "enable subtitle background; use --no-subtitle-background-enabled to "
            "disable (default: enabled)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-background-color",
        type=_hex_color,
        default=None,
        help="subtitle background color in #RRGGBB format (default: #000000)",
    )
    subtitle_group.add_argument(
        "--rounded-subtitle-background",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="use a rounded subtitle background (default: disabled)",
    )

    execution_group = parser.add_argument_group("execution")
    execution_group.add_argument(
        "--task-id",
        type=_task_id,
        default=None,
        help="custom UUID used for storage/tasks/<task-id>; generated automatically when omitted",
    )
    args = parser.parse_args(argv)

    if not args.video_subject.strip() and not args.video_script.strip():
        parser.error("one of --video-subject or --video-script is required")

    if args.video_source == "local" and args.stop_at == "terms":
        parser.error(
            "--stop-at terms has no effect with --video-source local "
            "(search terms are not generated for local sources)"
        )

    stage_requires_materials = args.stop_at in {"materials", "video"}
    has_video_materials = bool((args.video_materials or "").strip())
    if args.video_source == "local" and stage_requires_materials and not has_video_materials:
        parser.error(
            "--video-materials is required with --video-source local when "
            "--stop-at is materials or video"
        )
    if args.video_source != "local" and has_video_materials:
        parser.error("--video-materials can only be used with --video-source local")

    if args.bgm_file:
        if args.bgm_type in (None, "custom"):
            args.bgm_type = "custom"
        else:
            parser.error("--bgm-file can only be combined with --bgm-type custom")

    if args.sonilo_bgm_prompt:
        if args.bgm_type in (None, "sonilo"):
            args.bgm_type = "sonilo"
        else:
            parser.error(
                "--sonilo-bgm-prompt can only be combined with --bgm-type sonilo"
            )

    if args.custom_position is not None and args.subtitle_position != "custom":
        parser.error("--custom-position requires --subtitle-position custom")
    if args.stop_at == "subtitle" and not args.subtitle_enabled:
        parser.error("--stop-at subtitle cannot be combined with --no-subtitle-enabled")
    if args.subtitle_background_enabled is False and (
        args.subtitle_background_color is not None
        or args.rounded_subtitle_background is True
    ):
        parser.error(
            "subtitle background color or rounding cannot be enabled together with "
            "--no-subtitle-background-enabled"
        )

    return args


def build_video_params(args: argparse.Namespace) -> VideoParams:
    # 인자 도움말과 검증에는 애플리케이션 설정을 로딩할 필요가 없다. 작업 파라미터를 실제로
    # 만들 때만 모델을 import 해, ``cli.py -h`` 를 실행할 때 설정 초기화 로그가 나오지 않게 한다.
    from app.models.schema import MaterialInfo, VideoParams

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
        "voice_name": args.voice_name,
        "subtitle_enabled": args.subtitle_enabled,
    }

    optional_arg_names = [
        "video_language",
        "paragraph_number",
        "video_script_prompt",
        "custom_system_prompt",
        "video_concat_mode",
        "video_transition_mode",
        "video_clip_duration",
        "match_materials_to_script",
        "n_threads",
        "voice_volume",
        "voice_rate",
        "custom_audio_file",
        "bgm_type",
        "bgm_file",
        "bgm_volume",
        "sonilo_bgm_prompt",
        "font_name",
        "subtitle_position",
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

    if args.subtitle_background_enabled is False:
        params_kwargs["text_background_color"] = False
        params_kwargs["rounded_subtitle_background"] = False
    elif args.subtitle_background_color is not None:
        params_kwargs["text_background_color"] = args.subtitle_background_color
    elif args.subtitle_background_enabled is True:
        params_kwargs["text_background_color"] = True

    return VideoParams(**params_kwargs)


def _resolve_cli_file(
    raw_path: str,
    *,
    description: str,
    fallback_dir: str | None = None,
) -> str:
    """
    CLI 파일 인자를 현재 작업 디렉터리 기준 절대 경로로 해석하고, 작업을 시작하기 전에
    존재를 확인한다.

    로컬 소재는 예전 버전에서 항상 ``storage/local_videos`` 기준으로 해석됐다. 기존 스크립트
    호환을 위해 현재 디렉터리에서 상대 경로를 찾지 못하면 그 디렉터리로 되돌아가는 것을
    허용한다. 절대 경로는 언제나 사용자 입력 그대로 해석한다.
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
        # Windows 에서 드라이브 문자가 다르면 commonpath 를 계산할 수 없다. 이 경우 파일은 당연히 대상 디렉터리 밖이다.
        return False


def _resolve_managed_resource_file(
    raw_path: str,
    *,
    resource_dir: str,
    description: str,
) -> str:
    """프로젝트 리소스 파일을 해석하고, 절대 경로가 해당 리소스 디렉터리 안에 남아 있도록 보장한다."""
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


def prepare_cli_files(params: VideoParams, stop_at: str) -> None:
    """
    LLM/TTS 를 호출하기 전에 CLI 파일을 준비한다. 긴 흐름이 한참 진행된 뒤에야 경로 오류를
    알리는 일을 막기 위해서다.

    서비스 계층은 API 요청을 보호하려고 ``storage/local_videos`` 안의 소재만 읽도록 허용한다.
    CLI 는 로컬 진입점이므로 현재 디렉터리 상대 경로와 절대 경로를 모두 받는다. 디렉터리 밖의
    소재는 통제된 디렉터리로 복사한 뒤, 인자를 서비스 계층이 안전하게 쓸 수 있는 절대 경로로
    바꾼다.
    """
    from app.models import const
    from app.services import bgm as bgm_service
    from app.utils import utils

    local_material_extensions = {
        *(f".{extension}" for extension in const.FILE_TYPE_VIDEOS),
        *(f".{extension}" for extension in const.FILE_TYPE_IMAGES),
        ".avi",
        ".flv",
    }

    if params.custom_audio_file:
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

    if params.bgm_type == "custom":
        if not bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume):
            # 음량이 0 이면 하위 단계에서 모든 BGM 을 건너뛴다. 여기서 파일 인자도 함께 비워,
            # 읽히지도 않을 파일에 대해 CLI 가 경로 해석, 존재 확인, 형식 검증을 하지 않게 한다.
            params.bgm_file = ""
        elif not params.bgm_file:
            # 파일이 없는 것이 오류인지 여부는 공용 BGM 스위치에 달려 있다. argparse 단계에서
            # 무조건 막으면 ``custom + 0%`` 가 WebUI 및 서비스 계층과 다르게 동작한다.
            raise ValueError("--bgm-file is required when --bgm-type is custom")
        else:
            try:
                # CLI, WebUI, 작업 서비스는 같은 BGM 파일 경계를 공유해야 한다. 여기서 서비스
                # 계층의 해석을 그대로 재사용하면 사용자 업로드 디렉터리와 내장 음원 디렉터리를
                # 모두 지원하고, 새로 추가되는 오디오 형식과 경로 보안 규칙도 자동으로 물려받아
                # 여러 진입점이 화이트리스트를 따로 관리하지 않아도 된다.
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
        # 하위 단계가 resource/fonts 안의 파일명으로 경로를 이어 붙이므로 순수 파일명을 그대로 남긴다.
        params.font_name = os.path.basename(font_path)

    if params.video_source != "local" or stop_at not in {"materials", "video"}:
        return

    local_videos_dir = utils.storage_dir("local_videos", create=True)
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

    # 모든 입력 검사를 통과한 뒤에 복사한다. 두 번째 파일이 잘못됐을 때 첫 번째 파일의
    # 고아 사본이 남지 않게 하기 위해서다.
    prepared_paths: dict[str, str] = {}
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
                shutil.copy2(source_path, prepared_path)
                logger.info(
                    "copied CLI local material into managed storage: "
                    f"source={source_path}, target={prepared_path}"
                )
            prepared_paths[source_path] = prepared_path

        material.url = prepared_path


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = build_video_params(args)
        prepare_cli_files(params, stop_at=args.stop_at)
    except (ValueError, OSError) as exc:
        logger.error(f"invalid CLI input: {exc}")
        return 2

    # 도움말 인자는 parse_args 에서 곧바로 종료된다. 업무 서비스를 여기까지 늦춰 import 해
    # -h/--help 출력이 깔끔하게 유지되면서, 실제 작업의 초기화 흐름은 바뀌지 않게 한다.
    from app.services import task as tm
    from app.utils import utils

    task_id = args.task_id or utils.get_uuid()
    logger.info(f"start CLI task: task_id={task_id}, stop_at={args.stop_at}")
    try:
        result = tm.start(task_id=task_id, params=params, stop_at=args.stop_at)
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
        return 1

    print(json.dumps({"task_id": task_id, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
