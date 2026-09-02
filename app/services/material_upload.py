import os
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import uuid4

from loguru import logger
from PIL import Image, UnidentifiedImageError

from app.utils import utils


# Local materials are usually short clips. This matches Streamlit's default upload
# limit while still placing an explicit server-side bound on direct API clients.
MAX_VIDEO_MATERIAL_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_IMAGE_MATERIAL_UPLOAD_BYTES = 20 * 1024 * 1024
MATERIAL_VALIDATION_TIMEOUT_SECONDS = 120

SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".flv", ".mkv")
SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
SUPPORTED_MATERIAL_EXTENSIONS = (
    *SUPPORTED_VIDEO_EXTENSIONS,
    *SUPPORTED_IMAGE_EXTENSIONS,
)

_COPY_CHUNK_BYTES = 1024 * 1024
_INTERNAL_UPLOAD_PREFIX = ".material-upload-"
_IMAGE_FORMATS_BY_EXTENSION = {
    ".jpg": frozenset({"JPEG"}),
    ".jpeg": frozenset({"JPEG"}),
    ".png": frozenset({"PNG"}),
}


class MaterialUploadError(ValueError):
    """The uploaded material does not satisfy the file or media requirements."""


class MaterialServiceError(RuntimeError):
    """The server could not stage, validate, or persist an uploaded material."""


def uploaded_material_dir(create: bool = True) -> str:
    return utils.storage_dir("local_videos", create=create)


def _remove_staged_file(file_path: str) -> None:
    if not file_path or not os.path.exists(file_path):
        return
    try:
        os.remove(file_path)
    except OSError as exc:
        logger.warning(
            f"failed to remove staged local material: path={file_path}, "
            f"error={str(exc)}"
        )


def _material_kind(filename: str) -> Literal["video", "image"]:
    suffix = Path(filename).suffix.lower()
    if suffix in SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return "image"

    supported_formats = ", ".join(
        extension.removeprefix(".") for extension in SUPPORTED_MATERIAL_EXTENSIONS
    )
    raise MaterialUploadError(
        f"unsupported local material format; supported formats: {supported_formats}"
    )


def sanitize_material_filename(filename: str) -> str:
    """Return a display-safe basename and reject malformed or unsupported names."""
    safe_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if (
        not safe_name
        or safe_name in {".", ".."}
        or len(safe_name) > 255
        or any(ord(character) < 32 for character in safe_name)
        or safe_name.lower().startswith(_INTERNAL_UPLOAD_PREFIX)
    ):
        raise MaterialUploadError("invalid local material filename")
    _material_kind(safe_name)
    return safe_name


def _validate_image(file_path: str, extension: str) -> None:
    try:
        # Pillow protects against excessively large pixel dimensions. Treat its
        # warning threshold as an upload error too, rather than only rejecting at
        # the higher DecompressionBombError threshold.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file_path) as image:
                image_format = str(image.format or "").upper()
                if image_format not in _IMAGE_FORMATS_BY_EXTENSION[extension]:
                    raise MaterialUploadError(
                        "uploaded image content does not match its file extension"
                    )
                image.verify()
    except MaterialUploadError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise MaterialUploadError(
            "uploaded file must contain a valid JPEG or PNG image"
        ) from exc


def _validate_video(
    file_path: str, timeout_seconds: int = MATERIAL_VALIDATION_TIMEOUT_SECONDS
) -> None:
    # FFmpeg treats a standalone image as a one-frame video stream. Reject images
    # explicitly so renaming photo.jpg to photo.mp4 cannot bypass the media class.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file_path) as image:
                image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MaterialUploadError(
            "uploaded file must contain a video, not an image"
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        pass
    else:
        raise MaterialUploadError("uploaded file must contain a video, not an image")

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
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MaterialServiceError("FFmpeg material validation timed out") from exc
    except OSError as exc:
        raise MaterialServiceError(
            "failed to run FFmpeg for material validation"
        ) from exc
    if decoded.returncode != 0:
        raise MaterialUploadError(
            "uploaded file must contain a completely decodable video stream"
        )


def _stage_material_upload(
    filename: str, source: BinaryIO
) -> tuple[str, Literal["video", "image"], str, int]:
    safe_name = sanitize_material_filename(filename)
    material_kind = _material_kind(safe_name)
    maximum_bytes = (
        MAX_VIDEO_MATERIAL_UPLOAD_BYTES
        if material_kind == "video"
        else MAX_IMAGE_MATERIAL_UPLOAD_BYTES
    )
    maximum_megabytes = maximum_bytes // (1024 * 1024)

    try:
        target_dir = uploaded_material_dir(create=True)
    except OSError as exc:
        raise MaterialServiceError("failed to prepare local material storage") from exc

    temp_path = ""
    total_bytes = 0
    try:
        try:
            source.seek(0)
        except (AttributeError, OSError) as exc:
            raise MaterialUploadError("local material upload is not seekable") from exc

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
                    raise MaterialUploadError("local material upload must be binary")
                total_bytes += len(chunk)
                if total_bytes > maximum_bytes:
                    raise MaterialUploadError(
                        f"{material_kind} material exceeds the "
                        f"{maximum_megabytes} MB limit"
                    )
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if total_bytes == 0:
            raise MaterialUploadError("local material file is empty")
        return safe_name, material_kind, temp_path, total_bytes
    except Exception as exc:
        _remove_staged_file(temp_path)
        if isinstance(exc, MaterialUploadError):
            raise
        if isinstance(exc, OSError):
            raise MaterialServiceError("failed to stage local material upload") from exc
        raise
    finally:
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass


def save_material_upload(filename: str, source: BinaryIO) -> str:
    """Validate and atomically persist an uploaded local video or image."""
    safe_name, material_kind, temp_path, total_bytes = _stage_material_upload(
        filename, source
    )
    extension = Path(safe_name).suffix.lower()
    stored_name = f"{uuid4().hex}{extension}"
    target_path = os.path.join(os.path.dirname(temp_path), stored_name)

    try:
        if material_kind == "video":
            _validate_video(temp_path)
        else:
            _validate_image(temp_path, extension)

        try:
            os.replace(temp_path, target_path)
        except OSError as exc:
            raise MaterialServiceError(
                "failed to persist local material upload"
            ) from exc
        temp_path = ""
        logger.info(
            f"local material uploaded: original_name={safe_name}, "
            f"stored_name={stored_name}, kind={material_kind}, "
            f"size={total_bytes} bytes"
        )
        return stored_name
    finally:
        _remove_staged_file(temp_path)
