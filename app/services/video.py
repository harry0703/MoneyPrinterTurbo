import glob
import itertools
import os
import random
import gc
import shutil
import time
import ctypes
import sys
import warnings
import io
import contextlib
import logging
from typing import List

# Set moviepy and imageio logging level to WARNING to suppress detailed metadata logs
logging.basicConfig(level=logging.WARNING)
for logger_name in ['moviepy', 'imageio', 'imageio_ffmpeg']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

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
    vfx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont

from app.config import config
from app.config.config import load_config
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.services.llm import add_english_translations
from app.utils import utils

# Suppress FFmpeg handle invalid errors from moviepy's __del__ methods
# This is a common Windows subprocess issue that occurs during garbage collection
warnings.filterwarnings("ignore", message=".*句柄无效.*")
warnings.filterwarnings("ignore", message=".*invalid handle.*")

# Context manager to suppress stderr output (for cleanup operations)
@contextlib.contextmanager
def suppress_stderr():
    """Context manager to suppress stderr output"""
    original_stderr = sys.stderr
    try:
        sys.stderr = io.StringIO()
        yield
    finally:
        sys.stderr = original_stderr

# Monkey-patch FFMPEG_VideoReader.__del__ to suppress handle invalid errors
try:
    from moviepy.video.io.ffmpeg_reader import FFMPEG_VideoReader
    original_del = FFMPEG_VideoReader.__del__
    
    def safe_del(self):
        with suppress_stderr():
            try:
                original_del(self)
            except OSError as e:
                # Ignore handle invalid errors (WinError 6) during cleanup
                if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                    # Only log if it's not a handle invalid error
                    logger.debug(f"FFMPEG_VideoReader cleanup error (ignored): {e}")
            except Exception as e:
                # Suppress any other exceptions during __del__ to avoid crashes
                logger.debug(f"FFMPEG_VideoReader cleanup error (ignored): {e}")
    
    FFMPEG_VideoReader.__del__ = safe_del
    logger.debug("Applied safe cleanup patch for FFMPEG_VideoReader")
except ImportError:
    logger.debug("Could not patch FFMPEG_VideoReader (module not available)")
except Exception as e:
    logger.debug(f"Failed to patch FFMPEG_VideoReader: {e}")

# Monkey-patch FFMPEG_AudioReader.__del__ to suppress handle invalid errors
try:
    from moviepy.audio.io.ffmpeg_audioreader import FFMPEG_AudioReader
    original_audio_del = FFMPEG_AudioReader.__del__
    
    def safe_audio_del(self):
        with suppress_stderr():
            try:
                original_audio_del(self)
            except OSError as e:
                # Ignore handle invalid errors (WinError 6) during cleanup
                if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                    # Only log if it's not a handle invalid error
                    logger.debug(f"FFMPEG_AudioReader cleanup error (ignored): {e}")
            except Exception as e:
                # Suppress any other exceptions during __del__ to avoid crashes
                logger.debug(f"FFMPEG_AudioReader cleanup error (ignored): {e}")
    
    FFMPEG_AudioReader.__del__ = safe_audio_del
    logger.debug("Applied safe cleanup patch for FFMPEG_AudioReader")
except ImportError:
    logger.debug("Could not patch FFMPEG_AudioReader (module not available)")
except Exception as e:
    logger.debug(f"Failed to patch FFMPEG_AudioReader: {e}")

# Patch sys.excepthook to suppress handle invalid errors during interpreter shutdown
original_excepthook = sys.excepthook

def custom_excepthook(exc_type, exc_value, exc_traceback):
    """Custom exception hook to suppress handle invalid errors during shutdown"""
    error_str = str(exc_value)
    if "句柄无效" in error_str or "invalid handle" in error_str.lower():
        # Silently ignore handle invalid errors
        return
    # Call original excepthook for other exceptions
    original_excepthook(exc_type, exc_value, exc_traceback)

sys.excepthook = custom_excepthook
logger.debug("Applied custom exception hook to suppress handle invalid errors")

# Add global exception handler for unhandled exceptions during shutdown
def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler to suppress handle invalid errors"""
    if exc_type is None:
        return
    
    error_str = str(exc_value)
    if "句柄无效" in error_str or "invalid handle" in error_str.lower():
        # Silently ignore handle invalid errors
        return
    
    # Log other exceptions
    logger.error(f"Unhandled exception: {exc_type.__name__}: {exc_value}")

# Install the handler
sys.excepthook = handle_exception
logger.debug("Applied global exception handler for cleanup errors")

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
    # Reload config to get latest values
    _cfg = load_config()
    app_config = _cfg.get("app", {})
    
    use_gpu = app_config.get("use_gpu", False)
    # GPU defaults to highest quality, CPU defaults to high quality
    default_quality = "ultra" if use_gpu else "high"
    quality = app_config.get("video_quality", default_quality).lower()
    custom_bitrate = app_config.get("video_bitrate", "")
    
    # Get actual video codec to determine preset type
    actual_codec = get_video_codec()
    # Use CPU preset for libx264, GPU preset for others
    preset_type = "cpu" if actual_codec == "libx264" else "gpu"
    
    logger.info(f"Video encoding: codec={actual_codec}, quality={quality}")
    
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
    
    # logger.debug(f"Video encoding params: type={preset_type}, quality={quality}, bitrate={bitrate}, preset={encoding_preset}, crf={crf}")
    
    return {
        "bitrate": bitrate,
        "preset": encoding_preset,
        "crf": crf
    }

# Cache for video codec detection
_cached_video_codec = None

# Select video encoder based on configuration
def get_video_codec():
    """Select appropriate video encoder based on configuration and system environment"""
    global _cached_video_codec
    
    use_gpu = config.app.get("use_gpu", False)
    
    # Log GPU configuration status for video codec
    logger.info(f"GPU configuration for video codec: use_gpu={use_gpu}")
    
    # If use_gpu is True, always recheck GPU support (clear cache)
    if use_gpu:
        logger.info("use_gpu=True, clearing codec cache and rechecking GPU support")
        _cached_video_codec = None
    
    # Return cached result if available
    if _cached_video_codec is not None:
        logger.info(f"Using cached video codec: {_cached_video_codec}")
        return _cached_video_codec
    
    if not use_gpu:
        logger.info("Video encoder: CPU mode selected (libx264)")
        _cached_video_codec = "libx264"  # CPU encoder
        return _cached_video_codec
    
    # Check if GPU encoding is supported
    try:
        import subprocess
        # Get ffmpeg executable path
        ffmpeg_exe = os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")
        # logger.debug(f"Video encoder: Checking GPU support using ffmpeg executable: {ffmpeg_exe}")
        
        # Check if ffmpeg supports GPU encoders
        result = subprocess.run(
            [ffmpeg_exe, "-encoders"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Check for NVIDIA GPU support
        if "h264_nvenc" in result.stdout:
            logger.info("Video encoder: NVIDIA GPU mode selected (h264_nvenc) - GPU acceleration enabled")
            _cached_video_codec = "h264_nvenc"
            return _cached_video_codec
        # Check for AMD GPU support
        elif "h264_amf" in result.stdout:
            logger.info("Video encoder: AMD GPU mode selected (h264_amf) - GPU acceleration enabled")
            _cached_video_codec = "h264_amf"
            return _cached_video_codec
        # Check for Intel GPU support
        elif "h264_qsv" in result.stdout:
            logger.info("Video encoder: Intel GPU mode selected (h264_qsv) - GPU acceleration enabled")
            _cached_video_codec = "h264_qsv"
            return _cached_video_codec
        else:
            # GPU fallback: use_gpu=True but no GPU encoder available
            fallback_reason = "No supported GPU encoder found in FFmpeg"
            logger.warning(f"============================================")
            logger.warning(f"GPU FALLBACK DETECTED")
            logger.warning(f"============================================")
            logger.warning(f"Configuration: use_gpu=True")
            logger.warning(f"Reason: {fallback_reason}")
            logger.warning(f"Details:")
            logger.warning(f"  - NVIDIA GPU encoder (h264_nvenc): NOT FOUND")
            logger.warning(f"  - AMD GPU encoder (h264_amf): NOT FOUND")
            logger.warning(f"  - Intel GPU encoder (h264_qsv): NOT FOUND")
            logger.warning(f"Action: Falling back to CPU encoder (libx264)")
            logger.warning(f"To enable GPU encoding:")
            logger.warning(f"  1. Ensure GPU drivers are properly installed")
            logger.warning(f"  2. Install FFmpeg with GPU support (h264_nvenc/h264_amf/h264_qsv)")
            logger.warning(f"  3. Verify GPU encoder availability with: ffmpeg -encoders | grep h264")
            logger.warning(f"============================================")
            logger.debug(f"Available encoders: {result.stdout[:1000]}...")  # Log first 1000 chars of encoder list
            _cached_video_codec = "libx264"
            return _cached_video_codec
    except subprocess.TimeoutExpired:
        # GPU fallback: timeout while checking GPU support
        fallback_reason = "Timeout while checking GPU encoder availability"
        logger.warning(f"============================================")
        logger.warning(f"GPU FALLBACK DETECTED")
        logger.warning(f"============================================")
        logger.warning(f"Configuration: use_gpu=True")
        logger.warning(f"Reason: {fallback_reason}")
        logger.warning(f"Details: FFmpeg command 'ffmpeg -encoders' timed out after 10 seconds")
        logger.warning(f"Action: Falling back to CPU encoder (libx264)")
        logger.warning(f"Possible causes:")
        logger.warning(f"  - FFmpeg executable is not responding")
        logger.warning(f"  - System performance issues")
        logger.warning(f"  - Corrupted FFmpeg installation")
        logger.warning(f"============================================")
        _cached_video_codec = "libx264"
        return _cached_video_codec
    except FileNotFoundError:
        # GPU fallback: FFmpeg executable not found
        fallback_reason = "FFmpeg executable not found"
        logger.warning(f"============================================")
        logger.warning(f"GPU FALLBACK DETECTED")
        logger.warning(f"============================================")
        logger.warning(f"Configuration: use_gpu=True")
        logger.warning(f"Reason: {fallback_reason}")
        logger.warning(f"Details: FFmpeg executable not found at path: {ffmpeg_exe}")
        logger.warning(f"Action: Falling back to CPU encoder (libx264)")
        logger.warning(f"Solution:")
        logger.warning(f"  1. Install FFmpeg from https://www.gyan.dev/ffmpeg/builds/")
        logger.warning(f"  2. Set ffmpeg_path in config.toml")
        logger.warning(f"  3. Or set IMAGEIO_FFMPEG_EXE environment variable")
        logger.warning(f"============================================")
        _cached_video_codec = "libx264"
        return _cached_video_codec
    except Exception as e:
        # GPU fallback: unexpected error
        fallback_reason = f"Unexpected error while checking GPU support: {type(e).__name__}"
        logger.warning(f"============================================")
        logger.warning(f"GPU FALLBACK DETECTED")
        logger.warning(f"============================================")
        logger.warning(f"Configuration: use_gpu=True")
        logger.warning(f"Reason: {fallback_reason}")
        logger.warning(f"Error details: {str(e)}")
        logger.warning(f"Action: Falling back to CPU encoder (libx264)")
        logger.warning(f"Debug information:")
        logger.warning(f"  - FFmpeg executable: {ffmpeg_exe}")
        logger.warning(f"  - Error type: {type(e).__name__}")
        logger.warning(f"============================================")
        _cached_video_codec = "libx264"
        return _cached_video_codec

video_codec = get_video_codec()
video_encoding_params = get_video_encoding_params()
logger.info(f"Video encoder initialized: {video_codec} (GPU for video codec: {config.app.get('use_gpu', False)})")

def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            try:
                clip.reader.close()
            except Exception as e:
                # Ignore handle invalid errors
                if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                    logger.error(f"failed to close clip reader: {str(e)}")
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            try:
                if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                    try:
                        clip.audio.reader.close()
                    except Exception as e:
                        # Ignore handle invalid errors
                        if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                            logger.error(f"failed to close audio reader: {str(e)}")
                clip.audio.close()
            except Exception as e:
                # Ignore handle invalid errors
                if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                    logger.error(f"failed to close audio clip: {str(e)}")
            finally:
                try:
                    del clip.audio
                except:
                    pass
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            try:
                if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                    try:
                        clip.mask.reader.close()
                    except Exception as e:
                        # Ignore handle invalid errors
                        if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                            logger.error(f"failed to close mask reader: {str(e)}")
                clip.mask.close()
            except Exception as e:
                # Ignore handle invalid errors
                if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                    logger.error(f"failed to close mask clip: {str(e)}")
            finally:
                try:
                    del clip.mask
                except:
                    pass
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
        # Try to close the clip itself
        try:
            clip.close()
        except Exception as e:
            # Ignore handle invalid errors
            if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower():
                logger.error(f"failed to close clip: {str(e)}")
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    try:
        del clip
    except:
        pass
    
    # Only collect garbage if necessary
    # gc.collect()  # Commented out to avoid triggering __del__ methods prematurely

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


def preprocess_video(materials, clip_duration=5):
    """
    Preprocess video materials, converting images to videos if needed.
    
    Args:
        materials: List of MaterialInfo objects
        clip_duration: Duration for image-based videos (if int, use fixed duration; if tuple, use random duration in range)
        
    Returns:
        List of MaterialInfo objects with processed videos
    """
    from app.models.schema import MaterialInfo
    import random
    
    if not materials:
        return []
    
    processed_materials = []
    
    for material in materials:
        if not material or not material.url:
            continue
        
        # Check if the material is an image
        if material.url.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
            # Convert image to video
            try:
                # Create a temporary video file path
                video_path = material.url + '.mp4'
                
                # Determine clip duration (random 3-5 seconds for images)
                if isinstance(clip_duration, tuple) and len(clip_duration) == 2:
                    actual_duration = random.uniform(clip_duration[0], clip_duration[1])
                else:
                    actual_duration = clip_duration
                
                # Use moviepy to create a video from the image
                clip = ImageClip(material.url).with_duration(actual_duration)
                clip.write_videofile(video_path, fps=24)
                
                # Create a new MaterialInfo with the video path
                new_material = MaterialInfo()
                new_material.url = video_path
                new_material.provider = material.provider
                new_material.duration = actual_duration
                
                processed_materials.append(new_material)
                logger.info(f"Converted image to video: {material.url} -> {video_path} ({actual_duration:.1f}s)")
            except Exception as e:
                logger.error(f"Failed to convert image to video: {material.url} -> {str(e)}")
                continue
        else:
            # Already a video, add as is
            processed_materials.append(material)
    
    return processed_materials


def match_local_videos_by_keywords(materials, scene_keywords):
    """
    Match local videos by scene keywords based on filename and metadata.
    Uses similarity matching for better semantic relevance.
    
    Args:
        materials: List of MaterialInfo objects
        scene_keywords: List of scene keywords to match against
        
    Returns:
        List of MaterialInfo objects sorted by match score
    """
    from app.models.schema import MaterialInfo
    import difflib
    
    if not materials or not scene_keywords:
        logger.info(f"No materials or keywords provided for matching. Materials: {len(materials) if materials else 0}, Keywords: {len(scene_keywords) if scene_keywords else 0}")
        return materials
    
    # Normalize scene keywords
    normalized_keywords = [kw.lower().strip() for kw in scene_keywords if kw and kw.strip()]
    
    if not normalized_keywords:
        logger.info("No valid keywords after normalization")
        return materials
    
    # Add English translations for non-English keywords to improve matching
    enhanced_keywords = add_english_translations([kw for kw in scene_keywords if kw and kw.strip()])
    enhanced_normalized_keywords = [kw.lower().strip() for kw in enhanced_keywords if kw and kw.strip()]
    
    logger.info(f"Starting local material matching with {len(enhanced_normalized_keywords)} keywords: {enhanced_normalized_keywords}")
    logger.info(f"Processing {len(materials)} local materials")
    
    # Use enhanced keywords for matching
    normalized_keywords = enhanced_normalized_keywords
    
    scored_materials = []
    
    for material in materials:
        if not material or not material.url:
            logger.warning("Skipping invalid material (empty or no URL)")
            continue
        
        score = 0
        filename = os.path.basename(material.url).lower()
        filename_without_ext = os.path.splitext(filename)[0]
        
        # Detailed scoring breakdown
        scoring_details = {
            'filename': filename,
            'exact_matches': 0,
            'partial_matches': 0,
            'similarity_scores': {}
        }
        
        # Check for exact keyword matches in filename (traditional matching)
        for keyword in normalized_keywords:
            if keyword in filename:
                score += 10  # High score for exact match
                scoring_details['exact_matches'] += 1
        
        # Check for partial matches (traditional matching)
        for keyword in normalized_keywords:
            if keyword in filename or filename in keyword:
                score += 5  # Medium score for partial match
                scoring_details['partial_matches'] += 1
        
        # Calculate similarity score for each keyword (improved matching)
        for keyword in normalized_keywords:
            # Calculate similarity ratio
            similarity = difflib.SequenceMatcher(None, keyword, filename_without_ext).ratio()
            
            # Convert similarity to score (0-10 scale)
            similarity_score = similarity * 10
            score += similarity_score
            
            scoring_details['similarity_scores'][keyword] = similarity
        
        # Add to scored list
        scored_materials.append((material, score, scoring_details))
    
    # Sort by score (descending)
    scored_materials.sort(key=lambda x: x[1], reverse=True)
    
    # Return sorted materials
    sorted_materials = [item[0] for item in scored_materials]
    
    # Log simplified matching results
    logger.info(f"Matched {len(sorted_materials)} materials by keywords: {normalized_keywords}")
    
    # Log top 5 matching results (simplified)
    if scored_materials:
        logger.info("Top 5 matching results:")
        for i, (material, score, _) in enumerate(scored_materials[:5]):
            logger.info(f"  {i+1}. {os.path.basename(material.url)} (score: {score:.2f})")
        
        # Log basic statistics
        total_score = sum(item[1] for item in scored_materials)
        average_score = total_score / len(scored_materials)
        max_score = max(item[1] for item in scored_materials)
        
        logger.info(f"Matching statistics: total={len(scored_materials)}, avg_score={average_score:.2f}, max_score={max_score:.2f}")
    
    return sorted_materials


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
    scene_info: str = None,
    local_video_paths: List[str] = None,
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
        try:
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
        except Exception as e:
            logger.error(f"failed to process video file {video_path}: {str(e)}")
            continue

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
                logger.info(f"Processing clip {i+1}: source={clip_w}x{clip_h}, ratio={clip_ratio:.2f}, target={video_width}x{video_height}, ratio={video_ratio:.2f}")
                
                # Use unified crop function that handles both upscaling and cropping
                # Use higher max_scale for 3:4 videos to ensure they fill the screen width
                # For local materials, use a much higher max_scale to avoid skipping user-provided materials
                if local_video_paths and subclipped_item.file_path in local_video_paths:
                    max_scale = 5.0  # Allow up to 500% upscaling for local materials
                    logger.info(f"Processing local material clip {i+1}: {subclipped_item.file_path}, using max_scale={max_scale}")
                else:
                    max_scale = 1.5 if video_aspect == VideoAspect.portrait_3_4 else 1.10
                    logger.info(f"Processing online material clip {i+1}: {subclipped_item.file_path}, using max_scale={max_scale}")
                clip = crop_clip_to_target(clip, video_width, video_height, max_scale=max_scale)
                if clip is None:
                    if local_video_paths and subclipped_item.file_path in local_video_paths:
                        logger.warning(f"Local clip {i+1} could not be processed even with relaxed quality constraints, skipping")
                    else:
                        logger.warning(f"Online clip {i+1} could not be processed within quality constraints, skipping")
                    continue
                    
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if video_transition_mode and video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip,1)
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip,1)
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip,1, shuffle_side)
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip,1, shuffle_side)
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c,1),
                    lambda c: video_effects.fadeout_transition(c,1),
                    lambda c: video_effects.slidein_transition(c,1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c,1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            # Apply brightness and contrast enhancement
            brightness_factor = config.app.get("video_brightness", 1.0)
            contrast_factor = config.app.get("video_contrast", 1.0)
            
            if brightness_factor != 1.0:
                clip = video_effects.brightness_enhance(clip, brightness_factor)
            
            if contrast_factor != 1.0:
                clip = video_effects.contrast_enhance(clip, contrast_factor)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)
            
            # Store processed clip in memory instead of writing to temp file
            # This avoids the first encoding step
            processed_clips.append(clip)
            video_duration += clip.duration
            logger.info(f"Clip {i+1} processed in memory, duration: {clip.duration:.2f}s")
            
            # Release memory periodically
            if len(processed_clips) % 5 == 0:
                gc.collect()
                logger.debug(f"Memory released, processed {len(processed_clips)} clips so far")
            
        except Exception as e:
            logger.error(f"failed to process clip {i+1}: {str(e)}")
            # Release memory in case of error
            gc.collect()
            continue
    
    # Check if we have any processed clips
    if not processed_clips:
        logger.error("No video clips were successfully processed")
        return None
    
    # loop processed clips until video duration matches or exceeds the audio duration.
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        # Instead of keeping all clips in memory, calculate how many loops we need
        base_duration = video_duration
        if base_duration <= 0:
            logger.error(f"video duration is zero or negative ({video_duration:.2f}s), cannot loop clips")
            return None
        num_loops = int(audio_duration / base_duration) + 1
        logger.info(f"Need {num_loops} loops to match audio duration")
        
        # Only keep base clips in memory and reuse them
        base_clips = processed_clips.copy()
        for i in range(num_loops - 1):
            for clip in base_clips:
                if video_duration >= audio_duration:
                    break
                processed_clips.append(clip)
                video_duration += clip.duration
                # Release memory periodically
                if len(processed_clips) % 10 == 0:
                    gc.collect()
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
        # Force garbage collection after loop
        gc.collect()
     
    # merge video clips and add audio in one step to reduce encoding loss
    logger.info("starting clip merging and audio addition process")
    if not processed_clips:
        logger.warning("no clips available for merging")
        return None
    
    # Concatenate all clips in memory
    logger.info(f"concatenating {len(processed_clips)} clips in memory")
    try:
        # Concatenate all clips at once (no intermediate encoding)
        final_video = concatenate_videoclips(processed_clips)
        logger.info(f"clips concatenated, total duration: {final_video.duration:.2f}s")
        
        # Load audio
        audio_clip = AudioFileClip(audio_file)
        
        # Trim audio to match video duration
        video_duration_final = final_video.duration
        audio_duration = audio_clip.duration
        if audio_duration > video_duration_final:
            audio_clip = audio_clip.subclipped(0, video_duration_final)
            logger.info(f"audio trimmed to match video duration: {video_duration_final:.2f}s")
        
        # Add audio to video
        final_video = final_video.with_audio(audio_clip)
        if scene_info:
            logger.info(f"audio added to video {scene_info}")
        else:
            logger.info("audio added to video")
        
        # Write final video with audio (single encoding step)
        logger.info("writing final video with audio (single encoding step)")
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
        # Get the latest video codec (dynamic detection)
        current_codec = get_video_codec()
        current_encoding_params = get_video_encoding_params()
        
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
        close_clip(audio_clip)
        for clip in processed_clips:
            close_clip(clip)
        
    except Exception as e:
        logger.error(f"failed to merge clips and add audio: {str(e)}")
        return None
    
    logger.info("video combining completed")
    return combined_video_path


def crop_clip_to_target(clip, target_width, target_height, max_scale=1.10):
    """
    Crop a video clip to target dimensions while maintaining quality.
    For clips smaller than target: upscale first (within max_scale limit), then crop.
    For clips larger than target: crop directly.
    Centers the crop on the original video.
    
    Args:
        clip: VideoFileClip to crop
        target_width: Target width in pixels
        target_height: Target height in pixels
        max_scale: Maximum allowed scaling factor (default 1.10 = 110%)
    
    Returns:
        Cropped video clip
    """
    clip_w, clip_h = clip.size
    target_ratio = target_width / target_height
    clip_ratio = clip_w / clip_h
    
    logger.info(f"Processing clip: {clip_w}x{clip_h} -> {target_width}x{target_height}, ratios: clip={clip_ratio:.3f}, target={target_ratio:.3f}")
    
    # Calculate scale factors for width and height
    scale_w = target_width / clip_w
    scale_h = target_height / clip_h
    
    # Determine if we need to upscale
    needs_upscale = clip_w < target_width or clip_h < target_height
    
    if needs_upscale:
        # Clip is smaller than target in at least one dimension
        # Calculate the scale factor to make the smaller dimension match target
        # while maintaining aspect ratio
        if clip_ratio > target_ratio:
            # Clip is relatively wider, scale based on height
            scale_factor = scale_h
            logger.info(f"Clip is wider ratio, scaling based on height: {scale_factor:.3f}x")
        else:
            # Clip is relatively taller, scale based on width
            scale_factor = scale_w
            logger.info(f"Clip is taller ratio, scaling based on width: {scale_factor:.3f}x")
        
        # Check if scale is within allowed limit
        if scale_factor >= max_scale:
            logger.warning(f"Scale factor {scale_factor:.3f}x exceeds max allowed {max_scale:.3f}x")
            return None
        
        # Upscale the clip
        new_width = int(clip_w * scale_factor)
        new_height = int(clip_h * scale_factor)
        logger.info(f"Upscaling: {clip_w}x{clip_h} -> {new_width}x{new_height} ({scale_factor:.3f}x)")
        clip = clip.resized(new_size=(new_width, new_height))
        clip_w, clip_h = new_width, new_height
    else:
        logger.info(f"No upscaling needed, clip is larger than target")
    
    # Now crop to target dimensions (center crop)
    if clip_w > target_width or clip_h > target_height:
        if clip_ratio > target_ratio:
            # After scaling, clip is still wider than target - crop width
            new_width = int(clip_h * target_ratio)
            new_height = clip_h
            x_center = clip_w // 2
            x1 = x_center - new_width // 2
            y1 = 0
            logger.info(f"Cropping width: {clip_w}x{clip_h} -> {new_width}x{new_height}, crop_x={x1}")
        else:
            # After scaling, clip is taller than target - crop height
            new_width = clip_w
            new_height = int(clip_w / target_ratio)
            y_center = clip_h // 2
            x1 = 0
            y1 = y_center - new_height // 2
            logger.info(f"Cropping height: {clip_w}x{clip_h} -> {new_width}x{new_height}, crop_y={y1}")
        
        # Crop to target dimensions
        clip = clip.with_effects([vfx.Crop(x1=x1, y1=y1, width=new_width, height=new_height)])
    
    # Final resize if needed (should be minimal or none)
    final_w, final_h = clip.size
    if final_w != target_width or final_h != target_height:
        logger.info(f"Final resize: {final_w}x{final_h} -> {target_width}x{target_height}")
        clip = clip.resized(new_size=(target_width, target_height))
    
    logger.success(f"Clip processed successfully: {target_width}x{target_height}")
    return clip


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
                        # Get subtitle margin from config (default 0.05 = 5% on each side)
                        # Reload config to get latest values
                        _cfg = load_config()
                        ui_config = _cfg.get("ui", {})
                        subtitle_margin = ui_config.get("subtitle_margin", 0.05)
                        max_width = video_clip.w * (1 - 2 * subtitle_margin)
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
