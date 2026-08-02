import math
import os
import re
import socket
import threading
import time
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from functools import partial
from os import path
from uuid import uuid4

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import bgm as bgm_service
from app.services import (
    elevenlabs_music,
    llm,
    material,
    sonilo,
    subtitle,
    task_artifacts,
    twelvelabs,
    video,
    voice,
)
from app.services import upload_post
from app.services import state as sm
from app.utils import file_security, utils


# 업로드 요청은 최대 몇 분까지 기다릴 수 있으므로, 영상 생성 작업의 동시 실행 자리를 계속
# 점유해서는 안 된다. 고정 크기 스레드 풀로 업로드 처리량을 통제 가능한 범위로 묶으면서,
# 영상 산출물이 만들어지면 바로 완료 상태로 넘어가게 한다.
_cross_post_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="mpt-cross-post",
)
_cross_post_max_pending_tasks = max(
    1,
    int(config.app.get("upload_post_max_pending_tasks", 10)),
)
_cross_post_slots = threading.BoundedSemaphore(_cross_post_max_pending_tasks)
_cross_post_registry_lock = threading.RLock()
_cross_post_futures: dict[str, Future] = {}
_cross_post_process_owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
_ACTIVE_CROSS_POST_STATES = {
    const.CROSS_POST_STATE_PENDING,
    const.CROSS_POST_STATE_PROCESSING,
}
_CROSS_POST_STATE_WRITE_ATTEMPTS = 3
_CROSS_POST_STATE_RETRY_DELAY_SECONDS = 0.1
_INTERRUPTED_CROSS_POST_ERROR = (
    "cross-posting was interrupted before the process completed"
)
# 영상 배경음악 서비스는 ``is_enabled`` 와 ``generate_bgm`` 만 구현하면 된다. 제공자 간
# 차이는 파일 확장자, 도메인 예외, WebUI 경고 코드에 모여 있다. 작업 조율, 0 음량 단축
# 처리, 실패 시 기능 저하는 모두 같은 경로를 재사용하므로, 나중에 제공자를 추가할 때
# 비슷한 흐름을 여러 벌 관리하지 않아도 된다.
_VIDEO_MUSIC_PROVIDERS = {
    "sonilo": {
        "service": sonilo,
        "error_type": sonilo.SoniloError,
        "suffix": ".m4a",
        "warning_code": "sonilo_bgm_failed",
        "display_name": "Sonilo",
    },
    "elevenlabs": {
        "service": elevenlabs_music,
        "error_type": elevenlabs_music.ElevenLabsMusicError,
        "suffix": ".mp3",
        "warning_code": "elevenlabs_bgm_failed",
        "display_name": "ElevenLabs",
    },
}


def _get_video_music_prompt(params: VideoParams) -> str:
    """
    현재 영상 배경음악 제공자가 실제로 쓰는 프롬프트를 읽는다.

    새 작업은 제공자와 무관한 필드를 쓴다. 예전 Sonilo CLI 파라미터와 지난 작업에는
    ``sonilo_bgm_prompt`` 만 있을 수 있으므로, Sonilo 의 공용 필드가 비어 있을 때만 예전
    필드를 읽는다.
    """
    prompt = str(params.video_music_prompt or "").strip()
    if params.bgm_type == "sonilo" and not prompt:
        prompt = str(params.sonilo_bgm_prompt or "").strip()
    return prompt


def is_task_busy(task: dict | None) -> bool:
    """작업이 아직 생성 중이거나 업로드 중인지 판정한다. 모든 삭제 진입점이 재사용한다."""
    if not task:
        return False

    state = task.get("state")
    try:
        state = int(state)
    except (TypeError, ValueError):
        pass

    # 영상 생성과 플랫폼 업로드 모두 작업 디렉터리를 계속 읽을 수 있다. 둘 다 사용 중으로
    # 보면, API 와 WebUI 가 규칙을 따로 관리하다가 한쪽은 삭제를 허용하고 다른 쪽은 막는
    # 불일치가 생기는 것을 피할 수 있다.
    return (
        state == const.TASK_STATE_PROCESSING
        or task.get("cross_post_state") in _ACTIVE_CROSS_POST_STATES
    )


def _register_cross_post_future(task_id: str, future: Future) -> None:
    """현재 프로세스가 들고 있는 업로드 Future 를 등록한다. 시작 시 복구와 테스트가 실제 실행 상태를 판정하는 데 쓴다."""
    with _cross_post_registry_lock:
        _cross_post_futures[task_id] = future


def _unregister_cross_post_future(task_id: str, future: Future | None = None) -> None:
    """일치하는 Future 만 제거한다. 예전 콜백이 같은 작업에 나중에 등록된 새 작업을 잘못 지우지 않게 하기 위해서다."""
    with _cross_post_registry_lock:
        current = _cross_post_futures.get(task_id)
        if current is None or (future is not None and current is not future):
            return
        _cross_post_futures.pop(task_id, None)


def _is_cross_post_active_in_process(task_id: str) -> bool:
    """현재 프로세스가 아직 끝나지 않은 업로드 작업을 들고 있는지 판정한다."""
    with _cross_post_registry_lock:
        future = _cross_post_futures.get(task_id)
        return future is not None and not future.done()


def _is_windows_process_alive(process_id: int) -> bool:
    """읽기 전용 Win32 API 로 프로세스 상태를 판정한다. os.kill 로 프로세스를 잘못 종료하지 않기 위해서다."""
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # ctypes 는 선언하지 않은 반환값을 기본적으로 32 비트 int 로 본다. Windows 의 64 비트
    # 프로세스 핸들이 이 때문에 잘릴 수 있으므로, Win32 함수 시그니처를 명시적으로 선언한
    # 뒤에 호출해야 한다.
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == error_invalid_parameter:
            return False
        if error_code == error_access_denied:
            # 프로세스는 있는데 현재 사용자에게 조회 권한이 없다면, 보수적으로 살아 있다고
            # 봐야 한다. 다른 계정이 실행 중인 업로드 작업을 잘못 회수하지 않기 위해서다.
            return True
        logger.warning(
            "failed to open cross-post owner process on Windows, "
            f"process_id: {process_id}, error_code: {error_code}"
        )
        return True

    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            error_code = ctypes.get_last_error()
            logger.warning(
                "failed to read cross-post owner process state on Windows, "
                f"process_id: {process_id}, error_code: {error_code}"
            )
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _is_cross_post_owner_alive(owner: str | None) -> bool:
    """영속화된 업로드 작업의 로컬 프로세스가 아직 존재하는지 판정한다."""
    if not owner:
        return False

    try:
        hostname, process_id_text, _ = owner.split(":", 2)
        process_id = int(process_id_text)
    except (TypeError, ValueError):
        logger.warning(f"invalid cross-post owner metadata: {owner}")
        return False

    # 다른 호스트의 프로세스는 신뢰할 수 있게 탐지할 수 없다. Redis 를 공유하는 다중 호스트
    # 배포에서는 보수적으로 아직 실행 중이라고 봐야, 현재 노드가 다른 노드에서 읽고 있는
    # 영상 파일을 잘못 지우지 않는다.
    if hostname != socket.gethostname():
        return True

    # 현재 프로세스 안에 실제 업로드 작업이 남아 있는지는 Future 레지스트리가 이미 정확히
    # 판정한다. 여기까지 왔다는 것은 레지스트리에 해당 Future 가 없다는 뜻이므로, owner 가
    # 현재 프로세스와 완전히 같더라도 중단된 것으로 봐야 한다. 이렇게 하면 최종 상태 쓰기가
    # 계속 실패하고 Future 는 이미 끝난 상황도 덮을 수 있다.
    if process_id == os.getpid():
        return False

    # Windows 의 os.kill(pid, 0) 은 POSIX 와 의미가 달라 대상 프로세스를 곧바로 종료할 수 있다.
    # 조회 권한만 요청하는 Win32 API 를 써서 대상 프로세스에 어떤 시그널도 보내지 않는다.
    if os.name == "nt":
        return _is_windows_process_alive(process_id)

    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        logger.warning(
            f"failed to inspect cross-post owner process, owner: {owner}, error: {exc}"
        )
        return True
    return True


def _mark_task_failed(task_id: str, stage: str, error: str) -> dict:
    """구조화된 실패 정보를 기록하고, 작업이 실패하기 전까지 도달한 진행률을 보존한다."""
    existing_task = None
    try:
        existing_task = sm.state.get_task(task_id)
    except Exception as exc:
        logger.warning(f"failed to read task state before failure update: {exc}")

    # 개별 서비스 함수가 조율 계층보다 정확한 오류 원인을 갖고 있는 경우가 많다. 이후의 빈
    # 결과 검사가 이를 일반적인 문구로 덮어써서는 안 된다. 그러면 API 호출자는 여전히
    # 모호한 정보만 보게 된다.
    if (
        existing_task
        and existing_task.get("state") == const.TASK_STATE_FAILED
        and existing_task.get("error")
    ):
        return existing_task

    message = str(error or "unknown task error").strip()
    progress = int((existing_task or {}).get("progress", 0) or 0)
    logger.error(
        f"task failed, task_id: {task_id}, stage: {stage}, error: {message}"
    )
    failure = {
        "task_id": task_id,
        "state": const.TASK_STATE_FAILED,
        "progress": progress,
        "failed_stage": stage,
        "error": message,
    }
    sm.state.update_task(
        task_id,
        state=failure["state"],
        progress=failure["progress"],
        failed_stage=failure["failed_stage"],
        error=failure["error"],
    )
    return failure


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    # 알 수 없는 이름은 기본 스타일로 대체된다. 요청값을 그대로 두면 매니페스트에
    # 쓰이지 않은 스타일이 기록돼, 나중에 같은 작업을 되살렸을 때 결과가 달라진다.
    params.script_style = llm.resolve_script_style(params.script_style)

    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
            video_script_prompt=params.video_script_prompt,
            custom_system_prompt=params.custom_system_prompt,
            script_style=params.script_style,
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        _mark_task_failed(task_id, "script", "failed to generate video script")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        # 소재를 대본 순서에 맞추도록 켰다면, 키워드 자체도 대본 서술 순서대로 생성해야 한다.
        # 그러지 않으면 이후에 순서대로 내려받고 순서대로 이어붙여도 결국 하나의 전역 주제어
        # 묶음을 재사용할 뿐이라, '뒤쪽 내용의 화면이 먼저 나오는' 문제를 개선하지 못한다.
        video_terms = llm.generate_terms(
            video_subject=params.video_subject,
            video_script=video_script,
            amount=8 if params.match_materials_to_script else 5,
            match_script_order=params.match_materials_to_script,
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        _mark_task_failed(
            task_id,
            "terms",
            "failed to generate video search terms",
        )
        return None

    # 선택적인 TwelveLabs Marengo 의미 기반 재정렬. 켜져 있지 않으면 원래 순서를 그대로
    # 반환하며 아무 부작용도 없다. 순서 매칭 모드에서는 키워드 순서 자체가 대본 서술
    # 순서이므로 그대로 유지해야 해서 건너뛴다.
    if not params.match_materials_to_script:
        video_terms = twelvelabs.rerank_terms_by_subject(
            video_subject=params.video_subject,
            search_terms=video_terms,
        )

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }
    task_artifacts.write_script_data(task_id, script_data)


def resolve_custom_audio_file(task_id: str, custom_audio_file: str | None) -> str:
    requested_file = (custom_audio_file or "").strip()
    if not requested_file:
        return ""

    task_dir = utils.task_dir(task_id)
    try:
        return file_security.resolve_path_within_directory(
            task_dir,
            requested_file,
        )
    except ValueError as exc:
        task_dir_error = exc

    server_audio_file = path.realpath(
        requested_file
        if path.isabs(requested_file)
        else path.join(utils.root_dir(), requested_file)
    )
    if not path.isabs(requested_file):
        project_root = path.realpath(utils.root_dir())
        try:
            if path.commonpath([project_root, server_audio_file]) != project_root:
                raise ValueError(
                    "relative custom audio paths must stay within the project directory"
                )
        except ValueError as exc:
            raise ValueError(
                "custom audio file must be task-local or an existing server-side file"
            ) from exc

    if not path.isfile(server_audio_file):
        raise ValueError(
            "custom audio file does not exist or is not a file"
        ) from task_dir_error

    return server_audio_file


def _resolve_reusable_voice_preview(
    task_id: str,
    params,
    video_script: str,
    voice_preview: dict | None,
) -> tuple[str, float, object] | None:
    """
    WebUI 가 제출한 전체 미리듣기 캐시를 검증하고 해석한다.

    이 페이로드는 공개 API 파라미터가 아니라 현재 프로세스의 WebUI 에서만 온다. 그렇더라도
    백그라운드 작업은 대본과 모든 나레이션 파라미터를 다시 대조하고, 오디오가 현재 작업
    디렉터리 안에 있도록 제한한다. 하나라도 어긋나면 일반 TTS 로 되돌려, 오래된 미리듣기가
    정식 결과물을 오염시키지 않게 한다.
    """
    if not voice_preview:
        return None

    expected_values = {
        "script": str(video_script or "").strip(),
        "voice_name": params.voice_name,
        "voice_rate": float(params.voice_rate),
        "voice_volume": float(params.voice_volume),
    }
    if not math.isclose(float(params.voice_volume), 1.0) or any(
        voice_preview.get(key) != value for key, value in expected_values.items()
    ):
        logger.info(
            f"skip stale voice preview cache, task_id: {task_id}, "
            "reason: voice parameters changed"
        )
        return None

    preview_file = path.realpath(str(voice_preview.get("audio_file") or ""))
    task_root = path.realpath(utils.task_dir(task_id))
    try:
        preview_is_task_local = path.commonpath([task_root, preview_file]) == task_root
    except ValueError:
        preview_is_task_local = False

    duration = voice_preview.get("duration")
    sub_maker = voice_preview.get("sub_maker")
    if (
        not preview_is_task_local
        or not path.isfile(preview_file)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
        or sub_maker is None
    ):
        logger.warning(
            f"skip invalid voice preview cache, task_id: {task_id}, "
            f"audio_file: {preview_file or '<empty>'}"
        )
        return None

    logger.info(
        f"using full voice preview audio, task_id: {task_id}, duration: {duration:.2f}s"
    )
    return preview_file, math.ceil(duration), sub_maker


def generate_audio(task_id, params, video_script, voice_preview=None):
    """
    Generate audio for the video script.
    If a custom audio file is provided, it will be used directly.
    There will be no subtitle maker object returned in this case.
    Otherwise, TTS will be used to generate the audio.
    Returns:
        - audio_file: path to the generated or provided audio file
        - audio_duration: duration of the audio in seconds
        - sub_maker: subtitle maker object if TTS is used, None otherwise
    """
    logger.info("\n\n## generating audio")
    # /audio 와 /subtitle 요청 모델에는 custom_audio_file 이 없다. 여기서 호환되게 읽어,
    # 엔드포인트를 직접 호출할 때 속성 오류가 나지 않게 한다.
    requested_custom_audio_file = getattr(params, "custom_audio_file", None)
    try:
        custom_audio_file = resolve_custom_audio_file(
            task_id, requested_custom_audio_file
        )
    except ValueError as exc:
        _mark_task_failed(
            task_id,
            "audio",
            f"invalid custom audio file: {exc}",
        )
        return None, None, None

    if not custom_audio_file:
        reusable_preview = _resolve_reusable_voice_preview(
            task_id,
            params,
            video_script,
            voice_preview,
        )
        if reusable_preview:
            return reusable_preview

        logger.info("no custom audio file provided, using TTS to generate audio.")
        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")
        sub_maker = voice.tts(
            text=video_script,
            voice_name=voice.parse_voice_name(params.voice_name),
            voice_rate=params.voice_rate,
            voice_file=audio_file,
        )
        if sub_maker is None:
            _mark_task_failed(
                task_id,
                "audio",
                "failed to synthesize audio; verify the selected voice and TTS connectivity",
            )
            return None, None, None
        audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
        if audio_duration == 0:
            _mark_task_failed(task_id, "audio", "generated audio duration is zero")
            return None, None, None
        return audio_file, audio_duration, sub_maker
    else:
        logger.info(f"using custom audio file: {custom_audio_file}")
        audio_duration = voice.get_audio_duration(custom_audio_file)
        if audio_duration == 0:
            _mark_task_failed(
                task_id,
                "audio",
                "custom audio duration is zero",
            )
            return None, None, None
        return custom_audio_file, audio_duration, None

def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    '''
    Generate subtitle for the video script.
    If subtitle generation is disabled or no subtitle maker is provided, it will return an empty string.
    Otherwise, it will generate the subtitle using the specified provider.
    Returns:
        - subtitle_path: path to the generated subtitle file
    '''
    logger.info("\n\n## generating subtitle")
    if not params.subtitle_enabled:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    if not subtitle_provider:
        logger.info("subtitle provider is empty, skip subtitle generation")
        return ""

    if sub_maker is None and subtitle_provider != "whisper":
        # 사용자 오디오는 TTS 를 거치지 않으므로 Edge/Azure 같은 TTS 가 돌려주는 sub_maker
        # 타임라인이 없다. 오디오 파일에서 바로 자막을 받아쓸 수 있는 것은 Whisper 뿐이다.
        # 다른 자막 제공자는 기존 동작을 그대로 유지해, 잘못된 빈 타임라인을 만들지 않게 한다.
        logger.warning(
            "subtitle maker is missing, skip subtitle generation for provider: "
            f"{subtitle_provider}"
        )
        return ""

    if subtitle_provider == "edge":
        voice.create_subtitle(
            text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
        )
        if not os.path.exists(subtitle_path):
            # Edge 자막은 타임라인과 대본이 맞지 않아 파일을 만들지 못하는 경우가 가끔 있다.
            # 여기서 Whisper 로 자동 전환해서는 안 된다. 그러면 첫 실패에서 사용자가 모르는
            # 사이에 수 GB 짜리 모델을 내려받게 된다. Whisper 를 명시적으로 설정했을 때만
            # 모델 로딩을 허용하고, Edge 가 실패하면 자막 없는 영상을 남기고 원인을 기록해
            # 예상치 못한 네트워크·디스크 비용이 발생하지 않게 한다.
            logger.warning(
                "edge subtitle generation did not produce a subtitle file; "
                "skip subtitles without falling back to whisper"
            )
            return ""

    if subtitle_provider == "whisper":
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script)

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            _mark_task_failed(
                task_id,
                "materials",
                "no valid local video materials were found",
            )
            return None
        return [material_info.url for material_info in materials]
    else:
        logger.info(f"\n\n## downloading videos from {params.video_source}")
        # 순서 매칭 모드는 사용자가 명시적으로 켰을 때만 동작한다. 여기서는 소재 다운로드가
        # 키워드 순서대로 번갈아 진행되도록 강제해, 앞쪽 키워드 하나가 소재를 너무 많이
        # 가져가 뒤쪽 대본 주제를 최종 타임라인에서 밀어내는 것을 막는다.
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_concat_mode=(
                VideoConcatMode.sequential
                if params.match_materials_to_script
                else params.video_concat_mode
            ),
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
            match_script_order=params.match_materials_to_script,
        )
        if not downloaded_videos:
            _mark_task_failed(
                task_id,
                "materials",
                f"failed to download video materials from {params.video_source}",
            )
            return None
        return downloaded_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path, audio_duration
):
    final_video_paths = []
    combined_video_paths = []
    warnings = []
    video_music_provider = _VIDEO_MUSIC_PROVIDERS.get(params.bgm_type)
    video_music_requested = (
        video_music_provider is not None
        and bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)
    )
    # 여러 영상을 생성할 때는 차이를 주려고 기본적으로 소재를 섞는다. 하지만 '소재를 대본
    # 순서에 맞추기' 가 노리는 것은 타임라인의 안정성과 설명 가능성이므로, 켜져 있으면 모든
    # 출력이 순차 이어붙이기를 쓴다.
    if params.match_materials_to_script:
        video_concat_mode = VideoConcatMode.sequential
    elif params.video_count == 1:
        video_concat_mode = params.video_concat_mode
    else:
        video_concat_mode = VideoConcatMode.random
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
            clip_speed=params.video_clip_speed,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        # 영상 배경음악 모드에서는 기본 BGM 해석을 먼저 명확히 끈다. 예전 작업에 남은
        # bgm_file 이 잘못 쓰이는 것을 막기 위해서다. 음량이 0 보다 클 때만 프록시를 만들고
        # 유료 API 를 호출하며, 0 음량이면 일괄로 건너뛴다.
        bgm_file_override = "" if video_music_provider else None
        if video_music_requested:
            service = video_music_provider["service"]
            display_name = video_music_provider["display_name"]
            warning_code = video_music_provider["warning_code"]
            generated_bgm_path = path.join(
                utils.task_dir(task_id),
                (f"{params.bgm_type}-bgm-{index}{video_music_provider['suffix']}"),
            )
            try:
                service.generate_bgm(
                    video_path=combined_video_path,
                    output_path=generated_bgm_path,
                    video_duration=audio_duration,
                    prompt=_get_video_music_prompt(params),
                )
                bgm_file_override = generated_bgm_path
            except video_music_provider["error_type"] as exc:
                # 영상, 나레이션, 자막이 모두 만들어진 상태라면 외부 배경음악의 일시적 실패로
                # 작업 전체를 버려서는 안 된다. 이번 영상에서는 BGM 을 명확히 끄고, 기능이
                # 낮아졌다는 결과를 WebUI 로 돌려줘 사용자에게 알린다.
                logger.warning(
                    f"{display_name} BGM generation failed: task_id={task_id}, "
                    f"video_index={index}, error={exc}"
                )
                bgm_file_override = ""
                warnings.append({"code": warning_code, "video_index": index})

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        bgm_mix_succeeded = video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
            bgm_file_override=bgm_file_override,
        )
        if (
            video_music_provider is not None
            and bgm_file_override
            and not bgm_mix_succeeded
        ):
            # 외부 서비스가 성공적으로 반환하고 FFmpeg 검증도 통과했더라도, MoviePy 의 최종
            # 믹싱이 실행 환경 때문에 실패할 수 있다. 영상 서비스는 BGM 없는 결과물을 남긴다.
            # API 생성이 실패한 경우에는 override 가 비어 있으므로 경고가 중복되지 않는다.
            warnings.append(
                {
                    "code": video_music_provider["warning_code"],
                    "video_index": index,
                }
            )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths, warnings


def _patch_cross_post_state(task_id: str, **kwargs) -> bool | None:
    """업로드 필드를 안전하게 갱신한다. 상태 백엔드에 일시적 장애가 나면 제한된 횟수만 재시도한다."""
    for attempt in range(1, _CROSS_POST_STATE_WRITE_ATTEMPTS + 1):
        try:
            return sm.state.patch_task(task_id, **kwargs)
        except Exception as exc:
            # Redis 가 잠깐 끊겼다고 작업이 영원히 pending/processing 에 머물러서는 안 된다.
            # 업로드 상태 쓰기는 빈도가 매우 낮으므로, 고정 횟수와 짧은 대기만으로 순간적인
            # 장애를 덮을 수 있고 백그라운드 스레드가 무한정 막히지도 않는다. 마지막 실패는
            # 원인을 짚기 쉽도록 스택 전체를 남긴다.
            if attempt >= _CROSS_POST_STATE_WRITE_ATTEMPTS:
                logger.exception(
                    f"failed to update cross-post state after retries, "
                    f"task_id: {task_id}, fields: {', '.join(kwargs)}, "
                    f"attempts: {attempt}, error: {exc}"
                )
                return None

            logger.warning(
                f"retry cross-post state update, task_id: {task_id}, "
                f"fields: {', '.join(kwargs)}, attempt: {attempt}, error: {exc}"
            )
            time.sleep(_CROSS_POST_STATE_RETRY_DELAY_SECONDS)

    return None


def _record_cross_post_failure(
    task_id: str,
    error: Exception,
    results: list[dict] | None = None,
) -> None:
    """업로드 실패를 최대한 저장한다. 상태 백엔드를 쓸 수 없으면 로그가 진단 정보를 남긴다."""
    updated = _patch_cross_post_state(
        task_id,
        cross_post_state=const.CROSS_POST_STATE_FAILED,
        cross_post_results=results or None,
        cross_post_error=str(error),
        cross_post_owner=None,
    )
    if updated is False:
        logger.warning(f"discard cross-post failure for missing task: {task_id}")


def _ensure_cross_post_terminal_state(task_id: str) -> None:
    """Future 가 끝난 뒤에도 활성 상태로 남은 작업을 실패로 수렴시킨다."""
    try:
        task = sm.state.get_task(task_id)
    except Exception as exc:
        # 여기는 이미 Future 의 최종 콜백이라, 예외를 처리해 줄 동기 호출자가 뒤에 없다.
        # 상태 백엔드가 복구되면 다음 프로세스 시작 때 복구 로직이 남은 상태를 처리한다.
        logger.exception(
            f"failed to verify final cross-post state, task_id: {task_id}, error: {exc}"
        )
        return

    if not task or task.get("cross_post_state") not in _ACTIVE_CROSS_POST_STATES:
        return

    logger.warning(
        f"cross-post worker ended without terminal state, task_id: {task_id}, "
        f"state: {task.get('cross_post_state')}"
    )
    _record_cross_post_failure(
        task_id,
        RuntimeError("cross-post worker ended without persisting a terminal state"),
        task.get("cross_post_results"),
    )


def recover_interrupted_cross_posts(page_size: int = 100) -> int | None:
    """
    프로세스를 재시작한 뒤 복구할 수 없는 업로드 작업을 실패로 표시한다.

    플랫폼 업로드는 현재 프로세스 안의 스레드 풀을 쓰며 영속 작업 큐가 아니다. 프로세스가
    시작될 때 Redis 에 남아 있던 pending/processing 은 저절로 이어서 실행되지 않는다. 이를
    계속 실행 중으로 취급하면 사용자는 작업을 영영 삭제할 수 없다. 여기서는 상태를 페이지
    단위로 스캔해, 현재 프로세스에 대응 Future 가 없는 활성 기록만 처리하고 이미 생성된
    영상 결과는 그대로 남긴다.
    """
    recovered = 0
    page = 1

    while True:
        try:
            tasks, total = sm.state.get_all_tasks(page, page_size)
        except Exception as exc:
            logger.exception(f"failed to recover interrupted cross-post tasks: {exc}")
            return None

        for task in tasks:
            task_id = str(task.get("task_id") or "")
            if (
                not task_id
                or task.get("cross_post_state") not in _ACTIVE_CROSS_POST_STATES
                or _is_cross_post_active_in_process(task_id)
                or _is_cross_post_owner_alive(task.get("cross_post_owner"))
            ):
                continue

            updated = _patch_cross_post_state(
                task_id,
                cross_post_state=const.CROSS_POST_STATE_FAILED,
                cross_post_error=_INTERRUPTED_CROSS_POST_ERROR,
                cross_post_owner=None,
            )
            if updated is True:
                recovered += 1

        if page * page_size >= total or not tasks:
            break
        page += 1

    if recovered:
        logger.warning(f"recovered interrupted cross-post tasks: {recovered}")
    return recovered


def _run_cross_post(
    task_id: str,
    video_paths: tuple[str, ...],
    video_subject: str,
    video_script: str,
    video_language: str,
    platforms: tuple[str, ...],
    youtube_privacy_status: str,
) -> None:
    """플랫폼 업로드를 백그라운드에서 실행하고, 업로드 관련 작업 필드만 덧붙인다."""
    results = []
    try:
        state_updated = _patch_cross_post_state(
            task_id,
            cross_post_state=const.CROSS_POST_STATE_PROCESSING,
            cross_post_error=None,
            cross_post_owner=_cross_post_process_owner,
        )
        if state_updated is not True:
            # False 는 작업이 삭제됐다는 뜻이고, None 은 상태 백엔드를 잠시 쓸 수 없다는 뜻이다.
            # 두 경우 모두 외부 엔드포인트 호출을 이어 가서는 안 된다. 그러면 사용자가 이번
            # 업로드를 조회하거나 통제할 수 없게 된다.
            if state_updated is False:
                logger.warning(f"skip cross-post for missing task: {task_id}")
            else:
                _record_cross_post_failure(
                    task_id,
                    RuntimeError("failed to persist cross-post processing state"),
                )
            return

        logger.info(
            f"cross-post started, task_id: {task_id}, platforms: {', '.join(platforms)}"
        )
        youtube_extra = None
        if any(platform.startswith("youtube") for platform in platforms):
            metadata = llm.generate_social_metadata(
                video_subject=video_subject,
                video_script=video_script,
                language=video_language or "",
                platform="youtube_shorts",
            )
            youtube_extra = {
                "youtube_title": metadata.get("title", video_subject),
                "youtube_description": metadata.get("caption", ""),
                "tags": metadata.get("hashtags", []),
                "privacyStatus": youtube_privacy_status,
                "containsSyntheticMedia": True,
            }

        for video_path in video_paths:
            result = upload_post.cross_post_video(
                video_path=video_path,
                title=video_subject or "Check out this video! #shorts #viral",
                platforms=list(platforms),
                youtube_extra=youtube_extra,
            )
            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "error": "Upload-Post returned an invalid response",
                }
            results.append(result)

        failures = [result for result in results if not result.get("success")]
        if failures:
            error_messages = [
                str(
                    result.get("error")
                    or result.get("message")
                    or "unknown upload error"
                )
                for result in failures
            ]
            cross_post_state = const.CROSS_POST_STATE_FAILED
            cross_post_error = "; ".join(error_messages)
            logger.warning(
                f"cross-post completed with failures, task_id: {task_id}, "
                f"failed: {len(failures)}, total: {len(results)}"
            )
        else:
            cross_post_state = const.CROSS_POST_STATE_COMPLETE
            cross_post_error = None
            logger.success(
                f"cross-post completed, task_id: {task_id}, videos: {len(results)}"
            )

        state_updated = _patch_cross_post_state(
            task_id,
            cross_post_state=cross_post_state,
            cross_post_results=results,
            cross_post_error=cross_post_error,
            cross_post_owner=None,
        )
        if state_updated is False:
            logger.warning(f"discard cross-post result for missing task: {task_id}")
        elif state_updated is None:
            # 업로드는 끝났는데 결과가 저장되지 않았다면 processing 을 그대로 둬서는 안 된다.
            # 실패 상태 쓰기도 제한된 재시도를 한 번 더 거치므로, 적어도 호출자는 명확한
            # 최종 상태를 받게 된다.
            _record_cross_post_failure(
                task_id,
                RuntimeError("failed to persist final cross-post result"),
                results,
            )
    except Exception as exc:
        # 업로드 실패는 업로드 상태에만 영향을 줘야 하며, 이미 끝난 영상 작업을 거꾸로
        # 덮어써서는 안 된다. 예외 원문을 작업 상태에 기록해, API 호출자가 서버 로그를 보지
        # 않고도 문제를 짚을 수 있게 한다.
        logger.exception(f"cross-post failed, task_id: {task_id}, error: {exc}")
        _record_cross_post_failure(task_id, exc, results)


def _run_cross_post_with_slot(*args) -> None:
    """업로드 작업을 실행하고, 성공·실패·예외 어느 경우에도 큐 용량을 반드시 돌려준다."""
    try:
        _run_cross_post(*args)
    except Exception as exc:
        # _run_cross_post 이 예상되는 예외는 이미 처리한다. 여기는 마지막 보호막으로, 앞으로
        # 추가될 로직이 던지는 예외가 아무도 읽지 않는 Future 안에만 남는 것을 막는다.
        task_id = str(args[0]) if args else "unknown"
        logger.exception(
            f"cross-post worker crashed, task_id: {task_id}, error: {exc}"
        )
        if args:
            _record_cross_post_failure(task_id, exc)
    finally:
        _cross_post_slots.release()


def _finalize_cross_post_future(task_id: str, future: Future) -> None:
    """Future 등록을 정리하고, 취소·예외·상태 쓰기 실패가 모두 수렴하도록 보장한다."""
    _unregister_cross_post_future(task_id, future)

    try:
        error = future.exception()
    except CancelledError:
        logger.warning(f"cross-post future was cancelled, task_id: {task_id}")
        # Future 가 실행되기 전에 취소되면 worker 의 finally 가 돌지 않는다. 따라서 콜백에서
        # 큐 용량을 돌려주고 영속 상태를 실패로 바꿔야 한다.
        _cross_post_slots.release()
        _record_cross_post_failure(
            task_id,
            RuntimeError("cross-post job was cancelled before execution"),
        )
        return
    except Exception as exc:
        logger.exception(
            f"failed to inspect cross-post future, task_id: {task_id}, error: {exc}"
        )
        _ensure_cross_post_terminal_state(task_id)
        return

    if error is not None:
        logger.error(
            f"cross-post future failed, task_id: {task_id}, "
            f"error: {type(error).__name__}: {error}"
        )

    _ensure_cross_post_terminal_state(task_id)


def _schedule_cross_post(
    task_id: str,
    video_paths: list[str],
    params: VideoParams,
    video_script: str,
    platforms: list[str],
    youtube_privacy_status: str,
) -> str | None:
    """백그라운드 업로드 작업을 제출한다. 성공하면 None 을, 스케줄에 실패하면 조회 가능한 오류 원인을 반환한다."""
    if not _cross_post_slots.acquire(blocking=False):
        error = "cross-post queue is full; publishing was skipped"
        logger.warning(
            f"skip cross-post because queue is full, task_id: {task_id}, "
            f"capacity: {_cross_post_max_pending_tasks}"
        )
        _patch_cross_post_state(
            task_id,
            cross_post_state=const.CROSS_POST_STATE_FAILED,
            cross_post_error=error,
            cross_post_owner=None,
        )
        return error

    try:
        future = _cross_post_executor.submit(
            _run_cross_post_with_slot,
            task_id,
            tuple(video_paths),
            params.video_subject or "",
            video_script,
            params.video_language or "",
            tuple(platforms),
            youtube_privacy_status,
        )
        _register_cross_post_future(task_id, future)
        future.add_done_callback(partial(_finalize_cross_post_future, task_id))
    except RuntimeError as exc:
        _unregister_cross_post_future(task_id)
        _cross_post_slots.release()
        logger.exception(
            f"failed to schedule cross-post, task_id: {task_id}, error: {exc}"
        )
        _patch_cross_post_state(
            task_id,
            cross_post_state=const.CROSS_POST_STATE_FAILED,
            cross_post_error=f"failed to schedule cross-post: {exc}",
            cross_post_owner=None,
        )
        return f"failed to schedule cross-post: {exc}"

    return None


def _run_pipeline(
    task_id,
    params: VideoParams,
    stop_at: str = "video",
    voice_preview: dict | None = None,
):
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    # 영상 배경음악 제공자가 필요한 것은 완전한 결과물 생성 흐름뿐이다. 키가 없는 전체 작업은
    # 최대한 일찍 막아 LLM, TTS, 소재 서비스 크레딧을 먼저 소모하지 않게 한다. 중간 산출물
    # 엔드포인트는 여전히 따로 쓸 수 있다.
    video_music_provider = _VIDEO_MUSIC_PROVIDERS.get(params.bgm_type)
    video_music_enabled = (
        stop_at == "video"
        and video_music_provider is not None
        and bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)
    )
    if video_music_enabled:
        service = video_music_provider["service"]
        display_name = video_music_provider["display_name"]
        if not service.is_enabled():
            return _mark_task_failed(
                task_id,
                "preflight",
                f"{display_name} background music requires an API key",
            )

        # WebUI 는 입력 길이를 제한하지만 API, CLI, 지난 작업은 프런트엔드 위젯을 우회할 수
        # 있다. 대본, 나레이션, 소재를 만들기 전에 제공자 상한으로 한 번 더 검증해, 영상을
        # 다 합성한 뒤에야 외부 요청이 거부되는 일을 막는다. 서비스 계층도 같은 검증을
        # 그대로 유지해 직접 호출 시의 마지막 방어선으로 둔다.
        music_prompt = _get_video_music_prompt(params)
        max_prompt_length = int(getattr(service, "MAX_PROMPT_LENGTH", 0) or 0)
        if max_prompt_length and len(music_prompt) > max_prompt_length:
            return _mark_task_failed(
                task_id,
                "preflight",
                (f"{display_name} music prompt exceeds {max_prompt_length} characters"),
            )

        # 제공자는 과금되지 않는 계정 사전 검사를 선택적으로 제공할 수 있다. 검사 함수는
        # 확정적인 오류만 던져야 한다. 네트워크가 흔들리거나 권한 범위를 확인할 수 없을 때는
        # 서비스 계층이 경고를 남기고 실제 생성을 계속한다.
        validate_access = getattr(service, "validate_generation_access", None)
        if callable(validate_access):
            try:
                validate_access()
            except video_music_provider["error_type"] as exc:
                return _mark_task_failed(task_id, "preflight", str(exc))

    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        error = (
            video_script.removeprefix("Error: ").strip()
            if isinstance(video_script, str) and "Error: " in video_script
            else "failed to generate video script"
        )
        return _mark_task_failed(task_id, "script", error)

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate terms
    video_terms = ""
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            return _mark_task_failed(
                task_id,
                "terms",
                "failed to generate video search terms",
            )

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Generate audio
    audio_file, audio_duration, sub_maker = generate_audio(
        task_id,
        params,
        video_script,
        voice_preview=voice_preview,
    )
    if not audio_file:
        return _mark_task_failed(
            task_id,
            "audio",
            "failed to prepare narration audio",
        )

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Generate subtitle
    subtitle_path = generate_subtitle(
        task_id, params, video_script, sub_maker, audio_file
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Get video materials
    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not downloaded_videos:
        return _mark_task_failed(
            task_id,
            "materials",
            "failed to prepare video materials",
        )

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 영상 이어붙이기 모드를 다뤄야 하는 것은 완전한 영상 생성 흐름뿐이다.
    # 이렇게 하면 /subtitle 이나 /audio 같은 요청이 없는 필드에 접근하지 않는다.
    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 6. Generate final videos
    # card 레이아웃은 상단 여백에 얹을 문구가 있어야 의미가 있다. 사용자가 직접 넣지
    # 않았을 때만 생성한다. 대본 첫 문장을 그대로 쓰면 길고 밋밋해서 따로 뽑는다.
    if params.layout == "card":
        if not str(params.headline or "").strip():
            params.headline = llm.generate_headline(
                video_subject=params.video_subject,
                video_script=video_script,
                language=params.video_language,
            )
            # 헤드라인은 주제와 대본에서 나온 문장이라 그 안의 내용이 그대로 딸려온다.
            # 만들어졌는지만 남기고 본문은 로그에 쓰지 않는다.
            logger.info(f"headline generated: {len(params.headline)} characters")

        # 그리는 자리에서 두 줄로 자른다. 여기서 같이 줄여 두지 않으면 영상에는
        # 잘린 문구가, 기록에는 원본이 남아 둘이 어긋난다. 매니페스트는 헤드라인이
        # 정해지기 전에 쓰이므로 어느 경로든 여기서 보완한다.
        params.headline = video._clamp_headline(params.headline)
        task_artifacts.patch_script_data(task_id, headline=params.headline)

    final_video_paths, combined_video_paths, generation_warnings = generate_final_videos(
        task_id,
        params,
        downloaded_videos,
        audio_file,
        subtitle_path,
        audio_duration,
    )

    # 자막 글꼴은 대본을 그릴 수 없을 때 생성 중에 교체된다. 매니페스트는 생성 전에
    # 쓰이므로 그대로 두면 요청값만 남아, 이 작업을 다시 불러왔을 때 실제로 쓰인
    # 글꼴과 어긋난다. 실행 결과를 기록해 추적할 수 있게 한다.
    task_artifacts.patch_script_data(task_id, effective_font_name=params.font_name)

    if not final_video_paths:
        return _mark_task_failed(
            task_id,
            "video",
            "failed to generate final video",
        )

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    # 7. 영상 생성 작업을 먼저 끝내고, 필요하면 그다음에 플랫폼 업로드를 제출한다. 외부
    # 업로드는 몇 분이 걸릴 수 있으므로 영상 결과 반환을 막아서는 안 되고, 이미 만들어진
    # 결과물에 거꾸로 영향을 줘서도 안 된다.
    cross_post_enabled = (
        upload_post.upload_post_service.is_configured()
        and upload_post.upload_post_service.auto_upload
    )
    platforms = (
        list(upload_post.upload_post_service.platforms)
        if cross_post_enabled
        else []
    )
    should_cross_post = cross_post_enabled and bool(platforms)
    if cross_post_enabled and not platforms:
        logger.warning(
            f"skip cross-post because no platforms are configured, task_id: {task_id}"
        )
    cross_post_state = const.CROSS_POST_STATE_PENDING if should_cross_post else None

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
        "cross_post_state": cross_post_state,
        "cross_post_results": None,
        "cross_post_error": None,
        "cross_post_owner": _cross_post_process_owner if should_cross_post else None,
        "warnings": generation_warnings or None,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )

    if should_cross_post:
        scheduling_error = _schedule_cross_post(
            task_id=task_id,
            video_paths=final_video_paths,
            params=params,
            video_script=video_script,
            platforms=platforms,
            youtube_privacy_status=(
                upload_post.upload_post_service.youtube_privacy_status
            ),
        )
        # 큐가 가득 찼거나 스레드 풀이 닫힌 것은 동기적으로 알 수 있는 스케줄 실패다. 작업
        # 상태는 이미 스케줄 함수가 갱신했으므로, 여기서는 반환 스냅샷을 맞춰 준다. 호출자가
        # 이후 조회와 어긋나는 pending 을 받지 않게 하기 위해서다.
        if scheduling_error:
            kwargs["cross_post_state"] = const.CROSS_POST_STATE_FAILED
            kwargs["cross_post_error"] = scheduling_error
            kwargs["cross_post_owner"] = None

    return kwargs


def start(
    task_id,
    params: VideoParams,
    stop_at: str = "video",
    voice_preview: dict | None = None,
):
    """작업 파이프라인을 실행하고, 예상치 못한 예외도 조회 가능한 실패 상태로 바뀌도록 보장한다."""
    try:
        return _run_pipeline(
            task_id,
            params,
            stop_at=stop_at,
            voice_preview=voice_preview,
        )
    except Exception as exc:
        logger.exception(
            f"unexpected task pipeline failure, task_id: {task_id}, error: {exc}"
        )
        return _mark_task_failed(
            task_id,
            "pipeline",
            f"{type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="돈의 역할",
        voice_name="ko-KR-SunHiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
