import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from loguru import logger

from app.utils import file_security, utils


# Streamlit 은 기본적으로 큰 업로드 파일을 허용하지만, 배경음악은 보통 몇 MB 에 불과하다.
# 여기서 서버 상한을 명시해, API 나 WebUI 가 아주 큰 파일을 통째로 디스크에 써서 같은
# 프로세스의 영상 작업에 영향을 주는 일을 막는다.
MAX_BGM_UPLOAD_BYTES = 30 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_INTERNAL_UPLOAD_PREFIX = ".bgm-upload-"
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
# MoviePy 는 결국 FFmpeg 로 배경음악을 디코딩하므로 굳이 MP3 로 제한할 필요는 없다.
# 여기서는 널리 쓰이고 의미가 분명한 오디오 확장자만 열어 둬, MP4 같은 영상 컨테이너가
# 배경음악으로 업로드되는 것을 막는다. 이 튜플은 WebUI 업로드 위젯의 단일 데이터 소스이기도
# 해서, 나중에 형식을 추가하거나 뺄 때 앞뒤가 어긋나지 않는다.
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
    """업로드 파일이 배경음악의 보안 또는 형식 요구를 만족하지 못했음을 나타낸다."""


class BgmServiceError(RuntimeError):
    """FFmpeg 나 파일 시스템을 쓸 수 없는 등 서버 실행 장애를 나타낸다."""


def should_use_bgm(bgm_type: str | None, bgm_volume: float | None) -> bool:
    """
    현재 작업이 배경음악을 다뤄야 하는지 한곳에서 판정한다.

    이 규칙은 구체적인 소스와 무관하다. 소스를 고르지 않았거나 음량이 유효하지 않거나
    음량이 0 이하이면, 무작위·사용자 지정·Sonilo 는 물론 앞으로 추가될 제공자도 모두 파일
    해석, 외부 생성, 최종 믹싱을 건너뛰어야 한다. 공용 BGM 서비스에 두면 제공자를 추가할
    때마다 0 음량 판정을 복제하지 않아도 된다.
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
    사용자 배경음악의 영속 디렉터리를 반환한다.

    내장 음원은 코드 자원이므로 resource/songs 에 그대로 둔다. 사용자가 올린 내용은 런타임
    데이터이므로 Docker 가 마운트한 storage 아래에 둬야 컨테이너를 다시 만들어도 남고,
    Git 작업 트리도 더럽히지 않는다.
    """
    return utils.storage_dir("bgm", create=create)


def _remove_staged_file(file_path: str) -> None:
    """업로드 임시 파일을 최대한 정리하되, 호출자가 처리 중인 원래 예외를 덮지 않는다."""
    if not file_path or not os.path.exists(file_path):
        return
    try:
        os.remove(file_path)
    except OSError as exc:
        # 임시 파일은 예약된 접두사를 써서 BGM 목록에 들어가지 않는다. 정리 실패가 '오디오가
        # 잘못됨' 같은 더 정확한 원래 예외를 덮어서는 안 되지만, 운영자가 원인을 짚을 수 있게
        # 경로와 시스템 오류는 남겨야 한다.
        logger.warning(
            f"failed to remove staged background music: path={file_path}, "
            f"error={str(exc)}"
        )


def sanitize_upload_filename(filename: str) -> str:
    """플랫폼에 상관없이 표시 가능한 오디오 파일명을 뽑아내고, 잘못된 이름과 지원하지 않는 확장자를 거부한다."""
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

    # Windows 는 확장자 앞 첫 부분을 장치 이름으로 인식한다. 예를 들어 CON.mp3, LPT1.wav 는
    # 일반 파일로 만들 수 없다. 서버가 최종적으로 UUID 를 쓰더라도 이런 이름을 미리 거부하면
    # API 의 입력 동작이 플랫폼마다 달라지지 않는다.
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
    프로젝트에 현재 설정된 FFmpeg 만으로 파일에 완전히 디코딩 가능한 오디오 스트림이 있는지 검증한다.

    이 프로젝트는 imageio-ffmpeg 가 제공하는 포터블 FFmpeg 를 허용하는데, 이 설치 방식은
    FFprobe 가 함께 있다는 것을 보장하지 않으므로 별도 바이너리 의존성을 새로 추가할 수 없다.
    `-map 0:a:0` 은 오디오 스트림이 없으면 실패하고, `-xerror` 는 디코딩 오류를 실패로 올린다.
    완전히 디코딩하면 암호화된 파일이나 무작위 데이터가 우연히 오디오 프레임 헤더와 맞아떨어져
    생기는 오판도 걸러 낸다. 파일에 앨범 아트 같은 부가 스트림이 있어도 되지만, 검증은 첫 번째
    오디오 스트림만 한다.
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
    디스크의 오디오 파일이 프로젝트 FFmpeg 로 완전히 디코딩되는지 검증한다.

    업로드 사전 검사는 보통 30 초면 되지만, Sonilo 가 만든 배경음악은 최대 6 분에 이를 수
    있다. 그래서 타임아웃을 조절할 수 있는 재사용 진입점을 밖으로 제공한다. 이 서비스는
    FFmpeg 에만 의존하며 시스템에 FFprobe 를 따로 설치하도록 요구하지 않는다.
    """
    if not os.path.isfile(file_path) or os.path.getsize(file_path) <= 0:
        raise BgmUploadError("background music file is empty or missing")
    _validate_audio(file_path, timeout_seconds=timeout_seconds)


def _stage_bgm_upload(filename: str, source: BinaryIO) -> tuple[str, str, int]:
    """
    업로드 스트림을 같은 디렉터리의 임시 파일에 쓰고, 안전한 파일명·임시 경로·바이트 수를 반환한다.

    WebUI 의 업로드 사전 검사와 최종 영속화는 청크 읽기, 크기 제한, 파일명 규칙을 완전히
    동일하게 써야 한다. 그러지 않으면 화면에는 사용 가능하다고 나오는데 생성을 누르면 서버가
    거부하는 상태 분열이 생길 수 있다. 임시 파일은 호출자가 오디오 탐지를 마친 뒤 삭제하거나
    원자적으로 교체한다.
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

        # 원본 확장자를 남겨 두면 컨테이너 헤더가 없는 AAC 같은 형식에서 FFmpeg 가 올바른
        # demuxer 를 고를 수 있다. 임시 파일은 여전히 대상 디렉터리에 둬서 마지막 os.replace 가
        # 원자적으로 동작하게 한다.
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
        # Streamlit 은 같은 UploadedFile 로 브라우저 미리듣기도 해야 한다. 파일 포인터를
        # 되돌려 놓으면 검증 후 플레이어나 최종 저장이 빈 내용을 읽는 일을 막을 수 있다.
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass


def validate_bgm_upload(filename: str, source: BinaryIO) -> str:
    """업로드 오디오를 완전히 검증하되 영속화하지는 않는다. WebUI 가 '준비 완료' 를 표시하기 전 사전 검사용이다."""
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
    사용자 배경음악을 청크 단위, 크기 제한, 원자적 교체 방식으로 저장한다.

    사용 상황에는 FastAPI 의 UploadFile 과 Streamlit 의 UploadedFile 이 있으며, 둘 다 바이너리
    파일 인터페이스를 제공한다. 같은 디렉터리의 임시 파일에 먼저 쓰고 검증한 뒤 os.replace 로
    원자적으로 저장하면, 동시 업로드나 프로세스 중단으로 반쯤 쓰인 오디오 파일이 남는 것을
    막을 수 있다. 또한 같은 이름으로 올려도 서로 다른 UUID 저장 키를 받게 되어, 대기 중이거나
    실행 중인 작업은 항상 원래의 변경되지 않는 파일을 참조한다.
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
    """사용자가 올린 배경음악과 내장 배경음악을 함께 나열한다."""
    files_by_name: dict[str, str] = {}
    for directory in (utils.song_dir(), uploaded_bgm_dir(create=True)):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory), key=str.lower):
            # 업로드 사전 검사와 최종 저장 모두 같은 디렉터리에 파일을 잠깐 만든다. 임시 파일은
            # 올바른 오디오 확장자를 갖고 있지만 아직 검증이 끝나지 않았으므로, 무작위 BGM
            # 목록에 미리 뽑혀서는 안 된다.
            if name.startswith(_INTERNAL_UPLOAD_PREFIX):
                continue
            if Path(name).suffix.lower() not in SUPPORTED_BGM_EXTENSIONS:
                continue
            file_path = os.path.join(directory, name)
            try:
                # 열거 결과도 실제 경로를 검증해야 한다. 그러지 않으면 공격자가 허용 디렉터리에
                # 외부 파일을 가리키는 오디오 심볼릭 링크를 두고, 무작위 BGM 경로를 통해
                # MoviePy 에 넘길 수 있다.
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
    사용자 업로드 디렉터리와 내장 음원 디렉터리에서 BGM 을 해석하고, 두 화이트리스트 밖의 경로는 거부한다.

    파일명은 사용자 디렉터리를 먼저 맞춰 보며, `output000.mp3`, 절대 화이트리스트 경로,
    `./resource/songs/output000.mp3` 같은 예전 사용법도 그대로 지원한다. 새로 올린 파일은
    UUID 를 쓰므로 정상적인 경우 내장 음원이나 예전 업로드와 이름이 겹치지 않는다.
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
