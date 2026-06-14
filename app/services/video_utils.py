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
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    vfx,
    concatenate_videoclips,
)
from app.utils.composite_clip_factory import create_composite_video_clip
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
    Parse a color string to an RGB or RGBA tuple.
    Supports:
    - Named colors: "black", "white", "red", "green", "blue", etc.
    - RGB format: "rgb(0, 0, 0)"
    - RGBA format: "rgba(0, 0, 0, 0.5)"
    - Hex format: "#000000" or "#000"
    """
    color_str = color_str.strip().lower()
    
    # Check named colors
    if color_str in COLOR_MAP:
        return COLOR_MAP[color_str]
    
    # Check RGBA format
    if color_str.startswith("rgba(") and color_str.endswith(")"):
        try:
            values = color_str[5:-1].split(",")
            r = int(values[0].strip())
            g = int(values[1].strip())
            b = int(values[2].strip())
            a = float(values[3].strip())
            # Convert alpha from 0-1 to 0-255
            a_int = int(a * 255)
            return (r, g, b, a_int)
        except:
            pass
    
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
import threading


class EncodingProgressMonitor:
    """
    Monitors video encoding progress by watching the output file size.
    Provides periodic progress updates without interfering with MoviePy.
    """
    
    def __init__(self, task_id=None, output_file=None, progress_callback=None, log_interval=10):
        """
        Initialize the progress monitor.
        
        Args:
            task_id: Optional task ID for tracking and state updates
            output_file: Path to the output video file being created
            progress_callback: Optional callback function(progress: float, message: str)
            log_interval: How often to log progress in seconds (default: 10)
        """
        self.task_id = task_id
        self.output_file = output_file
        self.progress_callback = progress_callback
        self.log_interval = log_interval
        self.monitoring = False
        self.monitor_thread = None
        
    def start_monitoring(self, estimated_final_size_mb=None):
        """
        Start monitoring encoding progress in a background thread.
        
        Args:
            estimated_final_size_mb: Estimated final file size in MB (optional)
        """
        self.monitoring = True
        self.estimated_final_size = estimated_final_size_mb
        self.start_time = time.time()
        self.last_log_time = time.time()
        self.last_size = 0
        
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True  # Thread will be killed when main thread exits
        )
        self.monitor_thread.start()
        logger.info("📊 Encoding progress monitor started")
    
    def stop_monitoring(self):
        """Stop the progress monitoring."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
        logger.info("📊 Encoding progress monitor stopped")
    
    def _monitor_loop(self):
        """Background thread that monitors file size."""
        while self.monitoring:
            try:
                current_time = time.time()
                
                # Check if file exists and get its size
                if os.path.exists(self.output_file):
                    current_size_mb = os.path.getsize(self.output_file) / (1024 * 1024)
                    elapsed = current_time - self.start_time
                    
                    # Log progress periodically
                    if current_time - self.last_log_time >= self.log_interval:
                        # Calculate progress percentage
                        if self.estimated_final_size and self.estimated_final_size > 0:
                            percentage = min(100, (current_size_mb / self.estimated_final_size) * 100)
                        else:
                            # Without estimated size, just log the file size
                            percentage = 0
                        
                        # Calculate write speed
                        size_diff = current_size_mb - self.last_size
                        time_diff = current_time - self.last_log_time
                        speed_mbps = size_diff / time_diff if time_diff > 0 else 0
                        
                        # Calculate ETA
                        if percentage > 0 and self.estimated_final_size:
                            remaining_mb = self.estimated_final_size - current_size_mb
                            eta_seconds = remaining_mb / speed_mbps if speed_mbps > 0 else 0
                            eta_str = f"ETA: {int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                        elif speed_mbps > 0 and self.estimated_final_size:
                            remaining_mb = self.estimated_final_size - current_size_mb
                            eta_seconds = remaining_mb / speed_mbps
                            eta_str = f"ETA: {int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                        else:
                            eta_str = "ETA: calculating..."
                        
                        # Log progress
                        if percentage > 0:
                            logger.info(
                                f"🎬 Encoding progress: {percentage:.1f}% | "
                                f"Size: {current_size_mb:.1f}MB | "
                                f"Speed: {speed_mbps:.2f}MB/s | "
                                f"Elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s | "
                                f"{eta_str}"
                            )
                        else:
                            logger.info(
                                f"🎬 Encoding: {current_size_mb:.1f}MB written | "
                                f"Speed: {speed_mbps:.2f}MB/s | "
                                f"Elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s"
                            )
                        
                        self.last_log_time = current_time
                        self.last_size = current_size_mb
                        
                        # Update task state in state manager for UI updates
                        if self.task_id and percentage > 0:
                            try:
                                from app.services import state as sm
                                from app.models import const
                                # Scale progress to 90-100 range (final encoding phase)
                                scaled_progress = 90 + (percentage / 100) * 10
                                sm.state.update_task(
                                    self.task_id,
                                    state=const.TASK_STATE_PROCESSING,
                                    progress=int(scaled_progress)
                                )
                            except Exception as e:
                                logger.debug(f"Failed to update task state (ignored): {e}")
                        
                        # Call custom progress callback if provided
                        if self.progress_callback and percentage > 0:
                            scaled_progress = 90 + (percentage / 100) * 10
                            self.progress_callback(
                                scaled_progress, 
                                f"Encoding video: {percentage:.1f}%"
                            )
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.debug(f"Progress monitoring error (ignored): {e}")
                time.sleep(10)  # Check every 10 seconds even after errors


def create_encoding_progress_monitor(task_id=None, output_file=None, progress_callback=None, log_interval=10):
    """
    Factory function to create an encoding progress monitor.
    
    Args:
        task_id: Optional task ID for tracking
        output_file: Path to the output video file
        progress_callback: Optional callback function(progress: float, message: str)
        log_interval: How often to log progress in seconds (default: 10)
        
    Returns:
        EncodingProgressMonitor instance
    """
    return EncodingProgressMonitor(
        task_id=task_id,
        output_file=output_file,
        progress_callback=progress_callback,
        log_interval=log_interval
    )
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

# Cache for video codec detection: (use_gpu_value, codec_string)
# Storing the use_gpu value alongside the codec allows us to detect config
# changes and only re-run the expensive `ffmpeg -encoders` subprocess when
# the GPU setting has actually changed.
_cached_codec_entry: tuple = None  # (use_gpu: bool, codec: str)

# Select video encoder based on configuration
def get_video_codec():
    """Select appropriate video encoder based on configuration and system environment"""
    global _cached_codec_entry

    use_gpu = config.app.get("use_gpu", False)

    # Return cached result if the use_gpu setting hasn't changed
    if _cached_codec_entry is not None and _cached_codec_entry[0] == use_gpu:
        return _cached_codec_entry[1]

    if not use_gpu:
        logger.info("Video encoder: CPU mode selected (libx264)")
        _cached_codec_entry = (False, "libx264")
        return "libx264"

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
            codec = "h264_nvenc"
            logger.info(f"Video encoder: NVIDIA GPU mode selected ({codec})")
        # Check for AMD GPU support
        elif "h264_amf" in result.stdout:
            codec = "h264_amf"
            logger.info(f"Video encoder: AMD GPU mode selected ({codec})")
        # Check for Intel GPU support
        elif "h264_qsv" in result.stdout:
            codec = "h264_qsv"
            logger.info(f"Video encoder: Intel GPU mode selected ({codec})")
        else:
            # GPU fallback: use_gpu=True but no GPU encoder available
            logger.warning("GPU FALLBACK: No supported GPU encoder found in FFmpeg, using libx264")
            codec = "libx264"
        _cached_codec_entry = (True, codec)
        return codec
    except subprocess.TimeoutExpired:
        logger.warning("GPU FALLBACK: FFmpeg '-encoders' timed out, using libx264")
        _cached_codec_entry = (True, "libx264")
        return "libx264"
    except FileNotFoundError:
        logger.warning(f"GPU FALLBACK: FFmpeg executable not found at '{ffmpeg_exe}', using libx264")
        _cached_codec_entry = (True, "libx264")
        return "libx264"
    except Exception as e:
        logger.warning(f"GPU FALLBACK: {type(e).__name__}: {e}, using libx264")
        _cached_codec_entry = (True, "libx264")
        return "libx264"

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
        try:
            if hasattr(clip, 'reader'):
                reader = clip.reader
                if reader is not None:
                    try:
                        reader.close()
                    except Exception as e:
                        # Ignore handle invalid and access denied errors
                        if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower() and "[WinError 5]" not in str(e) and "拒绝访问" not in str(e):
                            logger.error(f"failed to close clip reader: {str(e)}")
        except Exception:
            pass
            
        # close audio resources
        try:
            if hasattr(clip, 'audio'):
                audio = clip.audio
                if audio is not None:
                    try:
                        if hasattr(audio, 'reader'):
                            audio_reader = audio.reader
                            if audio_reader is not None:
                                try:
                                    audio_reader.close()
                                except Exception as e:
                                    # Ignore handle invalid and access denied errors
                                    if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower() and "[WinError 5]" not in str(e) and "拒绝访问" not in str(e):
                                        logger.error(f"failed to close audio reader: {str(e)}")
                        audio.close()
                    except Exception as e:
                        # Ignore handle invalid and access denied errors
                        if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower() and "[WinError 5]" not in str(e) and "拒绝访问" not in str(e):
                            logger.error(f"failed to close audio clip: {str(e)}")
                    finally:
                        try:
                            del clip.audio
                        except:
                            pass
        except Exception:
            pass
            
        # close mask resources
        try:
            if hasattr(clip, 'mask'):
                mask = clip.mask
                if mask is not None:
                    try:
                        if hasattr(mask, 'reader'):
                            mask_reader = mask.reader
                            if mask_reader is not None:
                                try:
                                    mask_reader.close()
                                except Exception as e:
                                    # Ignore handle invalid and access denied errors
                                    if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower() and "[WinError 5]" not in str(e) and "拒绝访问" not in str(e):
                                        logger.error(f"failed to close mask reader: {str(e)}")
                        mask.close()
                    except Exception as e:
                        # Ignore handle invalid and access denied errors
                        if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower() and "[WinError 5]" not in str(e) and "拒绝访问" not in str(e):
                            logger.error(f"failed to close mask clip: {str(e)}")
                    finally:
                        try:
                            del clip.mask
                        except:
                            pass
        except Exception:
            pass
            
        # handle child clips in composite clips
        try:
            if hasattr(clip, 'clips'):
                child_clips = clip.clips
                if child_clips:
                    for child_clip in child_clips:
                        if child_clip is not clip:  # avoid possible circular references
                            close_clip(child_clip)
            
            # clear clip list
            if hasattr(clip, 'clips'):
                clip.clips = []
        except Exception:
            pass
            
        # Try to close the clip itself
        try:
            clip.close()
        except Exception as e:
            # Ignore handle invalid and access denied errors
            if "句柄无效" not in str(e) and "invalid handle" not in str(e).lower() and "[WinError 5]" not in str(e) and "拒绝访问" not in str(e):
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
        composite = create_composite_video_clip(
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
        composite = create_composite_video_clip(
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
    
    # Note: The fl_image method is deprecated in moviepy 2.x
    # We use the scaling approach which is more reliable across moviepy versions
    # If you have scipy installed and want to use gaussian blur, 
    # you can uncomment the scipy section below
    
    # Check if scipy is available and use gaussian blur
    # try:
    #     from scipy.ndimage import gaussian_filter
    #     import numpy as np
    #     
    #     # For video clips, we need to process each frame
    #     def blur_frame(frame):
    #         # Apply gaussian filter to each frame
    #         if len(frame.shape) == 3:
    #             # Color image
    #             blurred = np.zeros_like(frame)
    #             for i in range(frame.shape[2]):
    #                 blurred[:, :, i] = gaussian_filter(frame[:, :, i], sigma=blur_radius)
    #             return blurred
    #         else:
    #             # Grayscale image
    #             return gaussian_filter(frame, sigma=blur_radius)
    #     
    #     # Apply blur to the clip using fl_image
    #     blurred_clip = clip.fl_image(blur_frame)
    #     return blurred_clip
    #     
    # except (ImportError, AttributeError):
    #     # scipy not available or fl_image not available (moviepy 2.x)
    #     pass
    
    # Use aggressive scaling down-up approach
    # This creates smooth blur by downscaling to a small size then upscaling back
    logger.info("Using scaling approach for blur effect")
    
    w, h = clip.size
    
    # Calculate target small size based on blur radius
    # Higher blur radius = smaller intermediate size = more blur
    # Formula: scale from 50% (radius=0) down to 5% (radius=50+)
    # blur_radius=15 → ~35% scale
    # blur_radius=30 → ~20% scale
    # blur_radius=50 → ~5% scale
    target_scale = max(0.05, 0.5 - (blur_radius / 100.0))
    
    small_w = max(16, int(w * target_scale))
    small_h = max(16, int(h * target_scale))
    
    logger.info(f"Blur settings: radius={blur_radius}, scale={target_scale:.2%}, size={small_w}x{small_h}")
    
    # Apply multiple downscale-upscale passes for smoother blur
    intermediate_clip = clip
    
    # Number of passes increases with blur radius
    num_passes = min(5, max(2, blur_radius // 20))
    
    for pass_num in range(num_passes):
        # Scale down with high-quality resampling (moviepy 2.x uses 'resized')
        intermediate_clip = intermediate_clip.resized(
            new_size=(small_w, small_h)
        )
        
        # Scale back up with high-quality resampling
        intermediate_clip = intermediate_clip.resized(
            new_size=(w, h)
        )
        
        logger.debug(f"Blur pass {pass_num + 1}/{num_passes} completed")
    
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


def wrap_text(text, max_width, font="Arial", fontsize=60, auto_fit=False, min_font_ratio=0.85):
    """Wrap text to fit within max_width.
    
    Args:
        text: Text to wrap
        max_width: Maximum width in pixels
        font: Path to font file
        fontsize: Font size in points
        auto_fit: If True, try reducing font size to fit on a single line before wrapping
        min_font_ratio: Minimum font size ratio when auto_fit is enabled (default 0.85 = 85%)
    
    Returns:
        Tuple of (wrapped_text, text_height, actual_font_size)
    """
    actual_fontsize = fontsize
    img_font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        if not inner_text:
            return 0, 0
        left, top, right, bottom = img_font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    
    # Auto-fit: try reducing font size to avoid line breaks
    if auto_fit and width > max_width and fontsize > 1:
        best_size = fontsize
        for test_ratio in range(int(min_font_ratio * 100), 100):
            test_size = int(fontsize * test_ratio / 100)
            if test_size < 8:
                break
            img_font = ImageFont.truetype(font, test_size)
            w, h = get_text_size(text)
            if w <= max_width:
                best_size = test_size
                width, height = w, h
                break
        
        if best_size < fontsize:
            actual_fontsize = best_size
            # Re-create font at the fitted size
            img_font = ImageFont.truetype(font, actual_fontsize)
    
    if width <= max_width:
        return text, height, actual_fontsize

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
    
    return wrapped_text, total_height, actual_fontsize

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
