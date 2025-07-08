import glob
import itertools
import os
import random
import shutil
import subprocess
import json
from typing import List
from loguru import logger

from app.models.schema import (
    VideoAspect,
    VideoParams,
    VideoConcatMode,
    VideoTransitionMode,
)

from app.utils import utils


def get_bgm_file(bgm_type: str, bgm_file: str):
    if bgm_type == "random":
        bgm_dir = utils.resource_dir("bgm")
        if not os.path.exists(bgm_dir):
            logger.warning(f"BGM directory not found: {bgm_dir}, trying assets/bgm")
            bgm_dir = utils.resource_dir("assets/bgm")
            if not os.path.exists(bgm_dir):
                logger.warning(f"BGM directory not found: {bgm_dir}, skip adding BGM.")
                return ""

        bgm_files = glob.glob(os.path.join(bgm_dir, "*.mp3"))
        if not bgm_files:
            logger.warning(f"No BGM files found in {bgm_dir}, skip adding BGM.")
            return ""
        return random.choice(bgm_files)

    if bgm_type == "local":
        return bgm_file

    return ""


def _run_ffmpeg_command(command: list):
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.error(f"FFmpeg command failed with return code {process.returncode}")
            logger.error(f"FFmpeg stderr: {stderr}")
            return False
        logger.debug(f"FFmpeg command successful: {' '.join(command)}")
        logger.debug(f"FFmpeg stderr: {stderr}")
        return True
    except FileNotFoundError:
        logger.error("ffmpeg or ffprobe not found. Please ensure they are installed and in your PATH.")
        return False
    except Exception as e:
        logger.error(f"An error occurred while running ffmpeg: {e}")
        return False


def get_video_duration(video_path: str) -> float:
    """Get the duration of a video using ffprobe."""
    command = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        logger.error(f"Error getting duration for {video_path}: {e}")
        return 0.0


def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]
    for file in files:
        if os.path.exists(file):
            try:
                os.remove(file)
            except Exception as e:
                logger.warning(f"Failed to delete file {file}: {e}")


def create_video_clip_from_segments(segments: list, video_aspect: VideoAspect, output_path: str):
    """
    Creates a video clip by concatenating pre-defined video segments.

    Args:
        segments (list): A list of VideoSegment objects, where each object represents a video segment
                         and contains 'path' and 'duration' attributes.
        video_aspect (VideoAspect): The aspect ratio of the output video.
        output_path (str): The path to save the output video clip.

    Returns:
        bool: True if the command was successful, False otherwise.
    """
    if not segments:
        logger.warning("No video segments provided, cannot create video clip.")
        return False

    w, h = video_aspect.to_resolution()
    scale_filter = f"scale={w}:{h}:force_original_aspect_ratio=increase"
    crop_filter = f"crop={w}:{h}"
    sar_filter = "setsar=1"
    fps_filter = "fps=60"

    filter_complex_parts = []
    concat_inputs = ""
    input_files = []
    input_mappings = {}

    total_duration = sum(seg.duration for seg in segments)

    for i, segment in enumerate(segments):
        input_path = segment.path
        duration = segment.duration

        if input_path not in input_mappings:
            input_mappings[input_path] = len(input_files)
            input_files.append(input_path)

        input_idx = input_mappings[input_path]
        input_specifier = f"[{input_idx}:v]"

        # Each segment is trimmed from the start of the source video.
        trim_filter = f"{input_specifier}trim=start=1:duration={duration},setpts=PTS-STARTPTS"

        processed_clip_name = f"[v{i}]"
        filter_complex_parts.append(f"{trim_filter},{scale_filter},{crop_filter},{fps_filter}{processed_clip_name}")
        concat_inputs += processed_clip_name

    concat_filter = f"{concat_inputs}concat=n={len(segments)}:v=1:a=0,setsar=1[outv]"
    filter_complex_parts.append(concat_filter)

    command = [
        "ffmpeg", "-y",
    ]
    for file_path in input_files:
        command.extend(["-i", file_path])

    command.extend([
        "-filter_complex",
        ";".join(filter_complex_parts),
        "-map", "[outv]",
        "-c:v", "libx264",
        "-crf", "18",
        "-an",
        "-r", "60",
        "-t", str(total_duration),
        output_path
    ])

    logger.info(f"Creating video clip for {output_path} with {len(segments)} segments (total duration: {total_duration:.2f}s) using ffmpeg.")
    return _run_ffmpeg_command(command)


def concatenate_videos(video_paths: List[str], output_path: str, transition_mode: VideoTransitionMode = VideoTransitionMode.none):
    logger.info(f"Concatenating {len(video_paths)} videos into {output_path} with transition: {transition_mode.name}")

    if not video_paths:
        logger.error("No video paths provided for concatenation.")
        return False

    if len(video_paths) == 1:
        logger.info("Only one video, copying to output path.")
        shutil.copy(video_paths[0], output_path)
        return True

    use_transition = transition_mode != VideoTransitionMode.none

    # Nested function for fallback to simple concatenation
    def fallback_concat():
        logger.info("Using simple concat demuxer (no transitions).")
        temp_file_path = os.path.join(os.path.dirname(output_path), "temp_video_list.txt")
        try:
            with open(temp_file_path, "w", encoding="utf-8") as f:
                for video_path in video_paths:
                    # Normalize path for ffmpeg concat demuxer, which is sensitive to backslashes
                    normalized_path = video_path.replace('\\', '/')
                    f.write(f"file '{normalized_path}'\n")
            
            command = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", temp_file_path,
                "-c", "copy",
                output_path
            ]
            
            if _run_ffmpeg_command(command):
                logger.success(f"Successfully concatenated videos using concat demuxer: {output_path}")
                return True
            else:
                logger.error("Failed to concatenate videos using concat demuxer.")
                return False
        finally:
            delete_files(temp_file_path)

    if not use_transition:
        return fallback_concat()

    # Proceed with transitions using xfade
    logger.info("Using xfade for transitions.")
    transition_duration = 0.5  # seconds
    video_durations = [get_video_duration(p) for p in video_paths]

    if any(d == 0.0 for d in video_durations):
        logger.warning("Could not determine duration for all video clips, falling back to simple concatenation.")
        return fallback_concat()

    command = ["ffmpeg", "-y"]
    for path in video_paths:
        command.extend(["-i", path])

    filter_chains = []
    # Initial stream is [0:v]
    last_stream_name = "[0:v]"
    total_duration = 0

    for i in range(1, len(video_paths)):
        total_duration += video_durations[i-1]
        offset = total_duration - transition_duration
        
        input_stream_name = f"[{i}:v]"
        output_stream_name = f"[v{i}]"
        
        filter_chains.append(f"{last_stream_name}{input_stream_name}xfade=transition=fade:duration={transition_duration}:offset={offset}{output_stream_name}")
        last_stream_name = output_stream_name

    filter_complex = ";".join(filter_chains)

    command.extend([
        "-filter_complex", filter_complex,
        "-map", last_stream_name,
        "-c:v", "libx264",
        "-movflags", "+faststart",
        output_path
    ])

    if _run_ffmpeg_command(command):
        logger.success(f"Successfully concatenated videos with transitions: {output_path}")
        return True
    else:
        logger.warning("FFmpeg command with transition failed, falling back to simple concatenation.")
        return fallback_concat()


def add_audio_to_video(video_path: str, audio_path: str, output_path: str):
    video_path = os.path.normpath(video_path)
    audio_path = os.path.normpath(audio_path)
    output_path = os.path.normpath(output_path)

    # Check if the video already has an audio stream
    has_audio_stream = False
    try:
        probe_command = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path
        ]
        process = subprocess.run(probe_command, check=True, capture_output=True, text=True)
        if process.stdout.strip():
            has_audio_stream = True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"Could not probe video for audio stream: {e}")

    if has_audio_stream:
        command = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path,
        ]
    else:
        command = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            output_path,
        ]
    return _run_ffmpeg_command(command)


def add_bgm_to_video(video_path: str, bgm_path: str, bgm_volume: float, output_path: str) -> bool:
    video_path = os.path.normpath(video_path)
    bgm_path = os.path.normpath(bgm_path)
    output_path = os.path.normpath(output_path)
    """
    Mixes background music into a video's audio track using ffmpeg and outputs a new video file.
    """
    logger.info(f"Mixing BGM '{bgm_path}' into video '{video_path}'")

    video_duration = get_video_duration(video_path)
    if video_duration == 0.0:
        logger.error(f"Could not get duration of video {video_path}")
        return False

    command = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-stream_loop", "-1",
        "-i", bgm_path,
        "-filter_complex", f"[0:a]volume=1.0[a0];[1:a]volume={bgm_volume}[a1];[a0][a1]amix=inputs=2:duration=first[a]",

        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-t", str(video_duration),
        "-shortest", # Add -shortest parameter here
        output_path,
    ]

    return _run_ffmpeg_command(command)


def add_subtitles_to_video(video_path: str, srt_path: str, font_name: str, font_size: int, text_fore_color: str, stroke_color: str, stroke_width: float, subtitle_position: str, custom_position: float, output_path: str):
    video_path = os.path.normpath(video_path)
    srt_path = os.path.normpath(srt_path)
    output_path = os.path.normpath(output_path)
    font_path = utils.get_font_path(font_name)
    if not os.path.exists(font_path):
        logger.error(f"Font '{font_name}' not found, using default.")
        font_path = utils.get_font_path("MicrosoftYaHeiBold.ttc")

    # This is the robust way to escape paths for ffmpeg filters on Windows
    def escape_ffmpeg_path(path):
        # Replace backslashes with forward slashes
        escaped_path = path.replace('\\', '/')
        # Escape colons
        escaped_path = escaped_path.replace(':', '\\:')
        return escaped_path

    style_options = [
        f"FontName='{os.path.basename(font_path)}'",
        f"FontSize={font_size}",
        f"PrimaryColour=&H{utils.rgb_to_bgr_hex(text_fore_color)}",
        f"BorderStyle=1",
        f"OutlineColour=&H{utils.rgb_to_bgr_hex(stroke_color)}",
        f"Outline={stroke_width}",
        f"Shadow=0",
        f"MarginV=20"
    ]

    if subtitle_position == 'bottom':
        style_options.append("Alignment=2")  # Bottom center
    elif subtitle_position == 'top':
        style_options.append("Alignment=8")  # Top center
    elif subtitle_position == 'center':
        style_options.append("Alignment=5")  # Middle center
    else:  # custom
        style_options.append(f"Alignment=2,MarginV={int(custom_position)}")

    style_string = ','.join(style_options)

    # Correctly escape paths for ffmpeg's filtergraph
    font_dir_escaped = escape_ffmpeg_path(os.path.dirname(font_path))
    srt_path_escaped = escape_ffmpeg_path(srt_path)

    subtitles_filter = f"subtitles='{srt_path_escaped}':force_style='{style_string}':fontsdir='{font_dir_escaped}'"

    command = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", subtitles_filter,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-vsync", "cfr",
        output_path
    ]

    return _run_ffmpeg_command(command)

# ... (rest of the code remains the same)

def process_scene_video(material_url: str, output_dir: str, target_duration: float, aspect_ratio: str = "16:9") -> str:
    """
    下载单个视频素材，并将其处理（剪辑/循环）到目标时长，同时调整分辨率。
    这是实现音画同步的关键步骤之一。
    """
    try:
        # 创建一个唯一的文件名
        video_filename = os.path.join(output_dir, f"scene_{os.path.basename(material_url)}")
        
        # 下载视频
        response = requests.get(material_url, stream=True)
        response.raise_for_status()
        with open(video_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Downloaded scene video to {video_filename}")


        clip = VideoFileClip(video_filename)
        
        # 如果原始视频时长短于目标时长，就循环视频
        if clip.duration < target_duration:
            clip = clip.loop(duration=target_duration)
        # 如果原始视频时长长于目标时长，就剪辑视频
        else:
            clip = clip.subclip(0, target_duration)
            
        # 调整分辨率和宽高比
        if aspect_ratio == "16:9":
            target_resolution = (1920, 1080)
        else: # 9:16
            target_resolution = (1080, 1920)
        
        # 使用crop和resize确保画面内容不被拉伸
        clip_resized = clip.resize(height=target_resolution[1]) if clip.size[0]/clip.size[1] < target_resolution[0]/target_resolution[1] else clip.resize(width=target_resolution[0])
        clip_cropped = clip_resized.crop(x_center=clip_resized.size[0]/2, y_center=clip_resized.size[1]/2, width=target_resolution[0], height=target_resolution[1])

        processed_filename = os.path.join(output_dir, f"processed_{os.path.basename(video_filename)}")
        clip_cropped.write_videofile(processed_filename, codec="libx264", audio_codec="aac", fps=30, ffmpeg_params=['-pix_fmt', 'yuv420p'])
        
        clip.close()
        clip_cropped.close()
        os.remove(video_filename) # 删除原始下载文件

        logger.info(f"Processed scene video to {processed_filename}, duration: {target_duration}s")
        return processed_filename

    except Exception as e:
        logger.error(f"Error processing scene video from {material_url}: {e}")
        return None

def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
) -> str:
    """
    Generates the final video by adding background music and subtitles using FFmpeg.

    Args:
        video_path (str): Path to the source video file.
        audio_path (str): Path to the background music file.
        subtitle_path (str): Path to the subtitle file.
        output_file (str): Path to save the final output video.
        params (VideoParams): Video parameters including bgm_volume.

    Returns:
        str: The path to the final video if successful, otherwise an empty string.
    """
    logger.info(f"Generating final video for {output_file}")
    temp_dir = os.path.join(os.path.dirname(output_file), "temp_gen")
    os.makedirs(temp_dir, exist_ok=True)

    final_video_path = ""

    try:
        # Step 1: Add background music
        logger.info("Step 1: Adding background music.")
        video_with_bgm_path = os.path.join(temp_dir, f"bgm_{os.path.basename(video_path)}")
        bgm_added_path = add_bgm_to_video_ffmpeg(
            video_path=video_path,
            bgm_path=audio_path,
            output_path=video_with_bgm_path,
            bgm_volume=params.bgm_volume
        )
        if not bgm_added_path:
            logger.error("Failed to add background music. Aborting video generation.")
            return ""

        # Step 2: Add subtitles
        logger.info("Step 2: Adding subtitles.")
        subtitled_video_path = add_subtitles_to_video_ffmpeg(
            video_path=bgm_added_path,
            subtitles_path=subtitle_path,
            output_path=output_file
        )

        if subtitled_video_path:
            logger.success(f"Successfully generated final video: {output_file}")
            final_video_path = output_file
        else:
            logger.error("Failed to add subtitles. Final video not created.")

    finally:
        # Clean up temporary directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    
    return final_video_path
    
