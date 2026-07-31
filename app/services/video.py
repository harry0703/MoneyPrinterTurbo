import itertools
import io
import os
import random
import gc
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import ExitStack, redirect_stdout
from functools import lru_cache
from typing import List
from loguru import logger
import numpy as np
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import Image, ImageDraw, ImageFont

from app.config import config
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import bgm as bgm_service
from app.services.utils import video_effects
from app.utils import file_security, utils

class SubClippedVideoClip:
    def __init__(
        self,
        file_path,
        start_time=None,
        end_time=None,
        width=None,
        height=None,
        duration=None,
        source_file_path=None,
    ):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        self.source_file_path = source_file_path or file_path
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
# Docker 안의 ffmpeg/AAC 조합은 기본 설정에서 오디오 품질이 흔들리기 쉽다. 여기서
# 오디오 비트레이트를 명시적으로 올려, 결과물 단계에서 기본값이 너무 낮아 눈에 띄는
# 왜곡이 생기는 것을 막는다.
audio_bitrate = "192k"
fps = 30
# FFmpeg 가 프레임레이트에 맞춰 이어붙이거나 트랜스코딩할 때, 최종 길이가 MoviePy 가 읽은
# 이론상 길이보다 수십 밀리초 짧아질 수 있다. 여기서 영상 소재에 아주 작은 안전 여유를 둬,
# 프레임 반올림 때문에 오디오 끝부분에서 검은 화면, 끊김, 마지막 나레이션에 화면이 없는
# 상황이 생기지 않게 한다.
_VIDEO_DURATION_SAFETY_MARGIN = 0.1
_MIN_MATERIAL_DIMENSION = 480
# 메신저 앱과 일부 인코더는 화면 크기를 내림한다. 예를 들어 WhatsApp 은 9:16 소재를
# 478x850 으로 압축하는데, 이는 480 보다 2 픽셀 작다. 480 으로 딱 잘라 막으면 이런 소재가
# 전부 버려져 결국 "no valid materials found" 로 통째로 실패한다. 여기에 아주 작은 허용치를
# 둬서, 반올림 때문에 기준을 살짝 밑도는 소재는 통과시키면서 진짜 저화질 소재는 계속 막는다.
_MIN_DIMENSION_TOLERANCE = 10
_DEFAULT_VIDEO_CODEC = "libx264"
_SUPPORTED_VIDEO_CODECS = (
    "libx264",
    "h264_nvenc",
    "h264_amf",
    "h264_qsv",
    "h264_mf",
    "h264_videotoolbox",
)
_runtime_disabled_video_codecs = set()


def _get_required_video_duration(audio_duration: float) -> float:
    """
    영상 소재를 이어붙일 목표 길이를 반환한다.

    쓰이는 상황: 영상을 합성할 때 소재 길이가 나레이션 오디오를 덮어야 한다. '정확히 같게'
    만들면 FFmpeg 의 프레임레이트 반올림 때문에 최종 영상이 살짝 짧아질 수 있으므로, 일괄로
    약간의 여유를 더한다. 함수를 따로 뺀 것은 테스트하기 쉽고 나중에 실제 피드백에 따라
    여유 크기를 조정하기 쉽게 하기 위해서다.
    """
    return max(0.0, float(audio_duration) + _VIDEO_DURATION_SAFETY_MARGIN)


def is_material_resolution_acceptable(width: int, height: int) -> bool:
    """
    소재 해상도가 합성에 충분한지 판정한다.

    명목상 최소값은 480x480 이지만, 인코더나 메신저 앱의 내림 때문에 생기는 크기
    (예: WhatsApp 의 478x850) 를 받아들이려고 `_MIN_DIMENSION_TOLERANCE` 픽셀만큼 낮은
    값까지 허용한다.
    """
    min_dimension = _MIN_MATERIAL_DIMENSION - _MIN_DIMENSION_TOLERANCE
    return width >= min_dimension and height >= min_dimension


def _prioritize_unique_source_clips(
    subclipped_items: List[SubClippedVideoClip],
    concat_mode: VideoConcatMode,
) -> List[SubClippedVideoClip]:
    """
    원본 소재 하나가 한 번만 나오도록 우선 배치해, 결과물에 같은 소재가 반복될 확률을 낮춘다.

    온라인 소재에서는 '긴 영상 하나가 여러 짧은 조각으로 잘리는' 경우가 흔하다. 예전 로직은
    random 모드에서 모든 짧은 조각을 그냥 섞어서, 같은 원본 영상의 여러 조각이 앞부분과
    중간에 흩어져 사용자에게는 소재가 반복되는 것처럼 보였다. 이 함수는 조각 순서만 조정한다.
    원본 파일마다 가장 긴 조각을 먼저 놓고 나머지 조각은 예비로 둔다. 소재 총 길이가 부족하면
    뒤쪽 조각으로 오디오 길이를 채우는 것도 계속 허용해, 영상 생성 성공률을 해치지 않는다.
    가장 긴 조각을 먼저 고르는 이유는, 영상 끝부분의 자잘한 짧은 조각이 무작위로 뽑혀 소재가
    충분한데도 너무 일찍 재사용되는 것을 막기 위해서다.
    """
    if not subclipped_items:
        return []

    concat_mode_value = getattr(concat_mode, "value", concat_mode)
    if concat_mode_value != VideoConcatMode.random.value:
        return subclipped_items

    grouped_items: dict[str, list[SubClippedVideoClip]] = {}
    for item in subclipped_items:
        grouped_items.setdefault(item.source_file_path, []).append(item)

    primary_items = []
    overflow_items = []
    for items in grouped_items.values():
        primary_item = max(items, key=lambda item: item.duration)
        primary_items.append(primary_item)
        overflow_items.extend(item for item in items if item is not primary_item)

    random.shuffle(primary_items)
    random.shuffle(overflow_items)
    logger.info(
        "prioritized unique video materials, "
        f"sources: {len(grouped_items)}, "
        f"primary clips: {len(primary_items)}, "
        f"fallback clips: {len(overflow_items)}"
    )
    return primary_items + overflow_items


def get_ffmpeg_binary():
    """
    예전에 video 서비스에서 FFmpeg 경로를 직접 읽던 호출자를 위한 호환 함수.

    실제 해석 로직은 `app.utils.utils.get_ffmpeg_binary()` 로 옮겼다. 영상, 음성은 물론
    앞으로 추가될 경로도 모두 같은 우선순위를 재사용해야 한다. 여기에 얇은 래퍼를 남긴 것은
    외부 스크립트나 예전 테스트가 `app.services.video.get_ffmpeg_binary` 를 직접 import 할 때
    AttributeError 가 나지 않게 하기 위해서다.
    """
    return utils.get_ffmpeg_binary()


def _get_configured_video_codec() -> str:
    """
    사용자가 설정한 영상 인코더를 읽는다.

    이 설정은 고급 사용자용으로, NVENC/AMF/QSV/VideoToolbox 같은 하드웨어 인코딩을 켜 보는
    데 쓴다. 여기서 일부러 고정된 화이트리스트만 허용한다. 임의의 FFmpeg 파라미터를 열어 주면
    사용자가 잘못 입력했을 때 출력 형식을 통제할 수 없고, 심하면 생성 작업이 한참 뒤 단계에서야
    실패하기 때문이다.
    """
    configured_codec = str(
        config.app.get("video_codec", _DEFAULT_VIDEO_CODEC) or _DEFAULT_VIDEO_CODEC
    ).strip()
    if configured_codec not in _SUPPORTED_VIDEO_CODECS:
        logger.warning(
            f"unsupported video codec configured: {configured_codec}, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}"
        )
        return _DEFAULT_VIDEO_CODEC
    return configured_codec


@lru_cache(maxsize=16)
def _ffmpeg_encoder_exists(ffmpeg_binary: str, codec: str) -> bool:
    """
    현재 FFmpeg 가 지정한 인코더를 지원한다고 밝히는지 확인한다.

    이것으로는 FFmpeg 가 빌드될 때 해당 encoder 를 포함했다는 것만 알 수 있을 뿐, 지금 머신의
    하드웨어와 드라이버에서 반드시 동작한다는 뜻은 아니다. 그래서 실제 인코딩이 실패하면
    여전히 libx264 로 되돌아간다.
    """
    try:
        result = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "failed to inspect ffmpeg encoders, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}: {str(exc)}"
        )
        return False

    if result.returncode != 0:
        logger.warning(
            "failed to inspect ffmpeg encoders, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}: {(result.stderr or result.stdout or '').strip()}"
        )
        return False
    return codec in result.stdout


def _get_effective_video_codec(preferred_codec: str | None = None) -> str:
    """
    이번에 실제로 쓸 영상 인코더를 반환한다.

    사용자가 하드웨어 인코더를 골랐다면 먼저 FFmpeg encoder 목록을 확인한다. 이 프로세스에서
    이미 실제 인코딩이 실패한 적이 있다면 곧바로 되돌려, 한 작업 안에서 모든 조각이 똑같이
    실패하는 것을 막는다.
    """
    selected_codec = preferred_codec or _get_configured_video_codec()
    if selected_codec == _DEFAULT_VIDEO_CODEC:
        return _DEFAULT_VIDEO_CODEC

    if selected_codec in _runtime_disabled_video_codecs:
        logger.warning(
            f"video codec {selected_codec} was disabled after a runtime failure, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}"
        )
        return _DEFAULT_VIDEO_CODEC

    ffmpeg_binary = utils.get_ffmpeg_binary()
    if not _ffmpeg_encoder_exists(ffmpeg_binary, selected_codec):
        logger.warning(
            f"ffmpeg encoder {selected_codec} is not available, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}"
        )
        return _DEFAULT_VIDEO_CODEC

    return selected_codec


def _disable_runtime_video_codec(codec: str, reason: str):
    if codec == _DEFAULT_VIDEO_CODEC:
        return
    _runtime_disabled_video_codecs.add(codec)
    logger.warning(
        f"video codec {codec} failed, fallback to {_DEFAULT_VIDEO_CODEC}. "
        f"reason: {reason}"
    )


def _get_temp_audio_dir(output_dir: str) -> str:
    """
    Return the directory to use for MoviePy's temporary audio file.

    On Windows, Windows Defender can lock files written to the task output
    directory while scanning them, causing MoviePy to fail with a
    PermissionError (WinError 32) on the TEMP_MPY_wvf_snd temp file and
    leaving the final MP4 at 0 bytes.  Using the system temp directory
    sidesteps the scan without changing behaviour on other platforms.

    On Linux/macOS/Docker the output directory is returned unchanged so
    existing behaviour is preserved.
    """
    if sys.platform == "win32":
        return tempfile.gettempdir()
    return output_dir


def _fallback_write_videofile(clip, output_file: str, failed_codec: str, reason: str, **kwargs):
    """
    하드웨어 인코딩이 실패하면 libx264 로 재시도하고, 재시도가 성공했을 때만 그 하드웨어
    인코더를 비활성화한다.

    Windows 에서 FFmpeg 실패 원인은 꽤 복잡하다. 그래픽카드나 드라이버가 지원하지 않을 수도
    있고, 출력 파일이 사용 중이거나 디렉터리 권한, 백신 차단 같은 일반적인 IO 문제일 수도 있다.
    libx264 로는 성공적으로 쓸 수 있을 때만 원래 실패가 하드웨어 인코더 자체에서 왔을 가능성이
    크다고 판단할 수 있고, 이후 작업이 애먼 피해를 보지 않는다.
    """
    clip.write_videofile(output_file, codec=_DEFAULT_VIDEO_CODEC, **kwargs)
    _disable_runtime_video_codec(failed_codec, reason)
    return _DEFAULT_VIDEO_CODEC


def _write_videofile_with_codec_fallback(clip, output_file: str, codec: str, **kwargs):
    """
    지정한 인코더로 영상을 쓰고, 실패하면 libx264 로 한 번 자동 재시도한다.

    하드웨어 인코더를 쓸 수 있는지는 FFmpeg 뿐 아니라 그래픽카드, 드라이버, 현재 실행 환경에도
    달려 있다. 고급 인코더를 쓸 수 없다고 해서 생성 작업 전체가 실패해서는 안 되므로, 되돌리는
    처리를 여기에 모아 둔다.
    """
    effective_codec = _get_effective_video_codec(codec)
    try:
        clip.write_videofile(output_file, codec=effective_codec, **kwargs)
        return effective_codec
    except Exception as exc:
        if effective_codec == _DEFAULT_VIDEO_CODEC:
            raise
        return _fallback_write_videofile(
            clip,
            output_file,
            failed_codec=effective_codec,
            reason=str(exc),
            **kwargs,
        )


def _escape_ffmpeg_concat_path(file_path: str) -> str:
    # concat demuxer 는 경로를 작은따옴표로 감싸므로, 경로 안의 작은따옴표를 먼저 이스케이프해야 한다.
    return file_path.replace("'", "'\\''")


def _format_ffmpeg_concat_path(file_path: str) -> str:
    """
    concat demuxer 파일 목록에 쓸 경로를 만든다.

    FFmpeg 공식 문서는 concat list 안의 특수 문자와 공백을 이스케이프하도록 요구한다. Windows
    절대 경로의 역슬래시도 이스케이프 문자로 해석되기 쉽다. 여기서는 슬래시 형태로 통일해
    `C:\\Users\\...` 를 `C:/Users/...` 로 바꾸고, 그다음 작은따옴표를 처리해 macOS/Linux 와도
    호환되게 한다.
    """
    absolute_path = os.path.abspath(file_path)
    return _escape_ffmpeg_concat_path(absolute_path.replace("\\", "/"))


def concat_video_clips_with_ffmpeg(
    clip_files: List[str],
    output_file: str,
    threads: int,
    output_dir: str,
    max_duration: float | None = None,
):
    concat_list_file = os.path.join(output_dir, "ffmpeg-concat-list.txt")
    with open(concat_list_file, "w", encoding="utf-8") as fp:
        for clip_file in clip_files:
            fp.write(f"file '{_format_ffmpeg_concat_path(clip_file)}'\n")

    def build_command(codec: str) -> list[str]:
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list_file,
            "-c:v",
            codec,
            "-threads",
            str(threads or 2),
            "-pix_fmt",
            "yuv420p",
        ]
        if max_duration is not None and max_duration > 0:
            command.extend(["-t", f"{max_duration:.3f}"])
        command.append(output_file)
        return command

    def run_concat(codec: str):
        command = build_command(codec)
        # ffmpeg 로 한 번만 이어붙이고 인코딩해, MoviePy 가 조각별로 합치면서 반복 재인코딩하는
        # 것을 피한다. 이렇게 하면 화질 열화와 색 틀어짐 위험이 줄어든다.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_message or "ffmpeg concat failed")
        return codec

    try:
        effective_codec = _get_effective_video_codec()
        try:
            return run_concat(effective_codec)
        except Exception as exc:
            if effective_codec == _DEFAULT_VIDEO_CODEC:
                raise
            result_codec = run_concat(_DEFAULT_VIDEO_CODEC)
            _disable_runtime_video_codec(effective_codec, str(exc))
            return result_codec
    finally:
        delete_files(concat_list_file)


def _sanitize_image_file(image_path: str) -> str:
    # 일부 로컬 이미지는 Pillow 로는 열리지만, 손상된 EXIF/eXIf 메타데이터 때문에 ImageClip 이
    # 해석 단계에서 곧바로 예외를 던진다. 여기서 '깨끗한 이미지' 를 다시 내보내 잘못된
    # 메타데이터를 벗겨 낸다.
    image_root, _ = os.path.splitext(image_path)
    sanitized_path = f"{image_root}.sanitized.png"

    with Image.open(image_path) as image:
        image.load()
        # PNG 로 통일해 내보내, JPEG/PNG 의 서로 다른 메타데이터 경로가 손상된 블록을 계속 끌고 오지 않게 한다.
        cleaned_image = Image.new(image.mode, image.size)
        cleaned_image.putdata(list(image.getdata()))
        cleaned_image.save(sanitized_path)

    return sanitized_path


def _open_image_clip_with_fallback(image_path: str):
    # 원본 이미지를 먼저 그대로 열어 본다. 손상된 메타데이터 때문에 실패하면 메타데이터 없는 사본을 만들어 본다.
    try:
        return ImageClip(image_path), image_path
    except Exception as exc:
        logger.warning(
            f"failed to open image directly, trying sanitized copy: {image_path}, error: {str(exc)}"
        )
        sanitized_path = _sanitize_image_file(image_path)
        return ImageClip(sanitized_path), sanitized_path


def _open_video_clip_quietly(video_path: str, audio: bool = False) -> VideoFileClip:
    """
    영상 파일을 조용히 연다. MoviePy 2.1.x 가 ffmpeg 탐지 정보를 stdout 에 그대로 출력하는 것을 막는다.

    배경:
    현재 의존성 버전의 `FFMPEG_VideoReader` 안에는 `print(self.infos)` 와
    `print(ffmpeg command)` 가 있어서, 오디오 트랙이 없는 중간 영상을 읽을 때
    `audio_found: False` 를 출력한다. 이는 입력 소재의 metadata 일 뿐 최종 결과물에 오디오가
    없다는 뜻이 아니지만, WebUI/터미널 사용자에게 생성이 실패한 것처럼 오해를 준다.

    구현:
    1. VideoFileClip 을 여는 짧은 구간에서만 stdout 을 리디렉션한다.
    2. 기본값은 `audio=False` 다. 이 프로젝트의 영상 소재 단계에서는 소재의 원본 소리를
       남길 필요가 없고, 최종 오디오는 `generate_video()` 단계에서 한꺼번에 붙이기 때문이다.
    3. 의존 라이브러리가 실제로 무언가를 출력했다면 debug 로그로 낮춰, 필요할 때 확인할 수 있게 한다.
    """
    captured_stdout = io.StringIO()
    with redirect_stdout(captured_stdout):
        clip = VideoFileClip(video_path, audio=audio)

    moviepy_stdout = captured_stdout.getvalue().strip()
    if moviepy_stdout:
        logger.debug(
            "suppressed MoviePy video reader stdout for "
            f"{video_path}, chars: {len(moviepy_stdout)}"
        )

    return clip


def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]

    # 영상을 반복해서 채울 때는 같은 임시 조각 경로가 FFmpeg 이어붙이기 목록에 여러 번 등장한다.
    # 이어붙이기는 중복 항목을 그대로 둬야 하지만 정리는 한 번만 삭제할 수 있다. 여기서 원래
    # 순서를 유지하며 중복을 제거해, 모든 호출자가 멱등한 동작을 얻고 첫 삭제가 성공한 뒤
    # FileNotFoundError 가 줄줄이 출력되는 것도 막는다.
    unique_files = dict.fromkeys(file for file in files if file)
    for file in unique_files:
        try:
            os.remove(file)
        except FileNotFoundError:
            # 정리 작업은 파일이 이미 없는 경우를 허용한다. FFmpeg 실패 경로나 동시 정리가 이미
            # 파일을 회수했을 수 있다. 이는 사용자가 처리할 문제가 아니므로 생성 로그를 더럽혀서는 안 된다.
            continue
        except OSError as e:
            # 권한, 읽기 전용 파일 시스템, 디스크 이상은 실제 임시 파일을 남긴다. warning 을 남겨
            # 구체적인 경로와 시스템 오류로 환경 문제를 짚을 수 있게 한다.
            logger.warning(f"failed to delete temporary file {file}: {str(e)}")


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file:
        try:
            resolved_bgm_file = bgm_service.resolve_bgm_file(bgm_file)
        except ValueError as exc:
            # API 요청의 bgm_file 은 사용자 입력이므로, 사용자 BGM 또는 내장 음원 디렉터리로만
            # 해석되도록 허용한다. MoviePy 가 설정이나 키 같은 임의의 서버 파일을 읽지 못하게 하기 위해서다.
            logger.warning(
                f"reject unsafe bgm file: {bgm_file}, error: {str(exc)}"
            )
            return ""
        return resolved_bgm_file

    if bgm_type == "random":
        files = bgm_service.list_bgm_files()
        # 배경음악 디렉터리가 비어 있으면 곧바로 'BGM 사용 안 함' 으로 되돌려, random.choice([]) 가 예외를 던지지 않게 한다.
        if not files:
            logger.warning("no background music files found")
            return ""
        return random.choice(files)

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
    clip_speed: float = 1.0,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    try:
        # 여기서는 소재 영상을 이어붙일 길이를 정하려고 나레이션 오디오 길이만 읽으면 되고,
        # 이후로는 audio_clip 을 쓰지 않는다. 다 읽으면 바로 닫아, 조기 반환이나 예외 경로에서
        # 파일 핸들이 새지 않게 한다.
        audio_duration = audio_clip.duration
    finally:
        close_clip(audio_clip)
    logger.info(f"audio duration: {audio_duration} seconds")
    logger.info(f"maximum clip duration: {max_clip_duration} seconds")
    required_video_duration = _get_required_video_duration(audio_duration)
    logger.info(
        f"required video duration: {required_video_duration:.2f} seconds "
        f"(audio duration + {_VIDEO_DURATION_SAFETY_MARGIN:.2f}s safety margin)"
    )

    # API 를 직접 호출할 때 전환 모드를 넘기지 않은 경우를 지원해, 이후 .value 에 접근하다가 죽지 않게 한다.
    transition_value = getattr(video_transition_mode, "value", video_transition_mode)
    normalized_clip_speed = utils.normalize_clip_speed(clip_speed)
    if normalized_clip_speed != 1.0:
        # 최종 적용값을 한 번만 기록한다. API 의 범위 밖 파라미터가 정규화된 문제를 짚기 쉬우면서,
        # 조각마다 도는 핫 패스에서 같은 로그가 반복 출력되지도 않는다.
        logger.info(f"clip playback speed: {normalized_clip_speed:.2f}x")
    # max_clip_duration 이 제한하는 것은 결과물의 최종 재생 길이이지 원본 영상의 읽기 길이가
    # 아니다. MoviePy 가 1.5 초짜리 원본을 0.5 배속으로 재생하면 3 초 조각이 되고, 6 초짜리
    # 원본을 2 배속으로 재생해도 3 초 조각이 된다. 따라서 자르기 전에 속도로 원본 길이를
    # 역산해야 한다. 여전히 3 초를 고정으로 읽고 느리게 재생한 뒤 잘라 내면서 다음 조각은
    # 원본 3 초 지점부터 시작하면, 중간 1.5 초 화면이 통째로 건너뛰어진다. 이 계산은 속도가
    # 달라도 원본 타임라인이 끊기거나 겹치지 않도록 함께 보장한다.
    source_clip_duration = max_clip_duration * normalized_clip_speed
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    processed_clips = []
    subclipped_items = []
    video_duration = 0
    for video_path in video_paths:
        clip = _open_video_clip_quietly(video_path)
        clip_duration = clip.duration
        clip_w, clip_h = clip.size
        close_clip(clip)
        
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + source_clip_duration, clip_duration)

            # 유효한 구간은 모두 남긴다.
            # 이렇게 하면 '영상 전체가 max_clip_duration 보다 짧은' 소재를 잃지 않고,
            # 긴 영상의 마지막에 남은 짧은 꼬리 부분도 삼켜 버리지 않는다.
            if end_time > start_time:
                subclipped_items.append(
                    SubClippedVideoClip(
                        file_path=video_path,
                        start_time=start_time,
                        end_time=end_time,
                        width=clip_w,
                        height=clip_h,
                        source_file_path=video_path,
                    )
                )

            start_time = end_time
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    subclipped_items = _prioritize_unique_source_clips(
        subclipped_items=subclipped_items,
        concat_mode=video_concat_mode,
    )
        
    logger.debug(f"total subclipped items: {len(subclipped_items)}")
    
    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    for i, subclipped_item in enumerate(subclipped_items):
        if video_duration >= required_video_duration:
            break
        
        logger.debug(
            f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, "
            f"source: {os.path.basename(subclipped_item.source_file_path)}, "
            f"current duration: {video_duration:.2f}s, "
            f"remaining: {required_video_duration - video_duration:.2f}s"
        )
        
        try:
            clip = _open_video_clip_quietly(subclipped_item.file_path).subclipped(
                subclipped_item.start_time, subclipped_item.end_time
            )
            # 재생 속도는 소재 자체의 속성이므로 전환보다 먼저 적용해야 한다. 그래야 Fade/Slide
            # 같은 1 초 전환이 소재 속도를 따라 0.5 초나 2 초가 되지 않는다. 이후의 최대 길이
            # 자르기는 부동소수점 오차나 비정상 소재 길이에 대한 안전장치로 계속 남아, 최종
            # 조각이 설정 상한을 넘지 않도록 보장한다.
            if normalized_clip_speed != 1.0:
                clip = clip.with_speed_scaled(normalized_clip_speed)
            clip_duration = clip.duration
            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                logger.debug(f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}")
                
                if clip_ratio == video_ratio:
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)

                    background = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)
                    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                    clip = CompositeVideoClip([background, clip_resized])
                    
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if transition_value in (None, VideoTransitionMode.none.value):
                clip = clip
            elif transition_value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip, 1)
            elif transition_value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip, 1)
            elif transition_value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip, 1, shuffle_side)
            elif transition_value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip, 1, shuffle_side)
            elif transition_value == VideoTransitionMode.zoom_in.value:
                clip = video_effects.zoomin_transition(clip, 1)
            elif transition_value == VideoTransitionMode.zoom_out.value:
                clip = video_effects.zoomout_transition(clip, 1)
            elif transition_value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c, 1),
                    lambda c: video_effects.fadeout_transition(c, 1),
                    lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                    lambda c: video_effects.zoomin_transition(c, 1),
                    lambda c: video_effects.zoomout_transition(c, 1),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)
                
            # wirte clip to temp file
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            _write_videofile_with_codec_fallback(
                clip,
                clip_file,
                codec=_get_configured_video_codec(),
                logger=None,
                fps=fps,
            )

            # Store clip duration before closing
            clip_duration_saved = clip.duration
            close_clip(clip)

            processed_clips.append(
                SubClippedVideoClip(
                    file_path=clip_file,
                    duration=clip_duration_saved,
                    width=clip_w,
                    height=clip_h,
                    source_file_path=subclipped_item.source_file_path,
                )
            )
            video_duration += clip_duration_saved
            
        except Exception as e:
            logger.error(f"failed to process clip: {str(e)}")
    
    # loop processed clips until the video duration covers the audio duration and the small safety margin.
    if video_duration < required_video_duration:
        logger.warning(
            f"video duration ({video_duration:.2f}s) is shorter than required duration "
            f"({required_video_duration:.2f}s), looping clips to match audio length."
        )
        base_clips = processed_clips.copy()
        for clip in itertools.cycle(base_clips):
            if video_duration >= required_video_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
        logger.info(
            f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, "
            f"required duration: {required_video_duration:.2f}s, "
            f"looped {len(processed_clips)-len(base_clips)} clips"
        )
     
    # merge video clips progressively, avoid loading all videos at once to avoid memory overflow
    logger.info("starting clip merging process")
    if not processed_clips:
        logger.warning("no clips available for merging")
        return combined_video_path
    
    clip_files = [clip.file_path for clip in processed_clips]
    logger.info(f"concatenating {len(clip_files)} clips with ffmpeg")
    concat_video_clips_with_ffmpeg(
        clip_files=clip_files,
        output_file=combined_video_path,
        threads=threads,
        output_dir=output_dir,
        max_duration=audio_duration,
    )
    
    # clean temp files
    delete_files(clip_files)
            
    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # 자막 줄바꿈은 TextClip 을 실제로 만들기 전에 끝내야 한다. 그러지 않으면 MoviePy 가 원본
    # 텍스트 기준으로만 렌더링 영역을 계산한다. 여기서 PIL 로 현재 글꼴과 크기에 맞춰 폭을 재,
    # 각 줄이 최대한 영상의 가용 폭 안에 들어가게 한다. 큰 글자나 긴 문장이 화면 밖으로
    # 넘치는 것을 막기 위해서다.
    font = ImageFont.truetype(font, fontsize)
    max_width = int(max_width)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        if not inner_text:
            return 0, fontsize
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    def split_long_token(token):
        # 토큰 하나가 이미 폭을 넘는 경우 (공백 없는 긴 문장이나 아주 긴 영어 단어에서 흔하다)
        # 글자 단위 분할로 낮춘다. 핵심은 candidate 가 폭을 넘는 것을 감지하면 아직 유효한 이전
        # current 를 먼저 확정하고, 현재 글자는 다음 줄로 넘기는 것이다. 폭을 넘긴 글자를
        # 이전 줄에 다시 밀어 넣어서는 안 된다.
        lines = []
        current = ""
        for char in token:
            candidate = f"{current}{char}"
            candidate_width, _ = get_text_size(candidate)
            if candidate_width <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = char
        if current:
            lines.append(current)
        return lines

    lines = []
    current = ""
    words = text.split(" ")
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)

        word_width, _ = get_text_size(word)
        if word_width <= max_width:
            current = word
        else:
            lines.extend(split_long_token(word))
            current = ""

    if current:
        lines.append(current)

    line_start_punctuation = "，。！？；：、,.!?;:)]}）】》」』”’"
    for index in range(1, len(lines)):
        # 긴 문장을 글자 단위로 나눌 때 마지막 마침표나 쉼표 같은 닫는 문장 부호가 혼자 다음 줄로
        # 밀려날 수 있다. 그러면 자막 배경이 비정상적으로 높아져, 본문 아래에 점 하나가 떨어진
        # 것처럼 보인다. 여기서는 줄바꿈 알고리즘을 다시 설계하지 않고, 이전 줄의 마지막 글자를
        # 문장 부호 줄 앞으로 옮겨 부호가 글자를 따라 표시되게 한다. 한글·영문에서 흔한 닫는
        # 문장 부호에 모두 적용된다.
        if not lines[index] or lines[index][0] not in line_start_punctuation:
            continue
        if len(lines[index - 1]) <= 1:
            continue

        candidate = f"{lines[index - 1][-1]}{lines[index]}"
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            lines[index] = candidate
            lines[index - 1] = lines[index - 1][:-1]

    result = "\n".join(line.strip() for line in lines if line.strip()).strip()
    height = len(lines) * height
    return result, height


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    # 자막 배경색은 API/WebUI 파라미터에서 오므로 비어 있거나 형식이 어긋날 수 있다. 여기서는
    # #RRGGBB 형식만 받아들이고 잘못된 값은 검은색으로 되돌려, PIL 렌더링 단계에서 예외가 나
    # 작업이 끊기는 것을 막는다.
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        try:
            return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        except ValueError:
            pass
    return (0, 0, 0)


def _rounded_subtitle_background_clip(
    width: int,
    height: int,
    color: str,
    alpha: int = 140,
    radius: int = 16,
) -> ImageClip:
    # 새 자막 배경은 사용자가 명시적으로 켰을 때만 쓴다. RGBA 이미지로 둥근 모서리의 반투명
    # 바탕을 그린 뒤 MoviePy 에 투명 ImageClip 으로 넘겨 합성에 참여시킨다. 이렇게 하면 기본
    # 경로는 전혀 바뀌지 않으면서, 더 부드러운 자막 시각 효과를 적은 비용으로 시험해 볼 수 있다.
    rgb = _hex_to_rgb(color)
    safe_alpha = max(0, min(255, int(alpha)))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, max(0, width - 1), max(0, height - 1)],
        radius=max(0, int(radius)),
        fill=(rgb[0], rgb[1], rgb[2], safe_alpha),
    )
    return ImageClip(np.array(img), transparent=True)


def _get_visible_center_position(
    text_clip: TextClip,
    container_width: int,
    container_height: int,
) -> tuple[int, int]:
    """
    글자의 실제로 보이는 픽셀을 기준으로 TextClip 을 배경 컨테이너 중앙에 놓는다.

    MoviePy 의 TextClip 은 글꼴의 행 높이와 baseline 에 맞춰 투명 캔버스를 만든다. 많은 글꼴에서
    실제로 보이는 글자 모양은 이 캔버스의 기하학적 중심에 있지 않다. 그래서 `with_position("center")`
    를 그대로 쓰면 투명 캔버스 전체가 가운데로 가서 자막이 위나 아래로 치우쳐 보인다. 여기서는
    TextClip 의 투명 mask 를 읽어 실제 픽셀이 있는 bbox 만으로 오프셋을 계산해, 사용자가 보는
    글자가 자막 배경 안에서 시각적으로 가운데 오게 한다.
    """
    x = int(round((container_width - text_clip.w) / 2))
    y = int(round((container_height - text_clip.h) / 2))

    try:
        if text_clip.mask is None:
            return x, y

        mask_frame = text_clip.mask.get_frame(0)
        ys, _ = np.where(mask_frame > 0.01)
        if len(ys) == 0:
            return x, y

        visible_top = int(ys.min())
        visible_bottom = int(ys.max())
        visible_height = visible_bottom - visible_top + 1
        y = int(round((container_height - visible_height) / 2 - visible_top))
    except Exception as exc:
        logger.debug(f"failed to center subtitle text by visible mask: {str(exc)}")

    return x, y


def subtitle_colors_are_indistinguishable(params: VideoParams) -> bool:
    """자막 글자와 배경이 같은 색인지 판정해, 자막이 보이지 않을 수 있음을 사용자에게 알린다."""
    if not params.subtitle_enabled or not params.text_background_color:
        return False

    def normalize_color(value):
        if isinstance(value, bool):
            return "#000000" if value else ""
        return str(value or "").strip().lower()

    text_color = normalize_color(params.text_fore_color)
    background_color = normalize_color(params.text_background_color)
    return bool(text_color and text_color == background_color)


@lru_cache(maxsize=64)
def _subtitle_font_supports_sample(font_path: str, sample: str) -> bool:
    """글꼴이 예시 텍스트에 필요한 글리프를 갖고 있는지 확인하고, 반복 확인 결과를 캐시한다."""
    try:
        font = ImageFont.truetype(font_path, 30)
        missing_mask = font.getmask("\U0010ffff")
        missing_signature = (
            missing_mask.size,
            missing_mask.getbbox(),
            bytes(missing_mask),
        )
        for char in sample:
            char_mask = font.getmask(char)
            char_signature = (
                char_mask.size,
                char_mask.getbbox(),
                bytes(char_mask),
            )
            if char_mask.getbbox() is None or char_signature == missing_signature:
                return False
        return True
    except Exception as e:
        # 글꼴 탐지 실패가 사용자의 생성을 막아서는 안 된다. 환경 호환 문제를 짚을 수 있게 로그는 남긴다.
        logger.warning(f"failed to inspect subtitle font glyphs: {font_path}, {e}")
        return True


def subtitle_font_supports_text(font_path: str, text: str) -> bool:
    """글꼴이 텍스트의 문자와 숫자를 그릴 수 있는지 확인한다. 공백과 문장 부호는 무시한다."""
    sample = "".join(
        dict.fromkeys(
            char
            for char in str(text or "")
            if unicodedata.category(char)[0] in {"L", "N"}
        )
    )[:64]
    if not sample:
        return True
    return _subtitle_font_supports_sample(font_path, sample)


# 자막 글꼴은 WebUI 설정, config.toml, CLI 인자, API 파라미터 어디서든 올 수 있고,
# 저장된 값이 대본 언어와 맞지 않으면 자막이 통째로 두부(□)로 렌더링된다. 원본
# 프로젝트가 번들한 글꼴은 중국어·일본어용이라 한글이 없고, 반대로 한글 글꼴에는
# 한자·가나가 없다. 어느 한쪽을 기본값으로 고정하면 다른 쪽이 깨지므로, 생성
# 시점에 실제 자막 텍스트를 그릴 수 있는지 보고 필요할 때만 교체한다.
DEFAULT_SUBTITLE_FONT = "Pretendard-Bold.ttf"


def _read_subtitle_text(subtitle_path: str) -> str:
    try:
        with open(subtitle_path, mode="r", encoding="utf-8") as fp:
            return fp.read()
    except OSError:
        return ""


def resolve_subtitle_font(font_name: str, subtitle_path: str) -> str:
    """
    선택된 글꼴이 이번 자막을 그릴 수 없으면 그릴 수 있는 번들 글꼴로 교체한다.

    선택값을 무조건 덮지 않는다. 일본어 대본에 MicrosoftYaHei 를 고른 사용자는
    그대로 유지되고, 한국어 대본에 같은 글꼴이 저장돼 있을 때만 교체된다.
    교체는 사용자가 명시한 값을 바꾸는 동작이므로 경고를 남긴다.
    """
    subtitle_text = _read_subtitle_text(subtitle_path)
    if not subtitle_text:
        return font_name

    font_dir = utils.font_dir()
    if subtitle_font_supports_text(os.path.join(font_dir, font_name), subtitle_text):
        return font_name

    for candidate in sorted(os.listdir(font_dir)):
        if not candidate.lower().endswith((".ttf", ".ttc")):
            continue
        if subtitle_font_supports_text(os.path.join(font_dir, candidate), subtitle_text):
            logger.warning(
                f"subtitle font '{font_name}' cannot render this script, "
                f"falling back to '{candidate}'"
            )
            return candidate

    # 그릴 수 있는 글꼴이 하나도 없으면 사용자의 선택을 그대로 둔다. 임의로 바꿔도
    # 결과가 나아지지 않고, 원래 값이 남아 있어야 어떤 글꼴이 문제인지 알 수 있다.
    logger.warning(
        f"no bundled font can render this script, keeping '{font_name}'"
    )
    return font_name


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
    bgm_file_override: str | None = None,
) -> bool:
    """
    최종 영상을 합성하고, 이번 배경음악 처리가 성공했는지 반환한다.

    반환값은 BGM 처리 상태만 나타낸다. BGM 을 요청하지 않았거나 성공적으로 믹싱했으면 True 를,
    BGM 을 요청했지만 로딩·효과·믹싱이 실패했으면 False 를 반환한다. BGM 이 실패해도 나레이션만
    있는 영상은 계속 출력하며, 사용자에게 기능 저하 경고를 보여 줄지는 작업 조율 계층이 결정한다.
    """
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"generating video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = DEFAULT_SUBTITLE_FONT
        params.font_name = resolve_subtitle_font(params.font_name, subtitle_path)
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"  ⑤ font: {font_path}")

    def resolve_subtitle_background_color():
        # 예전 파라미터 호환: API 의 `text_background_color` 는 불리언일 수도 있고 실제 색상
        # 문자열일 수도 있다. 여기서 한곳에 정규화해, True/False 를 TextClip 에 그대로 넘겼을 때
        # 예측할 수 없는 렌더링 결과가 나오는 것을 막는다.
        if isinstance(params.text_background_color, bool):
            return "#000000" if params.text_background_color else None
        return params.text_background_color

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        bg_color = resolve_subtitle_background_color()
        rounded_bg_enabled = bool(
            getattr(params, "rounded_subtitle_background", False) and bg_color
        )
        has_subtitle_background = bool(bg_color)
        # 둥근 배경은 글자의 실제 폭에 맞춰 만들므로 좌우 여백을 더 절제해야 한다. 예전 사각형
        # 배경은 여유 있는 안전 여백을 그대로 둬, 예전 설정의 긴 자막이 가장자리에 붙거나
        # 잘리지 않게 한다.
        padding_ratio = 0.4 if rounded_bg_enabled else 0.6
        pad_x = int(params.font_size * padding_ratio) if has_subtitle_background else 0
        # 자막 배경은 글자 좌우에 분명한 안쪽 여백을 둬야 한다. 가용 폭에서 padding 을 먼저 빼고
        # 줄바꿈해, 긴 영문이나 큰 글자가 영상 폭의 90% 를 꽉 채웠을 때 글자가 배경 테두리에 붙어
        # 잘린 것처럼 보이는 것을 막는다. 일반 사각형 배경과 둥근 배경 모두 이 로직을 탄다.
        # 배경 없는 자막은 기존 최대 폭을 그대로 유지한다.
        text_max_width = max(1, int(max_width) - 2 * pad_x)
        wrapped_txt, txt_height = wrap_text(
            phrase,
            max_width=text_max_width,
            font=font_path,
            fontsize=params.font_size,
        )
        interline = int(params.font_size * 0.25)
        line_count = wrapped_txt.count("\n") + 1
        vertical_padding = int(params.font_size * 0.35)
        text_clip_margin_y = max(
            int(params.font_size * 0.3), int(params.stroke_width * 2)
        )
        # MoviePy 는 `method=label` 에서 텍스트 상자 높이를 자동으로 줄인다. 여러 줄 자막,
        # 테두리, 배경색이 있으면 마지막 줄의 아랫부분이 잘리기 쉽다. 여기서는 더 보수적인
        # 높이를 명시적으로 넘겨 줄 간격과 위아래 여백까지 함께 계산해, 자막 배경 상자와 글자
        # 자체가 온전히 렌더링되도록 보장한다.
        clip_h = int(txt_height + vertical_padding + (interline * line_count))

        if rounded_bg_enabled:
            # 둥근 배경은 영상 폭의 90% 를 그대로 쓰는 대신 글자 폭에 맞춰야 한다. 여기서 PIL 로
            # 가장 긴 줄을 먼저 재고 가로 안쪽 여백을 더해, 짧은 자막에 지나치게 넓은 바탕이
            # 생기는 것을 막는다.
            try:
                font = ImageFont.truetype(font_path, params.font_size)
                text_w = max(
                    int(font.getbbox(line)[2] - font.getbbox(line)[0])
                    for line in wrapped_txt.split("\n")
                )
            except Exception as exc:
                logger.warning(
                    f"failed to measure subtitle text width, fallback to max width: {str(exc)}"
                )
                text_w = int(max_width)

            box_w = max(1, min(int(max_width), text_w + 2 * pad_x))
            radius = max(8, int(params.font_size * 0.4))
            text_clip = TextClip(
                text=wrapped_txt,
                font=font_path,
                font_size=params.font_size,
                color=params.text_fore_color,
                bg_color=None,
                stroke_color=params.stroke_color,
                stroke_width=params.stroke_width,
                interline=interline,
                size=(box_w, None),
                text_align="center",
                margin=(0, text_clip_margin_y),
            )
            clip_h = max(clip_h, text_clip.h)
            bg_clip = _rounded_subtitle_background_clip(
                width=box_w,
                height=clip_h,
                color=bg_color,
                alpha=140,
                radius=radius,
            )
            text_position = _get_visible_center_position(text_clip, box_w, clip_h)
            _clip = CompositeVideoClip(
                [bg_clip, text_clip.with_position(text_position)],
                size=(box_w, clip_h),
            )
        elif bg_color:
            size = (
                int(max_width),
                clip_h,
            )
            text_clip = TextClip(
                text=wrapped_txt,
                font=font_path,
                font_size=params.font_size,
                color=params.text_fore_color,
                bg_color=None,
                stroke_color=params.stroke_color,
                stroke_width=params.stroke_width,
                interline=interline,
                size=(int(max_width), None),
                text_align="center",
                margin=(0, text_clip_margin_y),
            )
            size = (size[0], max(size[1], text_clip.h))
            bg_clip = _rounded_subtitle_background_clip(
                width=size[0],
                height=size[1],
                color=bg_color,
                alpha=255,
                radius=0,
            )
            text_position = _get_visible_center_position(text_clip, size[0], size[1])
            _clip = CompositeVideoClip(
                [bg_clip, text_clip.with_position(text_position)],
                size=size,
            )
        else:
            size = (
                int(max_width),
                clip_h,
            )
            _clip = TextClip(
                text=wrapped_txt,
                font=font_path,
                font_size=params.font_size,
                color=params.text_fore_color,
                bg_color=None,
                stroke_color=params.stroke_color,
                stroke_width=params.stroke_width,
                interline=interline,
                size=size,
                text_align="center",
            )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.with_start(subtitle_item[0][0])
        _clip = _clip.with_end(subtitle_item[0][1])
        _clip = _clip.with_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.with_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.with_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # Ensure the subtitle is fully within the screen bounds
            margin = 10  # Additional margin, in pixels
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(
                min_y, min(custom_y, max_y)
            )  # Constrain the y value within the valid range
            _clip = _clip.with_position(("center", custom_y))
        else:  # center
            _clip = _clip.with_position(("center", "center"))
        return _clip

    # MoviePy 의 CompositeAudioClip.close() 는 하위 AudioFileClip 을 닫지 않는다. 여기서
    # ExitStack 으로 모든 원본 파일 reader 를 명시적으로 들고 있어, 성공·자막 예외·믹싱 실패·
    # 영상 쓰기 실패 어느 경로에서도 FFmpeg 자식 프로세스를 놓아주게 한다. 특히 Windows 에서
    # 파일이 사용 중으로 잠기는 것을 막는다.
    with ExitStack() as clip_stack:
        source_video_clip = clip_stack.enter_context(
            _open_video_clip_quietly(video_path)
        )
        voice_source_clip = clip_stack.enter_context(AudioFileClip(audio_path))
        video_clip = source_video_clip
        audio_clip = voice_source_clip.with_effects(
            [afx.MultiplyVolume(params.voice_volume)]
        )

        def make_textclip(text):
            return TextClip(
                text=text,
                font=font_path,
                font_size=params.font_size,
            )

        if subtitle_path and os.path.exists(subtitle_path):
            sub = clip_stack.enter_context(
                SubtitlesClip(
                    subtitles=subtitle_path,
                    encoding="utf-8",
                    make_textclip=make_textclip,
                )
            )
            text_clips = []
            for item in sub.subtitles:
                clip = create_text_clip(subtitle_item=item)
                text_clips.append(clip)
            video_clip = CompositeVideoClip([video_clip, *text_clips])
            clip_stack.callback(video_clip.close)

        bgm_enabled = bgm_service.should_use_bgm(
            params.bgm_type, params.bgm_volume
        )
        if not bgm_enabled and params.bgm_type:
            # 모든 BGM 소스가 이 단축 규칙을 공유한다. 음량이 0 이하이면 무작위나 사용자 지정
            # 파일을 해석해서도 안 되고 제공자가 돌려준 파일을 로딩해서도 안 된다. 의미 없는
            # IO 와 믹싱을 피하기 위해서다.
            logger.info(
                f"skipping background music because volume is not positive: "
                f"type={params.bgm_type}, volume={params.bgm_volume}"
            )

        # 제공자 배경음악은 작업 조율 계층이 해당 파일을 직접 넘길 수 있다. None 은 무작위/사용자
        # 지정 BGM 해석을 그대로 따른다는 뜻이고, 빈 문자열은 이 BGM 을 명확히 끈다는 뜻이다.
        # 다만 어떤 소스든 공용 음량 규칙을 먼저 통과해야 한다.
        bgm_file = ""
        if bgm_enabled:
            bgm_file = (
                bgm_file_override
                if bgm_file_override is not None
                else get_bgm_file(
                    bgm_type=params.bgm_type,
                    bgm_file=params.bgm_file,
                )
            )
        bgm_mix_succeeded = True
        if bgm_file:
            try:
                bgm_effects = [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                ]
                # 서비스 안에서 해석한 무작위/사용자 지정 음악은 결과물보다 짧을 수 있어 반복해서
                # 채워야 한다. 작업 계층이 override 로 넘긴 파일은 제공자가 이미 길이를 맞췄다는
                # 뜻이다. 여기서는 파일 출처로 반복 여부를 정해, 앞으로 제공자를 추가할 때마다
                # 이름 화이트리스트를 고치지 않아도 되게 한다.
                if bgm_file_override is None:
                    bgm_effects.append(afx.AudioLoop(duration=video_clip.duration))
                bgm_source_clip = clip_stack.enter_context(AudioFileClip(bgm_file))
                bgm_clip = bgm_source_clip.with_effects(bgm_effects)
                audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
            except Exception:
                bgm_mix_succeeded = False
                # 스택 전체와 안정적인 맥락을 기록해 파일 디코딩, MoviePy 효과, CompositeAudioClip
                # 실패를 구분할 수 있게 한다. 파일 내용과 API 키는 로그에 들어가지 않는다.
                logger.exception(
                    f"failed to mix background music: type={params.bgm_type}, "
                    f"file={bgm_file}"
                )

        final_video_clip = video_clip.with_audio(audio_clip)
        clip_stack.callback(final_video_clip.close)
        # 입력 오디오의 샘플레이트를 명시적으로 그대로 쓰고, 가져올 수 없으면 MoviePy 기본값인
        # 44100Hz 로 되돌린다. 이렇게 하면 환경에 따라, 특히 Docker 안에서 다시 리샘플링되며
        # 음질이 흔들리는 일을 줄일 수 있다.
        output_audio_fps = int(getattr(audio_clip, "fps", 0) or 44100)
        _write_videofile_with_codec_fallback(
            final_video_clip,
            output_file=output_file,
            codec=_get_configured_video_codec(),
            audio_codec=audio_codec,
            audio_fps=output_audio_fps,
            audio_bitrate=audio_bitrate,
            temp_audiofile_path=_get_temp_audio_dir(output_dir),
            threads=params.n_threads or 2,
            logger=None,
            fps=fps,
        )
        return bgm_mix_succeeded


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    # WebUI 는 재생성 상황에서 빈 소재 목록을 넘길 수 있다. 여기서 빈 결과를 바로 반환해 NoneType 예외를 막는다.
    if not materials:
        return []

    # 전처리 검증을 통과한 소재만 반환해, 저해상도 이미지가 이후 영상 합성 흐름으로 계속 넘어가지 않게 한다.
    valid_materials = []
    local_videos_dir = utils.storage_dir("local_videos", create=True)

    for material in materials:
        if not material.url:
            continue

        try:
            material_source_path = file_security.resolve_path_within_directory(
                local_videos_dir, material.url
            )
        except ValueError as exc:
            # local video_source 의 소재 경로는 API 파라미터에서 오므로 전용 소재 디렉터리로
            # 제한해야 한다. 사용자가 파일명을 넘기는 것도, 예전에 반환되던 절대 경로도 지원하지만
            # 시스템의 다른 디렉터리로 빠져나가는 것은 허용하지 않는다. 임의 파일 읽기나 MoviePy 로
            # 로컬 민감 파일을 탐지하는 것을 막기 위해서다.
            logger.warning(
                f"skip unsafe local material: {material.url}, "
                f"local_videos_dir: {local_videos_dir}, error: {str(exc)}"
            )
            continue

        ext = utils.parse_extension(material_source_path)
        try:
            # 이미지 소재는 이미지 방식으로 바로 읽는다. VideoFileClip 이 먼저 오판한 뒤 불안정한 대비 분기를 타는 것을 막기 위해서다.
            if ext in const.FILE_TYPE_IMAGES:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            else:
                clip = _open_video_clip_quietly(material_source_path)
        except Exception:
            # 비표준 확장자이거나 탐지에 실패하면 이미지 모드로 되돌린다. 예전처럼 로컬 이미지 경로를 직접 넘기던 경우를 지원하기 위해서다.
            try:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            except Exception as exc:
                logger.warning(
                    f"skip unreadable local material: {material.url}, error: {str(exc)}"
                )
                continue
        try:
            width = clip.size[0]
            height = clip.size[1]
            if not is_material_resolution_acceptable(width, height):
                logger.warning(
                    f"low resolution material: {width}x{height}, minimum "
                    f"{_MIN_MATERIAL_DIMENSION}x{_MIN_MATERIAL_DIMENSION} required "
                    f"(tolerance {_MIN_DIMENSION_TOLERANCE}px)"
                )
                # 저해상도 소재를 감지하면 즉시 자원을 닫고, 그 소재를 이후 흐름에 반환하지 않는다.
                close_clip(clip)
                continue

            if ext in const.FILE_TYPE_IMAGES:
                logger.info(f"processing image: {material_source_path}")
                # 크기를 탐지할 때 소재를 이미 한 번 열었으므로, 탐지용 핸들을 먼저 놓아주고 내보내기용 이미지 clip 을 새로 만든다.
                close_clip(clip)
                # Create an image clip and set its duration to 3 seconds
                clip = (
                    ImageClip(material_source_path)
                    .with_duration(clip_duration)
                    .with_position("center")
                )
                # Apply a zoom effect using the resize method.
                # A lambda function is used to make the zoom effect dynamic over time.
                # The zoom effect starts from the original size and gradually scales up to 120%.
                # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
                # Note: 1 represents 100% size, so 1.2 represents 120% size.
                zoom_clip = clip.resized(
                    lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
                )

                # Optionally, create a composite video clip containing the zoomed clip.
                # This is useful when you want to add other elements to the video.
                final_clip = CompositeVideoClip([zoom_clip])

                # Output the video to a file.
                video_file = f"{material_source_path}.mp4"
                final_clip.write_videofile(video_file, fps=30, logger=None)
                close_clip(clip)
                close_clip(final_clip)
                material.url = video_file
                logger.success(f"image processed: {video_file}")
            else:
                # 일반 영상 소재는 크기만 읽어 검증하면 되므로, 검증이 끝나면 바로 핸들을 놓아준다.
                close_clip(clip)
                # Update url to the resolved absolute path so that downstream
                # stages (combine_videos) can open the file without re-resolving.
                material.url = material_source_path
        except Exception:
            close_clip(clip)
            raise

        valid_materials.append(material)

    return valid_materials
