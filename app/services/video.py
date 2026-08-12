import itertools
import io
import os
import random
import re
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
    vfx,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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
# Docker 里的 ffmpeg/AAC 组合在默认配置下更容易出现音频质量波动，
# 这里显式抬高音频码率，避免成片阶段因为默认值过低而引入明显失真。
audio_bitrate = "192k"
fps = 30
# FFmpeg 按帧率拼接/转码时，最终时长可能比 MoviePy 读到的理论时长短几十毫秒。
# 这里给视频素材多留一个很小的安全余量，避免音频末尾因为帧舍入出现黑屏、
# 卡顿或最后一小段旁白没有画面的情况。
_VIDEO_DURATION_SAFETY_MARGIN = 0.1
_MIN_MATERIAL_DIMENSION = 480
# 消息类应用和部分编码器会把画面尺寸向下取整，例如 WhatsApp 会把 9:16 的
# 素材压成 478x850，比 480 少两个像素。直接按 480 硬卡会让这类素材全部被
# 丢弃，最终以 "no valid materials found" 整体失败。这里留一个很小的容差，
# 既能放行仅仅因为取整而略低于阈值的素材，也仍然能挡住真正的低清素材。
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
    返回视频素材拼接的目标时长。

    使用场景：合成视频时需要素材时长覆盖旁白音频。只做到“刚好等于”
    音频时长时，FFmpeg 可能因为帧率舍入让最终视频略短，因此统一加一个
    轻量余量。函数独立出来，便于测试和后续按实际反馈调整余量大小。
    """
    return max(0.0, float(audio_duration) + _VIDEO_DURATION_SAFETY_MARGIN)


def is_material_resolution_acceptable(width: int, height: int) -> bool:
    """
    判断素材分辨率是否足够用于合成。

    标称最小值是 480x480，但允许比它低 `_MIN_DIMENSION_TOLERANCE` 个像素，
    以兼容编码器/消息应用向下取整导致的尺寸（例如 WhatsApp 的 478x850）。
    """
    min_dimension = _MIN_MATERIAL_DIMENSION - _MIN_DIMENSION_TOLERANCE
    return width >= min_dimension and height >= min_dimension


def _prioritize_unique_source_clips(
    subclipped_items: List[SubClippedVideoClip],
    concat_mode: VideoConcatMode,
) -> List[SubClippedVideoClip]:
    """
    优先让每个源素材只出现一次，降低成片里同一素材反复出现的概率。

    线上素材经常会遇到“一个长视频被切成多个短片段”的情况。旧逻辑在
    random 模式下直接打乱所有短片段，导致同一个源视频的多个切片可能
    分布在开头和中间，用户会感知为素材重复。本函数只调整片段顺序：
    先放每个源文件里最长的一个片段，剩余片段作为兜底；当素材总时长不足时，
    仍然允许后续片段补齐音频长度，避免破坏视频生成成功率。优先选择最长
    片段是为了避免随机选中视频尾部的零碎短片段，导致明明有足够素材却过早复用。
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
    兼容历史上直接从 video 服务读取 FFmpeg 路径的调用方。

    真正的解析逻辑已经抽到 `app.utils.utils.get_ffmpeg_binary()`，视频、语音
    和后续新增链路都应复用同一套优先级；这里保留薄包装，避免外部脚本或
    旧测试直接导入 `app.services.video.get_ffmpeg_binary` 时出现 AttributeError。
    """
    return utils.get_ffmpeg_binary()


def _get_configured_video_codec() -> str:
    """
    读取用户配置的视频编码器。

    该配置面向高级用户，用于尝试启用 NVENC/AMF/QSV/VideoToolbox 等硬件
    编码。这里刻意只允许固定白名单，避免开放任意 FFmpeg 参数后，用户填错
    参数导致输出格式不可控，甚至让生成任务在后续阶段才失败。
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
    检查当前 FFmpeg 是否声明支持指定编码器。

    这只能证明 FFmpeg 编译时包含该 encoder，不能证明当前机器硬件和驱动
    一定可用。因此实际编码失败时仍会再回退到 libx264。
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
    返回本次实际使用的视频编码器。

    用户选择硬件编码器时，先做 FFmpeg encoder 列表检测；如果本进程里已经
    实际编码失败过，也直接回退，避免一个任务里每个片段都重复失败。
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


def _fallback_write_videofile(
    clip, output_file: str, failed_codec: str, reason: str, **kwargs
):
    """
    硬件编码失败后用 libx264 重试，只有重试成功才禁用该硬件编码器。

    Windows 上 FFmpeg 失败原因比较复杂：可能是显卡/驱动不支持，也可能是输出
    文件被占用、目录权限、杀软拦截等通用 IO 问题。只有 libx264 能成功写出时，
    才能判断原始失败大概率来自硬件编码器本身，避免误伤后续任务。
    """
    clip.write_videofile(output_file, codec=_DEFAULT_VIDEO_CODEC, **kwargs)
    _disable_runtime_video_codec(failed_codec, reason)
    return _DEFAULT_VIDEO_CODEC


def _write_videofile_with_codec_fallback(clip, output_file: str, codec: str, **kwargs):
    """
    使用指定编码器写出视频，失败时自动用 libx264 重试一次。

    硬件编码器是否可用不仅取决于 FFmpeg，还取决于显卡、驱动和当前运行环境。
    生成任务不能因为高级编码器不可用而整体失败，所以这里把回退集中处理。
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
    # concat demuxer 使用单引号包裹路径，路径中的单引号需要先转义。
    return file_path.replace("'", "'\\''")


def _format_ffmpeg_concat_path(file_path: str) -> str:
    """
    生成 concat demuxer 文件列表中的路径。

    FFmpeg 官方文档要求 concat list 中的特殊字符和空格需要转义；Windows
    绝对路径里的反斜杠也容易被解析成转义字符。这里统一转成正斜杠形式，
    让 `C:\\Users\\...` 变成 `C:/Users/...`，再处理单引号，兼容 macOS/Linux。
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
        # 使用 ffmpeg 只做一次串联与编码，避免 MoviePy 逐段合并时反复重编码，
        # 从而降低画质劣化与颜色偏移风险。
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
    # 某些本地图片虽然能被 Pillow 打开，但会因为损坏的 EXIF/eXIf 元数据导致
    # ImageClip 在解析阶段直接抛异常。这里重新导出一份“干净图片”，把坏元数据剥离掉。
    image_root, _ = os.path.splitext(image_path)
    sanitized_path = f"{image_root}.sanitized.png"

    with Image.open(image_path) as image:
        image.load()
        # 统一导出为 PNG，避免 JPEG/PNG 不同元数据路径继续把坏块带过去。
        cleaned_image = Image.new(image.mode, image.size)
        cleaned_image.putdata(list(image.getdata()))
        cleaned_image.save(sanitized_path)

    return sanitized_path


def _open_image_clip_with_fallback(image_path: str):
    # 优先直接打开原始图片；如果因为损坏元数据失败，再尝试生成无元数据副本。
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
    安静地打开视频文件，避免 MoviePy 2.1.x 把 ffmpeg 探测信息直接打印到 stdout。

    背景：
    当前依赖版本的 `FFMPEG_VideoReader` 内部存在 `print(self.infos)` 和
    `print(ffmpeg command)`，读取无音轨的中间视频时会输出
    `audio_found: False`。这只是输入素材 metadata，不代表最终成片没有音频，
    但会误导 WebUI/终端用户以为生成失败。

    实现：
    1. 只在打开 VideoFileClip 的短窗口内重定向 stdout；
    2. 默认 `audio=False`，因为项目视频素材阶段不需要保留素材原声，
       最终音频会在 `generate_video()` 阶段统一挂载；
    3. 如果依赖库确实输出了内容，降级为 debug 日志，便于必要时排查。
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
        if hasattr(clip, "reader") and clip.reader is not None:
            clip.reader.close()

        # close audio resources
        if hasattr(clip, "audio") and clip.audio is not None:
            if hasattr(clip.audio, "reader") and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio

        # close mask resources
        if hasattr(clip, "mask") and clip.mask is not None:
            if hasattr(clip.mask, "reader") and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask

        # handle child clips in composite clips
        if hasattr(clip, "clips") and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)

        # clear clip list
        if hasattr(clip, "clips"):
            clip.clips = []

    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")

    del clip
    gc.collect()


def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]

    # 循环补足视频时，同一个临时片段路径会在 FFmpeg 拼接列表中出现多次。
    # 拼接必须保留重复项，但清理只能删除一次；这里按原顺序统一去重，让所有
    # 调用方都获得幂等行为，也避免首次删除成功后连续输出 FileNotFoundError。
    unique_files = dict.fromkeys(file for file in files if file)
    for file in unique_files:
        try:
            os.remove(file)
        except FileNotFoundError:
            # 清理动作允许文件已经不存在，例如 FFmpeg 失败路径或并发清理已经
            # 回收文件；这不是需要用户处理的问题，不应污染生成日志。
            continue
        except OSError as e:
            # 权限、只读文件系统或磁盘异常会留下真实临时文件，保留 warning
            # 便于根据具体路径和系统错误定位环境问题。
            logger.warning(f"failed to delete temporary file {file}: {str(e)}")


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file:
        try:
            resolved_bgm_file = bgm_service.resolve_bgm_file(bgm_file)
        except ValueError as exc:
            # API 请求里的 bgm_file 来自用户输入，只允许解析到用户 BGM 或内置
            # 歌曲目录，阻止 MoviePy 读取配置、密钥等任意服务器文件。
            logger.warning(f"reject unsafe bgm file: {bgm_file}, error: {str(exc)}")
            return ""
        return resolved_bgm_file

    if bgm_type == "random":
        files = bgm_service.list_bgm_files()
        # 当背景音乐目录为空时，直接回退为“不使用 BGM”，避免 random.choice([]) 抛异常。
        if not files:
            logger.warning("no background music files found")
            return ""
        return random.choice(files)

    return ""


def _center_crop_geometry(
    source_width: int,
    source_height: int,
    video_width: int,
    video_height: int,
) -> tuple[int, int, int, int]:
    """Largest centered rectangle of the source that already has the target ratio."""
    target_ratio = video_width / video_height
    if source_width / source_height > target_ratio:
        crop_width = min(source_width, int(round(source_height * target_ratio)))
        crop_height = source_height
    else:
        crop_width = source_width
        crop_height = min(source_height, int(round(source_width / target_ratio)))

    # yuv420p subsamples chroma by 2, so odd crop sizes are rejected by the encoder.
    crop_width -= crop_width % 2
    crop_height -= crop_height % 2
    return (
        crop_width,
        crop_height,
        (source_width - crop_width) // 2,
        (source_height - crop_height) // 2,
    )


def _pick_continuous_background_source(
    video_paths: List[str], source_duration_needed: float
) -> tuple[str, float, int, int] | None:
    """Pick a source long enough for the whole narration and a random start inside it."""
    candidates: List[tuple[str, float, int, int]] = []
    for video_path in video_paths:
        try:
            clip = _open_video_clip_quietly(video_path)
        except Exception as exc:
            logger.warning(
                f"failed to probe background source {video_path}: {str(exc)}"
            )
            continue

        try:
            source_duration = float(clip.duration or 0.0)
            source_width, source_height = clip.size
        finally:
            close_clip(clip)

        if source_duration >= source_duration_needed:
            candidates.append(
                (video_path, source_duration, int(source_width), int(source_height))
            )

    if not candidates:
        return None

    video_path, source_duration, source_width, source_height = random.choice(candidates)
    start_time = random.uniform(0.0, source_duration - source_duration_needed)
    return video_path, start_time, source_width, source_height


def _build_continuous_background(
    combined_video_path: str,
    video_paths: List[str],
    required_video_duration: float,
    video_width: int,
    video_height: int,
    threads: int,
    clip_speed: float,
) -> bool:
    """
    Write the background as one uninterrupted segment cut from a single source video.

    Cutting, cropping and scaling run inside a single FFmpeg filter chain. MoviePy would
    resample every frame in Python instead, which costs minutes per minute of footage.

    Returns False when no source is long enough or FFmpeg fails, so the caller falls
    back to the default multi-clip concatenation.
    """
    source_duration_needed = required_video_duration * clip_speed
    picked = _pick_continuous_background_source(video_paths, source_duration_needed)
    if picked is None:
        logger.warning(
            "continuous background needs one source video of at least "
            f"{source_duration_needed:.2f}s, falling back to clip concatenation"
        )
        return False

    source_path, start_time, source_width, source_height = picked
    crop_width, crop_height, crop_x, crop_y = _center_crop_geometry(
        source_width, source_height, video_width, video_height
    )
    filters = [
        f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}",
        f"scale={video_width}:{video_height}",
    ]
    if clip_speed != 1.0:
        filters.append(f"setpts=PTS/{clip_speed}")
    filters.append(f"fps={fps}")

    logger.info(
        f"continuous background: {os.path.basename(source_path)}, "
        f"start {start_time:.2f}s, {source_duration_needed:.2f}s of source footage, "
        f"crop {crop_width}x{crop_height}+{crop_x}+{crop_y}"
    )

    def build_command(codec: str) -> list[str]:
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            # Input-side seek and duration keep FFmpeg from decoding the skipped part
            # and stay correct when setpts rescales the output timeline.
            "-ss",
            f"{start_time:.3f}",
            "-t",
            f"{source_duration_needed:.3f}",
            "-i",
            source_path,
            "-an",
            "-vf",
            ",".join(filters),
            "-c:v",
            codec,
        ]
        if codec == _DEFAULT_VIDEO_CODEC:
            # This file is an intermediate that generate_video re-encodes anyway, and
            # the default preset costs ~3.5x the encoding time. Preset names are
            # encoder specific, so hardware codecs keep their own defaults.
            command.extend(["-preset", "veryfast"])
        command.extend(
            [
                "-threads",
                str(threads or 2),
                "-pix_fmt",
                "yuv420p",
                combined_video_path,
            ]
        )
        return command

    def run_cut(codec: str) -> None:
        result = subprocess.run(
            build_command(codec),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_message or "ffmpeg continuous background failed")

    try:
        effective_codec = _get_effective_video_codec()
        try:
            run_cut(effective_codec)
        except Exception as exc:
            if effective_codec == _DEFAULT_VIDEO_CODEC:
                raise
            run_cut(_DEFAULT_VIDEO_CODEC)
            _disable_runtime_video_codec(effective_codec, str(exc))
    except Exception as exc:
        logger.error(
            f"failed to cut continuous background: {str(exc)}, "
            "falling back to clip concatenation"
        )
        return False

    return True


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
    continuous_background: bool = False,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    try:
        # 这里只需要读取旁白音频时长来决定素材视频拼接长度；后续不会再使用
        # audio_clip。读取完成后立即关闭，避免早退或异常路径泄漏文件句柄。
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

    # 兼容 API 直接调用时未传转场模式的情况，避免后续访问 .value 时崩溃。
    transition_value = getattr(video_transition_mode, "value", video_transition_mode)
    normalized_clip_speed = utils.normalize_clip_speed(clip_speed)
    if normalized_clip_speed != 1.0:
        # 只记录一次最终生效值，既方便定位 API 越界参数被归一化的问题，
        # 也避免在逐片段热路径中重复输出相同日志。
        logger.info(f"clip playback speed: {normalized_clip_speed:.2f}x")
    # max_clip_duration 约束的是成片里的最终播放时长，而不是源视频读取时长。
    # MoviePy 以 0.5 倍速播放 1.5 秒源画面会得到 3 秒片段，以 2 倍速播放
    # 6 秒源画面同样会得到 3 秒片段。因此切片前必须按速度反推源时长；如果
    # 仍固定读取 3 秒再慢放、裁剪，下一段却从源视频第 3 秒开始，会跳过中间
    # 1.5 秒画面。该计算同时保证不同速度下的源时间线连续且无重叠。
    source_clip_duration = max_clip_duration * normalized_clip_speed
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    if continuous_background and _build_continuous_background(
        combined_video_path=combined_video_path,
        video_paths=video_paths,
        required_video_duration=required_video_duration,
        video_width=video_width,
        video_height=video_height,
        threads=threads,
        clip_speed=normalized_clip_speed,
    ):
        logger.info("video combining completed")
        return combined_video_path

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

            # 保留所有有效分段。
            # 这样既不会丢掉“整段视频本身就短于 max_clip_duration”的素材，
            # 也不会吞掉长视频最后剩下的一小段尾部内容。
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
            f"processing clip {i + 1}: {subclipped_item.width}x{subclipped_item.height}, "
            f"source: {os.path.basename(subclipped_item.source_file_path)}, "
            f"current duration: {video_duration:.2f}s, "
            f"remaining: {required_video_duration - video_duration:.2f}s"
        )

        try:
            clip = _open_video_clip_quietly(subclipped_item.file_path).subclipped(
                subclipped_item.start_time, subclipped_item.end_time
            )
            # 播放速度属于素材本身属性，应在转场前应用。这样 Fade/Slide 等一秒转场
            # 不会跟随素材速度变成 0.5 秒或 2 秒；后续最大时长裁剪继续作为
            # 浮点误差或异常素材时长的安全兜底，保证最终片段不突破配置上限。
            if normalized_clip_speed != 1.0:
                clip = clip.with_speed_scaled(normalized_clip_speed)
            clip_duration = clip.duration
            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                logger.debug(
                    f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}"
                )

                if clip_ratio == video_ratio:
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)

                    background = ColorClip(
                        size=(video_width, video_height), color=(0, 0, 0)
                    ).with_duration(clip_duration)
                    clip_resized = clip.resized(
                        new_size=(new_width, new_height)
                    ).with_position("center")
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
            clip_file = f"{output_dir}/temp-clip-{i + 1}.mp4"
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
            f"looped {len(processed_clips) - len(base_clips)} clips"
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
    # 字幕换行必须在真正创建 TextClip 前完成，否则 MoviePy 只会按原始文本
    # 计算渲染区域。这里用 PIL 按当前字体和字号测量宽度，确保每一行都尽量
    # 控制在视频可用宽度内，避免大字号或中文长句直接溢出画面。
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
        # 当一个 token 本身就超宽时（常见于中文无空格长句，或英文超长单词），
        # 退化为字符级拆分。关键点是：检测到 candidate 超宽时，先提交上一个
        # 仍然合法的 current，再把当前字符放入下一行，不能把超宽字符塞回上一行。
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
        # 中文长句按字符拆分时，最后一个句号、逗号等闭合标点可能被单独
        # 放到下一行，导致字幕背景被异常撑高，视觉上像一个小点掉在正文
        # 下方。这里在不重新设计换行算法的前提下，把上一行最后一个字
        # 移到标点行前面，让标点跟随文字显示，兼容中英文常见闭合标点。
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


_TOKEN_EDGE_RE = re.compile(r"^\W+|\W+$", re.UNICODE)

# Russian function words that must never become the highlighted keyword. Kept
# small on purpose: the length >= 5 filter already drops most of them, the set
# only covers the longer ones plus common short pronouns and prepositions.
_HIGHLIGHT_STOPWORDS = frozenset(
    {
        "и",
        "а",
        "но",
        "или",
        "либо",
        "ни",
        "же",
        "ли",
        "бы",
        "не",
        "нет",
        "в",
        "во",
        "на",
        "за",
        "к",
        "ко",
        "с",
        "со",
        "у",
        "о",
        "об",
        "обо",
        "от",
        "до",
        "по",
        "под",
        "над",
        "при",
        "про",
        "для",
        "без",
        "из",
        "через",
        "между",
        "перед",
        "после",
        "около",
        "вокруг",
        "я",
        "ты",
        "он",
        "она",
        "оно",
        "мы",
        "вы",
        "они",
        "меня",
        "тебя",
        "его",
        "её",
        "нас",
        "вас",
        "их",
        "себя",
        "мой",
        "твой",
        "свой",
        "наш",
        "ваш",
        "этот",
        "эта",
        "это",
        "эти",
        "тот",
        "та",
        "то",
        "те",
        "весь",
        "вся",
        "всё",
        "все",
        "этого",
        "этому",
        "своего",
        "своей",
        "своих",
        "что",
        "чтобы",
        "как",
        "когда",
        "тогда",
        "если",
        "потому",
        "поэтому",
        "также",
        "тоже",
        "даже",
        "именно",
        "только",
        "который",
        "которая",
        "которое",
        "которые",
        "которых",
    }
)


def _strip_token(token: str) -> str:
    return _TOKEN_EDGE_RE.sub("", token)


def pick_highlight_word(phrase: str) -> str | None:
    """
    Deterministic keyword choice for subtitle highlighting: a word with a
    digit wins, otherwise the longest non-stopword of 5+ chars, else None.
    """
    tokens = [
        stripped
        for stripped in (_strip_token(token) for token in phrase.split())
        if stripped
    ]
    for token in tokens:
        if any(char.isdigit() for char in token):
            return token
    candidates = [
        token
        for token in tokens
        if len(token) >= 5 and token.lower() not in _HIGHLIGHT_STOPWORDS
    ]
    if not candidates:
        return None
    return max(candidates, key=len)


def create_highlighted_text_clip(
    *,
    wrapped_txt: str,
    font_path: str,
    font_size: int,
    text_color: str,
    highlight_word: str | None,
    highlight_color: str,
    stroke_color: str | None,
    stroke_width: int,
    interline: int,
    width: int,
    height: int | None = None,
    margin_y: int = 0,
) -> ImageClip:
    """
    Render wrapped subtitle text into an RGBA ImageClip, painting one keyword
    in a different color. TextClip cannot mix colors within a line, so this
    path re-implements its centered layout with PIL word by word.
    """
    font = ImageFont.truetype(font_path, font_size)
    stroke_width = max(0, int(stroke_width))
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    lines = wrapped_txt.split("\n")
    text_block_h = line_height * len(lines) + interline * (len(lines) - 1)
    img_h = height if height is not None else text_block_h + 2 * margin_y
    img_h = max(int(img_h), text_block_h)
    img = Image.new("RGBA", (max(1, int(width)), max(1, img_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    stroke_fill = stroke_color if stroke_width > 0 else None
    highlight_pending = bool(highlight_word)
    y = int(round((img.height - text_block_h) / 2))
    for line in lines:
        x0 = (img.width - font.getlength(line)) / 2
        words = line.split(" ")
        for index, word in enumerate(words):
            if not word:
                continue
            # Offsets come from the full line prefix, not accumulated word
            # widths, so per-word rendering keeps TextClip-like spacing.
            prefix = " ".join(words[:index])
            x = x0 + (font.getlength(f"{prefix} ") if prefix else 0.0)
            color = text_color
            if highlight_pending and _strip_token(word) == highlight_word:
                color = highlight_color
                highlight_pending = False
            draw.text(
                (x, y),
                word,
                font=font,
                fill=color,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
        y += line_height + interline

    return ImageClip(np.array(img), transparent=True)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    # 字幕背景色来自 API/WebUI 参数，可能为空或格式不规范。这里统一只接受
    # #RRGGBB 形式，非法值回退为黑色，避免 PIL 渲染阶段抛出异常中断任务。
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
    # 新字幕背景仅在用户显式开启时使用：通过 RGBA 图片绘制圆角半透明底板，
    # 再交给 MoviePy 作为透明 ImageClip 参与合成。这样默认路径完全不变，
    # 同时可以低成本试验更柔和的字幕视觉效果。
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


# Horizontal offset from the frame centre, as a share of the frame width.
_GIF_SIDE_OFFSET_RANGE = (0.05, 0.13)
# Tilt in degrees. Anything past ~7 stops reading as a tilt and looks broken.
_GIF_TILT_RANGE = (2.0, 6.0)
_GIF_VERTICAL_JITTER = 0.07


def _rounded_mask_clip(width: int, height: int, radius: int) -> ImageClip:
    """Build a float mask so a rectangular gif renders with rounded corners."""
    img = Image.new("L", (width, height), 0)
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, max(0, width - 1), max(0, height - 1)],
        radius=max(0, int(radius)),
        fill=255,
    )
    return ImageClip(np.array(img).astype(float) / 255.0, is_mask=True)


def _shadow_image(width: int, height: int, radius: int, spread: int) -> Image.Image:
    img = Image.new("RGBA", (width + spread * 2, height + spread * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [spread, spread, spread + width - 1, spread + height - 1],
        radius=max(0, int(radius)),
        fill=(0, 0, 0, 110),
    )
    return img.filter(ImageFilter.GaussianBlur(radius=max(1, spread // 2)))


def _gif_shadow_clip(width: int, height: int, radius: int, spread: int) -> ImageClip:
    return ImageClip(
        np.array(_shadow_image(width, height, radius, spread)), transparent=True
    )


def _overlay_box(
    source_width: int,
    source_height: int,
    video_width: int,
    video_height: int,
    size_ratio: float,
) -> tuple[int, int]:
    target_width = max(1, int(video_width * size_ratio))
    source_width = max(1, int(source_width))
    source_height = max(1, int(source_height))
    target_height = max(1, int(target_width * source_height / source_width))

    # A tall overlay must not push into the subtitle band or off-frame.
    max_height = int(video_height * 0.45)
    if target_height > max_height:
        target_height = max_height
        target_width = max(1, int(target_height * source_width / source_height))
    return target_width, target_height


def _gif_overlay_box(
    gif_clip: VideoFileClip,
    video_width: int,
    video_height: int,
    size_ratio: float,
) -> tuple[int, int]:
    return _overlay_box(gif_clip.w, gif_clip.h, video_width, video_height, size_ratio)


def _deterministic_unit(seed: str) -> float:
    """Stable 0..1 value, so re-rendering a task reproduces the same layout."""
    return int(utils.md5(seed)[:8], 16) / 0xFFFFFFFF


def _gif_overlay_placement(
    index: int,
    seed: str,
    box_height: int,
    video_width: int,
    video_height: int,
    params: VideoParams,
) -> tuple[int, int, float]:
    """
    Scatter overlays instead of stacking them all in the middle of the frame.

    Consecutive gifs alternate sides and each one tilts towards the centre of
    the frame, which reads as pinned-on rather than pasted-in. Offsets are
    derived from the gif itself so the same task always renders identically.

    Subtitles are drawn at 95% of the height for "bottom" and at 5% for "top",
    so the vertical anchor sits on the opposite side of whichever band is used.
    """
    side = -1 if index % 2 == 0 else 1
    horizontal_jitter = _deterministic_unit(f"{seed}:x:{index}")
    vertical_jitter = _deterministic_unit(f"{seed}:y:{index}")
    tilt_jitter = _deterministic_unit(f"{seed}:tilt:{index}")

    offset_ratio = _GIF_SIDE_OFFSET_RANGE[0] + horizontal_jitter * (
        _GIF_SIDE_OFFSET_RANGE[1] - _GIF_SIDE_OFFSET_RANGE[0]
    )
    center_x = int(video_width / 2 + side * offset_ratio * video_width)

    if params.subtitle_enabled and params.subtitle_position == "top":
        base_center_y = video_height * 0.60
    else:
        base_center_y = video_height * 0.32
    center_y = int(
        base_center_y
        + (vertical_jitter - 0.5) * 2 * _GIF_VERTICAL_JITTER * video_height
    )

    # Rotate() turns anticlockwise on a positive angle, so a gif sitting left of
    # the centre needs a negative angle to lean its top edge back towards it.
    tilt = _GIF_TILT_RANGE[0] + tilt_jitter * (_GIF_TILT_RANGE[1] - _GIF_TILT_RANGE[0])
    angle = side * tilt

    margin = int(video_height * 0.03)
    center_y = max(
        margin + box_height // 2,
        min(center_y, video_height - margin - box_height // 2),
    )
    return center_x, center_y, angle


def _centered_position(
    center_x: int,
    center_y: int,
    width: int,
    height: int,
    video_width: int,
    video_height: int,
) -> tuple[int, int]:
    """Place a clip by its centre, clamped so a tilted card never leaves the frame."""
    x = int(center_x - width / 2)
    y = int(center_y - height / 2)
    x = max(0, min(x, max(0, video_width - width)))
    y = max(0, min(y, max(0, video_height - height)))
    return x, y


def _build_gif_overlay_clips(
    gif_overlays: List[dict],
    video_width: int,
    video_height: int,
    params: VideoParams,
    clip_stack: ExitStack,
) -> List[VideoFileClip]:
    """
    Turn downloaded gifs into positioned overlay clips.

    Each entry needs "path", "start" and "end". A gif shorter than its window is
    looped, a longer one is trimmed, so the overlay always covers exactly the
    subtitle line it was picked for.
    """
    overlays: List[VideoFileClip] = []
    size_ratio = max(0.1, min(float(getattr(params, "gif_size", 0.42) or 0.42), 0.9))
    fade = 0.25

    for overlay in gif_overlays:
        gif_path = str(overlay.get("path") or "")
        if not gif_path or not os.path.exists(gif_path):
            continue

        start = float(overlay.get("start", 0.0))
        end = float(overlay.get("end", 0.0))
        window = end - start
        if window <= 0:
            continue

        try:
            gif_clip = clip_stack.enter_context(
                _open_video_clip_quietly(gif_path, audio=False)
            )
            if not gif_clip.duration or gif_clip.duration <= 0:
                logger.warning(f"skipping gif overlay without duration: {gif_path}")
                continue

            box_width, box_height = _gif_overlay_box(
                gif_clip, video_width, video_height, size_ratio
            )
            gif_clip = gif_clip.resized(new_size=(box_width, box_height))
            if gif_clip.duration < window:
                gif_clip = gif_clip.with_effects([vfx.Loop(duration=window)])
            gif_clip = gif_clip.with_duration(window)

            radius = max(8, int(min(box_width, box_height) * 0.08))
            gif_clip = gif_clip.with_mask(
                _rounded_mask_clip(box_width, box_height, radius).with_duration(window)
            )

            # Sides alternate across the overlays that actually made it into the
            # composite, so a skipped gif does not put two cards on one side.
            placed_index = len(overlays) // 2
            center_x, center_y, angle = _gif_overlay_placement(
                index=placed_index,
                seed=os.path.basename(gif_path),
                box_height=box_height,
                video_width=video_width,
                video_height=video_height,
                params=params,
            )
            spread = max(4, int(box_width * 0.03))
            shadow = _gif_shadow_clip(box_width, box_height, radius, spread)
            shadow = shadow.with_duration(window)
            if angle:
                # Rotate() carries the rounded mask along via apply_to=["mask"]
                # and grows the clip size, so both layers are placed by centre.
                rotate = vfx.Rotate(angle, expand=True)
                gif_clip = gif_clip.with_effects([rotate])
                shadow = shadow.with_effects([rotate])

            x, y = _centered_position(
                center_x, center_y, gif_clip.w, gif_clip.h, video_width, video_height
            )
            shadow_x, shadow_y = _centered_position(
                center_x, center_y, shadow.w, shadow.h, video_width, video_height
            )
            shadow = shadow.with_start(start).with_position((shadow_x, shadow_y))
            gif_clip = gif_clip.with_start(start).with_position((x, y))

            effects = [vfx.CrossFadeIn(fade), vfx.CrossFadeOut(fade)]
            if window > fade * 2:
                shadow = shadow.with_effects(effects)
                gif_clip = gif_clip.with_effects(effects)

            overlays.append(shadow)
            overlays.append(gif_clip)
        except Exception as error:
            # A broken gif must never take the whole render down with it.
            logger.warning(f"failed to build gif overlay: {gif_path} => {str(error)}")

    logger.info(f"built {len(overlays) // 2} gif overlays")
    return overlays


_PHOTO_ANIMATIONS = ("pop", "slide", "kenburns")
_PHOTO_ENTRY_DURATION = 0.35
_PHOTO_POP_START_SCALE = 0.85
_PHOTO_KENBURNS_ZOOM = 0.10


def _ease_out(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return 1.0 - (1.0 - progress) ** 3


def _pick_photo_animation(seed: str, params: VideoParams) -> str:
    choice = str(getattr(params, "photo_animation", "random") or "random").lower()
    if choice in _PHOTO_ANIMATIONS:
        return choice
    unit = _deterministic_unit(f"{seed}:animation")
    return _PHOTO_ANIMATIONS[
        min(len(_PHOTO_ANIMATIONS) - 1, int(unit * len(_PHOTO_ANIMATIONS)))
    ]


def _photo_card_image(
    photo: Image.Image,
    box_width: int,
    box_height: int,
    radius: int,
    spread: int,
    angle: float,
) -> Image.Image:
    """
    Bake shadow + rounded photo into a single RGBA card.

    A static photo never changes between frames, so unlike gifs the tilt is
    applied once here in PIL instead of per-frame through vfx.Rotate. PIL's
    rotate() is anticlockwise on a positive angle, same as vfx.Rotate.
    """
    resized = photo.resize((box_width, box_height), Image.LANCZOS)
    rounded = Image.new("L", (box_width, box_height), 0)
    ImageDraw.Draw(rounded).rounded_rectangle(
        [0, 0, max(0, box_width - 1), max(0, box_height - 1)],
        radius=max(0, int(radius)),
        fill=255,
    )
    card = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    card.paste(resized, (0, 0), rounded)

    canvas = _shadow_image(box_width, box_height, radius, spread)
    canvas.alpha_composite(card, (spread, spread))
    if angle:
        canvas = canvas.rotate(angle, expand=True, resample=Image.BICUBIC)
    return canvas


def _build_photo_overlay_clips(
    photo_overlays: List[dict],
    video_width: int,
    video_height: int,
    params: VideoParams,
    clip_stack: ExitStack,
) -> List[VideoFileClip]:
    """
    Turn local photos into positioned overlay clips with an entry animation.

    Layout (side alternation, tilt, jitter) is shared with gif overlays, so
    photos read as part of the same visual system.
    """
    overlays: List[VideoFileClip] = []
    size_ratio = max(0.1, min(float(getattr(params, "photo_size", 0.42) or 0.42), 0.9))
    fade = 0.25
    placed = 0

    for overlay in photo_overlays:
        photo_path = str(overlay.get("path") or "")
        if not photo_path or not os.path.exists(photo_path):
            continue

        start = float(overlay.get("start", 0.0))
        end = float(overlay.get("end", 0.0))
        window = end - start
        if window <= 0:
            continue

        try:
            with Image.open(photo_path) as source:
                photo = ImageOps.exif_transpose(source).convert("RGB")

            box_width, box_height = _overlay_box(
                photo.width, photo.height, video_width, video_height, size_ratio
            )
            radius = max(8, int(min(box_width, box_height) * 0.08))
            spread = max(4, int(box_width * 0.03))
            seed = os.path.basename(photo_path)
            center_x, center_y, angle = _gif_overlay_placement(
                index=placed,
                seed=seed,
                box_height=box_height,
                video_width=video_width,
                video_height=video_height,
                params=params,
            )
            side = -1 if placed % 2 == 0 else 1
            animation = _pick_photo_animation(seed, params)
            entry = min(_PHOTO_ENTRY_DURATION, window / 2)
            fade_effects = (
                [vfx.CrossFadeIn(fade), vfx.CrossFadeOut(fade)]
                if window > fade * 2
                else []
            )

            if animation == "kenburns":
                # The photo slowly zooms inside a fixed card, so the frame,
                # mask and shadow stay put while the content drifts.
                inner = ImageClip(
                    np.array(photo.resize((box_width, box_height), Image.LANCZOS))
                ).with_duration(window)

                def zoom(t: float, window: float = window) -> float:
                    return 1.0 + _PHOTO_KENBURNS_ZOOM * (t / window)

                inner = inner.resized(zoom).with_position(
                    lambda t, z=zoom, w=box_width, h=box_height: (
                        (w - w * z(t)) / 2,
                        (h - h * z(t)) / 2,
                    )
                )
                card = CompositeVideoClip(
                    [inner], size=(box_width, box_height)
                ).with_duration(window)
                card = card.with_mask(
                    _rounded_mask_clip(box_width, box_height, radius).with_duration(
                        window
                    )
                )
                shadow = _gif_shadow_clip(box_width, box_height, radius, spread)
                shadow = shadow.with_duration(window)
                if angle:
                    rotate = vfx.Rotate(angle, expand=True)
                    card = card.with_effects([rotate])
                    shadow = shadow.with_effects([rotate])

                x, y = _centered_position(
                    center_x, center_y, card.w, card.h, video_width, video_height
                )
                shadow_x, shadow_y = _centered_position(
                    center_x, center_y, shadow.w, shadow.h, video_width, video_height
                )
                card = card.with_start(start).with_position((x, y))
                shadow = shadow.with_start(start).with_position((shadow_x, shadow_y))
                if fade_effects:
                    card = card.with_effects(fade_effects)
                    shadow = shadow.with_effects(fade_effects)
                overlays.append(shadow)
                overlays.append(card)
            else:
                card_image = _photo_card_image(
                    photo, box_width, box_height, radius, spread, angle
                )
                card = ImageClip(np.array(card_image), transparent=True).with_duration(
                    window
                )
                card_w, card_h = card.w, card.h
                x, y = _centered_position(
                    center_x, center_y, card_w, card_h, video_width, video_height
                )

                if animation == "pop":

                    def scale(t: float, entry: float = entry) -> float:
                        if t >= entry:
                            return 1.0
                        return _PHOTO_POP_START_SCALE + (
                            1.0 - _PHOTO_POP_START_SCALE
                        ) * _ease_out(t / entry)

                    card = card.resized(scale).with_position(
                        lambda t, s=scale, x=x, y=y, w=card_w, h=card_h: (
                            x + w * (1.0 - s(t)) / 2,
                            y + h * (1.0 - s(t)) / 2,
                        )
                    )
                else:  # slide
                    off_x = -card_w if side < 0 else video_width
                    card = card.with_position(
                        lambda t, x=x, y=y, off_x=off_x, entry=entry: (
                            x
                            if t >= entry
                            else off_x + (x - off_x) * _ease_out(t / entry),
                            y,
                        )
                    )

                card = card.with_start(start)
                if fade_effects:
                    card = card.with_effects(fade_effects)
                overlays.append(card)

            placed += 1
        except Exception as error:
            # A broken photo must never take the whole render down with it.
            logger.warning(
                f"failed to build photo overlay: {photo_path} => {str(error)}"
            )

    logger.info(f"built {placed} photo overlays")
    return overlays


def _get_visible_center_position(
    text_clip: TextClip | ImageClip,
    container_width: int,
    container_height: int,
) -> tuple[int, int]:
    """
    按文字真实可见像素把 TextClip 放到背景容器中心。

    MoviePy 的 TextClip 会按字体行高和 baseline 创建透明画布。很多字体的
    可见字形并不在这个画布的几何中心，直接 `with_position("center")`
    会把整块透明画布居中，导致字幕看起来偏上或偏下。这里读取 TextClip
    的透明 mask，只根据实际有像素的 bbox 计算偏移，让用户看到的文字
    在字幕背景里视觉居中。
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
    """判断字幕文字和背景是否同色，提醒用户可能无法看清字幕。"""
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
    """检查字体是否包含样本文字需要的字形，并缓存重复检查结果。"""
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
        # 字体探测失败不应阻止用户生成；保留日志供环境兼容问题排查。
        logger.warning(f"failed to inspect subtitle font glyphs: {font_path}, {e}")
        return True


def subtitle_font_supports_text(font_path: str, text: str) -> bool:
    """检查字体能否绘制文本中的字母和数字，忽略空白及标点符号。"""
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


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
    bgm_file_override: str | None = None,
    gif_overlays: List[dict] | None = None,
    photo_overlays: List[dict] | None = None,
) -> bool:
    """
    合成最终视频，并返回本次背景音乐处理是否成功。

    返回值只描述 BGM 处理状态：没有请求 BGM 或成功混合时返回 True；请求了
    BGM 但加载、特效或混合失败时返回 False。即使 BGM 失败仍会继续输出只有
    旁白的视频，让任务编排层决定是否向用户展示降级警告。
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
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"  ⑤ font: {font_path}")

    def resolve_subtitle_background_color():
        # 兼容历史参数：API 里 `text_background_color` 既可能是布尔值，
        # 也可能是实际颜色字符串。统一在这里归一化，避免把 True/False
        # 直接传给 TextClip 后出现不可预期的渲染结果。
        if isinstance(params.text_background_color, bool):
            return "#000000" if params.text_background_color else None
        return params.text_background_color

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        if getattr(params, "subtitle_uppercase", False):
            phrase = phrase.upper()
        highlight_enabled = bool(getattr(params, "subtitle_highlight_enabled", False))
        highlight_word = pick_highlight_word(phrase) if highlight_enabled else None
        highlight_color = getattr(params, "subtitle_highlight_color", "#FFD700")
        max_width = video_width * 0.9
        bg_color = resolve_subtitle_background_color()
        rounded_bg_enabled = bool(
            getattr(params, "rounded_subtitle_background", False) and bg_color
        )
        has_subtitle_background = bool(bg_color)
        # 圆角背景按文字真实宽度生成，左右留白应更克制；旧矩形背景仍保留
        # 较大的安全边距，避免历史配置中的长字幕贴边或被裁切。
        padding_ratio = 0.4 if rounded_bg_enabled else 0.6
        pad_x = int(params.font_size * padding_ratio) if has_subtitle_background else 0
        # 字幕背景需要给文字左右留出明确内边距。先从可用宽度中扣除
        # padding 再换行，避免长英文或大字号刚好撑满 90% 视频宽度后，
        # 文字贴到背景框边缘，看起来像被裁切。普通矩形背景和圆角背景
        # 都走这条逻辑；无背景字幕则保持原有最大宽度。
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
        # MoviePy 在 `method=label` 下会自动收缩文本框高度，遇到多行字幕、
        # 描边或背景色时，容易把最后一行的下半部分裁掉。这里显式传入
        # 一个更保守的高度，把行间距和额外上下留白一并算进去，保证字幕
        # 背景框与文字本身都能完整渲染出来。
        clip_h = int(txt_height + vertical_padding + (interline * line_count))

        if rounded_bg_enabled:
            # 圆角背景需要贴合文字宽度，而不是沿用 90% 视频宽度。这里先用
            # PIL 测量最长一行文字，再加水平内边距，避免短字幕出现过宽底板。
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
            if highlight_enabled:
                text_clip = create_highlighted_text_clip(
                    wrapped_txt=wrapped_txt,
                    font_path=font_path,
                    font_size=params.font_size,
                    text_color=params.text_fore_color,
                    highlight_word=highlight_word,
                    highlight_color=highlight_color,
                    stroke_color=params.stroke_color,
                    stroke_width=params.stroke_width,
                    interline=interline,
                    width=box_w,
                    margin_y=text_clip_margin_y,
                )
            else:
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
            if highlight_enabled:
                text_clip = create_highlighted_text_clip(
                    wrapped_txt=wrapped_txt,
                    font_path=font_path,
                    font_size=params.font_size,
                    text_color=params.text_fore_color,
                    highlight_word=highlight_word,
                    highlight_color=highlight_color,
                    stroke_color=params.stroke_color,
                    stroke_width=params.stroke_width,
                    interline=interline,
                    width=int(max_width),
                    margin_y=text_clip_margin_y,
                )
            else:
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
            if highlight_enabled:
                _clip = create_highlighted_text_clip(
                    wrapped_txt=wrapped_txt,
                    font_path=font_path,
                    font_size=params.font_size,
                    text_color=params.text_fore_color,
                    highlight_word=highlight_word,
                    highlight_color=highlight_color,
                    stroke_color=params.stroke_color,
                    stroke_width=params.stroke_width,
                    interline=interline,
                    width=size[0],
                    height=size[1],
                )
            else:
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

    # MoviePy 的 CompositeAudioClip.close() 不会关闭子 AudioFileClip。这里用
    # ExitStack 显式持有所有原始文件 reader，确保成功、字幕异常、混音失败和
    # 视频写入失败等路径都能释放 FFmpeg 子进程，尤其避免 Windows 文件被占用。
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

        # Gif overlays sit above the footage but below nothing else, so they are
        # composited after subtitles to keep the text readable on top of them.
        if gif_overlays:
            overlay_clips = _build_gif_overlay_clips(
                gif_overlays,
                video_width=video_width,
                video_height=video_height,
                params=params,
                clip_stack=clip_stack,
            )
            if overlay_clips:
                video_clip = CompositeVideoClip([video_clip, *overlay_clips])
                clip_stack.callback(video_clip.close)

        if photo_overlays:
            photo_clips = _build_photo_overlay_clips(
                photo_overlays,
                video_width=video_width,
                video_height=video_height,
                params=params,
                clip_stack=clip_stack,
            )
            if photo_clips:
                video_clip = CompositeVideoClip([video_clip, *photo_clips])
                clip_stack.callback(video_clip.close)

        bgm_enabled = bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)
        if not bgm_enabled and params.bgm_type:
            # 所有 BGM 来源共用这一条短路规则。音量不大于 0 时不能解析随机或
            # 自定义文件，也不能加载提供商返回的文件，避免无意义的 IO 和混音。
            logger.info(
                f"skipping background music because volume is not positive: "
                f"type={params.bgm_type}, volume={params.bgm_volume}"
            )

        # 提供商配乐可由任务编排层直接传入对应文件。None 表示沿用随机/自定义
        # BGM 解析，空字符串明确禁用本条 BGM；但任何来源都必须先通过通用音量规则。
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
                # 服务内解析的随机/自定义音乐可能比成片短，需要循环铺满；任务层
                # 通过 override 传入的文件表示提供商已经完成时长适配。这里依据
                # 文件来源决定是否循环，避免今后每增加一个提供商都修改名称白名单。
                if bgm_file_override is None:
                    bgm_effects.append(afx.AudioLoop(duration=video_clip.duration))
                bgm_source_clip = clip_stack.enter_context(AudioFileClip(bgm_file))
                bgm_clip = bgm_source_clip.with_effects(bgm_effects)
                audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
            except Exception:
                bgm_mix_succeeded = False
                # 记录完整堆栈和稳定上下文，便于区分文件解码、MoviePy 特效和
                # CompositeAudioClip 失败；文件内容与 API Key 不会进入日志。
                logger.exception(
                    f"failed to mix background music: type={params.bgm_type}, "
                    f"file={bgm_file}"
                )

        final_video_clip = video_clip.with_audio(audio_clip)
        clip_stack.callback(final_video_clip.close)
        # 显式沿用输入音频的采样率；如果取不到，再回退 MoviePy 默认的 44100Hz。
        # 这样可以减少不同环境，尤其 Docker 中再次重采样带来的音质波动。
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
    # WebUI 在某些二次生成场景下可能传入空素材列表，这里直接返回空结果，避免抛出 NoneType 异常。
    if not materials:
        return []

    # 仅返回通过预处理校验的素材，避免低分辨率图片继续进入后续的视频合成流程。
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
            # local video_source 的素材路径来自 API 参数，必须限制在专用素材目录。
            # 允许用户传文件名，也兼容历史返回的绝对路径，但不允许逃逸到系统
            # 其他目录，避免任意文件读取或通过 MoviePy 探测本地敏感文件。
            logger.warning(
                f"skip unsafe local material: {material.url}, "
                f"local_videos_dir: {local_videos_dir}, error: {str(exc)}"
            )
            continue

        ext = utils.parse_extension(material_source_path)
        try:
            # 图片素材直接按图片方式读取，避免先走 VideoFileClip 误判后触发不稳定的回退分支。
            if ext in const.FILE_TYPE_IMAGES:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            else:
                clip = _open_video_clip_quietly(material_source_path)
        except Exception:
            # 非标准扩展名或探测失败时再回退到图片模式，兼容历史上直接传本地图片路径的情况。
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
                # 探测到低分辨率素材后立即关闭资源，并且不要把该素材返回给后续流程。
                close_clip(clip)
                continue

            if ext in const.FILE_TYPE_IMAGES:
                logger.info(f"processing image: {material_source_path}")
                # 探测尺寸时已经打开过一次素材，这里先释放探测句柄，再重新创建用于导出的图片 clip。
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
                # 普通视频素材只需要读取尺寸做校验，校验完成后立即释放句柄即可。
                close_clip(clip)
                # Update url to the resolved absolute path so that downstream
                # stages (combine_videos) can open the file without re-resolving.
                material.url = material_source_path
        except Exception:
            close_clip(clip)
            raise

        valid_materials.append(material)

    return valid_materials
