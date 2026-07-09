import argparse
import json
import re
from typing import Sequence

from loguru import logger

from app.models.schema import MaterialInfo, VideoParams
from app.services import task as tm
from app.utils import utils


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
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"value must be >= 0, got {parsed}")
    return parsed


def _percent_position(value: str) -> float:
    parsed = float(value)
    if parsed < 0 or parsed > 100:
        raise argparse.ArgumentTypeError(
            f"custom-position must be between 0 and 100, got {parsed}"
        )
    return parsed


def _hex_color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError(
            f"color must use #RRGGBB format, got {value!r}"
        )
    return value


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
    if normalized in {"", "random", "custom"}:
        return normalized
    raise argparse.ArgumentTypeError("bgm-type must be one of: none, random, custom")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MoneyPrinterTurbo - Tạo video từ dòng lệnh"
    )
    parser.add_argument("--video-subject", required=True, help="chủ đề video")
    parser.add_argument("--video-script", default="", help="kịch bản tùy chỉnh")
    parser.add_argument("--video-terms", default=None, help="các từ khóa cách nhau bằng dấu phẩy")
    parser.add_argument(
        "--video-language",
        default=None,
        help="mã ngôn ngữ tạo kịch bản (mặc định: tự động phát hiện)",
    )
    parser.add_argument(
        "--paragraph-number",
        type=_paragraph_count,
        default=None,
        help="số đoạn kịch bản, 1-10",
    )
    parser.add_argument(
        "--video-script-prompt",
        default=None,
        help="yêu cầu kịch bản tùy chỉnh",
    )
    parser.add_argument(
        "--custom-system-prompt",
        default=None,
        help="system prompt tùy chỉnh để tạo kịch bản",
    )
    parser.add_argument(
        "--video-source",
        default="pexels",
        choices=["pexels", "pixabay", "coverr", "local"],
        help="nguồn tư liệu video",
    )
    parser.add_argument(
        "--video-materials",
        default="",
        help="đường dẫn tư liệu cục bộ cách nhau bằng dấu phẩy",
    )
    parser.add_argument(
        "--stop-at",
        default="video",
        choices=["script", "terms", "audio", "subtitle", "materials", "video"],
        help="giai đoạn dừng pipeline",
    )
    parser.add_argument(
        "--video-count", type=_positive_int, default=1, help="số lượng video đầu ra (>=1)"
    )
    parser.add_argument("--video-aspect", default="9:16", help="tỷ lệ khung hình video")
    parser.add_argument(
        "--video-concat-mode",
        choices=["random", "sequential"],
        default=None,
        help="chế độ nối video",
    )
    parser.add_argument(
        "--video-transition-mode",
        type=_transition_mode,
        default=None,
        metavar="{none,shuffle,fade-in,fade-out,slide-in,slide-out}",
        help="chế độ chuyển cảnh video",
    )
    parser.add_argument(
        "--video-clip-duration",
        type=_positive_int,
        default=None,
        help="thời lượng tối đa mỗi đoạn nguồn tính bằng giây",
    )
    parser.add_argument(
        "--match-materials-to-script",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="khớp tư liệu theo thứ tự kịch bản",
    )
    parser.add_argument("--voice-name", default="", help="tên giọng nói TTS")
    parser.add_argument(
        "--voice-volume",
        type=_non_negative_float,
        default=None,
        help="hệ số âm lượng giọng nói",
    )
    parser.add_argument(
        "--voice-rate",
        type=_non_negative_float,
        default=None,
        help="hệ số tốc độ đọc",
    )
    parser.add_argument(
        "--bgm-type",
        type=_bgm_type,
        default=None,
        metavar="{none,random,custom}",
        help="chế độ nhạc nền",
    )
    parser.add_argument("--bgm-file", default=None, help="tệp nhạc nền tùy chỉnh")
    parser.add_argument(
        "--bgm-volume",
        type=_non_negative_float,
        default=None,
        help="hệ số âm lượng nhạc nền",
    )
    parser.add_argument(
        "--subtitle-enabled",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="bật phụ đề (mặc định: bật, dùng --no-subtitle-enabled để tắt)",
    )
    parser.add_argument("--font-name", default=None, help="tên tệp phông chữ phụ đề")
    parser.add_argument(
        "--subtitle-position",
        choices=["top", "center", "bottom", "custom"],
        default=None,
        help="vị trí phụ đề",
    )
    parser.add_argument(
        "--custom-position",
        type=_percent_position,
        default=None,
        help="vị trí phụ đề tùy chỉnh theo phần trăm từ đầu trang, 0-100",
    )
    parser.add_argument(
        "--text-fore-color",
        type=_hex_color,
        default=None,
        help="màu chữ phụ đề định dạng #RRGGBB",
    )
    parser.add_argument(
        "--font-size", type=_positive_int, default=None, help="cỡ chữ phụ đề"
    )
    parser.add_argument(
        "--stroke-color",
        type=_hex_color,
        default=None,
        help="màu viền phụ đề định dạng #RRGGBB",
    )
    parser.add_argument(
        "--stroke-width",
        type=_non_negative_float,
        default=None,
        help="độ rộng viền phụ đề",
    )
    parser.add_argument(
        "--subtitle-background-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="bật nền phụ đề",
    )
    parser.add_argument(
        "--subtitle-background-color",
        type=_hex_color,
        default=None,
        help="màu nền phụ đề định dạng #RRGGBB",
    )
    parser.add_argument(
        "--rounded-subtitle-background",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="bật nền phụ đề bo tròn mờ trong suốt",
    )
    parser.add_argument("--task-id", default="", help="ID tác vụ tùy chỉnh")
    args = parser.parse_args(argv)

    if args.video_source == "local" and not (args.video_materials or "").strip():
        parser.error("--video-materials is required when --video-source is local")

    if args.video_source == "local" and args.stop_at == "terms":
        parser.error(
            "--stop-at terms has no effect with --video-source local "
            "(search terms are not generated for local sources)"
        )

    return args


def build_video_params(args: argparse.Namespace) -> VideoParams:
    video_terms = args.video_terms
    if video_terms:
        video_terms = [term.strip() for term in video_terms.split(",") if term.strip()]

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
        "video_subject": args.video_subject,
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
        "voice_volume",
        "voice_rate",
        "bgm_type",
        "bgm_file",
        "bgm_volume",
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


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    params = build_video_params(args)
    task_id = args.task_id or utils.get_uuid()
    logger.info(f"start cli task: {task_id}, stop_at: {args.stop_at}")
    result = tm.start(task_id=task_id, params=params, stop_at=args.stop_at)
    if not result:
        logger.error("video generation failed")
        return 1

    print(json.dumps({"task_id": task_id, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
