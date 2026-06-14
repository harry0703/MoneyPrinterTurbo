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

def process_final_video(
    task_id: str,
    params,
    scene_results: list = None,
    combined_video_path: str = None,
    video_clip=None,
    subtitle_file: str = None,
    audio_file: str = None,
    output_file: str = None,
    progress_callback=None
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
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.success(f"Video generated successfully: {output_file}")
        logger.info(f"Processing duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        
        return output_file
        
    except Exception as e:
        logger.error(f"Failed to process final video: {e}")
        raise
