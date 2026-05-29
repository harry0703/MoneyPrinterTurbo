import os
import time
from typing import List

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
from app.services.video_utils import wrap_text

from app.services.video_utils import (
    close_clip,
    get_video_codec,
    get_video_encoding_params,
    audio_codec,
    fps,
    create_encoding_progress_monitor,
)


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

def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params,
    progress_callback=None,
):
    """
    Combine video, audio and subtitles into final video
    
    Args:
        video_path: Path to video file
        audio_path: Path to audio file
        subtitle_path: Path to subtitle file
        output_file: Output file path
        params: Video parameters
        progress_callback: Optional callback function for progress updates
    """
    import time
    start_time = time.time()
    logger.info(f"starting video generation: {output_file}")
    
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, ColorClip, AudioClip, afx, ImageClip, concatenate_videoclips, concatenate_audioclips
        
        # Load video
        video_clip = VideoFileClip(video_path)
        
        # Validate that the video clip was loaded correctly (duration must be available)
        try:
            _duration = video_clip.duration
        except AttributeError:
            logger.error(f"Failed to load video: {video_path} - clip duration not available")
            if os.path.exists(video_path):
                file_size = os.path.getsize(video_path)
                logger.error(f"Video file exists but duration not readable. File size: {file_size} bytes")
                if file_size == 0:
                    logger.error("Video file is EMPTY (0 bytes) - source file may not have been written correctly")
            else:
                logger.error(f"Video file does not exist: {video_path}")
            raise ValueError(f"Cannot read video duration from: {video_path}") from None
        
        # Add pillarbox bars for 3:4 aspect ratio (convert to 9:16)
        # This must happen BEFORE subtitles are added so subtitles are positioned relative to output aspect
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
                
                # Calculate scale to fit within target width
                scale_factor = target_width / clip_w
                new_width = round(clip_w * scale_factor)
                new_height = round(clip_h * scale_factor)
                
                # Resize clip to fit target width
                scaled_clip = video_clip.resized(new_size=(new_width, new_height))
                
                # Calculate offset to center vertically
                y_offset = (target_height - new_height) // 2
                
                # Get output background color from params or config
                output_bg_color = getattr(params, 'output_bg_color', None) or 'black'
                bg_color = parse_color(output_bg_color)
                
                # Create background layer with configurable color
                background = ColorClip(
                    size=(target_width, target_height),
                    color=bg_color,
                    duration=video_clip.duration
                )
                
                # Composite the scaled clip on background
                video_clip = create_composite_video_clip([
                    background,
                    scaled_clip.with_position(("center", y_offset))
                ])
                logger.info(f"Added pillarbox for 3:4 -> 9:16: {clip_w}x{clip_h} -> {target_width}x{target_height}")
        
        # Add Silence Prefix FIRST (before audio and subtitles)
        from app.config.config import silence_duration as config_silence_duration
        logger.debug(f"- Loaded silence_duration from config: {config_silence_duration}")
        silence_duration = 0
        if config_silence_duration > 0:
            
            # Extract first frame and create a still frame clip (CLEAN - no subtitles yet!)
            # Ensure frame is in RGB format (0-255)
            import numpy as np
            first_frame = video_clip.get_frame(0)
            if len(first_frame.shape) == 2:
                # Convert grayscale to RGB
                first_frame = np.stack([first_frame] * 3, axis=-1)
            
            # Create still frame with explicit duration
            still_frame_clip = ImageClip(first_frame, duration=config_silence_duration)
            
            logger.debug(f"- Still frame clip created: type={type(still_frame_clip)}, duration={getattr(still_frame_clip, 'duration', 'NOT SET')}")
            logger.debug(f"- Original video clip before concat: type={type(video_clip)}, duration={getattr(video_clip, 'duration', 'NOT SET')}")
            
            # Add audio silence to match video extension (CRITICAL - keeps audio in sync!)
            if video_clip.audio:
                silence_clip = AudioClip(lambda t: 0, duration=config_silence_duration)
                extended_audio = concatenate_audioclips([silence_clip, video_clip.audio])
                video_clip = video_clip.with_audio(extended_audio)
                logger.debug(f"- Audio extended successfully: audio duration={getattr(video_clip.audio, 'duration', 'NOT SET')}")
            
            # Store original video duration before concatenation
            original_duration = getattr(video_clip, 'duration', 0)
            
            # Concatenate still frame with original video using safe version
            video_clip = safe_concatenate_videoclips([still_frame_clip, video_clip])
            logger.debug(f"- After safe_concatenate_videoclips: type={type(video_clip)}, duration={getattr(video_clip, 'duration', 'NOT SET')}")
            
            silence_duration = config_silence_duration
            
            logger.info(f"Silence Prefix prepended: {silence_duration}s clean still frame (no subtitles)")
        
        # Add title AFTER Silence Prefix so it starts from the beginning of the still frame
        if hasattr(params, 'title_enabled') and params.title_enabled and hasattr(params, 'title_text') and params.title_text:
            logger.info("Adding title to video")
            # Ensure video_clip has duration before passing to add_title_to_video
            video_clip = ensure_clip_duration(video_clip)
            logger.debug(f"- Before add_title_to_video: duration={getattr(video_clip, 'duration', 'NOT SET')}")
            from app.services.title import add_title_to_video
            try:
                video_clip = add_title_to_video(video_clip, params)
                logger.debug(f"- After add_title_to_video returned: duration={getattr(video_clip, 'duration', 'NOT SET')}")
            except Exception as e:
                logger.error(f"DEBUG - Exception in add_title_to_video: {type(e).__name__}: {e}")
                raise
            # Validate: ensure the returned clip has a valid duration
            if not hasattr(video_clip, 'duration') or video_clip.duration is None:
                logger.error("add_title_to_video returned a clip without valid duration")
                raise ValueError("Title clip duration not available") from None
            logger.info(f"Title added, video duration: {getattr(video_clip, 'duration', 'NOT SET')}s")
        
        # Add subtitles if enabled
        if params.subtitle_enabled and subtitle_path and os.path.exists(subtitle_path):
            logger.info("adding subtitles to video")
            try:
                # Load font with fallback support
                font_path = ""
                if not params.font_name:
                    params.font_name = "STHeitiMedium.ttc"
                
                # Use the same font validation logic as title.py
                from app.services.title import _get_valid_font_path
                font_path = _get_valid_font_path(params.font_name)
                
                # Create subtitle clips
                subtitle_clips = []
                
                # Import file_to_subtitles function
                from app.services.subtitle import file_to_subtitles, _srt_time_to_seconds
                
                # Parse subtitle file
                subtitle_items = file_to_subtitles(subtitle_path)
                logger.info(f"Loaded {len(subtitle_items)} subtitles from {subtitle_path}")
                
                # Process each subtitle item
                for item in subtitle_items:
                    index, time_str, text = item
                    
                    # Parse time string
                    start_end = time_str.split(" --> ")
                    if len(start_end) == 2:
                        # Convert to seconds - add Silence Prefix offset!
                        start_time_val = _srt_time_to_seconds(start_end[0]) + silence_duration
                        end_time = _srt_time_to_seconds(start_end[1]) + silence_duration
                        duration = end_time - start_time_val
                        
                        # Skip subtitles with negative or zero duration
                        if duration <= 0:
                            logger.warning(f"Skipping subtitle with invalid duration: {duration}s")
                            continue
                        
                        # Wrap text
                        # Get subtitle margin from config (default 0.05 = 5% on each side)
                        # Reload config to get latest values
                        _cfg = load_config()
                        ui_config = _cfg.get("ui", {})
                        subtitle_margin = ui_config.get("subtitle_margin", 0.05)
                        # Apply 5% safety buffer to account for getbbox vs TextClip rendering difference
                        max_width = video_clip.w * (1 - 2 * subtitle_margin) * 0.95
                        subtitle_auto_fit = ui_config.get("subtitle_auto_fit", False)
                        wrapped_text, _, _ = wrap_text(
                            text, max_width=max_width, font=font_path, fontsize=int(params.font_size),
                            auto_fit=subtitle_auto_fit
                        )
                        
                        # Create text clip
                        # Handle transparent background
                        bg_color = params.text_background_color
                        if bg_color == 'transparent':
                            bg_color = None
                        
                        txt_clip = TextClip(
                            text=wrapped_text,
                            font=font_path,
                            font_size=int(params.font_size),
                            color=params.text_fore_color,
                            bg_color=bg_color,
                            stroke_color=params.stroke_color,
                            stroke_width=int(params.stroke_width),
                        )
                        
                        # Position subtitle
                        margin_px = video_clip.h * subtitle_margin
                        if params.subtitle_position == "bottom":
                            txt_clip = txt_clip.with_position(("center", video_clip.h - margin_px - txt_clip.h))
                        elif params.subtitle_position == "top":
                            txt_clip = txt_clip.with_position(("center", margin_px))
                        elif params.subtitle_position == "custom":
                            max_y = video_clip.h - txt_clip.h - margin_px
                            min_y = margin_px
                            custom_y = (video_clip.h - txt_clip.h) * (params.custom_position / 100)
                            custom_y = max(min_y, min(custom_y, max_y))
                            txt_clip = txt_clip.with_position(("center", custom_y))
                        else:  # center
                            txt_clip = txt_clip.with_position(("center", "center"))
                        
                        # Set duration based on subtitle timestamps
                        txt_clip = txt_clip.with_start(start_time_val).with_duration(duration)
                        
                        subtitle_clips.append(txt_clip)
                
                logger.info(f"Created {len(subtitle_clips)} subtitle clips")
                
                # Composite video with subtitles
                if subtitle_clips:
                    video_clip = create_composite_video_clip([video_clip] + subtitle_clips)
                    logger.success("subtitles added to video")
                    logger.debug(f"- After subtitle processing: duration={getattr(video_clip, 'duration', 'NOT SET')}")
            except Exception as e:
                logger.error(f"failed to add subtitles: {e}")
        
        logger.debug(f"- Before loading audio: duration={getattr(video_clip, 'duration', 'NOT SET')}")
        
        # Load audio if provided (AFTER all other processing)
        if audio_path:
            logger.debug(f"- Processing audio: audio_path={audio_path}")
            audio_clip = AudioFileClip(audio_path)
            
            # Add delay at the beginning of audio to match video extension
            silence_clip = AudioClip(lambda t: 0, duration=config_silence_duration)
            audio_clip = concatenate_audioclips([silence_clip, audio_clip])
            
            # Check if video already has audio
            existing_audio = video_clip.audio
            
            if existing_audio:
                # Mix BGM with existing audio (scene integration scenario)
                logger.info("Mixing BGM with existing video audio")
                video_duration = getattr(video_clip, 'duration', None)
                if video_duration is None:
                    video_duration = getattr(video_clip, 'end', 120)
                bgm_clip = audio_clip.with_effects([
                    afx.MultiplyVolume(params.bgm_volume if hasattr(params, 'bgm_volume') else 0.2),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_duration),
                ])
                combined_audio = CompositeAudioClip([existing_audio, bgm_clip])
                video_clip = video_clip.with_audio(combined_audio)
            else:
                # No existing audio, set BGM as main audio (normal scenario)
                video_clip = video_clip.with_audio(audio_clip)
        
        # Write final video
        logger.info(f"writing final video to: {output_file}")
        
        # Final safeguard: ensure video_clip has a valid duration before writing
        if not hasattr(video_clip, 'duration') or video_clip.duration is None:
            logger.error(f"CRITICAL: video_clip has no duration attribute before write_videofile")
            # Try to compute duration from other properties
            if hasattr(video_clip, 'end') and hasattr(video_clip, 'start'):
                video_clip.duration = video_clip.end - video_clip.start
                logger.info(f"Set duration from end-start: {video_clip.duration}")
            elif hasattr(video_clip, 'end'):
                video_clip.duration = video_clip.end
                logger.info(f"Set duration from end: {video_clip.duration}")
            else:
                logger.error("Cannot determine video duration, setting default of 60 seconds")
                video_clip.duration = 60
        
        # Build ffmpeg parameters
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if get_video_encoding_params()["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(get_video_encoding_params()["crf"])])
        
        # Final check before writing
        logger.debug(f"- Final check before write_videofile:")
        logger.debug(f"- video_clip type: {type(video_clip)}")
        logger.debug(f"- hasattr duration: {hasattr(video_clip, 'duration')}")
        logger.debug(f"- duration value: {getattr(video_clip, 'duration', 'NOT SET')}")
        logger.debug(f"- hasattr end: {hasattr(video_clip, 'end')}")
        logger.debug(f"- end value: {getattr(video_clip, 'end', 'NOT SET')}")
        
        # Create and start progress monitor
        progress_monitor = create_encoding_progress_monitor(
            task_id=None,  # task_id not available here
            output_file=output_file,
            progress_callback=progress_callback,
            log_interval=60  # Log every 60 seconds (1 minute)
        )
        progress_monitor.start_monitoring()
        
        try:
            video_clip.write_videofile(
                filename=output_file,
                threads=2,
                logger=None,  # Keep None to avoid MoviePy compatibility issues
                temp_audiofile_path=os.path.dirname(output_file),
                audio_codec=audio_codec,
                fps=fps,
                codec=get_video_codec(),
                bitrate=get_video_encoding_params()["bitrate"],
                preset=get_video_encoding_params()["preset"],
                ffmpeg_params=ffmpeg_params
            )
        finally:
            # Stop progress monitor after encoding completes
            progress_monitor.stop_monitoring()
        
        # Close clips
        video_clip.close()
        if audio_path:
            audio_clip.close()
        
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.success(f"video generated successfully: {output_file}")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        return output_file
        
    except Exception as e:
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.error(f"failed to generate video: {e}")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        raise
