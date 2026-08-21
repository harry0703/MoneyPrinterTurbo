import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from loguru import logger

from app.utils import file_security, utils


# Streamlit allows fairly large uploads by default, but background music is usually only a few MB. Set an explicit
# server-side cap so the API or WebUI never writes an oversized file entirely to disk and disrupts video tasks in the same process.
MAX_BGM_UPLOAD_BYTES = 30 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_INTERNAL_UPLOAD_PREFIX = ".bgm-upload-"
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
# MoviePy decodes background music through FFmpeg, so there is no need to restrict uploads to MP3. Only mainstream,
# unambiguous audio extensions are accepted, preventing video containers such as MP4 from being uploaded as background music.
# The tuple doubles as the single source of truth for the WebUI upload widget, so formats never drift between front end and back end.
SUPPORTED_BGM_EXTENSIONS = (
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
)


class BgmUploadError(ValueError):
    """Indicates the uploaded file does not meet background music safety or format requirements."""


class BgmServiceError(RuntimeError):
    """Indicates a server-side execution failure such as FFmpeg or the filesystem being unavailable."""


def should_use_bgm(bgm_type: str | None, bgm_volume: float | None) -> bool:
    """
    Decide uniformly whether the current task needs any background music processing.

    The rule is source-agnostic: when no source is selected, the volume is invalid, or the volume
    is not greater than 0, random, custom, Sonilo, and any future provider must all skip file
    parsing, external generation, and final mixing. Keeping it in the shared BGM service avoids
    duplicating the zero-volume check for every new provider.
    """
    if not str(bgm_type or "").strip():
        return False
    try:
        normalized_volume = float(bgm_volume or 0)
    except (TypeError, ValueError):
        return False
    return math.isfinite(normalized_volume) and normalized_volume > 0


def uploaded_bgm_dir(create: bool = True) -> str:
    """
    Return the persistent directory for user background music.

    Built-in songs are code resources and stay in resource/songs; user uploads are runtime data
    and must live under the Docker-mounted storage directory so they survive container rebuilds
    and never pollute the Git workspace.
    """
    return utils.storage_dir("bgm", create=create)


def _remove_staged_file(file_path: str) -> None:
    """Best-effort cleanup of the upload temporary file without masking the original exception the caller is handling."""
    if not file_path or not os.path.exists(file_path):
        return
    try:
        os.remove(file_path)
    except OSError as exc:
        # Temporary files use a reserved prefix and never appear in the BGM list; a cleanup failure must not mask the more
        # accurate original exception (e.g. "invalid audio"), but the path and system error must remain for operators.
        logger.warning(
            f"failed to remove staged background music: path={file_path}, "
            f"error={str(exc)}"
        )


def sanitize_upload_filename(filename: str) -> str:
    """Extract a cross-platform-safe audio file name and reject illegal names and unsupported extensions."""
    safe_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if (
        not safe_name
        or safe_name in {".", ".."}
        or len(safe_name) > 255
        or any(ord(character) < 32 for character in safe_name)
        or any(character in _WINDOWS_INVALID_FILENAME_CHARS for character in safe_name)
        or safe_name.lower().startswith(_INTERNAL_UPLOAD_PREFIX)
    ):
        raise BgmUploadError("invalid background music filename")

    # Windows treats the first dot-separated segment before the extension as a device name — CON.mp3 and LPT1.wav
    # cannot be created as normal files. Even though the server ultimately uses UUIDs, rejecting such names up front keeps API input behavior identical across platforms.
    # keeps API input behavior identical across platforms.
    windows_basename = safe_name.split(".", 1)[0].rstrip(" .").upper()
    if windows_basename in _WINDOWS_RESERVED_FILENAMES:
        raise BgmUploadError("invalid background music filename")
    if Path(safe_name).suffix.lower() not in SUPPORTED_BGM_EXTENSIONS:
        supported_formats = ", ".join(
            extension.removeprefix(".").upper()
            for extension in SUPPORTED_BGM_EXTENSIONS
        )
        raise BgmUploadError(
            f"unsupported background music format; supported formats: {supported_formats}"
        )
    return safe_name


def _validate_audio(file_path: str, timeout_seconds: int = 30) -> None:
    """
    Verify with the project's configured FFmpeg only that the file contains a fully decodable audio stream.

    The project allows imageio-ffmpeg to provide a portable FFmpeg, which does not guarantee FFprobe,
    so no separate binary dependency may be added. `-map 0:a:0` fails when there is no audio stream
    and `-xerror` turns decode errors into failures; a full decode also catches encrypted files or
    random data accidentally matching an audio frame header. The file may contain extra streams such
    as album art, but only the first audio stream is validated.
    """
    try:
        decoded = subprocess.run(
            [
                utils.get_ffmpeg_binary(),
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                file_path,
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BgmServiceError("FFmpeg background music validation timed out") from exc
    except OSError as exc:
        raise BgmServiceError("failed to run FFmpeg for background music validation") from exc
    if decoded.returncode != 0:
        raise BgmUploadError("uploaded file must contain a decodable audio stream")


def validate_audio_file(file_path: str, timeout_seconds: int = 120) -> None:
    """
    Verify that an audio file on disk is fully decodable by the project's FFmpeg.

    Upload prechecks usually finish within 30 seconds; Sonilo-generated tracks can run up to 6 minutes,
    so a reusable entry point with an adjustable timeout is exposed. The service depends only on
    FFmpeg and never requires FFprobe to be installed.
    """
    if not os.path.isfile(file_path) or os.path.getsize(file_path) <= 0:
        raise BgmUploadError("background music file is empty or missing")
    _validate_audio(file_path, timeout_seconds=timeout_seconds)


def _stage_bgm_upload(filename: str, source: BinaryIO) -> tuple[str, str, int]:
    """
    Write an upload stream to a temporary file in the target directory, returning a safe file name, the temporary path, and the byte count.

    The WebUI's upload precheck and final persistence must use exactly the same chunked reading, size
    limits, and file name rules; otherwise the UI could show a file as ready while generation later
    rejects it. The temporary file is deleted or atomically replaced by the caller after audio probing.
    """
    safe_name = sanitize_upload_filename(filename)
    try:
        target_dir = uploaded_bgm_dir(create=True)
    except OSError as exc:
        raise BgmServiceError("failed to prepare background music storage") from exc
    temp_path = ""
    total_bytes = 0

    try:
        try:
            source.seek(0)
        except (AttributeError, OSError) as exc:
            raise BgmUploadError("background music upload is not seekable") from exc

        # Keep the original extension so FFmpeg can pick the right demuxer for header-less formats like AAC;
        # the temporary file stays in the target directory so the final os.replace remains atomic.
        descriptor, temp_path = tempfile.mkstemp(
            prefix=_INTERNAL_UPLOAD_PREFIX,
            suffix=Path(safe_name).suffix.lower(),
            dir=target_dir,
        )
        with os.fdopen(descriptor, "wb") as output:
            while True:
                chunk = source.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise BgmUploadError("background music upload must be binary")
                total_bytes += len(chunk)
                if total_bytes > MAX_BGM_UPLOAD_BYTES:
                    raise BgmUploadError("background music file exceeds the 30 MB limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if total_bytes == 0:
            raise BgmUploadError("background music file is empty")
        return safe_name, temp_path, total_bytes
    except Exception as exc:
        _remove_staged_file(temp_path)
        if isinstance(exc, BgmUploadError):
            raise
        if isinstance(exc, OSError):
            raise BgmServiceError("failed to stage background music upload") from exc
        raise
    finally:
        # Streamlit also reuses the same UploadedFile for browser playback; restoring the file pointer prevents
        # the player or the final save from reading empty content after validation.
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass


def validate_bgm_upload(filename: str, source: BinaryIO) -> str:
    """Fully validate an uploaded audio file without persisting it; used by the WebUI precheck before showing "ready"."""
    safe_name, temp_path, total_bytes = _stage_bgm_upload(filename, source)
    try:
        _validate_audio(temp_path)
        logger.debug(
            f"background music upload validated: name={safe_name}, "
            f"size={total_bytes} bytes"
        )
        return safe_name
    finally:
        _remove_staged_file(temp_path)


def save_bgm_upload(filename: str, source: BinaryIO) -> str:
    """
    Save user background music with chunked writes, size limits, and atomic replacement.

    Used by both FastAPI UploadFile and Streamlit UploadedFile since both expose a binary file
    interface. Write a temporary file in the same directory first and validate it, then persist via
    an atomic os.replace. This avoids half-written audio files from concurrent uploads or interrupted
    processes, and gives same-named uploads distinct UUID storage keys so queued or running tasks
    always reference the original immutable file.
    """
    safe_name, temp_path, total_bytes = _stage_bgm_upload(filename, source)
    stored_name = f"{uuid4().hex}{Path(safe_name).suffix.lower()}"
    target_path = os.path.join(os.path.dirname(temp_path), stored_name)

    try:
        _validate_audio(temp_path)
        try:
            os.replace(temp_path, target_path)
        except OSError as exc:
            raise BgmServiceError("failed to persist background music upload") from exc
        temp_path = ""
        logger.info(
            f"background music uploaded: original_name={safe_name}, "
            f"stored_name={stored_name}, size={total_bytes} bytes"
        )
        return stored_name
    finally:
        _remove_staged_file(temp_path)


def list_bgm_files() -> list[str]:
    """List available background music from user uploads and built-in songs."""
    files_by_name: dict[str, str] = {}
    for directory in (utils.song_dir(), uploaded_bgm_dir(create=True)):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory), key=str.lower):
            # Both the upload precheck and the final save briefly create a same-directory file. The temporary file carries a valid
            # audio extension but has not finished validation, so the random BGM list must not pick it up.
            if name.startswith(_INTERNAL_UPLOAD_PREFIX):
                continue
            if Path(name).suffix.lower() not in SUPPORTED_BGM_EXTENSIONS:
                continue
            file_path = os.path.join(directory, name)
            try:
                # Enumeration results also require real-path validation. Otherwise an attacker could plant an audio symlink in an
                # allowed directory pointing to an external file and hand it to MoviePy via the random BGM path.
                resolved_path = file_security.resolve_path_within_directory(
                    directory, file_path
                )
            except ValueError as exc:
                logger.warning(
                    f"skip unsafe background music file: name={name}, error={str(exc)}"
                )
                continue
            files_by_name[name] = resolved_path
    return [files_by_name[name] for name in sorted(files_by_name, key=str.lower)]


def resolve_bgm_file(unsafe_path: str) -> str:
    """
    Resolve BGM inside the user upload directory and the built-in songs directory, rejecting paths outside both whitelists.

    File names preferentially hit the user directory while legacy usages like `output000.mp3`, absolute
    whitelist paths, and `./resource/songs/output000.mp3` keep working. New uploads use UUIDs and do
    not normally collide with built-in songs or historical uploads.
    """
    if (
        not unsafe_path
        or Path(unsafe_path).suffix.lower() not in SUPPORTED_BGM_EXTENSIONS
    ):
        raise ValueError("unsupported background music path")

    candidates = [unsafe_path]
    if not os.path.isabs(unsafe_path):
        candidates.append(os.path.join(utils.root_dir(), unsafe_path))

    last_error = ValueError("background music file does not exist")
    for directory in (uploaded_bgm_dir(create=True), utils.song_dir()):
        for candidate in candidates:
            try:
                return file_security.resolve_path_within_directory(directory, candidate)
            except ValueError as exc:
                last_error = exc
    raise ValueError(str(last_error)) from last_error
