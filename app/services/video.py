import glob
import itertools
import os
import random
import gc
import shutil
import uuid
from typing import List
import multiprocessing
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
from moviepy.video.io.ffmpeg_writer import FFMPEG_VideoWriter
from PIL import Image, ImageEnhance, ImageFont

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


# Improved video quality settings
audio_codec = "aac"
video_codec = "libx264"
fps = 30
video_bitrate = "25M"
audio_bitrate = "320k"
crf = "15"
preset = "slower"

def get_optimal_encoding_params(width, height, content_type="video"):
    """Get optimal encoding parameters based on resolution and content type."""
    pixels = width * height
    
    # Adjust settings based on resolution and content
    if content_type == "image":
        # Images need higher quality settings
        if pixels >= 1920 * 1080:  # 1080p+
            return {"crf": "12", "bitrate": "35M", "preset": "slower"}
        elif pixels >= 1280 * 720:  # 720p+
            return {"crf": "16", "bitrate": "30M", "preset": "slower"}
        else:
            return {"crf": "18", "bitrate": "25M", "preset": "slow"}
    else:
        # Regular video content
        if pixels >= 1920 * 1080:  # 1080p+
            return {"crf": "18", "bitrate": "30M", "preset": "slower"}
        elif pixels >= 1280 * 720:  # 720p+
            return {"crf": "20", "bitrate": "25M", "preset": "slower"}
        else:
            return {"crf": "22", "bitrate": "20M", "preset": "slow"}

def get_standard_ffmpeg_params(width, height, content_type="video"):
    """Get standardized FFmpeg parameters for consistent quality."""
    params = get_optimal_encoding_params(width, height, content_type)
    if content_type == "image" or (width * height >= 1920 * 1080):
        # Use higher quality for images and high-res content
        pix_fmt = "yuv444p"
    else:
        # Use more compatible format for standard video
        pix_fmt = "yuv420p"

    return [
        "-crf", params["crf"],
        "-preset", params["preset"],
        "-profile:v", "high",
        "-level", "4.1",
        "-x264-params", "keyint=60:min-keyint=60:scenecut=0:ref=3:bframes=3:b-adapt=2:direct=auto:me=umh:subme=8:trellis=2:aq-mode=2",
        "-pix_fmt", pix_fmt,
        "-movflags", "+faststart",
        "-tune", "film",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-color_range", "tv",
        "-bf", "5",  # More B-frames for better compression
        "-g", "60",  # GOP size
        "-qmin", "10",  # Minimum quantizer
        "-qmax", "51",  # Maximum quantizer
        "-qdiff", "4",  # Max difference between quantizers
        "-sc_threshold", "40",  # Scene change threshold
        "-flags", "+cgop+mv4"  # Additional encoding flags
    ]

def ensure_even_dimensions(width, height):
    """Ensure dimensions are even numbers (required for h264)."""
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    return width, height

def close_clip(clip):
    if clip is None:
        return
        
    try:
        # handle child clips in composite clips first
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
        
        # close audio resources with better error handling
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                try:
                    # Check if the reader is still valid before closing
                    if hasattr(clip.audio.reader, 'proc') and clip.audio.reader.proc is not None:
                        if clip.audio.reader.proc.poll() is None:
                            clip.audio.reader.close()
                    else:
                        clip.audio.reader.close()
                except (OSError, AttributeError):
                    # Handle invalid handles and missing attributes
                    pass
            clip.audio = None
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                try:
                    clip.mask.reader.close()
                except (OSError, AttributeError):
                    pass
            clip.mask = None
            
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            try:
                clip.reader.close()
            except (OSError, AttributeError):
                pass
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
        # call clip's own close method if it exists
        if hasattr(clip, 'close'):
            try:
                clip.close()
            except (OSError, AttributeError):
                pass
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    try:
        del clip
    except:
        pass
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]
        
    for file in files:
        try:
            if os.path.exists(file):
                os.remove(file)
        except Exception as e:
            logger.debug(f"failed to delete file {file}: {str(e)}")

def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        if files:
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
    #threads: int = 2,
    threads = min(multiprocessing.cpu_count(), 6),
) -> str:
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"audio duration: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = min(audio_duration / len(video_paths), max_clip_duration)
    logger.info(f"calculated clip duration: {req_dur} seconds")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    video_width, video_height = ensure_even_dimensions(video_width, video_height)

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
                subclipped_items.append(SubClippedVideoClip(file_path=video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h))
            start_time = end_time    
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random subclipped_items order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
        
    logger.debug(f"total subclipped items: {len(subclipped_items)}")
    
    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
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
                
                if abs(clip_ratio - video_ratio) < 0.01:  # Almost same ratio
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    # Use better scaling algorithm for quality
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)
                    
                    # Ensure dimensions are even numbers
                    new_width, new_height = ensure_even_dimensions(new_width, new_height)

                    background = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)
                    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                    clip = CompositeVideoClip([background, clip_resized])
                    
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if video_transition_mode is None or video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode.value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip, 1)
            elif video_transition_mode.value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip, 1)
            elif video_transition_mode.value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip, 1, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip, 1, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c, 1),
                    lambda c: video_effects.fadeout_transition(c, 1),
                    lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)
                
            # Write clip to temp file with improved quality settings
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            encoding_params = get_optimal_encoding_params(video_width, video_height, "video")
            
            clip.write_videofile(clip_file, 
                logger=None, 
                fps=fps, 
                codec=video_codec,
                # Remove bitrate parameter as it conflicts with CRF in ffmpeg_params
                ffmpeg_params=get_standard_ffmpeg_params(video_width, video_height, "video")
            )
            
            # Store clip duration before closing
            clip_duration_value = clip.duration
            close_clip(clip)
        
            processed_clips.append(SubClippedVideoClip(file_path=clip_file, duration=clip_duration_value, width=clip_w, height=clip_h))
            video_duration += clip_duration_value
            
        except Exception as e:
            logger.error(f"failed to process clip: {str(e)}")
    
    # loop processed clips until the video duration matches or exceeds the audio duration.
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
        delete_files([clip.file_path for clip in processed_clips])
        logger.info("video combining completed")
        return combined_video_path
    
    try:
        # Load all processed clips
        video_clips = []
        for clip_info in processed_clips:
            try:
                clip = VideoFileClip(clip_info.file_path)
                if clip.duration > 0 and hasattr(clip, 'size') and None not in clip.size:
                    video_clips.append(clip)
                else:
                    logger.warning(f"Skipping invalid clip: {clip_info.file_path}")
                    close_clip(clip)
            except Exception as e:
                logger.error(f"Failed to load clip {clip_info.file_path}: {str(e)}")
                
        if not video_clips:
            logger.error("No valid clips could be loaded for final concatenation")
            return ""
            
        # Concatenate all clips at once with compose method for better quality
        logger.info(f"Concatenating {len(video_clips)} clips in a single operation")
        final_clip = concatenate_videoclips(video_clips, method="compose")
        
        # Write the final result directly
        encoding_params = get_optimal_encoding_params(video_width, video_height, "video")
        logger.info(f"Writing final video with quality settings: CRF {encoding_params['crf']}, preset {encoding_params['preset']}")
        
        final_clip.write_videofile(
            combined_video_path,
            threads=threads,
            logger=None,
            temp_audiofile_path=os.path.dirname(combined_video_path),
            audio_codec=audio_codec,
            fps=fps,
            ffmpeg_params=get_standard_ffmpeg_params(video_width, video_height, "video")
        )
        
        # Close all clips
        close_clip(final_clip)
        for clip in video_clips:
            close_clip(clip)
            
        logger.info("Video combining completed successfully")
        
    except Exception as e:
        logger.error(f"Error during final video concatenation: {str(e)}")
    finally:
        # Clean up temp files
        clip_files = [clip.file_path for clip in processed_clips]
        delete_files(clip_files)
        
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

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    return result, height

def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()
    video_width, video_height = ensure_even_dimensions(video_width, video_height)

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

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        interline = int(params.font_size * 0.25)
        size=(int(max_width), int(txt_height + params.font_size * 0.25 + (interline * (wrapped_txt.count("\n") + 1))))

        _clip = TextClip(
            text=wrapped_txt,
            font=font_path,
            font_size=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            interline=interline,
            size=size,
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

    video_clip = VideoFileClip(video_path).without_audio()
    audio_clip = AudioFileClip(audio_path).with_effects(
        [afx.MultiplyVolume(params.voice_volume)]
    )

    def make_textclip(text):
        return TextClip(
            text=text,
            font=font_path,
            font_size=params.font_size,
        )

    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(
            subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
        )
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_clip = CompositeVideoClip([video_clip, *text_clips])

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = AudioFileClip(bgm_file).with_effects(
                [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ]
            )
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")

    video_clip = video_clip.with_audio(audio_clip)
    
    # Use improved encoding settings
    try:
        # Get optimized encoding parameters
        encoding_params = get_optimal_encoding_params(video_width, video_height, "video")
        ffmpeg_params = get_standard_ffmpeg_params(video_width, video_height, "video")
        
        # For Windows, use a simpler approach to avoid path issues with two-pass encoding
        if os.name == 'nt':
            # Single pass with high quality settings
            video_clip.write_videofile(
                output_file,
                codec=video_codec,
                audio_codec=audio_codec,
                temp_audiofile_path=output_dir,
                threads=params.n_threads or 2,
                logger=None,
                fps=fps,
                ffmpeg_params=ffmpeg_params
            )
        else:
            # On Unix systems, we can use two-pass encoding more reliably
            # Prepare a unique passlogfile name to avoid conflicts
            passlog_id = str(uuid.uuid4())[:8]
            passlogfile = os.path.join(output_dir, f"ffmpeg2pass_{passlog_id}")
            
            # Create a temporary file for first pass output
            temp_first_pass = os.path.join(output_dir, f"temp_first_pass_{passlog_id}.mp4")
            
            # Flag to track if we should do second pass
            do_second_pass = True
            
            # First pass parameters with explicit passlogfile
            first_pass_params = ffmpeg_params + [
                "-pass", "1",
                "-passlogfile", passlogfile,
                "-an"  # No audio in first pass
            ]
            
            logger.info("Starting first pass encoding...")
            try:
                video_clip.write_videofile(
                    temp_first_pass,  # Write to temporary file instead of null
                    codec=video_codec,
                    audio=False,  # Skip audio processing in first pass
                    threads=params.n_threads or 2,
                    logger=None,
                    fps=fps,
                    ffmpeg_params=first_pass_params
                )
            except Exception as e:
                # If first pass fails, fallback to single-pass encoding
                logger.warning(f"First pass encoding failed: {e}. Falling back to single-pass encoding.")
                video_clip.write_videofile(
                    output_file,
                    codec=video_codec,
                    audio_codec=audio_codec,
                    temp_audiofile_path=output_dir,
                    threads=params.n_threads or 2,
                    logger=None,
                    fps=fps,
                    ffmpeg_params=ffmpeg_params
                )
                do_second_pass = False
            finally:
                # Clean up first pass temporary file
                if os.path.exists(temp_first_pass):
                    try:
                        os.remove(temp_first_pass)
                    except Exception as e:
                        logger.warning(f"Failed to delete temporary first pass file: {e}")
            
            # Second pass only if first pass succeeded
            if do_second_pass:
                logger.info("Starting second pass encoding...")
                second_pass_params = ffmpeg_params + [
                    "-pass", "2",
                    "-passlogfile", passlogfile
                ]
                video_clip.write_videofile(
                    output_file,
                    codec=video_codec,
                    audio_codec=audio_codec,
                    temp_audiofile_path=output_dir,
                    threads=params.n_threads or 2,
                    logger=None,
                    fps=fps,
                    ffmpeg_params=second_pass_params
                )
            
            # Clean up pass log files
            for f in glob.glob(f"{passlogfile}*"):
                try:
                    os.remove(f)
                except Exception as e:
                    logger.warning(f"Failed to delete pass log file {f}: {e}")
    finally:
        # Ensure all resources are properly closed
        close_clip(video_clip)
        close_clip(audio_clip)
        if 'bgm_clip' in locals():
            close_clip(bgm_clip)
        # Force garbage collection
        gc.collect()

def preprocess_video(materials: List[MaterialInfo], clip_duration=4, apply_denoising=False):
    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        
        # First load the clip
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)
            
        # Then apply denoising if needed and it's a video
        if ext not in const.FILE_TYPE_IMAGES and apply_denoising:
            # Apply subtle denoising to video clips that might benefit
            from moviepy.video.fx.all import denoise
            
            try:
                # Get a sample frame to analyze noise level
                frame = clip.get_frame(0)
                import numpy as np
                noise_estimate = np.std(frame)
                
                # Apply denoising only if noise level seems high
                if noise_estimate > 15:  # Threshold determined empirically
                    logger.info(f"Applying denoising to video with estimated noise: {noise_estimate:.2f}")
                    clip = denoise(clip, sigma=1.5, mode="fast")
            except Exception as e:
                logger.warning(f"Denoising attempt failed: {e}")

        width = clip.size[0]
        height = clip.size[1]
        
        # Improved resolution check
        min_resolution = 480
        # Calculate aspect ratio outside of conditional blocks so it's always defined
        aspect_ratio = width / height
        
        if width < min_resolution or height < min_resolution:
            logger.warning(f"Low resolution material: {width}x{height}, minimum {min_resolution}x{min_resolution} recommended")
            # Instead of skipping, apply upscaling for very low-res content
            if width < min_resolution/2 or height < min_resolution/2:
                logger.warning("Resolution too low, skipping")
                close_clip(clip)
                continue
            else:
                # Apply high-quality upscaling for borderline content
                logger.info(f"Applying high-quality upscaling to low-resolution content: {width}x{height}")
        
        # Calculate target dimensions while maintaining aspect ratio
        if width < height:
            new_width = min_resolution
            new_height = int(new_width / aspect_ratio)
        else:
            new_height = min_resolution
            new_width = int(new_height * aspect_ratio)
        
        # Ensure dimensions are even
        new_width, new_height = ensure_even_dimensions(new_width, new_height)
        
        # Use high-quality scaling
        clip = clip.resized(new_size=(new_width, new_height), resizer='lanczos')

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            
            # Ensure dimensions are even numbers and enhance for better quality
            width, height = ensure_even_dimensions(width, height)
            
            # Use higher resolution multiplier for sharper output
            quality_multiplier = 1.2 if width < 1080 else 1.0
            enhanced_width = int(width * quality_multiplier)
            enhanced_height = int(height * quality_multiplier)
            enhanced_width, enhanced_height = ensure_even_dimensions(enhanced_width, enhanced_height)
            
            # Close the original clip before creating a new one to avoid file handle conflicts
            close_clip(clip)

            # Create a new ImageClip with the image
            clip = (
                ImageClip(material.url)
                .resized(new_size=(enhanced_width, enhanced_height), resizer='bicubic')  # Use bicubic for better quality
                .with_duration(clip_duration)
                .with_position("center")
            )
            # More subtle and smoother zoom effect
            zoom_clip = clip.resized(
                lambda t: 1 + (0.05 * (t / clip.duration)),  # Reduced zoom from 0.1 to 0.05 for smoother effect
                resizer='lanczos'  # Ensure high-quality scaling
            )

            # Create composite with enhanced quality
            final_clip = CompositeVideoClip([zoom_clip])

            # Output with maximum quality settings
            video_file = f"{material.url}.mp4"
            encoding_params = get_optimal_encoding_params(enhanced_width, enhanced_height, "image")
            
            final_clip.write_videofile(video_file,
                fps=fps,
                logger='bar',
                codec=video_codec,
                # Remove bitrate parameter as it conflicts with CRF in ffmpeg_params
                ffmpeg_params=get_standard_ffmpeg_params(enhanced_width, enhanced_height, "image"),
                write_logfile=False,
                verbose=False
            )
            
            # Close all clips to properly release resources
            close_clip(final_clip)
            close_clip(zoom_clip) 
            close_clip(clip)
            material.url = video_file
            logger.success(f"high-quality image processed: {video_file}")
        else:
            close_clip(clip)
            
    return materials