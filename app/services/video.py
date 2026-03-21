import glob
import itertools
import os
import random
import gc
import shutil
import time
import ctypes
from typing import List
from loguru import logger
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont

from app.config import config
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.utils import utils

class SubClippedVideoClip:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None, duration=None):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
fps = 30

# Video quality preset configuration
VIDEO_QUALITY_PRESETS = {
    "cpu": {
        "low": {
            "bitrate": "3M",
            "preset": "fast",
            "crf": 28,
            "description": "Low quality, fast encoding"
        },
        "medium": {
            "bitrate": "5M",
            "preset": "medium",
            "crf": 23,
            "description": "Medium quality, balanced encoding"
        },
        "high": {
            "bitrate": "8M",
            "preset": "slow",
            "crf": 20,
            "description": "High quality, slower encoding"
        },
        "ultra": {
            "bitrate": "12M",
            "preset": "slower",
            "crf": 18,
            "description": "Ultra quality, very slow encoding"
        }
    },
    "gpu": {
        "low": {
            "bitrate": "4M",
            "preset": "p5",
            "crf": 28,
            "description": "Low quality, fast encoding (GPU)"
        },
        "medium": {
            "bitrate": "6M",
            "preset": "p4",
            "crf": 23,
            "description": "Medium quality, balanced encoding (GPU)"
        },
        "high": {
            "bitrate": "10M",
            "preset": "p3",
            "crf": 20,
            "description": "High quality, good encoding (GPU)"
        },
        "ultra": {
            "bitrate": "15M",
            "preset": "p2",
            "crf": 18,
            "description": "Ultra quality, best encoding (GPU)"
        }
    }
}

def get_video_encoding_params():
    """Get video encoding parameters"""
    use_gpu = config.app.get("use_gpu", False)
    # GPU defaults to highest quality, CPU defaults to high quality
    default_quality = "ultra" if use_gpu else "high"
    quality = config.app.get("video_quality", default_quality).lower()
    custom_bitrate = config.app.get("video_bitrate", "")
    
    # Select CPU or GPU preset
    preset_type = "gpu" if use_gpu else "cpu"
    
    # Get quality preset
    preset = VIDEO_QUALITY_PRESETS[preset_type].get(quality, VIDEO_QUALITY_PRESETS[preset_type][default_quality])
    
    # Use custom bitrate if set
    if custom_bitrate:
        bitrate = custom_bitrate
    else:
        bitrate = preset["bitrate"]
    
    # Get encoding preset and CRF value
    encoding_preset = preset["preset"]
    crf = preset["crf"]
    
    logger.info(f"Video encoding params: type={preset_type}, quality={quality}, bitrate={bitrate}, preset={encoding_preset}, crf={crf}")
    
    return {
        "bitrate": bitrate,
        "preset": encoding_preset,
        "crf": crf
    }

# Select video encoder based on configuration
def get_video_codec():
    """Select appropriate video encoder based on configuration and system environment"""
    use_gpu = config.app.get("use_gpu", False)
    
    if not use_gpu:
        logger.info("Video encoder: CPU mode selected (libx264)")
        return "libx264"  # CPU encoder
    
    # Check if NVIDIA GPU encoding is supported
    try:
        import subprocess
        # Get ffmpeg executable path
        ffmpeg_exe = os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")
        logger.debug(f"Using ffmpeg executable: {ffmpeg_exe}")
        
        # Check if ffmpeg supports nvenc encoder
        result = subprocess.run(
            [ffmpeg_exe, "-encoders"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "h264_nvenc" in result.stdout:
            logger.info("Video encoder: GPU mode selected (h264_nvenc) - NVIDIA GPU acceleration enabled")
            return "h264_nvenc"
        else:
            logger.warning("Video encoder: GPU requested but not supported, falling back to CPU (libx264)")
            return "libx264"
    except Exception as e:
        logger.error(f"Video encoder: Failed to check GPU support, using CPU (libx264). Error: {e}")
        return "libx264"

video_codec = get_video_codec()
video_encoding_params = get_video_encoding_params()
logger.info(f"Video encoder initialized: {video_codec} (GPU: {config.app.get('use_gpu', False)})")

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
        
    for file in files:
        try:
            os.remove(file)
        except:
            pass

def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
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
) -> str:
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"audio duration: {audio_duration} seconds")
    # Close audio_clip immediately after getting duration, we'll reopen it later if needed
    close_clip(audio_clip)
    audio_clip = None
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"maximum clip duration: {req_dur} seconds")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    processed_clips = []
    subclipped_items = []
    video_duration = 0
    for video_path in video_paths:
        clip = VideoFileClip(video_path)
        clip_duration = clip.duration
        clip_w, clip_h = clip.size
        close_clip(clip)
        
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)            
            if clip_duration - start_time >= max_clip_duration:
                subclipped_items.append(SubClippedVideoClip(file_path= video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h))
            start_time = end_time    
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random subclipped_items order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
        
    logger.debug(f"total subclipped items: {len(subclipped_items)}")
    
    # Add downloaded clips over and over until we reach the duration of the audio (max_duration) has been reached
    for i, subclipped_item in enumerate(subclipped_items):
        if video_duration > audio_duration:
            break
        
        logger.debug(f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, current duration: {video_duration:.2f}s, remaining: {audio_duration - video_duration:.2f}s")
        
        try:
            clip = VideoFileClip(subclipped_item.file_path).subclipped(subclipped_item.start_time, subclipped_item.end_time)
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
            if video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode.value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip,1)
            elif video_transition_mode.value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip,1)
            elif video_transition_mode.value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip,1, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip,1, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c,1),
                    lambda c: video_effects.fadeout_transition(c,1),
                    lambda c: video_effects.slidein_transition(c,1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c,1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)
                
            # write clip to temp file
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            # Build ffmpeg parameters
            ffmpeg_params = ["-pix_fmt", "yuv420p"]
            if video_encoding_params["crf"] is not None:
                ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
            
            clip.write_videofile(
                clip_file,
                logger=None,
                fps=fps,
                codec=video_codec,
                bitrate=video_encoding_params["bitrate"],
                preset=video_encoding_params["preset"],
                ffmpeg_params=ffmpeg_params
            )
            
            close_clip(clip)
        
            processed_clips.append(SubClippedVideoClip(file_path=clip_file, duration=clip.duration, width=clip_w, height=clip_h))
            video_duration += clip.duration
            
        except Exception as e:
            logger.error(f"failed to process clip: {str(e)}")
    
    # loop processed clips until video duration matches or exceeds the audio duration.
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_clips = processed_clips.copy()
        for clip in itertools.cycle(base_clips):
            if video_duration >= audio_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
     
    # merge video clips progressively, avoid loading all videos at once to avoid memory overflow
    logger.info("starting clip merging process")
    if not processed_clips:
        logger.warning("no clips available for merging")
        return combined_video_path
    
    # if there is only one clip, use it directly
    if len(processed_clips) == 1:
        logger.info("using single clip directly")
        shutil.copy(processed_clips[0].file_path, combined_video_path)
        delete_files(processed_clips)
        logger.info("video combining completed")
        return combined_video_path
    
    # create initial video file as base
    base_clip_path = processed_clips[0].file_path
    temp_merged_video = f"{output_dir}/temp-merged-video.mp4"
    temp_merged_next = f"{output_dir}/temp-merged-next.mp4"
    
    # copy first clip as initial merged video
    shutil.copy(base_clip_path, temp_merged_video)
    
    # merge remaining video clips one by one
    for i, clip in enumerate(processed_clips[1:], 1):
        logger.info(f"merging clip {i}/{len(processed_clips)-1}, duration: {clip.duration:.2f}s")
        
        try:
            # load current base video and next clip to merge
            base_clip = VideoFileClip(temp_merged_video)
            next_clip = VideoFileClip(clip.file_path)
            
            # merge these two clips
            merged_clip = concatenate_videoclips([base_clip, next_clip])

            # save merged result to temp file
            # Build ffmpeg parameters
            ffmpeg_params = ["-pix_fmt", "yuv420p"]
            if video_encoding_params["crf"] is not None:
                ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
            
            merged_clip.write_videofile(
                filename=temp_merged_next,
                threads=int(threads),
                logger=None,
                temp_audiofile_path=output_dir,
                audio_codec=audio_codec,
                fps=fps,
                codec=video_codec,
                bitrate=video_encoding_params["bitrate"],
                preset=video_encoding_params["preset"],
                ffmpeg_params=ffmpeg_params
            )
            close_clip(base_clip)
            close_clip(next_clip)
            close_clip(merged_clip)
            
            # swap temp files for next iteration
            temp_merged_video, temp_merged_next = temp_merged_next, temp_merged_video
            
        except Exception as e:
            logger.error(f"failed to merge clip {i}: {str(e)}")
            break
    
    # final merged video is in temp_merged_video
    # move to final destination
    try:
        if os.path.exists(temp_merged_video):
            shutil.move(temp_merged_video, combined_video_path)
            logger.success(f"merged video saved to: {combined_video_path}")
    except Exception as e:
        logger.error(f"failed to move merged video: {str(e)}")
    
    # clean temp files
    clip_files = [clip.file_path for clip in processed_clips]
    delete_files(clip_files)
    
    # Add audio to the combined video
    logger.info("adding audio to combined video")
    temp_with_audio = None
    video_clip = None
    audio_clip_for_video = None
    audio_clip_trimmed = None
    
    try:
        # Load the combined video
        video_clip = VideoFileClip(combined_video_path)
        
        # Reopen audio file to add it to video
        audio_clip_for_video = AudioFileClip(audio_file)
        
        # Trim audio to match video duration
        video_duration = video_clip.duration
        audio_clip_trimmed = audio_clip_for_video.subclipped(0, min(video_duration, audio_clip_for_video.duration))
        video_clip = video_clip.with_audio(audio_clip_trimmed)
        
        # Write video with audio to temp file
        temp_with_audio = f"{output_dir}/temp-with-audio.mp4"
        # Build ffmpeg parameters
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
        # Write video with audio to temp file
        video_clip.write_videofile(
            filename=temp_with_audio,
            threads=int(threads),
            logger=None,
            temp_audiofile_path=output_dir,
            audio_codec=audio_codec,
            fps=fps,
            codec=video_codec,
            bitrate=video_encoding_params["bitrate"],
            preset=video_encoding_params["preset"],
            ffmpeg_params=ffmpeg_params
        )
        
        logger.success("audio added to combined video")
    except Exception as e:
        logger.error(f"failed to add audio to combined video: {e}")
    finally:
        # Close all clips in finally block to ensure they are always closed
        if video_clip is not None:
            try:
                video_clip.close()
            except Exception as e:
                logger.warning(f"failed to close video_clip: {e}")
        if audio_clip_trimmed is not None:
            try:
                audio_clip_trimmed.close()
            except Exception as e:
                logger.warning(f"failed to close audio_clip_trimmed: {e}")
        if audio_clip_for_video is not None:
            try:
                audio_clip_for_video.close()
            except Exception as e:
                logger.warning(f"failed to close audio_clip_for_video: {e}")
        
        # Force garbage collection to release file handles
        gc.collect()
        
        # Replace original with audio version using robust retry mechanism
        if temp_with_audio and os.path.exists(temp_with_audio):
            # Retry mechanism for file replacement
            max_retries = 10
            retry_delay = 1.0  # Start with 1 second
            
            for attempt in range(max_retries):
                try:
                    # Try to remove original file
                    if os.path.exists(combined_video_path):
                        # Use shutil.move instead of os.rename for better Windows compatibility
                        shutil.move(temp_with_audio, combined_video_path)
                    else:
                        # If original doesn't exist, just rename
                        os.rename(temp_with_audio, combined_video_path)
                    logger.success("video file replaced with audio version")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"failed to replace video file (attempt {attempt + 1}/{max_retries}): {e}, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 1.2  # Exponential backoff
                        gc.collect()  # Force garbage collection again
                        # Try to delete the file using Windows API
                        try:
                            # Try to delete using Windows API
                            if os.path.exists(combined_video_path):
                                ctypes.windll.kernel32.SetFileAttributesW(combined_video_path, 128)  # FILE_ATTRIBUTE_NORMAL
                                ctypes.windll.kernel32.DeleteFileW(combined_video_path)
                        except:
                            pass
                    else:
                        logger.error(f"failed to replace video file after {max_retries} attempts: {e}")
                        # If replacement fails, use temp file as result
                        combined_video_path = temp_with_audio
    
    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # Create ImageFont
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    processed = True
    while processed:
        # Split text into two lines at the middle
        middle = len(text) // 2
        # Find the nearest space to split
        split_pos = text.rfind(' ', 0, middle)
        if split_pos == -1:
            split_pos = text.find(' ', middle)
        if split_pos == -1:
            break
        
        line1 = text[:split_pos]
        line2 = text[split_pos+1:]
        
        # Check if both lines fit within max_width
        w1, h1 = get_text_size(line1)
        w2, h2 = get_text_size(line2)
        
        if w1 <= max_width and w2 <= max_width:
            return f"{line1}\n{line2}", h1 + h2
        else:
            # If still too long, continue splitting the longer line
            if w1 > w2:
                text = line1
            else:
                text = line2
    
    # If we can't split nicely, just return the original
    return text, height

def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
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
    logger.info(f"starting video generation: {output_file}")
    
    try:
        # Load video
        video_clip = VideoFileClip(video_path)
        
        # Load audio
        audio_clip = AudioFileClip(audio_path)
        
        # Set audio to video
        video_clip = video_clip.with_audio(audio_clip)
        
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
                
                # Parse subtitle file
                with open(subtitle_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                current_time = 0
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Parse timecode and text (simplified parsing)
                    # Format: HH:MM:SS,mmm --> HH:MM:SS,mmm
                    if '-->' in line:
                        continue
                    
                    # Check if line is a number (subtitle index)
                    if line.isdigit():
                        continue
                    
                    # This is subtitle text
                    if line:
                        # Wrap text
                        max_width = video_clip.w * 0.9
                        wrapped_text, _ = wrap_text(line, max_width=max_width, font=font_path, fontsize=int(params.font_size))
                        
                        # Create text clip
                        txt_clip = TextClip(
                            text=wrapped_text,
                            font=font_path,
                            font_size=int(params.font_size),
                            color=params.text_fore_color,
                            bg_color=params.text_background_color,
                            stroke_color=params.stroke_color,
                            stroke_width=int(params.stroke_width),
                        )
                        
                        # Position subtitle
                        if params.subtitle_position == "bottom":
                            txt_clip = txt_clip.with_position(("center", video_clip.h * 0.95 - txt_clip.h))
                        elif params.subtitle_position == "top":
                            txt_clip = txt_clip.with_position(("center", video_clip.h * 0.05))
                        elif params.subtitle_position == "custom":
                            margin = 10
                            max_y = video_clip.h - txt_clip.h - margin
                            min_y = margin
                            custom_y = (video_clip.h - txt_clip.h) * (params.custom_position / 100)
                            custom_y = max(min_y, min(custom_y, max_y))
                            txt_clip = txt_clip.with_position(("center", custom_y))
                        else:  # center
                            txt_clip = txt_clip.with_position(("center", "center"))
                        
                        # Set duration (simplified - using fixed duration for each subtitle)
                        txt_clip = txt_clip.with_start(current_time).with_duration(2)
                        current_time += 2
                        
                        subtitle_clips.append(txt_clip)
                
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
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
        video_clip.write_videofile(
            filename=output_file,
            threads=2,
            logger=None,
            temp_audiofile_path=os.path.dirname(output_file),
            audio_codec=audio_codec,
            fps=fps,
            codec=video_codec,
            bitrate=video_encoding_params["bitrate"],
            preset=video_encoding_params["preset"],
            ffmpeg_params=ffmpeg_params
        )
        
        # Close clips
        video_clip.close()
        audio_clip.close()
        
        logger.success(f"video generated successfully: {output_file}")
        return output_file
        
    except Exception as e:
        logger.error(f"failed to generate video: {e}")
        raise
