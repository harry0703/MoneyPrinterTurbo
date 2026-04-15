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
import math
import psutil
from typing import List

# Set moviepy and imageio logging level to WARNING to suppress detailed metadata logs
logging.basicConfig(level=logging.WARNING)
for logger_name in ['moviepy', 'imageio', 'imageio_ffmpeg', 'ffmpeg', 'PIL']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Also set the root logger level to WARNING to suppress all debug logs
logging.getLogger().setLevel(logging.WARNING)

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
    
    # Get actual video codec to determine preset type first
    actual_codec = get_video_codec()
    # Use CPU preset for libx264, GPU preset for others
    preset_type = "cpu" if actual_codec == "libx264" else "gpu"
    
    # Set default quality based on actual codec type (not config use_gpu)
    # GPU defaults to highest quality, CPU defaults to high quality
    default_quality = "ultra" if preset_type == "gpu" else "high"
    quality = app_config.get("video_quality", default_quality).lower()
    custom_bitrate = app_config.get("video_bitrate", "")
    
    logger.info(f"Video encoding: codec={actual_codec}, preset_type={preset_type}, quality={quality}")
    
    # Get quality preset - use default_quality if requested quality not available for this preset type
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
    # logger.info(f"GPU configuration for video codec: use_gpu={use_gpu}")
    
    # If use_gpu is True, always recheck GPU support (clear cache)
    if use_gpu:
        # logger.info("use_gpu=True, clearing codec cache and rechecking GPU support")
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
            # logger.info("Video encoder: NVIDIA GPU mode selected (h264_nvenc) - GPU acceleration enabled")
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

def get_memory_usage():
    """Get current memory usage percentage"""
    memory = psutil.virtual_memory()
    return memory.percent

def check_memory_usage(threshold=85):
    """Check if memory usage exceeds threshold"""
    memory_usage = get_memory_usage()
    logger.debug(f"Current memory usage: {memory_usage:.2f}%")
    return memory_usage >= threshold

def memory_safe_wait():
    """Wait until memory usage drops below threshold"""
    while check_memory_usage():
        logger.warning(f"Memory usage high, waiting for 3 seconds...")
        # Force garbage collection before sleeping
        gc.collect()
        time.sleep(3)
    logger.debug("Memory usage acceptable, continuing processing")

def memory_safe_operation(func):
    """Decorator for memory-safe operations"""
    def wrapper(*args, **kwargs):
        # Check memory before operation
        memory_safe_wait()
        result = func(*args, **kwargs)
        # Check memory after operation
        memory_safe_wait()
        return result
    return wrapper

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
                try:
                    clip.write_videofile(video_path, fps=24)
                    
                    # Create a new MaterialInfo with the video path
                    new_material = MaterialInfo()
                    new_material.url = video_path
                    new_material.provider = material.provider
                    new_material.duration = actual_duration
                    
                    processed_materials.append(new_material)
                    logger.info(f"Converted image to video: {material.url} -> {video_path} ({actual_duration:.1f}s)")
                finally:
                    # Close the clip to release resources
                    close_clip(clip)
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


@memory_safe_operation
def process_scene_videos(
    scene_video_paths: List[str],
    video_aspect: VideoAspect,
    video_concat_mode: VideoConcatMode,
    video_transition_mode: VideoTransitionMode,
    max_clip_duration: int,
    local_video_paths: List[str] = None,
) -> List:
    """
    Process videos for a single scene
    
    Args:
        scene_video_paths: List of video paths for the scene
        video_aspect: Video aspect ratio
        video_concat_mode: Video concatenation mode
        video_transition_mode: Video transition mode
        max_clip_duration: Maximum clip duration
        local_video_paths: List of local video paths
    
    Returns:
        List of processed video clips
    """
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    
    processed_clips = []
    subclipped_items = []
    
    # Process videos
    for i, video_path in enumerate(scene_video_paths):
        try:
            # Check memory before processing each video
            memory_safe_wait()
            
            clip = VideoFileClip(video_path)
            clip_duration = clip.duration
            clip_w, clip_h = clip.size
            close_clip(clip)
            
            start_time = 0

            while start_time < clip_duration:
                end_time = min(start_time + max_clip_duration, clip_duration)            
                subclip = SubClippedVideoClip(file_path= video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h)
                subclipped_items.append(subclip)
                
                start_time = end_time    
                if video_concat_mode.value == VideoConcatMode.sequential.value:
                    break
        except Exception as e:
            logger.error(f"failed to process video file {video_path}: {str(e)}")
            # Release memory in case of error
            gc.collect()
            continue

    # Apply concat mode to scene's video clips
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
    
    # Process subclips
    for i, subclipped_item in enumerate(subclipped_items):
        try:
            # Check memory before processing each subclip
            memory_safe_wait()
            
            clip = VideoFileClip(subclipped_item.file_path).subclipped(subclipped_item.start_time, subclipped_item.end_time)
            clip_duration = clip.duration
            
            # Resize if needed
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                
                # Use unified crop function
                if local_video_paths and subclipped_item.file_path in local_video_paths:
                    max_scale = 5.0  # Allow up to 500% upscaling for local materials
                else:
                    max_scale = 1.5 if video_aspect == VideoAspect.portrait_3_4 else 1.10
                
                # Check memory before crop
                memory_safe_wait()
                
                old_clip = clip
                clip = crop_clip_to_target(clip, video_width, video_height, max_scale=max_scale)
                
                # Close old clip to release memory
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
                
                if clip is None:
                    if local_video_paths and subclipped_item.file_path in local_video_paths:
                        logger.warning(f"Local clip {i+1} could not be processed even with relaxed quality constraints, skipping")
                    else:
                        logger.warning(f"Online clip {i+1} could not be processed within quality constraints, skipping")
                    continue
            
            # Apply transitions
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if video_transition_mode and video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.fade_in.value:
                old_clip = clip
                clip = video_effects.fadein_transition(clip,1)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.fade_out.value:
                old_clip = clip
                clip = video_effects.fadeout_transition(clip,1)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.slide_in.value:
                old_clip = clip
                clip = video_effects.slidein_transition(clip,1, shuffle_side)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.slide_out.value:
                old_clip = clip
                clip = video_effects.slideout_transition(clip,1, shuffle_side)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c,1),
                    lambda c: video_effects.fadeout_transition(c,1),
                    lambda c: video_effects.slidein_transition(c,1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c,1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                old_clip = clip
                clip = shuffle_transition(clip)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")

            # Check brightness and filter out dark videos
            brightness_threshold = config.app.get("video_brightness_threshold", 0.3)
            try:
                brightness = video_effects.detect_brightness(clip)
                logger.debug(f"Clip brightness: {brightness:.3f}, threshold: {brightness_threshold}")
                
                if brightness < brightness_threshold:
                    logger.warning(f"Skipping dark video clip (brightness: {brightness:.3f} < {brightness_threshold})")
                    close_clip(clip)
                    continue
            except Exception as e:
                logger.debug(f"Error detecting brightness: {e}, continuing with clip")
            
            # Apply brightness and contrast enhancement
            brightness_factor = config.app.get("video_brightness", 1.0)
            contrast_factor = config.app.get("video_contrast", 1.0)
            
            if brightness_factor != 1.0:
                old_clip = clip
                clip = video_effects.brightness_enhance(clip, brightness_factor)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            
            if contrast_factor != 1.0:
                old_clip = clip
                clip = video_effects.contrast_enhance(clip, contrast_factor)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")

            if clip.duration > max_clip_duration:
                old_clip = clip
                clip = clip.subclipped(0, max_clip_duration)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            
            # Check memory before adding to processed clips
            memory_safe_wait()
            
            processed_clips.append(clip)
            
            # Release memory more frequently
            if len(processed_clips) % 3 == 0:
                logger.debug(f"Releasing memory after processing {len(processed_clips)} clips")
                gc.collect()
                
        except Exception as e:
            logger.error(f"failed to process clip {i+1}: {str(e)}")
            # Release memory in case of error
            gc.collect()
            continue
    
    # Final memory cleanup
    gc.collect()
    return processed_clips

def combine_scene_clips(
    scene_clips: List,
    audio_duration: float,
) -> List:
    """
    Combine clips for a single scene, handling duration matching
    
    Args:
        scene_clips: List of processed clips for the scene
        audio_duration: Target audio duration
    
    Returns:
        List of clips ready for final concatenation
    """
    processed_clips = []
    video_duration = 0
    
    # Add clips from the scene
    for clip in scene_clips:
        if video_duration > audio_duration:
            break
        processed_clips.append(clip)
        video_duration += clip.duration
        
        # Release memory periodically
        if len(processed_clips) % 10 == 0:
            gc.collect()
    
    # Loop if needed to match audio duration
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_duration = video_duration
        if base_duration <= 0:
            logger.error(f"video duration is zero or negative ({video_duration:.2f}s), cannot loop clips")
            return []
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
    
    return processed_clips


def combine_early_scenes(
    scene_clips_list: List[List],
    audio_duration: float,
) -> List:
    """
    Combine multiple scenes while maintaining scene order
    
    Args:
        scene_clips_list: List of processed clips for each scene
        audio_duration: Target audio duration
    
    Returns:
        List of clips ready for final concatenation
    """
    processed_clips = []
    video_duration = 0
    
    # Add clips from each scene in order
    for scene_index, scene_clips in enumerate(scene_clips_list):
        logger.info(f"Adding clips from scene {scene_index + 1}")
        for clip in scene_clips:
            if video_duration > audio_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
            
            # Release memory periodically
            if len(processed_clips) % 10 == 0:
                gc.collect()
    
    # Loop if needed to match audio duration
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_duration = video_duration
        if base_duration <= 0:
            logger.error(f"video duration is zero or negative ({video_duration:.2f}s), cannot loop clips")
            return []
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
    
    return processed_clips

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
        final_video = concatenate_videoclips(processed_clips)
        logger.info(f"clips concatenated, total duration: {final_video.duration:.2f}s")
        
        # Load audio if provided
        if audio_file:
            audio_clip = AudioFileClip(audio_file)
            
            # Trim audio to match video duration
            video_duration_final = final_video.duration
            audio_duration = audio_clip.duration
            if audio_duration > video_duration_final:
                audio_clip = audio_clip.subclipped(0, video_duration_final)
                logger.info(f"audio trimmed to match video duration: {video_duration_final:.2f}s")
            
            # Add audio to video
            final_video = final_video.with_audio(audio_clip)
        else:
            logger.info("Using existing audio from scene videos")
        
        # Write final video with audio (single encoding step)
        logger.info("writing final video with audio (single encoding step)")
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
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

def build_scene_video(
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
    intro_video_path: str = None,
    intro_duration: int = 10,
) -> str:
    # Handle audio_file being None (scene videos already contain audio)
    if audio_file:
        audio_clip = AudioFileClip(audio_file)
        audio_duration = audio_clip.duration
        logger.info(f"audio duration: {audio_duration} seconds")
        # Close audio_clip immediately after getting duration, we'll reopen it later if needed
        close_clip(audio_clip)
        audio_clip = None
    else:
        # Calculate total video duration from scene videos
        audio_duration = 0
        for video_path in video_paths:
            try:
                clip = VideoFileClip(video_path)
                audio_duration += clip.duration
                close_clip(clip)
            except Exception as e:
                logger.error(f"Failed to get duration for {video_path}: {e}")
        logger.info(f"Total video duration: {audio_duration} seconds")
    
    output_dir = os.path.dirname(combined_video_path)

    # Process intro video separately if provided
    intro_clips = []
    if intro_video_path:
        # Check if intro video exists
        if os.path.exists(intro_video_path):
            logger.info(f"Found intro video: {intro_video_path}")
            # Process intro video
            try:
                # Check if intro video is actually an image
                if intro_video_path.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    # Handle image as intro video with specified duration
                    logger.info(f"Processing image as intro video with duration: {intro_duration:.1f}s")
                    
                    # Create video from image with specified duration
                    clip = ImageClip(intro_video_path).with_duration(intro_duration)
                    try:
                        clip_duration = intro_duration
                        clip_w, clip_h = clip.size
                        
                        # Process intro clip
                        aspect = VideoAspect(video_aspect)
                        video_width, video_height = aspect.to_resolution()
                        
                        # Process intro video differently: fit without cropping, center on blue background
                        clip = fit_intro_video_to_target(clip, video_width, video_height)
                        
                        # Apply brightness and contrast enhancement
                        brightness_factor = config.app.get("video_brightness", 1.0)
                        contrast_factor = config.app.get("video_contrast", 1.0)
                        
                        if brightness_factor != 1.0:
                            clip = video_effects.brightness_enhance(clip, brightness_factor)
                        
                        if contrast_factor != 1.0:
                            clip = video_effects.contrast_enhance(clip, contrast_factor)
                        
                        intro_clips.append(clip)
                        logger.info(f"Image intro video processed: {intro_video_path} (duration: {intro_duration:.1f}s)")
                    finally:
                        # Close the original clip to release resources
                        # Note: We don't close the processed clip as it's added to intro_clips and will be closed later
                        try:
                            if clip and hasattr(clip, 'close'):
                                clip.close()
                        except Exception:
                            pass
                else:
                    # Process as regular video
                    clip = VideoFileClip(intro_video_path)
                    try:
                        clip_duration = clip.duration
                        clip_w, clip_h = clip.size
                    finally:
                        close_clip(clip)
                    
                    start_time = 0
                    end_time = min(start_time + intro_duration, clip_duration)
                    subclip = SubClippedVideoClip(file_path=intro_video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h)
                    
                    # Process intro clip
                    aspect = VideoAspect(video_aspect)
                    video_width, video_height = aspect.to_resolution()
                    
                    clip = VideoFileClip(subclip.file_path).subclipped(subclip.start_time, subclip.end_time)
                    try:
                        # Process intro video differently: fit without cropping, center on blue background
                        clip = fit_intro_video_to_target(clip, video_width, video_height)
                        
                        # Apply brightness and contrast enhancement
                        brightness_factor = config.app.get("video_brightness", 1.0)
                        contrast_factor = config.app.get("video_contrast", 1.0)
                        
                        if brightness_factor != 1.0:
                            clip = video_effects.brightness_enhance(clip, brightness_factor)
                        
                        if contrast_factor != 1.0:
                            clip = video_effects.contrast_enhance(clip, contrast_factor)
                        
                        intro_clips.append(clip)
                        logger.info(f"Video intro processed: {intro_video_path}")
                    finally:
                        # Close the original clip to release resources
                        # Note: We don't close the processed clip as it's added to intro_clips and will be closed later
                        try:
                            if clip and hasattr(clip, 'close'):
                                clip.close()
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Failed to process intro video: {str(e)}")
            
            # Remove intro video from regular video paths if it exists
            normalized_intro_path = os.path.abspath(intro_video_path)
            video_paths = [path for path in video_paths if os.path.abspath(path) != normalized_intro_path]
        else:
            logger.warning(f"Intro video path does not exist: {intro_video_path}")
    else:
        logger.info("No intro video provided")
    
    # Process regular videos as a single scene
    scene_clips = process_scene_videos(
        scene_video_paths=video_paths,
        video_aspect=video_aspect,
        video_concat_mode=video_concat_mode,
        video_transition_mode=video_transition_mode,
        max_clip_duration=max_clip_duration,
        local_video_paths=local_video_paths
    )
    
    # Combine intro clips with scene clips
    all_clips = intro_clips + scene_clips
    
    # Check if we have any processed clips
    if not all_clips:
        logger.error("No video clips were successfully processed")
        return None
    
    # Combine clips to match audio duration
    processed_clips = combine_scene_clips(
        scene_clips=all_clips,
        audio_duration=audio_duration
    )
    
    # Finalize video
    return finalize_video(
        processed_clips=processed_clips,
        combined_video_path=combined_video_path,
        audio_file=audio_file,
        threads=threads
    )


def fit_intro_video_to_target(clip, target_width, target_height, bg_color=(0, 0, 255)):
    """
    Fit intro video into target dimensions without cropping.
    Scales the video to fit within target, centers it on a background layer.
    
    Args:
        clip: VideoFileClip to process
        target_width: Target width in pixels
        target_height: Target height in pixels
        bg_color: Background color as RGB tuple (default: blue)
    
    Returns:
        Composite video clip with intro centered on background
    """
    clip_w, clip_h = clip.size
    target_ratio = target_width / target_height
    clip_ratio = clip_w / clip_h
    
    logger.info(f"Fitting intro video: {clip_w}x{clip_h} -> {target_width}x{target_height}")
    logger.info(f"Ratios - clip: {clip_ratio:.3f}, target: {target_ratio:.3f}")
    
    # Calculate scale factor to ensure at least one dimension matches target
    # Based on aspect ratio comparison to avoid cropping
    if clip_ratio > target_ratio:
        # Video is wider than target, scale based on width to fill horizontally
        scale_factor = target_width / clip_w
        logger.info(f"Video is wider (ratio {clip_ratio:.3f} > {target_ratio:.3f}), scaling based on width")
    elif clip_ratio < target_ratio:
        # Video is taller than target, scale based on height to fill vertically
        scale_factor = target_height / clip_h
        logger.info(f"Video is taller (ratio {clip_ratio:.3f} < {target_ratio:.3f}), scaling based on height")
    else:
        # Same aspect ratio, scale to fit exactly
        scale_factor = target_width / clip_w
        logger.info(f"Same aspect ratio, scaling to fit exactly")
    
    logger.info(f"Selected scale factor: {scale_factor:.3f}")
    
    # Scale the video
    new_width = round(clip_w * scale_factor)
    new_height = round(clip_h * scale_factor)
    logger.info(f"Scaling intro video: {clip_w}x{clip_h} -> {new_width}x{new_height}")
    
    scaled_clip = clip.resized(new_size=(new_width, new_height))
    
    # Create background layer
    background = ColorClip(
        size=(target_width, target_height),
        color=bg_color,
        duration=clip.duration
    )
    
    # Center the scaled clip on background
    x_offset = (target_width - new_width) // 2
    y_offset = (target_height - new_height) // 2
    
    logger.info(f"Positioning intro at center: x={x_offset}, y={y_offset}")
    
    # Composite the video on background
    composite = CompositeVideoClip(
        [background, scaled_clip.with_position((x_offset, y_offset))],
        size=(target_width, target_height)
    )
    composite = composite.with_duration(clip.duration)
    
    # Preserve audio if present
    if clip.audio is not None:
        composite = composite.with_audio(clip.audio)
    
    logger.success(f"Intro video fitted successfully: {target_width}x{target_height}")
    return composite


@memory_safe_operation
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
        
        # Check memory before upscale
        memory_safe_wait()
        
        # Create new clip and release old one
        old_clip = clip
        clip = clip.resized(new_size=(new_width, new_height))
        # Close old clip to release memory
        try:
            old_clip.close()
            del old_clip
            gc.collect()
        except Exception as e:
            logger.debug(f"Error closing old clip: {e}")
        
        clip_w, clip_h = new_width, new_height
    else:
        logger.debug(f"No upscaling needed, clip is larger than target")
    
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
        
        # Check memory before crop
        memory_safe_wait()
        
        # Crop to target dimensions
        old_clip = clip
        clip = clip.with_effects([vfx.Crop(x1=x1, y1=y1, width=new_width, height=new_height)])
        # Close old clip to release memory
        try:
            old_clip.close()
            del old_clip
            gc.collect()
        except Exception as e:
            logger.debug(f"Error closing old clip: {e}")
    
    # Final resize if needed (should be minimal or none)
    final_w, final_h = clip.size
    if final_w != target_width or final_h != target_height:
        logger.info(f"Final resize: {final_w}x{final_h} -> {target_width}x{target_height}")
        
        # Check memory before final resize
        memory_safe_wait()
        
        # Create new clip and release old one
        old_clip = clip
        clip = clip.resized(new_size=(target_width, target_height))
        # Close old clip to release memory
        try:
            old_clip.close()
            del old_clip
            gc.collect()
        except Exception as e:
            logger.debug(f"Error closing old clip: {e}")
    
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
    import time
    start_time = time.time()
    logger.info(f"starting video generation: {output_file}")
    
    try:
        # Load video
        video_clip = VideoFileClip(video_path)
        
        # Load audio if provided
        if audio_path:
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


def analyze_video_params(video_path):
    """
    Analyze video file and return parameters
    
    Args:
        video_path: Path to video file
        
    Returns:
        Dictionary containing video parameters, or None if failed
    """
    try:
        clip = VideoFileClip(video_path)
        params = {
            "width": clip.w,
            "height": clip.h,
            "fps": clip.fps,
            "duration": clip.duration
        }
        clip.close()
        logger.info(f"Analyzed video params: {params}")
        return params
    except Exception as e:
        logger.error(f"Failed to analyze video params: {e}")
        return None


def scan_task_files(task_id_or_path: str) -> dict:
    """
    Scan task directory and return detected files.
    
    Args:
        task_id_or_path: Task ID or direct directory path
        
    Returns:
        Dictionary containing detected files and their status
    """
    # Check if it's a direct directory path
    if os.path.isdir(task_id_or_path):
        task_dir = task_id_or_path
        task_id = os.path.basename(task_dir)
    else:
        # It's a task ID
        task_id = task_id_or_path
        task_dir = utils.task_dir(task_id)
    
    result = {
        "task_id": task_id,
        "task_dir": task_dir,
        "scene_videos": [],
        "audio_files": [],
        "subtitle_files": [],
        "is_valid": False,
        "total_scenes": 0,
        "combined_video": None,
        "global_audio": None,
        "global_subtitle": None,
    }
    
    if not os.path.exists(task_dir):
        logger.error(f"Task directory does not exist: {task_dir}")
        return result
    
    # Check global audio and subtitle files
    global_audio_path = os.path.join(task_dir, "audio.mp3")
    if os.path.exists(global_audio_path):
        result["global_audio"] = global_audio_path
        result["audio_files"].append(global_audio_path)
        logger.info(f"Found global audio: {global_audio_path}")
    
    global_subtitle_path = os.path.join(task_dir, "subtitle.srt")
    if os.path.exists(global_subtitle_path):
        result["global_subtitle"] = global_subtitle_path
        result["subtitle_files"].append(global_subtitle_path)
        logger.info(f"Found global subtitle: {global_subtitle_path}")
    
    # Scan for scene directories
    scene_dirs = []
    for item in os.listdir(task_dir):
        item_path = os.path.join(task_dir, item)
        if os.path.isdir(item_path) and item.startswith("scene_"):
            try:
                scene_num = int(item.split("_")[1])
                scene_dirs.append((scene_num, item_path))
            except (IndexError, ValueError):
                pass
    
    # Sort by scene number
    scene_dirs.sort(key=lambda x: x[0])
    
    for scene_num, scene_dir in scene_dirs:
        scene_video_path = os.path.join(scene_dir, "combined.mp4")
        scene_audio_path = os.path.join(scene_dir, "audio.mp3")
        scene_subtitle_path = os.path.join(scene_dir, "subtitle.srt")
        
        scene_info = {
            "scene_num": scene_num,
            "scene_dir": scene_dir,
            "video": scene_video_path if os.path.exists(scene_video_path) else None,
            "audio": scene_audio_path if os.path.exists(scene_audio_path) else None,
            "subtitle": scene_subtitle_path if os.path.exists(scene_subtitle_path) else None,
        }
        
        result["scene_videos"].append(scene_info)
        
        if scene_info["audio"]:
            result["audio_files"].append(scene_audio_path)
        if scene_info["subtitle"]:
            result["subtitle_files"].append(scene_subtitle_path)
        
        logger.info(f"Scene {scene_num}: video={scene_info['video'] is not None}, "
                   f"audio={scene_info['audio'] is not None}, "
                   f"subtitle={scene_info['subtitle'] is not None}")
    
    result["total_scenes"] = len(scene_dirs)
    
    # Check if we have valid scene videos to combine
    valid_scenes = [s for s in result["scene_videos"] if s["video"] is not None]
    if valid_scenes:
        result["is_valid"] = True
        logger.info(f"Task scan complete: {len(valid_scenes)} valid scenes found")
    else:
        logger.warning(f"No valid scene videos found in task directory: {task_dir}")
    
    return result


def recover_video_synthesis(task_id_or_path: str, progress_callback=None, start_scene=None, end_scene=None) -> str:
    """
    Recover video synthesis from existing task files.
    
    This function scans the task directory for existing scene videos,
    audio files, and subtitle files, then combines them into the final video.
    
    Args:
        task_id_or_path: Task ID or direct directory path
        progress_callback: Optional callback function for progress updates
        start_scene: Starting scene number (1-based), None for first scene
        end_scene: Ending scene number (1-based), None for last scene
        
    Returns:
        Path to the final video file, or None if failed
    """
    import time
    start_time = time.time()
    # Determine task ID and directory
    if os.path.isdir(task_id_or_path):
        task_dir = task_id_or_path
        task_id = os.path.basename(task_dir)
    else:
        task_id = task_id_or_path
        task_dir = utils.task_dir(task_id)
    
    logger.info(f"\n\n## Starting video synthesis recovery for task: {task_id}")
    
    # Scan task directory
    task_files = scan_task_files(task_id_or_path)
    
    if not task_files["is_valid"]:
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.error("No valid scene videos found in task directory")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        return None
    
    task_dir = task_files["task_dir"]
    valid_scenes = [s for s in task_files["scene_videos"] if s["video"] is not None]
    
    if not valid_scenes:
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.error("No valid scenes found")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        return None
    
    # Apply scene range filtering
    # Default to first scene if start_scene not specified
    actual_start_scene = start_scene if start_scene is not None else 1
    # Default to last scene if end_scene not specified
    actual_end_scene = end_scene if end_scene is not None else len(task_files['scene_videos'])
    
    # Convert to 0-based indices
    start_idx = actual_start_scene - 1
    end_idx = actual_end_scene - 1
    
    # Ensure indices are within bounds
    start_idx = max(0, start_idx)
    end_idx = min(len(valid_scenes) - 1, end_idx)
    
    # Filter scenes
    valid_scenes = valid_scenes[start_idx:end_idx + 1]
    
    if not valid_scenes:
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.error("No valid scenes in the specified range")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        return None
    
    logger.info(f"Filtered to {len(valid_scenes)} valid scenes (range: {actual_start_scene}-{actual_end_scene})")
    
    # Determine which audio and subtitle files to use
    subtitle_file = task_files["global_subtitle"]
    audio_file = None  # Scene videos already contain audio
    
    # Scene videos already contain audio, no need for separate audio processing
    logger.info("Scene videos already contain audio, skipping audio processing")
    
    if not subtitle_file:
        logger.info("No global subtitle found, searching for scene subtitles...")
        # Collect subtitles from scene directories
        scene_subtitles = []
        for scene in valid_scenes:
            scene_subtitle = scene.get("subtitle")
            if scene_subtitle and os.path.exists(scene_subtitle):
                scene_subtitles.append(scene_subtitle)
                logger.info(f"Found scene subtitle: {scene_subtitle}")
        
        if scene_subtitles:
            # Use merge_scene_subtitles function to merge scene subtitles with time offset
            logger.info(f"Merging {len(scene_subtitles)} scene subtitles into global subtitle")
            merged_subtitle_path = os.path.join(task_dir, "merged_subtitle.srt")
            
            try:
                from app.services.subtitle import merge_scene_subtitles
                # Create scene_results list with duration info
                scene_results = []
                for i, scene in enumerate(valid_scenes):
                    scene_result = {
                        "scene_index": i,
                        "subtitle_path": scene.get("subtitle"),
                        "combined_video_path": scene.get("video")
                    }
                    scene_results.append(scene_result)
                
                subtitle_file = merge_scene_subtitles(task_id, scene_results, merged_subtitle_path)
                
                if not subtitle_file:
                    logger.error("Failed to merge subtitles")
            except Exception as e:
                logger.error(f"Failed to merge subtitles: {e}")
        else:
            logger.info("No scene subtitles found, will proceed without subtitles")
    
    # Collect video paths
    video_paths = [s["video"] for s in valid_scenes]
    
    # Determine output path with scene range format
    # Use the actual start and end scene values already calculated
    output_path = os.path.join(task_dir, f"scenes_{actual_start_scene}_to_{actual_end_scene}.mp4")
    
    # Get video parameters from config
    _cfg = load_config()
    app_config = _cfg.get("app", {})
    
    # Analyze video parameters from scene videos
    video_params = None
    if video_paths:
        # Analyze first scene video as reference
        video_params = analyze_video_params(video_paths[0])
        
        # Verify other videos
        for i, video_path in enumerate(video_paths[1:], 1):
            other_params = analyze_video_params(video_path)
            if other_params:
                # Check if parameters match
                if other_params["width"] != video_params["width"] or \
                   other_params["height"] != video_params["height"]:
                    logger.warning(f"Scene {i+1} video parameters don't match reference")
            else:
                logger.warning(f"Failed to analyze scene {i+1} video")
    
    # Create VideoParams object
    from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
    
    # Determine video aspect ratio
    if video_params:
        # Calculate aspect ratio from video dimensions
        width, height = video_params["width"], video_params["height"]
        # Simplify aspect ratio
        gcd = math.gcd(width, height)
        aspect_ratio = f"{width//gcd}:{height//gcd}"
        logger.info(f"Using detected aspect ratio: {aspect_ratio}")
    else:
        # Fall back to config
        aspect_ratio = app_config.get("video_aspect", "9:16")
        logger.info(f"Using config aspect ratio: {aspect_ratio}")
    
    params = VideoParams(
        video_subject="Recovered Video",
        video_aspect=VideoAspect(aspect_ratio),
        video_concat_mode=VideoConcatMode(app_config.get("video_concat_mode", "random")),
        subtitle_enabled=app_config.get("subtitle_enabled", True),
        font_name=app_config.get("font_name", "STHeitiMedium.ttc"),
        font_size=app_config.get("font_size", 60),
        text_fore_color=app_config.get("text_fore_color", "white"),
        text_background_color=app_config.get("text_background_color", "transparent"),
        stroke_color=app_config.get("stroke_color", "black"),
        stroke_width=app_config.get("stroke_width", 2),
        subtitle_position=app_config.get("subtitle_position", "bottom")
    )
    
    if progress_callback:
        progress_callback(20, "Preparing video files...")
    
    # For scene integration tasks (target video level), use combine_all_scenes
    logger.info(f"Combining {len(video_paths)} scene videos using combine_all_scenes for scene integration task")
    
    if progress_callback:
        progress_callback(40, "Combining scene videos...")
    
    try:
        # Create scene_results list for combine_all_scenes
        scene_results = []
        for i, video_path in enumerate(video_paths):
            scene_result = {
                "combined_video_path": video_path
            }
            scene_results.append(scene_result)
        
        # Use combine_all_scenes function
        combined_video_path = os.path.join(task_dir, "temp_combined_scenes.mp4")
        
        # Import combine_all_scenes from task module
        from app.services.task import combine_all_scenes
        combined_video_path = combine_all_scenes(
            task_id=task_id,
            params=params,
            scene_results=scene_results
        )
        
        if not combined_video_path:
            import time
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error("Failed to combine scene videos")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            return None
        
        logger.success(f"Combined video created: {combined_video_path}")
        
    except Exception as e:
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.error(f"Failed to combine scene videos: {e}")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        return None
    
    if progress_callback:
        progress_callback(60, "Generating final video...")
    
    # Use existing generate_video function to add audio and subtitles
    try:
        from app.services.video import generate_video
        output_path = generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_file,
            output_file=output_path,
            params=params,
            progress_callback=progress_callback
        )
        
        if output_path and os.path.exists(output_path):
            import time
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.success(f"Final video generated: {output_path}")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            
            return output_path
        else:
            import time
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error("Failed to generate final video")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            return None
            
    except Exception as e:
        import time
        end_time = time.time()
        total_time = end_time - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.error(f"Failed to generate final video: {e}")
        logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        return None
