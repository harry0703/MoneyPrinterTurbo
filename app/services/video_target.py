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
    CompositeVideoClip,
    AudioClip,
    ColorClip,
)
from app.config.config import load_config
from app.utils import utils
from app.services.video_utils import wrap_text

from app.services.video_utils import (
    close_clip,
    get_video_codec,
    get_video_encoding_params,
    audio_codec,
    fps,
)


def finalize_video(
    processed_clips: List,
    combined_video_path: str,
    audio_file: str,
    threads: int,
    is_first_scene: bool = False,
) -> str:
    """
    Finalize video by concatenating clips and adding audio
    
    Args:
        processed_clips: List of processed video clips
        combined_video_path: Path to save the final video
        audio_file: Path to audio file
        threads: Number of threads to use
        is_first_scene: Whether this is the first scene (adds 0.3s delay to audio)
    
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
        final_video = concatenate_videoclips(processed_clips)
        logger.info(f"clips concatenated, total duration: {final_video.duration:.2f}s")
        
        # Note: Pillarbox is now added at the final video generation stage (after subtitles)
        
        # Load audio if provided
        if audio_file:
            audio_clip = AudioFileClip(audio_file)
            
            # Add 0.3 second delay at the beginning of the first scene's audio
            if is_first_scene:
                silence_clip = AudioClip(lambda t: 0, duration=0.3)
                audio_clip = concatenate_audioclips([silence_clip, audio_clip])
            
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
        from moviepy import CompositeAudioClip, afx
        
        # Load video
        video_clip = VideoFileClip(video_path)
        
        # Load audio if provided
        if audio_path:
            audio_clip = AudioFileClip(audio_path)
            
            # Check if video already has audio
            existing_audio = video_clip.audio
            
            if existing_audio:
                # Mix BGM with existing audio (scene integration scenario)
                logger.info("Mixing BGM with existing video audio")
                bgm_clip = audio_clip.with_effects([
                    afx.MultiplyVolume(params.bgm_volume if hasattr(params, 'bgm_volume') else 0.2),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ])
                combined_audio = CompositeAudioClip([existing_audio, bgm_clip])
                video_clip = video_clip.with_audio(combined_audio)
            else:
                # No existing audio, set BGM as main audio (normal scenario)
                video_clip = video_clip.with_audio(audio_clip)
        
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
                video_clip = CompositeVideoClip([
                    background,
                    scaled_clip.with_position(("center", y_offset))
                ])
                logger.info(f"Added pillarbox for 3:4 -> 9:16: {clip_w}x{clip_h} -> {target_width}x{target_height}")
        
        # Add subtitles if enabled
        if params.subtitle_enabled and subtitle_path and os.path.exists(subtitle_path):
            logger.info("adding subtitles to video")
            try:
                # Load font
                font_path = ""
                if not params.font_name:
                    params.font_name = "STHeitiMedium.ttc"
                font_path = os.path.join(utils.font_dir(), params.font_name)
                if os.name == "nt":
                    font_path = font_path.replace("\\", "/")
                
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
                        # Convert to seconds
                        start_time = _srt_time_to_seconds(start_end[0])
                        end_time = _srt_time_to_seconds(start_end[1])
                        duration = end_time - start_time
                        
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
                        max_width = video_clip.w * (1 - 2 * subtitle_margin)
                        wrapped_text, _ = wrap_text(text, max_width=max_width, font=font_path, fontsize=int(params.font_size))
                        
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
                        txt_clip = txt_clip.with_start(start_time).with_duration(duration)
                        
                        subtitle_clips.append(txt_clip)
                
                logger.info(f"Created {len(subtitle_clips)} subtitle clips")
                
                # Composite video with subtitles
                if subtitle_clips:
                    video_clip = CompositeVideoClip([video_clip] + subtitle_clips)
                    logger.success("subtitles added to video")
            except Exception as e:
                logger.error(f"failed to add subtitles: {e}")
        
        # Write final video
        logger.info(f"writing final video to: {output_file}")
        
        # Build ffmpeg parameters
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if get_video_encoding_params()["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(get_video_encoding_params()["crf"])])
        
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
