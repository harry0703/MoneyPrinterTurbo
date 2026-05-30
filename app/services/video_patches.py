import sys
import io
import contextlib
import logging
import warnings
from loguru import logger

# Set moviepy and imageio logging level to WARNING to suppress detailed metadata logs
logging.basicConfig(level=logging.WARNING)
for logger_name in ['moviepy', 'imageio', 'imageio_ffmpeg', 'ffmpeg', 'PIL']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Also set the root logger level to WARNING to suppress all debug logs
logging.getLogger().setLevel(logging.WARNING)

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
