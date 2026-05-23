import glob
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

COLOR_MAP = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 128),
    "gray": (128, 128, 128),
    "darkgray": (64, 64, 64),
    "lightgray": (192, 192, 192),
}

def parse_color(color_str: str) -> tuple:
    """
    Parse a color string to an RGB tuple.
    Supports:
    - Named colors: "black", "white", "red", "green", "blue", etc.
    - RGB format: "rgb(0, 0, 0)"
    - Hex format: "#000000" or "#000"
    """
    color_str = color_str.strip().lower()
    
    # Check named colors
    if color_str in COLOR_MAP:
        return COLOR_MAP[color_str]
    
    # Check RGB format
    if color_str.startswith("rgb(") and color_str.endswith(")"):
        try:
            values = color_str[4:-1].split(",")
            r, g, b = [int(v.strip()) for v in values]
            return (r, g, b)
        except:
            pass
    
    # Check hex format
    if color_str.startswith("#"):
        try:
            hex_str = color_str[1:]
            if len(hex_str) == 3:
                # Short hex format: #RGB
                r = int(hex_str[0] * 2, 16)
                g = int(hex_str[1] * 2, 16)
                b = int(hex_str[2] * 2, 16)
            elif len(hex_str) == 6:
                # Full hex format: #RRGGBB
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
            else:
                return COLOR_MAP["black"]
            return (r, g, b)
        except:
            pass
    
    # Default to black
    return COLOR_MAP["black"]

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


def copy_local_materials_to_task(task_id: str, materials: List) -> List:
    """
    Copy local materials to task-specific directory for isolation.
    
    Args:
        task_id: Task ID for creating task-specific directory
        materials: List of MaterialInfo objects with local file paths
        
    Returns:
        List of MaterialInfo objects with updated (task-specific) paths
    """
    from app.models.schema import MaterialInfo
    from app.utils import utils
    import shutil
    
    if not materials:
        return materials
    
    task_materials_dir = os.path.join(utils.task_dir(task_id), "materials")
    os.makedirs(task_materials_dir, exist_ok=True)
    
    processed_materials = []
    
    for material in materials:
        if not material or not material.url:
            continue
            
        original_path = material.url
        
        if original_path.startswith(('http://', 'https://', 'ftp://')):
            processed_materials.append(material)
            continue
        
        original_filename = os.path.basename(original_path)
        name, ext = os.path.splitext(original_filename)
        unique_filename = f"{name}_{task_id[:8]}{ext}"
        task_material_path = os.path.join(task_materials_dir, unique_filename)
        
        try:
            shutil.copy2(original_path, task_material_path)
            logger.info(f"Copied local material to task directory: {original_path} -> {task_material_path}")
            
            new_material = MaterialInfo(
                provider=material.provider,
                url=task_material_path,
                duration=round(material.duration)
            )
            processed_materials.append(new_material)
        except Exception as e:
            logger.warning(f"Failed to copy local material {original_path}: {str(e)}")
            processed_materials.append(material)
    
    logger.info(f"Copied {len(processed_materials)} local materials to task directory: {task_materials_dir}")
    return processed_materials


def fit_intro_video_to_target(clip, target_width, target_height, bg_color_str="black", bg_type="solid", blur_radius=15):
    """
    Fit intro video into target dimensions without cropping.
    Scales the video to fit within target, centers it on a background layer.
    
    Args:
        clip: VideoFileClip to process
        target_width: Target width in pixels
        target_height: Target height in pixels
        bg_color_str: Background color as string (name, hex, or rgb) - used when bg_type is "solid"
        bg_type: Background type - "solid" (solid color) or "blurred" (blurred stretched video)
        blur_radius: Blur radius when bg_type is "blurred" (default: 15)
    
    Returns:
        Composite video clip with intro centered on background
    """
    clip_w, clip_h = clip.size
    target_ratio = target_width / target_height
    clip_ratio = clip_w / clip_h
    
    logger.info(f"Fitting intro video: {clip_w}x{clip_h} -> {target_width}x{target_height}")
    logger.info(f"Ratios - clip: {clip_ratio:.3f}, target: {target_ratio:.3f}")
    logger.info(f"Background type: {bg_type}, blur radius: {blur_radius if bg_type == 'blurred' else 'N/A'}")
    logger.info(f"Background color: {bg_color_str}")
    
    # Parse background color
    bg_color = parse_color(bg_color_str)
    
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
    
    # Scale the video to fit within target dimensions
    new_width = round(clip_w * scale_factor)
    new_height = round(clip_h * scale_factor)
    logger.info(f"Scaling intro video: {clip_w}x{clip_h} -> {new_width}x{new_height}")
    
    scaled_clip = clip.resized(new_size=(new_width, new_height))
    
    # Calculate position to center the scaled clip
    x_offset = (target_width - new_width) // 2
    y_offset = (target_height - new_height) // 2
    
    logger.info(f"Positioning intro at center: x={x_offset}, y={y_offset}")
    
    # Create background based on bg_type
    if bg_type == "blurred":
        # Create blurred background
        # First, create a stretched version of the clip to fill the entire background
        stretched_background = clip.resized(new_size=(target_width, target_height))
        
        # Apply blur effect to the stretched background
        # moviepy uses different blur implementations, we'll use a lambda-based approach
        blurred_background = apply_blur_effect(stretched_background, blur_radius)
        
        # Close stretched_background to release resources
        close_clip(stretched_background)
        
        # Composite: blurred background at bottom, scaled clip on top
        composite = CompositeVideoClip(
            [blurred_background, scaled_clip.with_position((x_offset, y_offset))],
            size=(target_width, target_height)
        )
        
        # Close blurred_background to release resources
        close_clip(blurred_background)
        
        logger.info(f"Created blurred background with radius {blur_radius}")
    else:
        # Create solid color background (default behavior)
        background = ColorClip(
            size=(target_width, target_height),
            color=bg_color,
            duration=clip.duration
        )
        
        # Composite the video on background
        composite = CompositeVideoClip(
            [background, scaled_clip.with_position((x_offset, y_offset))],
            size=(target_width, target_height)
        )
        
        # Close background to release resources
        close_clip(background)
        
        logger.info(f"Created solid color background: {bg_color}")
    
    composite = composite.with_duration(clip.duration)
    
    # Preserve audio if present
    if clip.audio is not None:
        composite = composite.with_audio(clip.audio)
    
    logger.success(f"Intro video fitted successfully: {target_width}x{target_height} with {bg_type} background")
    return composite


def apply_blur_effect(clip, blur_radius):
    """
    Apply blur effect to a video clip.
    
    Args:
        clip: Video clip to blur
        blur_radius: Blur radius (higher = more blur)
    
    Returns:
        Blurred video clip
    """
    from moviepy import vfx
    
    # For moviepy, we can use multiple applications of resize with blurring
    # A more practical approach is to use PIL's ImageFilter or custom functions
    
    # Check if we have scipy available for gaussian blur
    try:
        from scipy.ndimage import gaussian_filter
        import numpy as np
        
        # For video clips, we need to process each frame
        def blur_frame(frame):
            # Apply gaussian filter to each frame
            if len(frame.shape) == 3:
                # Color image
                blurred = np.zeros_like(frame)
                for i in range(frame.shape[2]):
                    blurred[:, :, i] = gaussian_filter(frame[:, :, i], sigma=blur_radius)
                return blurred
            else:
                # Grayscale image
                return gaussian_filter(frame, sigma=blur_radius)
        
        # Apply blur to the clip using fl_image
        blurred_clip = clip.fl_image(blur_frame)
        return blurred_clip
        
    except ImportError:
        # Fallback: if scipy is not available, use multiple resize operations to simulate blur
        # This is less effective but doesn't require additional dependencies
        logger.warning("scipy not available, using fallback blur method")
        
        # Create a series of progressively smaller/larger resizes to simulate blur
        intermediate_clip = clip
        num_steps = max(1, blur_radius // 5)  # More steps for higher blur radius
        
        for i in range(num_steps):
            # Progressively scale down and back up
            scale_down = 1.0 - (0.2 * (i + 1) / num_steps)
            scale_up = 1.0 / scale_down
            
            # Scale down
            w, h = intermediate_clip.size
            new_w = max(1, int(w * scale_down))
            new_h = max(1, int(h * scale_down))
            intermediate_clip = intermediate_clip.resized(new_size=(new_w, new_h))
            
            # Scale back up
            intermediate_clip = intermediate_clip.resized(new_size=(w, h))
        
        return intermediate_clip


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
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        if not inner_text:
            return 0, 0
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    lines = []
    current_line = text.strip()
    
    punctuation_chars = '，,。.！!？?；;：:、'
    
    while current_line:
        current_width, line_height = get_text_size(current_line)
        
        if current_width <= max_width:
            lines.append(current_line)
            break
        
        split_pos = len(current_line) // 2
        
        current_width, _ = get_text_size(current_line)
        if current_width > max_width:
            target_chars = 0
            for i in range(1, len(current_line)):
                w, _ = get_text_size(current_line[:i])
                if w <= max_width:
                    target_chars = i
                else:
                    break
            
            if target_chars > 0:
                split_pos = target_chars
            else:
                split_pos = len(current_line) // 2
        
        best_split_pos = split_pos
        
        look_range = 5
        start_look = max(0, split_pos - look_range)
        end_look = min(len(current_line), split_pos + look_range)
        
        for i in range(end_look, start_look, -1):
            if i < len(current_line) and (current_line[i] in punctuation_chars or current_line[i] == ' '):
                best_split_pos = i + 1
                break
        
        line = current_line[:best_split_pos].strip()
        
        if not line:
            line = current_line[:max(1, len(current_line) // 2)]
            best_split_pos = len(line)
        
        lines.append(line)
        current_line = current_line[best_split_pos:].strip()
    
    wrapped_text = '\n'.join(lines)
    total_height = len(lines) * line_height
    
    return wrapped_text, total_height

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
        close_clip(clip)
        return params
    except Exception as e:
        logger.error(f"Failed to analyze video: {e}")
        return None
