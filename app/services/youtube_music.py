import math
import os
import subprocess
from pathlib import Path
from loguru import logger
from app.services import bgm as bgm_service
from app.utils import utils

YT_DLP_PATH = "C:\\Users\\Farhan\\yt-dlp\\yt-dlp.exe"

class YouTubeMusicError(RuntimeError):
    """表示 YouTube 音频下载或剪辑失败。"""

def is_enabled() -> bool:
    return os.path.exists(YT_DLP_PATH)


def download_full_audio(url: str) -> str:
    """仅下载 YouTube 音频并返回本地 mp3 路径，供预览使用。"""
    clean_url = url.split("|", 1)[0].strip()
    if not clean_url:
        raise YouTubeMusicError("YouTube URL is required")

    cache_folder = bgm_service.uploaded_bgm_dir(create=True)
    out_tmpl = os.path.join(cache_folder, "%(id)s.%(ext)s")
    cmd = [
        YT_DLP_PATH,
        "-x",
        "--audio-format", "mp3",
        "-o", out_tmpl,
        "-i",
        "--ignore-config",
        clean_url
    ]

    logger.info(f"running yt-dlp preview download command: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        logger.info(res.stdout)
    except subprocess.CalledProcessError as exc:
        logger.error(f"yt-dlp preview failed: {exc.stderr}")
        raise YouTubeMusicError(f"yt-dlp download failed: {exc.stderr}") from exc
    except Exception as exc:
        logger.error(f"yt-dlp preview execution error: {exc}")
        raise YouTubeMusicError(f"yt-dlp execution error: {exc}") from exc

    mp3_files = list(Path(cache_folder).glob("*.mp3"))
    if not mp3_files:
        raise YouTubeMusicError("No downloaded mp3 found after yt-dlp execution")
    return str(max(mp3_files, key=os.path.getmtime))

    logger.info(f"running yt-dlp preview download command: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        logger.info(res.stdout)
    except subprocess.CalledProcessError as exc:
        logger.error(f"yt-dlp preview failed: {exc.stderr}")
        raise YouTubeMusicError(f"yt-dlp download failed: {exc.stderr}") from exc
    except Exception as exc:
        logger.error(f"yt-dlp preview execution error: {exc}")
        raise YouTubeMusicError(f"yt-dlp execution error: {exc}") from exc

    mp3_files = list(Path(cache_folder).glob("*.mp3"))
    if not mp3_files:
        raise YouTubeMusicError("No downloaded mp3 found after yt-dlp execution")
    return str(max(mp3_files, key=os.path.getmtime))

def generate_bgm(video_path: str, output_path: str, video_duration: float, prompt: str) -> None:
    """
    prompt 格式为: URL|start_time (例如: https://www.youtube.com/watch?v=xxxx|0:30 或 https://www.youtube.com/watch?v=xxxx|30)
    使用 C:\\Users\\Farhan\\yt-dlp\\yt-dlp.exe 下载音频为 mp3，然后用 ffmpeg 根据 start_time 裁剪/循环铺满 video_duration。
    """
    parts = prompt.split("|", 1)
    url = parts[0].strip()
    start_str = parts[1].strip() if len(parts) > 1 else "0"

    if not url:
        raise YouTubeMusicError("YouTube URL is required in the music prompt")

    # 解析 start_time (支持秒数如 30 或 m:s 如 0:30)
    start_seconds = 0.0
    if ":" in start_str:
        try:
            time_parts = start_str.split(":")
            if len(time_parts) == 2:
                start_seconds = float(time_parts[0]) * 60 + float(time_parts[1])
            elif len(time_parts) == 3:
                start_seconds = float(time_parts[0]) * 3600 + float(time_parts[1]) * 60 + float(time_parts[2])
        except ValueError:
            start_seconds = 0.0
    else:
        try:
            start_seconds = float(start_str)
        except ValueError:
            start_seconds = 0.0

    cache_folder = bgm_service.uploaded_bgm_dir(create=True)
    
    # 构造 yt-dlp 命令：C:\Users\Farhan\yt-dlp\yt-dlp.exe -t mp3 -o "some cache folder" -i --ignore-config "%URL%"
    # 注意 -t 在较新 yt-dlp 中可能被废弃或对应 --extract-audio，但按用户要求原样或正确执行命令：
    # 用户原话: runs yt-dlp audio download from C:\Users\Farhan\yt-dlp\yt-dlp.exe -t mp3 -o "some cache folder" -i --ignore-config "%URL%"
    # 让我们使用 --extract-audio --audio-format mp3 加上指定的输出模板或目录。
    # 为了稳妥起见，输出模板设为 cache_folder / %(id)s.%(ext)s
    out_tmpl = os.path.join(cache_folder, "%(id)s.%(ext)s")
    
    cmd = [
        YT_DLP_PATH,
        "-x",
        "--audio-format", "mp3",
        "-o", out_tmpl,
        "-i",
        "--ignore-config",
        url
    ]

    logger.info(f"running yt-dlp command: {' '.join(cmd)}")
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        logger.info(res.stdout)
    except subprocess.CalledProcessError as exc:
        logger.error(f"yt-dlp failed: {exc.stderr}")
        raise YouTubeMusicError(f"yt-dlp download failed: {exc.stderr}") from exc
    except Exception as exc:
        logger.error(f"yt-dlp execution error: {exc}")
        raise YouTubeMusicError(f"yt-dlp execution error: {exc}") from exc

    # 找出下载下来的 mp3 文件（可以通过匹配最近修改的文件或者从输出获取，或者在 cache_folder 中找最新 mp3）
    mp3_files = list(Path(cache_folder).glob("*.mp3"))
    if not mp3_files:
        raise YouTubeMusicError("No downloaded mp3 found after yt-dlp execution")
    
    # 取最新的 mp3 文件
    downloaded_mp3 = max(mp3_files, key=os.path.getmtime)

    # 接下来使用 ffmpeg 根据 start_seconds 裁剪，并循环或截取到 video_duration
    # 如果用户指定的 start_seconds 超过了音频总时长，或者需要循环播放：
    # ffmpeg 命令处理：从 start_seconds 开始，如果不够 video_duration 则循环 (stream_loop)
    ffmpeg_bin = utils.get_ffmpeg_binary()
    
    # 先获取下载音频的时长
    try:
        probe = subprocess.run(
            [ffmpeg_bin, "-i", str(downloaded_mp3)],
            capture_output=True,
            text=True,
            check=False
        )
        # 从 stderr 解析 Duration: HH:MM:SS.ms
        duration_seconds = 60.0 # 默认
        for line in probe.stderr.splitlines():
            if "Duration:" in line:
                parts_dur = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = parts_dur.split(":")
                duration_seconds = float(h) * 3600 + float(m) * 60 + float(s)
                break
    except Exception:
        duration_seconds = 60.0

    # 如果 start_seconds 大于等于音频总时长，则从 0 开始
    if start_seconds >= duration_seconds:
        start_seconds = 0.0

    target_duration = float(video_duration) + 1.0 # 留点余量

    # 使用 ffmpeg 生成最终的输出音乐文件 output_path
    # 命令：ffmpeg -ss start_seconds -stream_loop -1 -i downloaded_mp3 -t target_duration -acodec libmp3lame output_path
    ffmpeg_cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", str(start_seconds),
        "-stream_loop", "-1",
        "-i", str(downloaded_mp3),
        "-t", str(target_duration),
        "-acodec", "libmp3lame",
        output_path
    ]

    logger.info(f"processing youtube audio with ffmpeg: {' '.join(ffmpeg_cmd)}")
    try:
        res = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True, timeout=120)
        logger.info(res.stdout)
    except subprocess.CalledProcessError as exc:
        logger.error(f"ffmpeg audio processing failed: {exc.stderr}")
        raise YouTubeMusicError(f"ffmpeg audio processing failed: {exc.stderr}") from exc
    except Exception as exc:
        logger.error(f"ffmpeg execution error: {exc}")
        raise YouTubeMusicError(f"ffmpeg execution error: {exc}") from exc
