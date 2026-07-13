import os
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from loguru import logger

from app.utils import file_security, utils


# Streamlit 默认允许较大的上传文件，但背景音乐通常只有几 MB。这里设置明确的
# 服务端上限，避免 API 或 WebUI 把超大文件完整写入磁盘，影响同一进程中的视频任务。
MAX_BGM_UPLOAD_BYTES = 30 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_INTERNAL_UPLOAD_PREFIX = ".bgm-upload-"
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
# MoviePy 最终通过 FFmpeg 解码背景音乐，因此不需要人为限制为 MP3。这里仅开放
# 主流且语义明确的音频扩展名，避免把 MP4 等带视频容器误当作背景音乐上传。
# 元组同时作为 WebUI 上传控件的单一数据源，后续增删格式时不会出现前后端不一致。
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
    """表示上传文件不满足背景音乐的安全或格式要求。"""


class BgmServiceError(RuntimeError):
    """表示 FFmpeg 或文件系统不可用等服务端执行故障。"""


def uploaded_bgm_dir(create: bool = True) -> str:
    """
    返回用户背景音乐的持久化目录。

    内置歌曲属于代码资源，继续放在 resource/songs；用户上传内容属于运行时数据，
    必须放在 Docker 已挂载的 storage 下，容器重建后才能保留，也不会污染 Git 工作区。
    """
    return utils.storage_dir("bgm", create=create)


def _remove_staged_file(file_path: str) -> None:
    """尽力清理上传临时文件，且不覆盖调用方正在处理的原始异常。"""
    if not file_path or not os.path.exists(file_path):
        return
    try:
        os.remove(file_path)
    except OSError as exc:
        # 临时文件使用保留前缀，不会进入 BGM 列表；清理失败不应把“音频非法”
        # 等更准确的原始异常覆盖掉，但必须留下路径和系统错误供运维定位。
        logger.warning(
            f"failed to remove staged background music: path={file_path}, "
            f"error={str(exc)}"
        )


def sanitize_upload_filename(filename: str) -> str:
    """提取可跨平台展示的音频文件名，并拒绝非法名称与不支持的扩展名。"""
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

    # Windows 会把扩展名前的首段识别为设备名，例如 CON.mp3、LPT1.wav 都
    # 不能作为普通文件创建。即使服务端最终使用 UUID，提前拒绝这类名称也能
    # 保证 API 在不同平台上的输入行为一致。
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


def _validate_audio(file_path: str) -> None:
    """
    仅使用项目当前配置的 FFmpeg 验证文件包含可完整解码的音频流。

    项目允许 imageio-ffmpeg 提供便携 FFmpeg，该安装方式不保证同时存在
    FFprobe，因此不能新增独立二进制依赖。`-map 0:a:0` 会在没有音频流时失败，
    `-xerror` 会把解码错误提升为失败；完整解码还能拦截加密文件或随机数据偶然
    命中音频帧头的误判。文件可以包含专辑封面等附加流，但只校验第一条音频流。
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
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BgmServiceError("FFmpeg background music validation timed out") from exc
    except OSError as exc:
        raise BgmServiceError("failed to run FFmpeg for background music validation") from exc
    if decoded.returncode != 0:
        raise BgmUploadError("uploaded file must contain a decodable audio stream")


def _stage_bgm_upload(filename: str, source: BinaryIO) -> tuple[str, str, int]:
    """
    将上传流写入同目录临时文件，并返回安全文件名、临时路径和字节数。

    WebUI 的上传预检和最终持久化必须使用完全相同的分块读取、大小限制与文件名
    规则，否则可能出现界面显示可用、点击生成后却被服务端拒绝的状态分裂。
    临时文件由调用方在完成音频探测后删除或原子替换。
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

        # 保留原始扩展名便于 FFmpeg 针对无容器头的 AAC 等格式选择正确的
        # demuxer；临时文件仍放在目标目录，以保证最终 os.replace 是原子操作。
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
        # Streamlit 还需要使用同一个 UploadedFile 做浏览器试听；恢复文件指针可
        # 避免校验后播放器或最终保存读取到空内容。
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass


def validate_bgm_upload(filename: str, source: BinaryIO) -> str:
    """完整校验上传音频但不持久化，用于 WebUI 在显示“已就绪”前预检。"""
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
    以分块、限量和原子替换的方式保存用户背景音乐。

    使用场景包括 FastAPI UploadFile 和 Streamlit UploadedFile，两者都提供二进制
    文件接口。先写同目录临时文件并验证，再通过 os.replace 原子落盘，既能避免
    并发上传或进程中断留下半个音频文件，也会让同名上传获得不同的 UUID 存储键，
    已排队或运行中的任务因此始终引用原来的不可变文件。
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
    """列出用户上传和内置的可用背景音乐。"""
    files_by_name: dict[str, str] = {}
    for directory in (utils.song_dir(), uploaded_bgm_dir(create=True)):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory), key=str.lower):
            # 上传预检和最终保存都会短暂创建同目录文件。临时文件虽然带有合法
            # 音频扩展名，但尚未完成校验，不能被随机 BGM 列表提前选中。
            if name.startswith(_INTERNAL_UPLOAD_PREFIX):
                continue
            if Path(name).suffix.lower() not in SUPPORTED_BGM_EXTENSIONS:
                continue
            file_path = os.path.join(directory, name)
            try:
                # 枚举结果同样需要真实路径校验。否则攻击者可在允许目录中放置
                # 指向外部文件的音频符号链接，再借随机 BGM 路径交给 MoviePy。
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
    在用户上传目录和内置歌曲目录中解析 BGM，并拒绝两个白名单之外的路径。

    文件名优先命中用户目录，同时保留 `output000.mp3`、绝对白名单路径和
    `./resource/songs/output000.mp3` 等旧用法。新上传文件使用 UUID，正常情况下
    不会与内置歌曲或历史上传发生重名。
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
