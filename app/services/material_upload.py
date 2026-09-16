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

# Keep these aligned with the local material formats the CLI accepts (cli.py
# derives its list from const.FILE_TYPE_VIDEOS / const.FILE_TYPE_IMAGES) and the
# render pipeline classifies (video.py reads const.FILE_TYPE_IMAGES). Accepting a
# narrower set here rejects uploads the rest of the pipeline already supports.
SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".flv", ".mkv", ".webm")
SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")
SUPPORTED_MATERIAL_EXTENSIONS = (
    *SUPPORTED_VIDEO_EXTENSIONS,
    *SUPPORTED_IMAGE_EXTENSIONS,
)

_COPY_CHUNK_BYTES = 1024 * 1024
_INTERNAL_UPLOAD_PREFIX = ".material-upload-"
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)}
    # 与 bgm.sanitize_upload_filename 及 webui/Main.py 的下载文件名规则保持同一份
    # 官方清单：Win32 把 Latin-1 上标数字 ¹、²、³ 也当作设备编号。
    | {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in ("¹", "²", "³")}
)
# 文件名会原样进入日志、API 响应和 WebUI 界面，因此除路径分隔符与 Win32 保留名外，
# 还要拒绝所有控制符和会改变显示形态的字符。此前只拦截 ord < 32（C0 控制符），
# 漏掉了同一类问题的另一半：
# * C1 控制符 U+007F-U+009F：U+0085 会被部分日志查看器渲染成换行，一个文件名就能
#   伪造出额外的、看起来独立的日志行。
# * 双向文本控制符 U+200E/U+200F/U+202A-U+202E/U+2066-U+2069：U+202E 之后的字符会被
#   反向渲染，"photo\u202egnp.mp4" 在资源管理器和日志里看起来像另一个扩展名。
# * U+2028/U+2029（Unicode 行/段分隔符）同样能在一行日志里制造视觉换行。
# 这些字符都无法在文件名输入框里键入，正常上传不受影响；判定与
# bgm.sanitize_upload_filename、app/controllers/base.py 的 normalize_task_id 一致。
_UNSAFE_FILENAME_CHARACTERS = frozenset(
    chr(code)
    for code in (
        *range(0x00, 0x20),
        *range(0x7F, 0xA0),
        0x200E,
        0x200F,
        0x2028,
        0x2029,
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
    )
)
_IMAGE_FORMATS_BY_EXTENSION = {
    ".jpg": frozenset({"JPEG"}),
    ".jpeg": frozenset({"JPEG"}),
    ".png": frozenset({"PNG"}),
    ".bmp": frozenset({"BMP"}),
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
        or any(character in _UNSAFE_FILENAME_CHARACTERS for character in safe_name)
        or any(character in _WINDOWS_INVALID_FILENAME_CHARS for character in safe_name)
        or safe_name.lower().startswith(_INTERNAL_UPLOAD_PREFIX)
    ):
        raise MaterialUploadError("invalid local material filename")

    # Keep the same rule as bgm.sanitize_upload_filename: Windows resolves the
    # segment before the extension as a device name, so CON.mp4 and LPT1.webm
    # cannot be created as ordinary files there. Even though the stored name is
    # a UUID in both endpoints, rejecting these names up front keeps the two
    # upload APIs behaving identically on every platform.
    windows_basename = safe_name.split(".", 1)[0].rstrip(" .").upper()
    if windows_basename in _WINDOWS_RESERVED_FILENAMES:
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
            "uploaded file must contain a valid JPEG, PNG, or BMP image"
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
