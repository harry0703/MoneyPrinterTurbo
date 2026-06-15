import os
import subprocess
import time
from typing import List, Optional

from loguru import logger
from moviepy import (
    AudioFileClip,
    concatenate_videoclips,
    concatenate_audioclips,
    VideoFileClip,
    TextClip,
    AudioClip,
    ColorClip,
)
from app.utils.composite_clip_factory import create_composite_video_clip, safe_concatenate_videoclips, ensure_clip_duration
from app.config.config import load_config
from app.utils import utils
from app.services.video_utils import wrap_text, parse_color

from app.services.video_utils import (
    close_clip,
    get_video_codec,
    get_video_encoding_params,
    audio_codec,
    fps,
    create_encoding_progress_monitor,
)


def _get_ffmpeg_exe() -> str:
    """Return the FFmpeg executable path, respecting the IMAGEIO_FFMPEG_EXE env var."""
    return os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")


def _get_font_family_name(font_path: str) -> str:
    """
    Extract the font family name from a font file using PIL.
    
    FFmpeg's subtitles filter (libass) needs a font family name (e.g. 'ST Heiti Medium')
    for the FontName style property, not a filename. PIL can read this from the font
    metadata reliably.
    
    Args:
        font_path: Absolute path to the font file (TTF or TTC).
    
    Returns:
        Font family name string. Falls back to filename stem on error.
    """
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(font_path, 12)
        # getname() returns (family_name, style_name)
        return font.getname()[0]
    except Exception:
        # Fallback: use the filename without extension
        return os.path.splitext(os.path.basename(font_path))[0]


def concat_videos_stream_copy(
    video_paths: List[str],
    output_path: str,
) -> bool:
    """
    Concatenate MP4 files using FFmpeg's concat demuxer with -c copy (no re-encoding).

    This is dramatically faster than loading clips into MoviePy and re-encoding,
    but requires all inputs to share the same codec, resolution, fps and pixel format —
    which is guaranteed when they all come from the same build_scene_video() pipeline.

    Args:
        video_paths: Ordered list of absolute paths to scene MP4 files.
        output_path: Destination MP4 path.

    Returns:
        True on success, False on any failure (caller should fall back to slow path).
    """
    if len(video_paths) < 2:
        logger.debug("concat_videos_stream_copy: fewer than 2 paths, skipping fast-path")
        return False

    ffmpeg_exe = _get_ffmpeg_exe()
    list_path = output_path + ".concat.txt"

    try:
        # Write the concat list file (FFmpeg concat demuxer format)
        with open(list_path, "w", encoding="utf-8") as fh:
            for p in video_paths:
                # FFmpeg requires single-quoted paths with internal quotes escaped
                escaped = p.replace("'", r"'\''")
                fh.write(f"file '{escaped}'\n")
        logger.debug(f"concat_videos_stream_copy: wrote concat list to {list_path}")

        result = subprocess.run(
            [
                ffmpeg_exe,
                "-y",                       # overwrite without asking
                "-f", "concat",
                "-safe", "0",
                "-i", list_path,
                "-c", "copy",               # zero re-encoding
                "-movflags", "+faststart",  # web-friendly moov atom placement
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.warning(
                f"concat_videos_stream_copy: FFmpeg exited with code {result.returncode}; "
                f"falling back to re-encode path. stderr: {result.stderr[:500]}"
            )
            return False

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.warning("concat_videos_stream_copy: output file is missing or empty; falling back")
            return False

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.success(
            f"concat_videos_stream_copy: {len(video_paths)} scenes stitched in "
            f"{output_path} ({size_mb:.1f} MB) — no re-encoding"
        )
        return True

    except subprocess.TimeoutExpired:
        logger.warning("concat_videos_stream_copy: FFmpeg timed out; falling back to re-encode path")
        return False
    except FileNotFoundError:
        logger.warning(
            f"concat_videos_stream_copy: FFmpeg not found at '{ffmpeg_exe}'; falling back"
        )
        return False
    except Exception as exc:
        logger.warning(f"concat_videos_stream_copy: unexpected error ({exc}); falling back")
        return False
    finally:
        # Always clean up the temporary concat list file
        try:
            if os.path.exists(list_path):
                os.remove(list_path)
        except OSError:
            pass


def finalize_video(
    processed_clips: List,
    combined_video_path: str,
    audio_file: str,
    threads: int,
) -> str:
    """
    Finalize video by concatenating clips and adding audio
    
    Args:
        processed_clips: List of processed video clips
        combined_video_path: Path to save the final video
        audio_file: Path to audio file
        threads: Number of threads to use
    
    Returns:
        Path to the final video
    """
    if not processed_clips:
        logger.warning("no clips available for merging")
        return None
    
    # Concatenate all clips in memory
    logger.debug(f"concatenating {len(processed_clips)} clips in memory")
    try:
        # Concatenate all clips at once (no intermediate encoding)
        final_video = safe_concatenate_videoclips(processed_clips)
        
        logger.info(f"clips concatenated, total duration: {final_video.duration:.2f}s")
        
        # Note: Pillarbox is now added at the final video generation stage (after subtitles)
        
        # Load audio if provided
        if audio_file:
            audio_clip = AudioFileClip(audio_file)
            
            # Trim video to match audio duration
            video_duration_final = final_video.duration
            audio_duration = audio_clip.duration
            if video_duration_final > audio_duration:
                final_video = final_video.subclipped(0, audio_duration)
                logger.info(f"video trimmed to match audio duration: {audio_duration:.2f}s")
            
            # Add audio to video
            final_video = final_video.with_audio(audio_clip)
        else:
            logger.info("Using existing audio from scene videos")
        
        # Write final video with audio (single encoding step)
        logger.info("writing final video with audio (single encoding step)")
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if get_video_encoding_params()["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(get_video_encoding_params()["crf"])])
        
        # Get the latest video codec (dynamic detection)
        current_codec = get_video_codec()
        current_encoding_params = get_video_encoding_params()
        
        output_dir = os.path.dirname(combined_video_path)
        
        try:
            final_video.write_videofile(
                filename=combined_video_path,
                threads=int(threads),
                logger=None,
                temp_audiofile_path=output_dir,
                audio_codec=audio_codec,
                fps=fps,
                codec=current_codec,
                bitrate=current_encoding_params["bitrate"],
                preset=current_encoding_params["preset"],
                ffmpeg_params=ffmpeg_params
            )
        except Exception as e:
            # If encoder not found, fallback to CPU encoder
            if "Unknown encoder" in str(e) or "Encoder not found" in str(e):
                logger.warning(f"Encoder {current_codec} not found, falling back to CPU encoder (libx264)")
                # Use CPU encoder
                current_codec = "libx264"
                # Get CPU encoding parameters
                current_encoding_params = get_video_encoding_params()
                # Try again with CPU encoder
                final_video.write_videofile(
                    filename=combined_video_path,
                    threads=int(threads),
                    logger=None,
                    temp_audiofile_path=output_dir,
                    audio_codec=audio_codec,
                    fps=fps,
                    codec=current_codec,
                    bitrate=current_encoding_params["bitrate"],
                    preset=current_encoding_params["preset"],
                    ffmpeg_params=ffmpeg_params
                )
            else:
                # Re-raise other exceptions
                raise
        
        logger.success(f"final video saved to: {combined_video_path}")
        
        # Verify the output file is valid before closing clips
        if os.path.exists(combined_video_path):
            file_size = os.path.getsize(combined_video_path)
            if file_size == 0:
                logger.error(f"Output video file is EMPTY: {combined_video_path}")
                close_clip(final_video)
                if audio_file:
                    close_clip(audio_clip)
                for clip in processed_clips:
                    close_clip(clip)
                return None
            # Quick validation: try to read the file back to ensure it's valid
            try:
                _verify_clip = VideoFileClip(combined_video_path)
                _verify_duration = _verify_clip.duration
                close_clip(_verify_clip)
                logger.info(f"Output file validated: {combined_video_path} ({file_size} bytes, {_verify_duration:.2f}s)")
            except Exception as ve:
                logger.error(f"Output video file validation failed: {combined_video_path} - {ve}")
                close_clip(final_video)
                if audio_file:
                    close_clip(audio_clip)
                for clip in processed_clips:
                    close_clip(clip)
                return None
        
        # Close all clips
        close_clip(final_video)
        if audio_file:
            close_clip(audio_clip)
        for clip in processed_clips:
            close_clip(clip)
        
    except Exception as e:
        logger.error(f"failed to merge clips and add audio: {str(e)}")
        return None
    
    logger.info("video combining completed")
    return combined_video_path


def _ffmpeg_fast_encode(
    video_path: str,
    output_file: str,
    silence_duration: float = 0,
    pillarbox: bool = False,
    pillarbox_bg_color: str = "black",
    subtitle_file: str = None,
    subtitle_params: dict = None,
    bgm_file: str = None,
    bgm_volume: float = 0.2,
    target_width: int = 1080,
    target_height: int = 1920,
    task_id: str = None,
    progress_callback=None,
) -> bool:
    """
    Use FFmpeg filter_complex to encode the final video in a single streaming pass,
    replacing MoviePy's frame-by-frame compositing.
    
    Handles: silence prefix, pillarbox, subtitle burn-in, BGM mixing, encoding.
    
    Args:
        video_path: Path to the combined scene video
        output_file: Output file path
        silence_duration: Seconds of still-frame prefix to prepend
        pillarbox: Whether to add pillarbox bars (3:4 in 9:16)
        pillarbox_bg_color: Background color for pillarbox
        subtitle_file: Path to SRT/ASS subtitle file to burn in
        subtitle_params: Dict with font_name, font_size, colors, position, margin
        bgm_file: Path to BGM audio file
        bgm_volume: BGM volume multiplier (0.0-1.0)
        target_width/height: Output resolution for pillarbox
        task_id: Task ID for progress monitoring
        progress_callback: Optional progress callback
    
    Returns:
        True on success, False on failure (caller should fall back to MoviePy)
    """
    ffmpeg_exe = os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")
    
    # Build input args
    inputs = ["-i", video_path]
    filter_parts = []
    cur_label = "0:v"
    
    audio_label = "0:a?"  # optional audio from video
    extra_outputs = []
    
    # 1. Silence prefix — tpad clones the first frame
    if silence_duration > 0:
        filter_parts.append(
            f"[{cur_label}]tpad=start_mode=clone:start_duration={silence_duration}[v_tpad]"
        )
        cur_label = "v_tpad"
        # Offset the audio by silence_duration using adelay
        filter_parts.append(
            f"[{audio_label}]adelay={int(silence_duration * 1000)}|{int(silence_duration * 1000)}[a_delayed]"
        )
        audio_label = "a_delayed"
    
    # 2. Pillarbox — pad to target dimensions with background color
    if pillarbox:
        filter_parts.append(
            f"[{cur_label}]scale={target_width}:{target_height}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:"
            f"color={pillarbox_bg_color}[v_padded]"
        )
        cur_label = "v_padded"
    
    # 3. Subtitle burn-in via FFmpeg subtitles filter
    if subtitle_file and os.path.exists(subtitle_file):
        # Escape colons and backslashes in the path for FFmpeg's subtitles filter
        escaped_sub = (subtitle_file
                       .replace("\\", "/")
                       .replace(":", "\\:")
                       .replace("'", "\\'"))
        
        sub_style = ""
        fonts_dir_option = ""
        if subtitle_params:
            style_parts = []
            if subtitle_params.get("font_name"):
                style_parts.append(f"FontName={subtitle_params['font_name']}")
            if subtitle_params.get("font_size"):
                style_parts.append(f"FontSize={subtitle_params['font_size']}")
            if subtitle_params.get("primary_color"):
                style_parts.append(f"PrimaryColour={subtitle_params['primary_color']}")
            if subtitle_params.get("outline_color"):
                style_parts.append(f"OutlineColour={subtitle_params['outline_color']}")
            if subtitle_params.get("outline_width"):
                style_parts.append(f"Outline={subtitle_params['outline_width']}")
            if subtitle_params.get("alignment"):
                style_parts.append(f"Alignment={subtitle_params['alignment']}")
            if subtitle_params.get("margin_v"):
                style_parts.append(f"MarginV={subtitle_params['margin_v']}")
            if style_parts:
                sub_style = f":force_style='{','.join(style_parts)}'"
            
            # If fonts_dir is provided, add it as a subtitles filter option
            # so libass can find the font by family name
            fonts_dir = subtitle_params.get("fonts_dir")
            if fonts_dir and os.path.isdir(fonts_dir):
                escaped_dir = (fonts_dir
                              .replace("\\", "/")
                              .replace(":", "\\:")
                              .replace("'", "\\'"))
                fonts_dir_option = f":fontsdir='{escaped_dir}'"
        
        filter_parts.append(
            f"[{cur_label}]subtitles='{escaped_sub}'{fonts_dir_option}{sub_style}[v_sub]"
        )
        cur_label = "v_sub"
    
    # 4. BGM mixing
    if bgm_file and os.path.exists(bgm_file):
        bgm_input_idx = len(inputs) // 2  # input index for BGM
        inputs.extend(["-stream_loop", "-1", "-i", bgm_file])
        
        # Adjust BGM volume
        filter_parts.append(
            f"[{bgm_input_idx}:a]volume={bgm_volume}[bgm_vol]"
        )
        
        # Mix with existing video audio (if any)
        filter_parts.append(
            f"[{audio_label}][bgm_vol]amix=inputs=2:duration=first:dropout_transition=3[a_mixed]"
        )
        audio_label = "a_mixed"
    
    # Build -filter_complex string
    filter_complex = ";".join(filter_parts) if filter_parts else ""
    
    # Build encoding args
    enc_params = get_video_encoding_params()
    codec = get_video_codec()
    
    enc_args = ["-c:v", codec]
    if codec == "libx264":
        enc_args.extend(["-crf", str(enc_params["crf"]), "-preset", enc_params["preset"]])
    elif codec == "h264_nvenc":
        enc_args.extend(["-b:v", enc_params["bitrate"], "-preset", enc_params["preset"]])
    elif codec == "h264_amf":
        enc_args.extend(["-b:v", enc_params["bitrate"], "-quality", "quality"])
    elif codec == "h264_qsv":
        enc_args.extend(["-b:v", enc_params["bitrate"], "-preset", "medium"])
    else:
        enc_args.extend(["-crf", str(enc_params.get("crf", 18)), "-preset", enc_params.get("preset", "medium")])
    
    # Build the full FFmpeg command
    cmd = [ffmpeg_exe, "-y"] + inputs
    
    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex])
    
    cmd.extend([
        "-map", f"[{cur_label}]",   # processed video
        "-map", f"[{audio_label}]",  # processed audio (optional)
        *enc_args,
        "-c:a", audio_codec,
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-fps_mode", "cfr",
        "-r", str(fps),
        "-shortest",
        "-movflags", "+faststart",
        output_file
    ])
    
    logger.info(f"FFmpeg fast encode: {' '.join(cmd[:10])}... ({len(filter_parts)} filters)")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            stderr_tail = result.stderr[-500:] if result.stderr else ""
            logger.warning(f"FFmpeg fast encode failed (rc={result.returncode}): {stderr_tail}")
            # Clean up partial output
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except OSError:
                    pass
            return False
        
        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            logger.warning("FFmpeg fast encode produced empty output")
            return False
        
        size_mb = os.path.getsize(output_file) / 1024 / 1024
        logger.success(f"FFmpeg fast encode complete: {output_file} ({size_mb:.1f} MB)")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg fast encode timed out (600s)")
        return False
    except Exception as e:
        logger.error(f"FFmpeg fast encode error: {e}")
        return False


def _fmt_duration(seconds):
    """Format seconds as HH:MM:SS string."""
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"


def _log_durations(end_time, task_create_time=None, task_start_time=None, scene_synthesis_start_time=None):
    """Log task lifecycle, task running duration, and scene synthesis duration."""
    if task_create_time:
        logger.info(f"Task lifecycle: {_fmt_duration(end_time - task_create_time)}")
    if task_start_time:
        logger.info(f"Task running duration: {_fmt_duration(end_time - task_start_time)}")
    if scene_synthesis_start_time:
        logger.info(f"Scene synthesis duration: {_fmt_duration(end_time - scene_synthesis_start_time)}")


def process_final_video(
    task_id: str,
    params,
    scene_results: list = None,
    combined_video_path: str = None,
    video_clip=None,
    subtitle_file: str = None,
    audio_file: str = None,
    output_file: str = None,
    progress_callback=None,
    task_create_time: float = None,
    task_start_time: float = None,
    scene_synthesis_start_time: float = None,
):
    """
    Shared function to process combined video after scene generation.
    Handles: silence prefix, title, subtitles, BGM, and final rendering.
    
    Args:
        task_id: Task ID
        params: Video parameters  
        scene_results: List of scene results (for subtitle merging)
        combined_video_path: Path to combined scene video (required if video_clip not provided)
        video_clip: Optional pre-loaded video clip
        subtitle_file: Path to subtitle file (optional, will be merged from scenes if not provided)
        audio_file: Optional BGM file
        output_file: Output file path (required)
        progress_callback: Optional callback function for progress updates
        task_create_time: Optional task creation time (time.time()). Used for "Task lifecycle" log.
        task_start_time: Optional task running start time (time.time()). Used for "Task running duration" log.
        scene_synthesis_start_time: Optional scene synthesis start time (time.time()). Used for "Scene synthesis duration" log.
    
    Returns:
        Final video path or None if failed
    """
    import time
    from loguru import logger
    from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, afx, ImageClip, TextClip
    import numpy as np
    from app.utils.composite_clip_factory import create_composite_video_clip, safe_concatenate_videoclips, ensure_clip_duration
    
    start_time = time.time()
    logger.info(f"Starting process_final_video for task: {task_id}")
    
    try:
        # Load video clip if not provided
        if video_clip is None:
            if not combined_video_path or not os.path.exists(combined_video_path):
                logger.error(f"Neither video_clip nor valid combined_video_path provided")
                return None
            
            video_clip = VideoFileClip(combined_video_path)
            logger.info(f"Loaded video clip: {combined_video_path}")
        
        # Validate that the video clip was loaded correctly
        try:
            _duration = video_clip.duration
        except AttributeError:
            logger.error(f"Failed to load video - clip duration not available")
            return None
        
        # Add pillarbox bars for 3:4 aspect ratio
        if hasattr(params, 'video_aspect') and params.video_aspect:
            from app.models.schema import VideoAspect
            
            video_aspect = params.video_aspect
            if isinstance(video_aspect, str):
                try:
                    video_aspect = VideoAspect(video_aspect)
                except ValueError:
                    video_aspect = None
            
            if video_aspect == VideoAspect.portrait_3_4:
                from app.services.video_utils import parse_color
                
                clip_w, clip_h = video_clip.size
                target_width, target_height = 1080, 1920
                
                scale_factor = target_width / clip_w
                new_width = round(clip_w * scale_factor)
                new_height = round(clip_h * scale_factor)
                
                scaled_clip = video_clip.resized(new_size=(new_width, new_height))
                y_offset = (target_height - new_height) // 2
                
                output_bg_color = getattr(params, 'output_bg_color', None) or 'black'
                bg_color = parse_color(output_bg_color)
                
                background = ColorClip(
                    size=(target_width, target_height),
                    color=bg_color,
                    duration=video_clip.duration
                )
                
                video_clip = create_composite_video_clip([
                    background,
                    scaled_clip.with_position(("center", y_offset))
                ])
                logger.info(f"Added pillarbox for 3:4 -> 9:16: {clip_w}x{clip_h} -> {target_width}x{target_height}")
        
        # Load config for silence duration
        from app.config.config import silence_duration as config_silence_duration
        silence_duration = 0
        
        # Add Silence Prefix FIRST
        if config_silence_duration > 0:
            from app.utils.composite_clip_factory import safe_concatenate_videoclips, ensure_clip_duration
            
            video_clip = ensure_clip_duration(video_clip)
            
            first_frame = video_clip.get_frame(0)
            if len(first_frame.shape) == 2:
                first_frame = np.stack([first_frame] * 3, axis=-1)
            
            still_frame_clip = ImageClip(first_frame, duration=config_silence_duration)
            video_clip = safe_concatenate_videoclips([still_frame_clip, video_clip])
            silence_duration = config_silence_duration
            
            logger.info(f"Silence Prefix prepended: {silence_duration}s clean still frame")
        
        # Add title AFTER Silence Prefix
        if hasattr(params, 'title_enabled') and params.title_enabled and hasattr(params, 'title_text') and params.title_text:
            logger.info("Adding title to video")
            video_clip = ensure_clip_duration(video_clip)
            from app.services.title import add_title_to_video
            
            try:
                video_clip = add_title_to_video(video_clip, params)
                logger.info(f"Title added, video duration: {getattr(video_clip, 'duration', 'NOT SET')}s")
            except Exception as e:
                logger.error(f"Failed to add title: {e}")
        
        # Add subtitle if enabled
        if params.subtitle_enabled:
            # Merge subtitles from scenes if no subtitle file provided
            using_merged_subtitle = False
            if not subtitle_file and scene_results:
                from app.services import subtitle
                merged_subtitle_path = subtitle.merge_scene_subtitles(
                    task_id, scene_results, silence_duration=silence_duration
                )
                if merged_subtitle_path and os.path.exists(merged_subtitle_path):
                    subtitle_file = merged_subtitle_path
                    using_merged_subtitle = True
                    logger.info(f"Using merged subtitle file (with silence duration offset): {subtitle_file}")
                elif scene_results:
                    subtitle_file = scene_results[0].get("subtitle_path")
                    logger.warning(f"Falling back to first scene subtitle (will add silence duration offset): {subtitle_file}")
            
            if subtitle_file and os.path.exists(subtitle_file):
                logger.info("Adding subtitles to video")
                try:
                    from app.services.title import _get_valid_font_path
                    from app.services.subtitle import file_to_subtitles, _srt_time_to_seconds
                    from app.services.video_utils import parse_color
                    
                    font_path = ""
                    if not params.font_name:
                        params.font_name = "STHeitiMedium.ttc"
                    font_path = _get_valid_font_path(params.font_name)
                    
                    subtitle_items = file_to_subtitles(subtitle_file)
                    logger.info(f"Loaded {len(subtitle_items)} subtitles from {subtitle_file}")
                    
                    subtitle_clips = []
                    video_width, video_height = video_clip.size
                    
                    if not os.path.exists(font_path):
                        logger.warning(f"Font file not found: {font_path}, using default font")
                        font_path = None
                    
                    _cfg = load_config()
                    ui_config = _cfg.get("ui", {})
                    subtitle_margin = ui_config.get("subtitle_margin", 0.05)
                    max_width = video_width * (1 - 2 * subtitle_margin) * 0.95
                    subtitle_auto_fit = ui_config.get("subtitle_auto_fit", False)
                    
                    for item in subtitle_items:
                        index, time_str, text = item
                        start_end = time_str.split(" --> ")
                        if len(start_end) == 2:
                            start_time_val = _srt_time_to_seconds(start_end[0])
                            end_time = _srt_time_to_seconds(start_end[1])
                            
                            # Adjust timestamps for silence duration
                            # Only add silence duration offset if subtitles are NOT already merged (i.e., using fallback or single video)
                            if not using_merged_subtitle and silence_duration > 0:
                                start_time_val += silence_duration
                                end_time += silence_duration
                                logger.debug(f"Added silence duration offset ({silence_duration}s) to subtitle")
                            
                            duration = end_time - start_time_val
                            if duration <= 0:
                                logger.warning(f"Skipping subtitle with invalid duration: {duration}s")
                                continue
                            
                            wrapped_text, _, _ = wrap_text(
                                text, max_width=max_width, font=font_path, 
                                fontsize=int(params.font_size), auto_fit=subtitle_auto_fit
                            )
                            
                            bg_color = params.text_background_color
                            if bg_color == 'transparent' or bg_color is False:
                                bg_color = None
                            elif isinstance(bg_color, str):
                                bg_color = parse_color(bg_color)
                            else:
                                bg_color = None
                            
                            txt_clip = TextClip(
                                text=wrapped_text,
                                font=font_path,
                                font_size=int(params.font_size),
                                color=parse_color(params.text_fore_color),
                                bg_color=bg_color,
                                stroke_color=parse_color(params.stroke_color),
                                stroke_width=int(params.stroke_width),
                            )
                            
                            margin_px = video_height * subtitle_margin
                            if params.subtitle_position == "bottom":
                                txt_clip = txt_clip.with_position(("center", video_height - margin_px - txt_clip.h))
                            elif params.subtitle_position == "top":
                                txt_clip = txt_clip.with_position(("center", margin_px))
                            elif params.subtitle_position == "custom":
                                max_y = video_height - txt_clip.h - margin_px
                                min_y = margin_px
                                custom_y = (video_height - txt_clip.h) * (params.custom_position / 100)
                                custom_y = max(min_y, min(custom_y, max_y))
                                txt_clip = txt_clip.with_position(("center", custom_y))
                            else:
                                txt_clip = txt_clip.with_position(("center", "center"))
                            
                            txt_clip = txt_clip.with_start(start_time_val).with_duration(duration)
                            subtitle_clips.append(txt_clip)
                    
                    logger.info(f"Created {len(subtitle_clips)} subtitle clips")
                    
                    if subtitle_clips:
                        video_clip = create_composite_video_clip([video_clip] + subtitle_clips)
                        logger.success("Subtitles added to video")
                except Exception as e:
                    logger.error(f"Failed to add subtitles: {e}")
        
        # Add BGM
        logger.info(f"Getting BGM file: bgm_type={getattr(params, 'bgm_type', 'none')}, bgm_file={getattr(params, 'bgm_file', '')}")
        bgm_file = None
        bgm_type = getattr(params, 'bgm_type', None)
        if bgm_type and bgm_type != 'none':
            from app.services.video_utils import get_bgm_file
            bgm_file = get_bgm_file(bgm_type=bgm_type, bgm_file=getattr(params, 'bgm_file', ''))
        
        # Also check audio_file parameter (for scene integration)
        if not bgm_file and audio_file and os.path.exists(audio_file):
            bgm_file = audio_file
        
        logger.info(f"BGM file result: {bgm_file}")
        
        if bgm_file and os.path.exists(bgm_file):
            try:
                bgm_clip = AudioFileClip(bgm_file).with_effects([
                    afx.MultiplyVolume(params.bgm_volume if hasattr(params, 'bgm_volume') else 0.2),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ])
                
                existing_audio = video_clip.audio
                if existing_audio:
                    combined_audio = CompositeAudioClip([existing_audio, bgm_clip])
                    video_clip = video_clip.with_audio(combined_audio)
                else:
                    video_clip = video_clip.with_audio(bgm_clip)
                
                logger.success("BGM added to video")
            except Exception as e:
                logger.error(f"Failed to add BGM: {e}")
        
        # Write final video
        logger.info(f"Writing final video to: {output_file}")
        
        # Ensure video_clip has valid duration
        if not hasattr(video_clip, 'duration') or video_clip.duration is None:
            logger.error("CRITICAL: video_clip has no duration attribute")
            return None
        
        # ── Determine whether title is enabled ──
        has_title = (hasattr(params, 'title_enabled') and params.title_enabled
                     and hasattr(params, 'title_text') and params.title_text)

        # ── Build shared FFmpeg params (used by both fast & hybrid paths) ──
        is_pillarbox = False
        if hasattr(params, 'video_aspect') and params.video_aspect:
            vasp = params.video_aspect
            logger.info(f"pillarbox check: raw video_aspect={vasp!r} (type={type(vasp).__name__})")
            if isinstance(vasp, str):
                from app.models.schema import VideoAspect as _VA
                try:
                    vasp = _VA(vasp)
                    logger.info(f"pillarbox check: converted via _VA -> {vasp!r} (value={vasp.value})")
                except ValueError:
                    logger.warning(f"pillarbox check: failed to parse video_aspect={vasp!r}")
                    vasp = None
            # Compare value "3:4" — use .value, NOT str() because Python 3.11+
            # str() on a str enum returns 'VideoAspect.portrait_3_4' (the repr),
            # not '3:4' (the actual value). .value always gives the raw value.
            if vasp is not None and hasattr(vasp, 'value') and vasp.value == "3:4":
                is_pillarbox = True
                logger.info("pillarbox check: IS 3:4 -> pillarbox enabled")
            else:
                vasp_val = getattr(vasp, 'value', str(vasp))
                logger.info(f"pillarbox check: vasp.value={vasp_val!r} != '3:4' -> pillarbox disabled")
        
        sub_params = None
        actual_sub_file = subtitle_file if subtitle_file and os.path.exists(subtitle_file) else None
        if actual_sub_file and params.subtitle_enabled:
            from app.services.title import _get_valid_font_path
            font_path = _get_valid_font_path(getattr(params, 'font_name', 'STHeitiMedium.ttc'))
            
            # Use font family name (libass can't resolve filenames like 'STHeitiMedium.ttc')
            font_family = _get_font_family_name(font_path) if font_path else "Arial"
            
            sub_params = {
                "font_name": font_family,
                "font_size": int(getattr(params, 'font_size', 28)),
                "primary_color": "&H00FFFFFF",
                "fonts_dir": os.path.dirname(font_path) if font_path else None,
            }
            
            pos = getattr(params, 'subtitle_position', 'bottom')
            align_map = {"bottom": 2, "top": 8, "center": 4, "custom": 2}
            sub_params["alignment"] = align_map.get(pos, 2)
            
            _ui_cfg = load_config().get("ui", {})
            margin_ratio = _ui_cfg.get("subtitle_margin", 0.05)
            sub_params["margin_v"] = int(1920 * margin_ratio)
            
            stroke_w = int(getattr(params, 'stroke_width', 0) or 0)
            if stroke_w > 0:
                sc = getattr(params, 'stroke_color', 'black')
                sub_params["outline_color"] = f"&H00{sc}" if not sc.startswith('&H') else sc
                sub_params["outline_width"] = stroke_w
        
        bgm_vol = float(getattr(params, 'bgm_volume', 0.2))
        
        # ── Hybrid path: FFmpeg (silence+pillarbox+subs+BGM) + MoviePy (title only) ──
        if has_title and combined_video_path and os.path.exists(combined_video_path):
            import uuid
            temp_no_title = os.path.join(
                os.path.dirname(output_file),
                f".no_title_{uuid.uuid4().hex[:8]}.mp4"
            )
            
            logger.info("Hybrid path: encoding base video via FFmpeg (silence+pillarbox+subs+BGM)...")
            ffmpeg_ok = _ffmpeg_fast_encode(
                video_path=combined_video_path,
                output_file=temp_no_title,
                silence_duration=silence_duration,
                pillarbox=is_pillarbox,
                pillarbox_bg_color=getattr(params, 'output_bg_color', None) or 'black',
                subtitle_file=actual_sub_file,
                subtitle_params=sub_params,
                bgm_file=bgm_file,
                bgm_volume=bgm_vol,
                target_width=1080,
                target_height=1920,
                task_id=task_id,
                progress_callback=progress_callback,
            )
            
            if ffmpeg_ok:
                new_clip = None
                try:
                    logger.info("Hybrid path: loading FFmpeg-encoded base and applying title overlay...")
                    new_clip = VideoFileClip(temp_no_title)
                    from app.services.title import add_title_to_video
                    new_clip = add_title_to_video(new_clip, params)
                    
                    # Swap clips — close old modified clip, keep new hybrid one
                    video_clip.close()
                    video_clip = new_clip
                    new_clip = None  # prevent double-close
                    logger.success("Hybrid path: title overlay applied successfully, proceeding to MoviePy write")
                except Exception as e:
                    logger.warning(f"Hybrid title overlay failed: {e}, falling back to full MoviePy")
                    if new_clip is not None:
                        new_clip.close()
                finally:
                    try:
                        if os.path.exists(temp_no_title):
                            os.remove(temp_no_title)
                    except OSError:
                        pass
            else:
                logger.warning("Hybrid path FFmpeg encode failed, falling back to full MoviePy")
        
        # ── Fast FFmpeg path (skip MoviePy compositing when no title) ──
        if not has_title and combined_video_path and os.path.exists(combined_video_path):
            ffmpeg_success = _ffmpeg_fast_encode(
                video_path=combined_video_path,
                output_file=output_file,
                silence_duration=silence_duration,
                pillarbox=is_pillarbox,
                pillarbox_bg_color=getattr(params, 'output_bg_color', None) or 'black',
                subtitle_file=actual_sub_file,
                subtitle_params=sub_params,
                bgm_file=bgm_file,
                bgm_volume=bgm_vol,
                target_width=1080,
                target_height=1920,
                task_id=task_id,
                progress_callback=progress_callback,
            )
            
            if ffmpeg_success:
                video_clip.close()
                end_time = time.time()
                logger.success(f"Video generated (fast FFmpeg): {output_file}")
                _log_durations(end_time, task_create_time, task_start_time, scene_synthesis_start_time)
                return output_file
            
            logger.warning("FFmpeg fast encode failed, falling back to MoviePy")
        
        # ── MoviePy encoding path (fallback or title requires TextClip) ──
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if get_video_encoding_params()["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(get_video_encoding_params()["crf"])])
        
        progress_monitor = create_encoding_progress_monitor(
            task_id=task_id,
            output_file=output_file,
            progress_callback=progress_callback,
            log_interval=60
        )
        progress_monitor.start_monitoring()
        
        try:
            video_clip.write_videofile(
                filename=output_file,
                threads=2,
                logger=None,
                temp_audiofile_path=os.path.dirname(output_file),
                audio_codec=audio_codec,
                fps=fps,
                codec=get_video_codec(),
                bitrate=get_video_encoding_params()["bitrate"],
                preset=get_video_encoding_params()["preset"],
                ffmpeg_params=ffmpeg_params
            )
        finally:
            progress_monitor.stop_monitoring()
        
        video_clip.close()
        
        end_time = time.time()
        logger.success(f"Video generated successfully: {output_file}")
        _log_durations(end_time, task_create_time, task_start_time, scene_synthesis_start_time)
        
        return output_file
        
    except Exception as e:
        logger.error(f"Failed to process final video: {e}")
        raise
