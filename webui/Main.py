import hashlib
import html
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import requests
import streamlit as st
from loguru import logger
from streamlit_tour import Tour

# WebUI 를 독립 진입점으로 실행할 때는 프로젝트 루트가 외부 의존성보다 앞서야 한다.
# 의존성에 들어 있는 같은 이름의 app 패키지가 MoneyPrinterTurbo 의 app 패키지를 가리는 것을 막기 위해서다.
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config
from app.models import const
from app.models.llm_provider import (
    DEFAULT_LLM_PROVIDER_ID,
    LLM_PROVIDER_REGISTRY,
    get_llm_provider,
    normalize_provider_override,
)
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import bgm as bgm_service
from app.services import cache_manager, llm, video, voice, webui_task
from app.services import elevenlabs_music as elevenlabs_music_service
from app.services import sonilo as sonilo_service
from app.services import state as sm
from app.services import task as tm
from app.services import version_checker
from app.utils.logging_utils import configure_terminal_logger
from app.utils import utils

st.set_page_config(
    page_title="MoneyPrinterTurbo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        "Report a bug": "https://github.com/harry0703/MoneyPrinterTurbo/issues",
        "About": "# MoneyPrinterTurbo\nSimply provide a topic or keyword for a video, and it will "
        "automatically generate the video copy, video materials, video subtitles, "
        "and video background music before synthesizing a high-definition short "
        "video.\n\nhttps://github.com/harry0703/MoneyPrinterTurbo",
    },
)


# Streamlit 1.59 는 페이지 오른쪽 위에 Deploy, skills nudge 같은 플랫폼 진입점을 기본으로 보여 준다.
# MoneyPrinterTurbo 는 최종 사용자를 위한 로컬 도구라, 이런 진입점은 상단에 큰 빈 공간을 만들고
# 새 사용자에게 추가 구성 요소를 설치해야 하는 것처럼 오해를 준다. 여기서 Streamlit 플랫폼
# 툴바를 숨기고 메인 컨테이너 상단 여백을 줄여, 프로젝트 자체의 제목·언어 선택·업무 설정 영역만 남긴다.
style_file = Path(__file__).with_name("styles.css")
streamlit_style = f"<style>{style_file.read_text(encoding='utf-8')}</style>"
st.markdown(streamlit_style, unsafe_allow_html=True)
# 리소스 디렉터리를 정의한다
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
# 언어 목록은 세션 상태를 초기화하기 전에 준비돼 있어야, 첫 방문 때 브라우저 locale 을 프로젝트가
# 실제로 지원하는 언어로 매핑할 수 있다. 자동 인식 결과는 현재 세션에만 반영되고 전역 설정은 바꾸지 않는다.
locales = utils.load_locales(i18n_dir)
DEFAULT_CHATTERBOX_BASE_URL = "http://127.0.0.1:4123/v1"
DEFAULT_CHATTERBOX_MODEL = "chatterbox"
DEFAULT_CHATTERBOX_VOICES = ["default-Female"]
ONBOARDING_TOUR_KEY = "mpt-onboarding-v1"
VOICE_MODE_TTS = "tts"
VOICE_MODE_UPLOAD = "upload"
VOICE_MODE_NONE = "none"
# '기본값' 은 WebUI 전용 sentinel 이라 config.toml 에 쓰이지도, FFmpeg 로 넘어가지도 않는다.
# 백엔드는 video_codec 이 설정되지 않으면 안정적인 libx264 를 계속 쓴다. 이 sentinel 을 따로 둬야
# '프로젝트 기본 정책을 따름' 과 '사용자가 libx264 를 명시적으로 고정함' 을 구분할 수 있고,
# 나중에 기본 정책을 안전하게 바꿀 수 있다.
DEFAULT_VIDEO_CODEC_OPTION = "__default__"
DEFAULT_SUBTITLE_SETTINGS = {
    "subtitle_enabled": True,
    "font_name": "Pretendard-Bold.ttf",
    "subtitle_position": "bottom",
    "custom_position": 70.0,
    "text_fore_color": "#FFFFFF",
    "font_size": 60,
    "stroke_color": "#000000",
    "stroke_width": 1.5,
    "subtitle_background_enabled": False,
    "subtitle_background_color": "#000000",
    "rounded_subtitle_background": False,
}
LOCAL_MATERIAL_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".flv",
    ".mkv",
    ".jpg",
    ".jpeg",
    ".png",
}
CUSTOM_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_FINAL_VIDEO_PATTERN = re.compile(
    r"^final-(?P<index>\d+)\.(?P<extension>mp4|mov|mkv|webm)$",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# 시작 설정, 세션 상태, 현지화
# -----------------------------------------------------------------------------


def _parse_chatterbox_voices(voices):
    # Chatterbox 는 자체 호스팅 서비스라 음색 목록을 사용자가 WebUI 에서 직접 입력한다.
    # 여기서 TOML 배열과 입력란의 쉼표 구분 문자열을 모두 지원해, 드롭다운·미리듣기 버튼·
    # 이후 생성 흐름이 서로 다른 형식을 써서 상태가 어긋나는 것을 막는다.
    if isinstance(voices, str):
        return [v.strip() for v in voices.split(",") if v.strip()]
    return [str(v).strip() for v in voices or [] if str(v).strip()]


def _sync_chatterbox_config_from_session_state():
    # Streamlit 버튼은 페이지 전체 rerun 을 일으키는데, Chatterbox 설정 입력란은 '음성 합성
    # 미리듣기' 버튼 뒤에 있다. 미리듣기에서 config.chatterbox 만 읽으면 사용자가 방금 입력란에
    # 넣은 base_url/model/voices 를 못 가져올 수 있다. session_state 에서 한 번 동기화하면
    # 버튼 로직과 입력란 표시 로직이 같은 최신 설정을 쓰게 된다.
    config.chatterbox["base_url"] = (
        st.session_state.get(
            "chatterbox_base_url_input",
            config.chatterbox.get("base_url") or DEFAULT_CHATTERBOX_BASE_URL,
        )
        or ""
    ).strip()
    config.chatterbox["api_key"] = st.session_state.get(
        "chatterbox_api_key_input", config.chatterbox.get("api_key", "")
    )
    config.chatterbox["model_id"] = (
        st.session_state.get(
            "chatterbox_model_input",
            config.chatterbox.get("model_id") or DEFAULT_CHATTERBOX_MODEL,
        )
        or DEFAULT_CHATTERBOX_MODEL
    ).strip()
    config.chatterbox["voices"] = _parse_chatterbox_voices(
        st.session_state.get(
            "chatterbox_voices_input",
            config.chatterbox.get("voices") or DEFAULT_CHATTERBOX_VOICES,
        )
    )


def _detect_audio_mime(audio_file: str, audio_bytes: bytes) -> str:
    # travisvn/chatterbox-tts-api 처럼 일부 OpenAI 호환 TTS 서비스는 response_format=mp3 로
    # 요청해도 WAV 내용을 반환한다. WebUI 미리듣기가 audio/mp3 로 고정되어 있으면 브라우저가
    # 재생하지 못할 수 있으므로, 여기서는 파일 헤더로 실제 형식을 판별한다.
    header = audio_bytes[:12]
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"ID3") or header[:2] in (
        b"\xff\xfb",
        b"\xff\xf3",
        b"\xff\xf2",
    ):
        return "audio/mp3"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    ext = os.path.splitext(audio_file)[1].lower()
    return {
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }.get(ext, "audio/mp3")


def _build_uploaded_file_path(uploaded_file, target_dir, allowed_extensions, prefix):
    """브라우저 업로드 파일을 저장할 통제된 서버 경로를 만든다."""
    original_name = os.path.basename(str(uploaded_file.name or ""))
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in allowed_extensions:
        logger.warning(
            f"reject unsupported uploaded file extension: {original_name or '<empty>'}"
        )
        raise ValueError("unsupported uploaded file type")

    normalized_target_dir = os.path.realpath(target_dir)
    os.makedirs(normalized_target_dir, exist_ok=True)
    # 브라우저가 넘긴 파일명을 재사용하지 않는다. 경로 구분자, 제어 문자, 동명 파일 덮어쓰기를
    # 피하기 위해서다. UUID 는 서버 저장에만 쓰이고, 업로드 위젯에서 사용자가 보는 원래 이름은 바뀌지 않는다.
    file_path = os.path.realpath(
        os.path.join(normalized_target_dir, f"{prefix}-{uuid4().hex}{extension}")
    )
    if os.path.commonpath([normalized_target_dir, file_path]) != normalized_target_dir:
        logger.warning(f"invalid uploaded file path: {file_path}")
        raise ValueError("invalid uploaded file path")
    return file_path


def _initialize_session_state():
    """rerun 을 넘어 유지되는 페이지 상태를 한곳에서 초기화한다."""
    if not st.session_state.get("cross_post_recovery_checked"):
        # WebUI 는 FastAPI 를 거치지 않고 단독으로 실행될 수 있으므로, 첫 세션 초기화 때
        # 프로세스 재시작이 남긴 업로드 상태도 처리해야 한다. 복구에 실패하면 표시를 남기지 않아
        # 이후 rerun 에서 다시 시도한다.
        recovered = tm.recover_interrupted_cross_posts()
        if recovered is not None:
            st.session_state["cross_post_recovery_checked"] = True

    saved_ui_language = config.ui.get("language", "")
    browser_locale = st.context.locale
    initial_ui_language = utils.resolve_ui_language(
        saved_language=saved_ui_language,
        browser_locale=browser_locale,
        supported_languages=locales.keys(),
    )

    defaults = {
        "video_subject": "",
        "video_script": "",
        "video_terms": "",
        "video_script_prompt": "",
        "custom_system_prompt": llm.DEFAULT_SCRIPT_SYSTEM_PROMPT,
        "script_style": llm.DEFAULT_SCRIPT_STYLE,
        "match_materials_to_script": bool(
            config.app.get("match_materials_to_script", False)
        ),
        "ui_language": initial_ui_language,
        # 이미 저장된 로컬 소재는 사용자가 대본만 고쳐서 계속 재사용할 수 있게 한다.
        "local_video_materials": [],
        # 생성 버튼 콜백이 작업을 먼저 등록해, 상단 진입점이 실행 중 개수를 즉시 표시할 수 있게 한다.
        "active_generation_tasks": {},
        # 현재 페이지에서 마지막으로 제출한 작업. 생성이 백그라운드 실행으로 바뀐 뒤로는 페이지
        # Fragment 가 이 ID 로 상태를 조회한다. 새로고침할 때 실행 중인 예전 페이지 스크립트에
        # 더는 의존하지 않는다.
        "current_generation_task_id": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


_initialize_session_state()


def tr(key):
    loc = locales.get(st.session_state["ui_language"], {})
    return loc.get("Translation", {}).get(key, key)


# -----------------------------------------------------------------------------
# 작업 관리: 이력 스캔, 실행 상태, 파라미터 복원, 목록 상호작용
# -----------------------------------------------------------------------------


def _format_task_time(timestamp):
    if not timestamp:
        return "-"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _format_task_subject(subject, max_length=30):
    subject = str(subject or "").replace("\n", " ").strip()
    if len(subject) <= max_length:
        return subject or "-"
    return f"{subject[:max_length]}..."


def _safe_load_task_script(task_path):
    script_file = os.path.join(task_path, "script.json")
    if not os.path.isfile(script_file):
        return {}

    try:
        with open(script_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"failed to read task script data: {script_file}, {e}")
        return {}


def _find_final_task_video(task_path: str) -> str:
    """
    작업 디렉터리에서 번호가 가장 작은 최종 결과물을 반환한다.

    합성 과정은 combined, temp-clip, MoviePy 임시 파일도 만든다. 이런 파일은 작업이 성공적으로
    끝났다는 뜻이 아니므로, 여기서는 ``final-<번호>.<확장자>`` 만 받아들인다.
    """
    try:
        files = os.listdir(task_path)
    except OSError:
        return ""

    candidates = []
    for file_name in files:
        match = _FINAL_VIDEO_PATTERN.fullmatch(file_name)
        if match:
            candidates.append((int(match.group("index")), file_name))

    if not candidates:
        return ""

    _, file_name = min(candidates, key=lambda item: item[0])
    return os.path.join(task_path, file_name)


def _build_restore_upload_requirements(params: Mapping) -> dict:
    """
    Streamlit 이 자동으로 복원할 수 없는, 지난 작업의 업로드 파일 의존성을 기록한다.

    브라우저는 프로그램이 file_uploader 를 다시 채우는 것을 허용하지 않는다. 그래서 작업을 복원할
    때 로컬 소재와 사용자 오디오 의존성을 따로 기록해 두고, 사용자가 다시 생성하기 전에 직접
    보충하거나 교체했는지 확인한다.
    """
    return {
        "local_materials": params.get("video_source") == "local",
        "custom_audio": bool(params.get("custom_audio_file")),
        "original_voice_name": params.get("voice_name") or "",
    }


def _get_unmet_restore_upload_requirements(
    requirements: Mapping | None,
    *,
    video_source: str,
    voice_name: str,
    has_local_materials: bool,
    has_custom_audio: bool,
    voice_mode: str | None = None,
) -> set[str]:
    """현재 폼에서 아직 채워지지 않은, 지난 업로드 파일 의존성을 반환한다."""
    requirements = requirements or {}
    unmet = set()

    if (
        requirements.get("local_materials")
        and video_source == "local"
        and not has_local_materials
    ):
        unmet.add("local_materials")

    if requirements.get("custom_audio") and not has_custom_audio:
        if voice_mode is not None:
            # 새 WebUI 는 나레이션 방식을 명시적으로 고르게 한다. 사용자가 자동 나레이션이나
            # 나레이션 없음으로 바꿨다면 지난 업로드 오디오를 직접 대체한 것이다. 업로드 모드를
            # 계속 고를 때만 다시 업로드를 요구한다.
            if voice_mode == VOICE_MODE_UPLOAD:
                unmet.add("custom_audio")
        elif voice_name == requirements.get("original_voice_name", ""):
            # 예전 호출자가 음색으로 판정하던 호환 동작을 유지해 API 와 기존 테스트 도구에 영향을 주지 않는다.
            unmet.add("custom_audio")

    return unmet


def _queue_task_restore(task_id):
    # 작업 목록은 fragment 안에서 돌기 때문에 이미 만들어진 메인 폼 위젯의 상태를 직접 바꿀 수 없다.
    # 여기서는 후보 작업만 기록하고 페이지 전체 rerun 을 일으킨다. 확인과 파라미터 복원은 메인
    # 페이지가 한곳에서 처리한다.
    st.session_state["task_restore_candidate_id"] = task_id
    st.session_state["task_manager_popover_nonce"] = (
        st.session_state.get("task_manager_popover_nonce", 0) + 1
    )
    st.rerun(scope="app")


def _normalize_task_state(state):
    if state in (
        const.TASK_STATE_COMPLETE,
        const.TASK_STATE_FAILED,
        const.TASK_STATE_PROCESSING,
    ):
        return state
    try:
        return int(state)
    except (TypeError, ValueError):
        return state


def _active_generation_tasks():
    tasks = st.session_state.setdefault("active_generation_tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
        st.session_state["active_generation_tasks"] = tasks
    return tasks


def _add_active_generation_task(task_id, subject=None):
    tasks = _active_generation_tasks()
    task = tasks.setdefault(task_id, {})
    task["subject"] = subject or task.get("subject") or task_id
    task["mtime"] = task.get("mtime") or datetime.now().timestamp()


def _remove_active_generation_task(task_id):
    tasks = _active_generation_tasks()
    if task_id in tasks:
        del tasks[task_id]
    if st.session_state.get("pending_generation_task_id") == task_id:
        del st.session_state["pending_generation_task_id"]


def _prepare_generation_task():
    # st.button 의 on_click 은 페이지 스크립트가 다시 실행되기 전에 호출된다. 여기서 작업 ID 를
    # 미리 만들어 두면 상단 작업 관리 진입점이 같은 rerun 안에서 '생성 중' 개수를 표시할 수 있다.
    task_id = str(uuid4())
    st.session_state["pending_generation_task_id"] = task_id
    subject = st.session_state.get("video_subject") or st.session_state.get(
        "video_script"
    )
    _add_active_generation_task(task_id, subject=subject)


def _task_state_label(state, has_video):
    normalized_state = _normalize_task_state(state)
    if normalized_state == const.TASK_STATE_COMPLETE:
        return tr("Task Status Complete")
    if normalized_state == const.TASK_STATE_FAILED:
        return tr("Task Status Failed")
    if normalized_state == const.TASK_STATE_PROCESSING:
        return tr("Task Status Processing")
    if has_video:
        return tr("Task Status Complete")
    return tr("Task Status History")


def _task_state_filter_key(task):
    normalized_state = _normalize_task_state(task.get("state"))
    if normalized_state == const.TASK_STATE_PROCESSING:
        return "processing"
    if normalized_state == const.TASK_STATE_FAILED:
        return "failed"
    if normalized_state == const.TASK_STATE_COMPLETE or task["video_file"]:
        return "complete"
    return "history"


def _scan_history_tasks(limit=30):
    tasks_root = utils.task_dir()
    if not os.path.isdir(tasks_root):
        return []

    # 작업 관리 fragment 는 2 초마다 갱신된다. 먼저 비용이 적은 디렉터리 메타데이터만 읽어 최근
    # 작업을 잘라 낸 뒤 script.json 과 영상 목록을 해석한다. 지난 작업이 많을 때 전체를 반복해서
    # 스캔하지 않기 위해서다.
    task_entries = []
    try:
        with os.scandir(tasks_root) as entries:
            for entry in entries:
                try:
                    if entry.name.startswith(".") or not entry.is_dir(
                        follow_symlinks=False
                    ):
                        continue
                    task_entries.append(
                        (
                            entry.stat(follow_symlinks=False).st_mtime,
                            entry.name,
                            entry.path,
                        )
                    )
                except OSError as e:
                    # 작업 디렉터리 하나가 삭제되는 중일 수 있다. 그 때문에 작업 패널 전체가 깨져서는 안 된다.
                    logger.debug(f"skip unavailable task directory: {entry.path}, {e}")
    except OSError as e:
        logger.warning(f"failed to scan task directory: {tasks_root}, {e}")
        return []

    task_entries.sort(key=lambda item: item[0], reverse=True)
    tasks = []
    for mtime, name, task_path in task_entries[:limit]:
        script_data = _safe_load_task_script(task_path)
        params_data = script_data.get("params", {}) if script_data else {}
        video_file = _find_final_task_video(task_path)
        subject = (
            params_data.get("video_subject")
            or script_data.get("script", "")[:40]
            or name
        )
        tasks.append(
            {
                "task_id": name,
                "subject": subject,
                "state": const.TASK_STATE_COMPLETE if video_file else None,
                "progress": 100 if video_file else 0,
                "mtime": mtime,
                "task_path": task_path,
                "video_file": video_file,
                "source": "history",
            }
        )

    return tasks


def _collect_task_summaries(limit=20):
    history_tasks = {task["task_id"]: task for task in _scan_history_tasks(limit=50)}

    try:
        runtime_tasks, _ = sm.state.get_all_tasks(1, 50)
    except Exception as e:
        logger.warning(f"failed to load runtime tasks: {e}")
        runtime_tasks = []

    for task in runtime_tasks:
        task_id = task.get("task_id", "")
        if not task_id:
            continue

        task_path = os.path.join(utils.task_dir(), task_id)
        history_task = history_tasks.get(task_id, {})
        video_files = task.get("videos") or []
        video_file = (
            video_files[0] if video_files else history_task.get("video_file", "")
        )
        subject = (
            task.get("video_subject")
            or history_task.get("subject")
            or (task.get("script", "")[:40] if task.get("script") else "")
            or task_id
        )

        history_tasks[task_id] = {
            "task_id": task_id,
            "subject": subject,
            "state": task.get("state"),
            "cross_post_state": task.get("cross_post_state"),
            "progress": int(task.get("progress", 0) or 0),
            "mtime": os.path.getmtime(task_path)
            if os.path.isdir(task_path)
            else history_task.get("mtime", 0),
            "task_path": task_path,
            "video_file": video_file,
            "source": "runtime",
        }

    for task_id, active_task in _active_generation_tasks().items():
        history_task = history_tasks.get(task_id, {})
        if history_task and _task_state_filter_key(history_task) in {
            "complete",
            "failed",
        }:
            # 세션의 active 표시는 작업이 상태 저장소에 기록되기 직전의 아주 짧은 구간만 덮는 역할이다.
            # 백그라운드 작업이 끝난 뒤에는 실제 최종 상태를 따라야 하며, 실패한 작업을 다시 생성 중으로
            # 보여 줘서는 안 된다.
            continue

        task_path = os.path.join(utils.task_dir(), task_id)
        history_tasks[task_id] = {
            "task_id": task_id,
            "subject": active_task.get("subject")
            or history_task.get("subject")
            or task_id,
            "state": const.TASK_STATE_PROCESSING,
            "progress": history_task.get("progress", 0),
            "mtime": active_task.get("mtime")
            or history_task.get("mtime", datetime.now().timestamp()),
            "task_path": task_path,
            "video_file": history_task.get("video_file", ""),
            "source": "active",
        }

    tasks = list(history_tasks.values())
    return sorted(tasks, key=lambda item: item["mtime"], reverse=True)[:limit]


def _open_task_path(task_path):
    tasks_root = os.path.abspath(utils.task_dir())
    normalized_path = os.path.abspath(task_path)
    if not normalized_path.startswith(tasks_root + os.sep):
        logger.warning(f"invalid task folder path: {normalized_path}")
        return
    if os.path.isdir(normalized_path):
        webbrowser.open(f"file://{normalized_path}")


def _open_task_video(video_file):
    tasks_root = os.path.abspath(utils.task_dir())
    normalized_file = os.path.abspath(video_file)

    # 영상 경로는 작업 디렉터리 스캔이나 런타임 상태에서 온다. 여기서도 작업 디렉터리 안의 파일만
    # 열 수 있게 제한해, UI 조작이 비정상 경로를 타고 임의의 로컬 파일을 여는 기능으로 번지지 않게 한다.
    if not normalized_file.startswith(tasks_root + os.sep):
        logger.warning(f"invalid task video path: {normalized_file}")
        return
    if not os.path.isfile(normalized_file):
        logger.warning(f"task video does not exist: {normalized_file}")
        return

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", normalized_file])
        elif sys.platform.startswith("win"):
            os.startfile(normalized_file)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", normalized_file])
    except Exception as e:
        logger.error(f"failed to open task video: {normalized_file}, {e}")


def _delete_task(task_id, task_path, task_state=None):
    # 화면에 보이는 상태는 백그라운드 작업보다 뒤처질 수 있다. 삭제 전에 전달된 상태, 현재 세션의
    # 활성 작업, 최신 상태를 함께 확인해, 방금 시작했거나 중간 영상을 이미 만든 작업이 잘못 삭제되는
    # 것을 막는다.
    current_task = None
    try:
        current_task = sm.state.get_task(task_id)
    except Exception as e:
        logger.exception(f"failed to verify task state before deletion: {task_id}, {e}")
        return False

    task_snapshot = dict(current_task or {})
    task_snapshot.setdefault("state", task_state)
    if task_id in _active_generation_tasks():
        task_snapshot["state"] = const.TASK_STATE_PROCESSING

    if tm.is_task_busy(task_snapshot):
        logger.warning(f"refused to delete running task: {task_id}")
        return False

    tasks_root = os.path.abspath(utils.task_dir())
    normalized_path = os.path.abspath(task_path)

    # 작업 삭제는 작업 상태와 로컬 생성 파일을 제거한다. 반드시 storage/tasks 아래로 한정해야
    # 비정상 task_path 때문에 다른 로컬 디렉터리가 잘못 지워지는 일을 막을 수 있다.
    if not normalized_path.startswith(tasks_root + os.sep):
        logger.warning(f"invalid task folder path for deletion: {normalized_path}")
        return False

    try:
        if hasattr(sm.state, "delete_task"):
            sm.state.delete_task(task_id)
        if os.path.isdir(normalized_path):
            shutil.rmtree(normalized_path)
        logger.info(f"deleted task: {task_id}")
        return True
    except Exception as e:
        logger.exception(f"failed to delete task: {task_id}, {e}")
        return False


def _count_processing_tasks(tasks):
    # 상단 작업 관리 진입점은 '생성 중' 작업 개수만 보여 주면 된다.
    # 내부 상태 key 로 판정해, 다국어 표시 문구에 의존하다가 언어마다 집계가 달라지는 것을 막는다.
    processing_task_ids = {
        task["task_id"]
        for task in tasks
        if _task_state_filter_key(task) == "processing"
    }
    return len(processing_task_ids)


def _task_manager_label(processing_count):
    label = tr("Task Manager")
    if processing_count <= 0:
        return label
    return f"{label} · {processing_count}"


def _render_task_table(filtered_tasks, key_prefix):
    with st.container(key=f"task_table_header_{key_prefix}"):
        header_cols = st.columns([1.1, 1.7, 3.0, 0.8, 1.6], vertical_alignment="center")
        header_cols[0].caption(tr("Task Status"))
        header_cols[1].caption(tr("Task Updated At"))
        header_cols[2].caption(tr("Task Subject"))
        header_cols[3].caption(tr("Task Progress"))
        header_cols[4].caption(tr("Task Actions"))

    if not filtered_tasks:
        st.info(tr("No Tasks Match Filter"))
        return

    visible_tasks = filtered_tasks[:12]
    list_height = min(390, max(96, len(visible_tasks) * 58))
    with st.container(height=list_height, border=False):
        for task in visible_tasks:
            task_id = task["task_id"]
            has_video = bool(task["video_file"] and os.path.isfile(task["video_file"]))
            is_processing = _task_state_filter_key(task) == "processing"
            is_busy = is_processing or tm.is_task_busy(task)
            has_restore_data = os.path.isfile(
                os.path.join(task["task_path"], "script.json")
            )
            safe_task_key = "".join(ch if ch.isalnum() else "_" for ch in task_id)[:40]

            # Streamlit 기본 bordered container 와 columns 로 각 줄의 동작을 유지한다.
            # 직접 만든 HTML/CSS 표보다 Streamlit 버전 변화에 안정적이고,
            # dataframe 보다 재생·폴더 열기·삭제 같은 인라인 동작을 남기기 좋다.
            with st.container(
                key=f"task_row_{key_prefix}_{safe_task_key}", border=True
            ):
                row_cols = st.columns(
                    [1.1, 1.7, 3.0, 0.8, 1.6],
                    vertical_alignment="center",
                )
                row_cols[0].write(_task_state_label(task["state"], has_video))
                row_cols[1].write(_format_task_time(task["mtime"]))
                row_cols[2].write(_format_task_subject(task["subject"]))
                row_cols[3].write(f"{task['progress']}%")

                action_cols = row_cols[4].columns(
                    4,
                    vertical_alignment="center",
                    gap="small",
                )
                with action_cols[0]:
                    play_label = tr("Play")
                    if st.button(
                        play_label,
                        key=f"play_task_{key_prefix}_{task_id}",
                        use_container_width=True,
                        icon=":material/play_arrow:",
                        help=play_label,
                        disabled=not has_video,
                    ):
                        _open_task_video(task["video_file"])

                with action_cols[1]:
                    open_label = tr("Open Task Folder")
                    if st.button(
                        open_label,
                        key=f"open_task_{key_prefix}_{task_id}",
                        use_container_width=True,
                        icon=":material/folder_open:",
                        help=open_label,
                    ):
                        _open_task_path(task["task_path"])

                with action_cols[2]:
                    restore_label = tr("Regenerate Task")
                    if st.button(
                        restore_label,
                        key=f"restore_task_{key_prefix}_{task_id}",
                        use_container_width=True,
                        icon=":material/replay:",
                        help=restore_label,
                        disabled=is_processing or not has_restore_data,
                    ):
                        _queue_task_restore(task_id)

                with action_cols[3]:
                    delete_label = tr("Delete Task")
                    delete_help = (
                        f"{delete_label} ({tr('Task Status Processing')})"
                        if is_busy
                        else delete_label
                    )
                    if st.button(
                        delete_label,
                        key=f"delete_task_{key_prefix}_{task_id}",
                        use_container_width=True,
                        icon=":material/delete:",
                        help=delete_help,
                        disabled=is_busy,
                    ):
                        if _delete_task(task_id, task["task_path"], task["state"]):
                            st.toast(tr("Task Deleted"))
                            st.rerun()
                        else:
                            st.error(tr("Task Delete Failed"))


def _render_task_manager_panel(tasks=None):
    tasks = tasks if tasks is not None else _collect_task_summaries()
    if not tasks:
        st.info(tr("No Tasks Yet"))
        return

    # Streamlit 1.59 는 상태를 가진 Tabs 의 지연 렌더링을 지원한다. 전환할 때 현재 목록만 다시 만들어,
    # 주기 Fragment 가 2 초마다 작업 줄과 동작 버튼을 네 벌씩 다시 만드는 것을 피한다.
    status_tabs = [
        ("all", tr("All Tasks")),
        ("processing", tr("Task Status Processing")),
        ("complete", tr("Task Status Complete")),
        ("failed", tr("Task Status Failed")),
    ]
    tabs = st.tabs(
        [label for _, label in status_tabs],
        key="task_manager_status_tabs",
        on_change="rerun",
    )
    for (status_key, _), tab in zip(status_tabs, tabs):
        if not tab.open:
            continue
        with tab:
            filtered_tasks = [
                task
                for task in tasks
                if status_key == "all" or _task_state_filter_key(task) == status_key
            ]
            _render_task_table(filtered_tasks, status_key)


@st.fragment(run_every="2s")
def _render_task_manager_entry():
    # 작업은 현재 페이지에서도, 다른 페이지에서도 시작될 수 있다. 진입점만 별도 fragment 로 주기
    # 갱신해 작업 개수와 popover 내용만 바꾸고, 메인 페이지의 폼 입력은 끊지 않는다.
    task_summaries = _collect_task_summaries()
    processing_task_count = _count_processing_tasks(task_summaries)
    with st.container(key="task_manager_entry", width="content"):
        with st.popover(
            _task_manager_label(processing_task_count),
            width="content",
            key=(
                "task_manager_popover_"
                f"{st.session_state.get('task_manager_popover_nonce', 0)}"
            ),
        ):
            _render_task_manager_panel(task_summaries)


def _load_task_restore_payload(task_id):
    tasks_root = os.path.realpath(utils.task_dir())
    task_path = os.path.realpath(os.path.join(tasks_root, str(task_id)))
    try:
        if os.path.commonpath([tasks_root, task_path]) != tasks_root:
            raise ValueError("task path is outside the task directory")
    except ValueError as e:
        logger.warning(f"invalid task restore path: {task_id}, {e}")
        return None

    script_data = _safe_load_task_script(task_path)
    raw_params = script_data.get("params")
    if not isinstance(raw_params, dict):
        logger.warning(f"task has no restorable parameters: {task_id}")
        return None

    params_input = dict(raw_params)
    if script_data.get("script"):
        params_input["video_script"] = script_data["script"]
    if script_data.get("search_terms"):
        params_input["video_terms"] = script_data["search_terms"]

    try:
        params = VideoParams.model_validate(params_input).model_dump(mode="json")
    except Exception as e:
        logger.warning(f"failed to validate task restore parameters: {task_id}, {e}")
        return None

    return {
        "task_id": str(task_id),
        "subject": params.get("video_subject") or script_data.get("script") or task_id,
        "params": params,
    }


def _infer_tts_server_from_voice(voice_name):
    if voice.is_no_voice(voice_name):
        return voice.NO_VOICE_NAME
    if voice.is_siliconflow_voice(voice_name):
        return "siliconflow"
    if voice.is_gemini_voice(voice_name):
        return "gemini-tts"
    if voice.is_mimo_voice(voice_name):
        return "mimo-tts"
    if voice.is_elevenlabs_voice(voice_name):
        return "elevenlabs"
    if voice.is_chatterbox_voice(voice_name):
        return "chatterbox"
    if voice.is_azure_v2_voice(voice_name):
        return "azure-tts-v2"
    return "azure-tts-v1"


def _set_stable_widget_value(key, value):
    if value is not None:
        st.session_state[localized_widget_key(key)] = value


def _apply_pending_task_restore():
    payload = st.session_state.pop("task_restore_payload", None)
    if not payload:
        return False

    params = payload["params"]
    video_terms = params.get("video_terms") or ""
    if isinstance(video_terms, list):
        video_terms = ", ".join(str(term) for term in video_terms)

    # 대본 및 고급 대본 설정.
    st.session_state["video_subject"] = params.get("video_subject") or ""
    st.session_state["video_script"] = params.get("video_script") or ""
    st.session_state["video_terms"] = str(video_terms)
    _set_stable_widget_value(
        "script_language_select", params.get("video_language") or ""
    )
    st.session_state["paragraph_number_input"] = params.get("paragraph_number", 1)
    st.session_state["video_script_prompt"] = params.get("video_script_prompt") or ""
    script_style = params.get("script_style") or llm.DEFAULT_SCRIPT_STYLE
    st.session_state["script_style"] = script_style
    _set_stable_widget_value("script_style_select", script_style)
    st.session_state["custom_system_prompt"] = params.get(
        "custom_system_prompt"
    ) or llm.script_style_prompt(script_style)

    # 영상 설정. 소재 업로드 위젯은 서버가 채울 수 없으므로 로컬 소재는 사용자가 다시 골라야 한다.
    video_source = params.get("video_source") or "pexels"
    _set_stable_widget_value("video_source_select", video_source)
    _set_stable_widget_value(
        "video_concat_mode_select", params.get("video_concat_mode") or "random"
    )
    _set_stable_widget_value(
        "video_transition_mode_select",
        params.get("video_transition_mode") or VideoTransitionMode.none.value,
    )
    _set_stable_widget_value(
        f"video_aspect_for_{video_source}",
        params.get("video_aspect") or VideoAspect.portrait.value,
    )
    _set_stable_widget_value(
        "video_clip_duration_select", params.get("video_clip_duration", 3)
    )
    _set_stable_widget_value(
        "video_clip_speed_slider",
        # API 는 WebUI 범위를 벗어나는 속도를 기록할 수 있다. 작업 생성 단계에서 안전하게 정규화하지만
        # 이력에는 원래 값이 남을 수 있다. 작업을 복원하기 전에 다시 정규화해, Streamlit slider 에
        # 범위 밖 값이나 NaN, 무한대가 들어가 위젯 상태가 깨지는 것을 막는다.
        utils.normalize_clip_speed(params.get("video_clip_speed", 1.0)),
    )
    _set_stable_widget_value("video_count_select", params.get("video_count", 1))
    st.session_state["match_materials_to_script"] = bool(
        params.get("match_materials_to_script", False)
    )

    # 오디오 설정. 예전 작업에는 TTS server 가 기록되지 않았으므로 지난 voice_name 으로 추론한다.
    voice_name = params.get("voice_name") or voice.NO_VOICE_NAME
    tts_server = _infer_tts_server_from_voice(voice_name)
    if params.get("custom_audio_file"):
        voice_mode = VOICE_MODE_UPLOAD
    elif voice.is_no_voice(voice_name):
        voice_mode = VOICE_MODE_NONE
    else:
        voice_mode = VOICE_MODE_TTS
    _set_stable_widget_value("voice_mode_control", voice_mode)
    if tts_server != voice.NO_VOICE_NAME:
        _set_stable_widget_value("tts_server_select", tts_server)
        _set_stable_widget_value(f"speech_synthesis_select_{tts_server}", voice_name)
    _set_stable_widget_value("voice_volume_select", params.get("voice_volume", 1.0))
    _set_stable_widget_value("voice_rate_select", params.get("voice_rate", 1.0))
    bgm_type = params.get("bgm_type") or ""
    _set_stable_widget_value("bgm_type_select", bgm_type)
    _set_stable_widget_value("bgm_volume_select", params.get("bgm_volume", 0.2))
    st.session_state["custom_bgm_file_input"] = params.get("bgm_file") or ""
    st.session_state["sonilo_bgm_prompt_input"] = (
        params.get("video_music_prompt") or params.get("sonilo_bgm_prompt") or ""
    )
    st.session_state["elevenlabs_music_prompt_input"] = (
        params.get("video_music_prompt") or ""
    )

    # 자막 설정. 예전 작업의 범위 밖 값은 최소한으로 잘라, Slider 가 초기화되지 못하는 일을 막는다.
    st.session_state["subtitle_enabled_checkbox"] = bool(
        params.get("subtitle_enabled", True)
    )
    _set_stable_widget_value("font_name_select", params.get("font_name") or "")
    _set_stable_widget_value(
        "subtitle_position_select", params.get("subtitle_position") or "bottom"
    )
    custom_position = min(100.0, max(0.0, float(params.get("custom_position", 70.0))))
    st.session_state["custom_position_input"] = str(custom_position)
    st.session_state["font_color_picker"] = params.get("text_fore_color") or "#FFFFFF"
    st.session_state["font_size_slider"] = min(
        100, max(30, int(params.get("font_size", 60)))
    )
    st.session_state["stroke_color_picker"] = params.get("stroke_color") or "#000000"
    st.session_state["stroke_width_slider"] = min(
        10.0, max(0.0, float(params.get("stroke_width", 1.5)))
    )
    background_color = params.get("text_background_color")
    background_enabled = bool(background_color)
    st.session_state["subtitle_background_enabled_checkbox"] = background_enabled
    if isinstance(background_color, str):
        st.session_state["subtitle_background_color_picker"] = background_color
    st.session_state["rounded_subtitle_background_checkbox"] = bool(
        params.get("rounded_subtitle_background", False) and background_enabled
    )

    st.session_state.pop("local_video_materials_uploader", None)
    # 지난 작업에는 소재 경로만 저장되어 있어, 그 파일이 현재 환경에도 남아 있다고 보장할 수 없다.
    # 동시에 현재 페이지에 캐시된 업로드 소재도 비워, 복원 뒤 다른 작업의 파일을 잘못 쓰는 것을 막는다.
    st.session_state["local_video_materials"] = []
    st.session_state.pop("custom_audio_file_uploader", None)
    st.session_state.pop("custom_bgm_uploader", None)
    st.session_state.pop("custom_bgm_validation", None)
    st.session_state["task_restore_upload_requirements"] = (
        _build_restore_upload_requirements(params)
    )

    st.session_state["task_restore_succeeded"] = True
    logger.info(f"restored task configuration: {payload['task_id']}")
    return True


def _dismiss_task_restore_dialog():
    st.session_state.pop("task_restore_candidate_id", None)


@st.dialog(
    tr("Regenerate Task"),
    width="small",
    on_dismiss=_dismiss_task_restore_dialog,
)
def _render_task_restore_dialog(task_id):
    payload = _load_task_restore_payload(task_id)
    if payload is None:
        st.error(tr("Task Restore Failed"))
        if st.button(tr("Cancel"), key="cancel_invalid_task_restore"):
            st.session_state.pop("task_restore_candidate_id", None)
            st.rerun(scope="app")
        return

    st.write(tr("Regenerate Task Confirmation"))
    st.caption(_format_task_subject(payload["subject"], max_length=80))
    cancel_col, load_col = st.columns(2)
    if cancel_col.button(
        tr("Cancel"),
        key="cancel_task_restore",
        use_container_width=True,
    ):
        st.session_state.pop("task_restore_candidate_id", None)
        st.rerun(scope="app")
    if load_col.button(
        tr("Load Task Configuration"),
        key="confirm_task_restore",
        type="primary",
        use_container_width=True,
    ):
        st.session_state["task_restore_payload"] = payload
        st.session_state.pop("task_restore_candidate_id", None)
        st.rerun(scope="app")


def _dismiss_settings_dialog():
    """설정 팝업을 닫고, 다음 페이지 rerun 에서 자동으로 다시 열리지 않게 한다."""
    st.session_state["settings_dialog_open"] = False


def _render_brand(available_update: str | None = None):
    """프로젝트 이름, 현재 버전, 선택적인 업데이트 진입점을 그린다."""
    update_link = ""
    if available_update:
        update_label = html.escape(
            tr("Update Available").format(version=available_update)
        )
        # Streamlit 은 넘겨받은 HTML 도 Markdown 으로 계속 해석한다. 링크를 한 줄로 유지해,
        # 여러 줄 문자열의 들여쓰기가 코드 블록으로 인식되어 페이지에 HTML 원문이 그대로 보이는 것을 막는다.
        update_link = (
            '<a class="mpt-brand__update" '
            f'href="{version_checker.LATEST_RELEASE_PAGE_URL}" '
            'target="_blank" rel="noopener noreferrer" '
            f'aria-label="{update_label}" title="{update_label}">'
            f"{update_label}</a>"
        )
    st.markdown(
        f"""
        <h1 class="mpt-brand">
            <span class="mpt-brand__name">MoneyPrinterTurbo</span>
            <a class="mpt-brand__version"
               href="https://github.com/harry0703/MoneyPrinterTurbo"
               target="_blank"
               rel="noopener noreferrer"
               aria-label="Open MoneyPrinterTurbo on GitHub"
               title="Open project on GitHub">v{html.escape(str(config.project_version))}</a>
            {update_link}
        </h1>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every="1s")
def _render_pending_version_check():
    """확인이 끝나지 않았으면 브랜드 영역만 갱신해, 페이지 전체 폼이 막히거나 반복 실행되지 않게 한다."""
    snapshot = version_checker.poll_available_update(config.project_version)
    if snapshot.complete:
        # 확인이 끝나면 페이지를 한 번 새로 그려 상단 바를 정적 렌더링으로 바꾸고 fragment 폴링을 멈춘다.
        # 이 갱신은 백그라운드 요청이 끝난 뒤에 일어나므로 초기 페이지의 다른 내용이 늦어지지 않는다.
        st.rerun(scope="app")
    _render_brand()


def _render_top_bar():
    """브랜드, 작업 관리, 설정, 언어 전환으로 이루어진 페이지 상단 바를 그린다."""
    # 상단 바는 브랜드 영역과 동작 영역 두 개로 나뉜다. 좁은 화면에서는 Streamlit 이 두 영역을
    # 통째로 줄바꿈하고, 동작 영역 안에서는 남은 폭에 따라 다시 자동 줄바꿈된다.
    with st.container(key="top_bar"):
        brand_col, actions_col = st.columns(
            [3.5, 2.0],
            vertical_alignment="center",
            gap="small",
        )

    with brand_col:
        update_snapshot = version_checker.poll_available_update(
            config.project_version
        )
        if update_snapshot.complete:
            _render_brand(update_snapshot.available_version)
        else:
            _render_pending_version_check()

    with actions_col:
        with st.container(
            key="top_bar_actions",
            horizontal=True,
            horizontal_alignment="right",
            vertical_alignment="center",
            gap="small",
            width="stretch",
        ):
            _render_task_manager_entry()

            if st.button(
                tr("Settings"),
                key="open_settings_dialog_button",
                type="secondary",
                icon=":material/settings:",
                width="content",
            ):
                st.session_state["settings_dialog_open"] = True

            language_codes = list(locales.keys())
            selected_index = 0
            for i, code in enumerate(language_codes):
                if code == st.session_state.get("ui_language", ""):
                    selected_index = i

            selected_language_code = st.selectbox(
                "Language / 언어",
                options=language_codes,
                index=selected_index,
                format_func=lambda code: locales[code].get("Language", code),
                key="top_language_code_selector",
                label_visibility="collapsed",
                width=180,
            )
            if selected_language_code:
                previous_language = st.session_state.get("ui_language", "")
                if selected_language_code != previous_language:
                    logger.info(
                        "UI language changed by user: "
                        f"previous_language={previous_language or '<empty>'}, "
                        f"selected_language={selected_language_code}"
                    )
                    st.session_state["ui_language"] = selected_language_code
                    # 브라우저 자동 인식은 현재 세션에만 영향을 준다. 사용자가 직접 드롭다운을 바꿨을
                    # 때만 config.toml 에 기록하며, 이후 새 세션은 그 명시적 선택을 우선한다.
                    config.ui["language"] = selected_language_code
                    config.save_config()
                    # 언어를 바꾼 뒤 강제로 새로 그린다. selectbox 가 예전 언어 문구를 계속 보여 주지 않게 하기 위해서다.
                    st.rerun()


support_locales = [
    "zh-CN",
    "zh-HK",
    "zh-TW",
    "de-DE",
    "en-US",
    "es-ES",
    "fr-FR",
    "ja-JP",
    "ko-KR",
    "ru-RU",
    "vi-VN",
    "th-TH",
    "tr-TR",
]


# -----------------------------------------------------------------------------
# 공용 UI 구성 요소, 리소스 캐시, 로그
# -----------------------------------------------------------------------------


@st.cache_data(ttl=30, show_spinner=False)
def get_all_fonts():
    # 글꼴 디렉터리는 거의 바뀌지 않지만 Streamlit 은 위젯을 조작할 때마다 페이지를 rerun 한다.
    # 짧은 주기 캐시를 쓰면 os.walk 가 연달아 반복되는 것을 피하면서, 글꼴을 추가해도 최대 30 초
    # 안에는 인식되도록 보장할 수 있다.
    fonts = []
    # 하위 디렉터리는 훑지 않는다. 목록은 파일명만 돌려주고 선택값도 파일명으로
    # 저장되므로, 하위 폴더 글꼴을 노출하면 사용자가 고른 뒤 경로 해석에서 실패한다.
    for root, dirs, files in os.walk(font_dir):
        dirs.clear()
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
    fonts.sort()
    return fonts


@st.cache_data(ttl=30, show_spinner=False)
def get_all_songs():
    # 배경음악도 글꼴과 같은 짧은 주기 전략을 쓰고 영구 캐시는 하지 않는다. rerun 성능과, 실행 중
    # 사용자가 음악 파일을 직접 추가하는 상황을 함께 고려한 것이다.
    songs = []
    for root, dirs, files in os.walk(song_dir):
        for file in files:
            if file.endswith(".mp3"):
                songs.append(file)
    return songs


def open_task_folder(task_id):
    try:
        # task_id 는 항상 서버가 만든 UUID 여야 한다. 여기서 형식을 먼저 검증해, 비정상 값이 경로
        # 결합을 타고 작업 디렉터리 밖에 접근하는 것을 막고, 이후 디렉터리를 열 때 플랫폼 셸이
        # 특수 문자를 해석하는 일도 피한다.
        normalized_task_id = str(UUID(str(task_id)))
        tasks_root = os.path.abspath(os.path.join(root_dir, "storage", "tasks"))
        path = os.path.abspath(os.path.join(tasks_root, normalized_task_id))

        # UUID 검증을 통과했더라도 최종 경로가 작업 루트 디렉터리 안에 있는지 다시 확인한다.
        # 나중에 호출자가 task_id 출처를 바꿀 때 경로 탈출 위험이 들어오는 것을 막기 위해서다.
        if not path.startswith(tasks_root + os.sep):
            logger.warning(f"invalid task folder path: {path}")
            return

        if os.path.isdir(path):
            webbrowser.open(f"file://{path}")
    except Exception as e:
        logger.exception(f"failed to open task folder: task_id={task_id}, error={e}")


@st.cache_resource
def init_log():
    # 기본 로그 Handler 는 페이지 세션 상태가 아니라 프로세스 단위 자원이다. Streamlit 은 위젯을
    # 조작할 때마다 페이지 스크립트를 rerun 하고, 코드 핫 리로드로 캐시가 무효화될 수도 있다.
    # 로그 초기화는 터미널 Handler 만 정확히 교체해야 하며, 생성 중인 작업이 쓰는 WebUI 임시
    # Handler 를 비워서는 안 된다.
    _lvl = "DEBUG"

    return configure_terminal_logger(
        sys.stdout,
        level=_lvl,
        colorize=True,
    )


init_log()


def tr_optional(key, fallback_language=""):
    loc = locales.get(st.session_state["ui_language"], {})
    value = loc.get("Translation", {}).get(key, "")
    if not value and fallback_language:
        fallback_loc = locales.get(fallback_language, {})
        value = fallback_loc.get("Translation", {}).get(key, "")
    return value if value else ""


def render_onboarding_tour():
    # 안내 투어는 안정적인 진입점 세 곳만 다루고 Dialog, Tabs, 업무 폼을 제어하려 하지 않는다.
    # 그래야 새 사용자가 전체 흐름을 이해하면서도, 안내 상태가 Streamlit 동적 컴포넌트의 수명
    # 주기와 얽히지 않는다.
    steps = [
        Tour.bind(
            "open_settings_dialog_button",
            title=tr("Onboarding Model Settings Title"),
            desc=tr("Onboarding Model Settings Description"),
            side="bottom",
            align="end",
        ),
        Tour.bind(
            "main_settings_grid",
            title=tr("Onboarding Creation Settings Title"),
            desc=tr("Onboarding Creation Settings Description"),
            side="top",
            align="center",
        ),
        Tour.bind(
            "generate_video_button",
            title=tr("Onboarding Generate Video Title"),
            desc=tr("Onboarding Generate Video Description"),
            side="top",
            align="center",
        ),
    ]

    # streamlit-tour 1.1.0 은 Python 생성자 인자로 내비게이션 문구를 노출하지 않지만, 하위의
    # Driver.js 는 각 단계 popover 설정에서 버튼 텍스트를 덮어쓰는 것을 지원한다. 여기서 현지화
    # 문구를 한꺼번에 주입하고 내용을 HTML 이스케이프한다. 컴포넌트가 이 필드들을 innerHTML 로
    # 렌더링하기 때문이다.
    previous_text = html.escape(tr("Onboarding Previous"))
    next_text = html.escape(tr("Onboarding Next"))
    done_text = html.escape(tr("Onboarding Done"))
    for index, step in enumerate(steps):
        step.popover["prevBtnText"] = f"&larr; {previous_text}"
        # Driver.js 는 단계별 설정을 병합할 때, 변수를 이미 치환한 진행 템플릿을 덮어쓴다. 그래서
        # 현재 단계와 전체 단계 수를 직접 써넣어 페이지에 해석되지 않은 {{current}} 자리표시자가
        # 보이지 않게 한다.
        step.popover["progressText"] = f"{index + 1} / {len(steps)}"
        if index == len(steps) - 1:
            step.popover["doneBtnText"] = done_text
        else:
            step.popover["nextBtnText"] = f"{next_text} &rarr;"

    tour = Tour(
        steps=steps,
        key=ONBOARDING_TOUR_KEY,
        show_progress=True,
        animate=True,
        overlay_opacity=0.55,
        one_time_tour=True,
    )

    # Streamlit 세션마다 한 번만 직접 시작한다. 이미 끝냈는지는 컴포넌트가 브라우저 localStorage 로
    # 판정하므로, 페이지 rerun 이나 일반 위젯 조작 때문에 안내가 반복해서 뜨지 않는다.
    auto_start_key = f"{ONBOARDING_TOUR_KEY}-auto-started"
    if not st.session_state.get(auto_start_key, False):
        st.session_state[auto_start_key] = True
        tour.start()


def _render_generation_logs(task_id):
    """백그라운드 작업 로그 스냅샷을 그린다. 작업 스레드에서 Streamlit 세션 상태에 접근하지 않는다."""
    if config.ui.get("hide_log", False):
        return

    log_records = webui_task.get_task_logs(task_id)
    if not log_records:
        return

    st.code("\n".join(log_records))


def _render_generation_task_snapshot(task_id, task):
    """상태 저장소의 스냅샷을 바탕으로 진행률, 실패 원인, 최종 결과물을 그린다."""
    if not task:
        st.info(tr("Generating Video"))
        _render_generation_logs(task_id)
        return

    state = _normalize_task_state(task.get("state"))
    progress = max(0, min(100, int(task.get("progress", 0) or 0)))
    if state == const.TASK_STATE_PROCESSING:
        st.info(tr("Generating Video"))
        st.progress(
            progress,
            text=f"{tr('Task Progress')}: {progress}%",
        )
        _render_generation_logs(task_id)
        return

    if state == const.TASK_STATE_FAILED:
        error = str(task.get("error") or "").strip()
        message = tr("Video Generation Failed")
        st.error(f"{message}: {error}" if error else message)
        _render_generation_logs(task_id)
        return

    video_files = task.get("videos") or []
    if state != const.TASK_STATE_COMPLETE or not video_files:
        st.error(tr("Video Generation Failed"))
        _render_generation_logs(task_id)
        return

    st.success(tr("Video Generation Completed"))
    for warning in task.get("warnings") or []:
        if isinstance(warning, Mapping) and warning.get("code") == "sonilo_bgm_failed":
            st.warning(
                tr("Sonilo BGM Fallback Warning").format(
                    index=warning.get("video_index", "")
                )
            )
        elif (
            isinstance(warning, Mapping)
            and warning.get("code") == "elevenlabs_bgm_failed"
        ):
            st.warning(
                tr("ElevenLabs BGM Fallback Warning").format(
                    index=warning.get("video_index", "")
                )
            )
        else:
            st.warning(str(warning))

    try:
        player_cols = st.columns(len(video_files) * 2 + 1)
        for i, url in enumerate(video_files):
            player_cols[i * 2 + 1].video(url)
    except Exception as exc:
        logger.exception(
            f"failed to render generated video preview: task_id={task_id}, "
            f"video_files={video_files}, error={exc}"
        )

    _render_generation_logs(task_id)
    if st.session_state.get("opened_generation_task_id") != task_id:
        # 예전 동기 흐름은 생성이 끝나면 작업 디렉터리를 자동으로 열었다. Fragment 는 반복 실행될 수
        # 있으므로 세션 표시로 작업마다 한 번만 열리게 해, Finder/탐색기가 연달아 뜨는 것을 막는다.
        st.session_state["opened_generation_task_id"] = task_id
        open_task_folder(task_id)
        logger.info(f"{tr('Video Generation Completed')}: task_id={task_id}")


@st.fragment(run_every=webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS)
def _render_running_generation_task(task_id):
    """작업이 도는 동안에만 폴링한다. 끝나면 정적 결과로 되돌려 불필요한 주기 갱신을 멈춘다."""
    try:
        task = sm.state.get_task(task_id)
    except Exception as exc:
        logger.exception(
            f"failed to query WebUI generation task: task_id={task_id}, error={exc}"
        )
        st.error(tr("Video Generation Failed"))
        return

    state = _normalize_task_state((task or {}).get("state"))
    if state in {const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED}:
        _remove_active_generation_task(task_id)
        # 이제 전체 페이지 스크립트에는 오래 걸리는 생성 로직이 없으므로 안전하게 rerun 해 결과를
        # 정적 렌더링으로 바꿀 수 있다. 그래야 작업이 끝난 뒤 브라우저에 2 초 폴링 Fragment 가
        # 영구히 남지 않는다.
        st.rerun(scope="app")

    _render_generation_task_snapshot(task_id, task)


def _render_current_generation_task():
    """생성 버튼 아래에, 현재 페이지에서 마지막으로 제출한 작업을 조회할 수 있는 UI 를 되살린다."""
    task_id = st.session_state.get("current_generation_task_id", "")
    if not task_id:
        return

    try:
        task = sm.state.get_task(task_id)
    except Exception as exc:
        logger.exception(
            f"failed to query current WebUI task: task_id={task_id}, error={exc}"
        )
        st.error(tr("Video Generation Failed"))
        return

    state = _normalize_task_state((task or {}).get("state"))
    if state in {const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED}:
        _remove_active_generation_task(task_id)
        _render_generation_task_snapshot(task_id, task)
        return

    _render_running_generation_task(task_id)


def get_llm_provider_tips(provider_id, **kwargs):
    # LLM provider 설명 문구는 `llm_provider_tips.<provider_id>` 규칙으로 통일한다.
    # 그래야 provider 를 추가할 때 locale 에 문구만 채우면 되고, 문구가 없으면 설명 블록을
    # 그리지 않아 Main.py 에 하드코딩된 설명이 계속 쌓이지 않는다.
    provider = get_llm_provider(provider_id)
    if provider is None:
        return ""

    # Provider 설정 설명은 현재 중국어와 영어 두 벌의 표준 템플릿만 관리한다. 다른 화면 언어는
    # 영어를 쓴다. locale 에 영어를 복사해 둔 뒤 오래도록 동기화되지 않는 상황을 피하기 위해서다.
    # 어떤 언어가 전량 번역을 마치면 그때 여기 독립 관리 범위에 추가한다.
    ui_language = st.session_state.get("ui_language", "en")
    tips_language = ui_language if ui_language in {"zh", "en"} else "en"
    tips = (
        locales.get(tips_language, {}).get("Translation", {}).get(provider.tips_key, "")
    )
    if not tips:
        return tips

    format_context = {
        "api_key_url": provider.api_key_url,
        "default_model": provider.default_model,
        "default_base_url": provider.default_base_url,
        **{
            f"default_{field.config_suffix}": field.default_value
            for field in provider.extra_fields
        },
        **kwargs,
    }
    try:
        return tips.format(**format_context)
    except Exception as e:
        logger.warning(f"format llm provider tips failed: {provider_id}, {e}")
        return tips


def get_llm_provider_label(provider):
    return tr_optional(provider.label_key) or provider.default_label


def get_tts_provider_tips(provider_id):
    # TTS 설정 설명도 LLM Provider 와 같은 관리 전략을 쓴다. 중국어와 영어만 관리하고 다른 화면
    # 언어는 영어로 되돌린다. 복사해 둔 뒤 오래도록 동기화되지 않는 것을 피하기 위해서다.
    ui_language = st.session_state.get("ui_language", "en")
    tips_language = ui_language if ui_language in {"zh", "en"} else "en"
    return (
        locales.get(tips_language, {})
        .get("Translation", {})
        .get(f"tts_provider_tips.{provider_id}", "")
    )


def localized_widget_key(name, *parts):
    # 일부 Streamlit selectbox 는 안정적인 key 로 선택 상태를 기억하지만 표시 텍스트는 locale 에서 온다.
    # 언어를 바꿀 때 언어도 key 에 넣으면 위젯이 강제로 다시 만들어져, 선택 항목이 예전 언어로
    # 남아 보이는 것을 막을 수 있다.
    language = st.session_state.get("ui_language", config.ui.get("language", ""))
    suffix_parts = [name, language, *[str(part) for part in parts if part]]
    return "_".join(suffix_parts)


def stable_selectbox(label, options, default_value, key, format_func=None, **kwargs):
    # Streamlit 1.59 는 selectbox 의 상태 재사용에 더 민감하다. 위젯에 고정 key 가 없거나 실제
    # 옵션이 임시 인덱스 묶음일 뿐이면, 페이지 rerun 뒤 다시 계산된 index 에 덮이기 쉽다. 사용자
    # 입장에서는 첫 선택이 먹히지 않아 다시 골라야 하는 것으로 나타난다. 이 helper 는 안정적인
    # 업무 값을 실제 옵션으로 쓰고 그 값을 session_state 에 보관한다. 표시 문구는 format_func 으로만
    # 변환해, 번역 문구·옵션 순서·상위 설정 변화가 선택 상태에 영향을 주지 않게 한다.
    options = list(options)
    if not options:
        raise ValueError(f"selectbox options cannot be empty: {key}")

    if default_value not in options:
        default_value = options[0]

    widget_key = localized_widget_key(key)
    selected_value = st.session_state.get(widget_key)
    if selected_value not in options:
        # 상위 옵션이 바뀌면 (예: TTS provider 를 바꿔 음성 목록이 달라진 경우) 예전 값은 더 이상
        # 유효하지 않다. 위젯을 만들기 전에 session_state 를 초기화하고, 이후에는 key 만 상태를
        # 관리하게 하며 index 를 함께 넘기지 않는다. 그래야 rerun 때 Streamlit 이 다시 계산한
        # index 로 사용자가 방금 고른 값을 덮어써 첫 선택이 먹히지 않는 일을 막을 수 있다.
        st.session_state[widget_key] = default_value

    if format_func is None:
        format_func = str

    return st.selectbox(
        label,
        options=options,
        format_func=format_func,
        key=widget_key,
        **kwargs,
    )


def sync_script_order_concat_mode():
    """대본 순서 매칭이 켜져 있으면 순차 이어붙이기로 고정하고, 꺼지면 원래 선택을 되돌린다."""
    widget_key = localized_widget_key("video_concat_mode_select")
    previous_key = "video_concat_mode_before_script_order_match"
    match_script_order = bool(st.session_state.get("match_materials_to_script", False))

    if match_script_order:
        current_mode = st.session_state.get(widget_key, VideoConcatMode.random.value)
        if current_mode != VideoConcatMode.sequential.value:
            st.session_state[previous_key] = current_mode
        st.session_state[widget_key] = VideoConcatMode.sequential.value
        return

    previous_mode = st.session_state.pop(previous_key, None)
    if previous_mode in {
        VideoConcatMode.sequential.value,
        VideoConcatMode.random.value,
    }:
        st.session_state[widget_key] = previous_mode


def reset_script_system_prompt():
    """고급 대본 설정의 시스템 프롬프트를 현재 선택한 스타일의 기본 내용으로 되돌린다."""
    # stable_selectbox 는 언어별 key 로 상태를 보관한다. 원래 key 로 읽으면 항상
    # 비어 있어서, 어떤 스타일을 골라도 기본 프롬프트로 되돌아간다.
    style = st.session_state.get(
        localized_widget_key("script_style_select"),
        st.session_state.get("script_style", llm.DEFAULT_SCRIPT_STYLE),
    )
    st.session_state["script_style"] = style
    st.session_state["custom_system_prompt"] = llm.script_style_prompt(style)


def reset_subtitle_settings():
    """WebUI 자막 위젯과 저장된 설정을 기본값으로 되돌린다."""
    defaults = DEFAULT_SUBTITLE_SETTINGS
    st.session_state["subtitle_enabled_checkbox"] = defaults["subtitle_enabled"]
    _set_stable_widget_value("font_name_select", defaults["font_name"])
    _set_stable_widget_value("subtitle_position_select", defaults["subtitle_position"])
    st.session_state["custom_position_input"] = str(defaults["custom_position"])
    st.session_state["font_color_picker"] = defaults["text_fore_color"]
    st.session_state["font_size_slider"] = defaults["font_size"]
    st.session_state["stroke_color_picker"] = defaults["stroke_color"]
    st.session_state["stroke_width_slider"] = defaults["stroke_width"]
    st.session_state["subtitle_background_enabled_checkbox"] = defaults[
        "subtitle_background_enabled"
    ]
    st.session_state["subtitle_background_color_picker"] = defaults[
        "subtitle_background_color"
    ]
    st.session_state["rounded_subtitle_background_checkbox"] = defaults[
        "rounded_subtitle_background"
    ]

    # 저장되는 UI 옵션도 함께 맞춰, 되돌린 뒤 페이지를 새로고침해도 기본 설정이 유지되게 한다.
    for key in (
        "font_name",
        "subtitle_position",
        "custom_position",
        "text_fore_color",
        "font_size",
        "subtitle_background_enabled",
        "subtitle_background_color",
        "rounded_subtitle_background",
    ):
        config.ui[key] = defaults[key]


@st.dialog(tr("Final Prompt Preview"), width="large")
def render_script_prompt_preview(prompt):
    """모델에 보낼 전체 대본 생성 프롬프트를 보여 준다."""
    st.code(prompt, language="markdown", wrap_lines=True)


def stable_segmented_control(
    label, options, default_value, key, format_func=None, **kwargs
):
    """안정적인 업무 값으로 단일 선택 분할 위젯을 만든다. 언어를 바꾼 뒤 상태가 표시 문구에 덮이지 않게 하기 위해서다."""
    options = list(options)
    if not options:
        raise ValueError(f"segmented control options cannot be empty: {key}")

    if default_value not in options:
        default_value = options[0]

    widget_key = localized_widget_key(key)
    if st.session_state.get(widget_key) not in options:
        st.session_state[widget_key] = default_value

    return st.segmented_control(
        label,
        options=options,
        selection_mode="single",
        required=True,
        format_func=format_func or str,
        key=widget_key,
        **kwargs,
    )


@st.cache_data(ttl=300, show_spinner=False)
def get_groq_model_ids(api_key: str, base_url: str) -> list[str]:
    if not api_key:
        return []

    normalized_base_url = (
        (base_url or "https://api.groq.com/openai/v1").strip().rstrip("/")
    )
    models_url = f"{normalized_base_url}/models"

    try:
        response = requests.get(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])

        model_ids = []
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_ids.append(model_id.strip())

        return sorted(set(model_ids))
    except Exception as e:
        logger.warning(f"failed to fetch groq models: {e}")
        return []


def _get_material_api_keys(config_key):
    """설정의 소재 API 키를 WebUI 에서 편집 가능한 문자열로 변환한다."""
    api_keys = config.app.get(config_key, [])
    if isinstance(api_keys, str):
        api_keys = [api_keys]
    return ", ".join(api_keys)


def _save_material_api_keys(config_key, value):
    """쉼표로 구분된 소재 API 키를 저장하고, 사용자가 예전 설정을 명시적으로 비울 수 있게 한다."""
    normalized_value = value.replace(" ", "")
    config.app[config_key] = normalized_value.split(",") if normalized_value else []


def _format_file_size(size_bytes):
    """바이트 수를 설정 화면에 표시하기 좋은 간결한 용량 문구로 만든다."""
    size = float(max(0, size_bytes))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


@st.cache_data(ttl=30, show_spinner=False)
def _get_video_cache_stats(max_age_days=None):
    """
    디렉터리 통계를 짧은 주기로 캐시해, 설정 팝업 안에서 위젯을 조작할 때마다 많은 파일을 반복
    스캔하지 않게 한다.

    캐시 키에 정리 일수가 들어 있어 범위를 바꿔도 범위마다 한 번씩만 스캔한다. 직접 새로고침하거나
    정리가 끝나면 명시적으로 비우므로, 최대 30 초짜리 캐시가 실제 삭제 시의 재스캔에 영향을 주지 않는다.
    """
    return cache_manager.get_video_cache_stats(max_age_days=max_age_days)


def _render_cache_management_settings(panel):
    """기본 온라인 영상 소재 캐시의 통계, 미리보기, 안전한 정리 동작을 그린다."""
    with panel:
        cleanup_message = st.session_state.pop("video_cache_cleanup_message", None)
        if cleanup_message:
            message_type, message = cleanup_message
            if message_type == "success":
                st.success(message)
            else:
                st.warning(message)

        st.caption(tr("Video Cache Directory"))
        st.code(cache_manager.video_cache_dir(), language="text")

        total_stats = _get_video_cache_stats()
        metric_count, metric_size, metric_oldest = st.columns(3)
        metric_count.metric(tr("Cache File Count"), total_stats.file_count)
        metric_size.metric(
            tr("Cache Total Size"), _format_file_size(total_stats.total_size)
        )
        oldest_text = (
            datetime.fromtimestamp(total_stats.oldest_mtime).strftime("%Y-%m-%d")
            if total_stats.oldest_mtime is not None
            else "-"
        )
        metric_oldest.metric(tr("Oldest Cache Date"), oldest_text)

        st.caption(tr("Video Cache Management Help"))
        cleanup_options = (30, 7, 90, None)
        cleanup_labels = {
            30: tr("Cache Older Than 30 Days"),
            7: tr("Cache Older Than 7 Days"),
            90: tr("Cache Older Than 90 Days"),
            None: tr("All Video Cache"),
        }
        max_age_days = st.selectbox(
            tr("Cache Cleanup Range"),
            options=cleanup_options,
            format_func=lambda value: cleanup_labels[value],
            key="video_cache_cleanup_range",
        )
        cleanup_preview = _get_video_cache_stats(max_age_days=max_age_days)
        st.info(
            tr("Cache Cleanup Preview").format(
                count=cleanup_preview.file_count,
                size=_format_file_size(cleanup_preview.total_size),
            )
        )

        confirm_nonce = st.session_state.get("video_cache_cleanup_confirm_nonce", 0)
        confirmed = st.checkbox(
            tr("Confirm Cache Cleanup"),
            key=f"video_cache_cleanup_confirm_{confirm_nonce}",
        )
        refresh_col, open_col, cleanup_col = st.columns(3)
        if refresh_col.button(
            tr("Refresh Cache Stats"),
            key="refresh_video_cache_stats",
            use_container_width=True,
            icon=":material/refresh:",
        ):
            _get_video_cache_stats.clear()
            st.rerun(scope="fragment")

        if open_col.button(
            tr("Open Cache Directory"),
            key="open_video_cache_directory",
            use_container_width=True,
            icon=":material/folder_open:",
        ):
            webbrowser.open(Path(cache_manager.video_cache_dir()).as_uri())

        cleanup_disabled = not confirmed or cleanup_preview.file_count == 0
        if cleanup_col.button(
            tr("Clean Cache Now"),
            key="clean_video_cache_now",
            type="primary",
            disabled=cleanup_disabled,
            use_container_width=True,
            icon=":material/delete_sweep:",
        ):
            result = cache_manager.clean_video_cache(max_age_days=max_age_days)
            message_key = (
                "Cache Cleanup Completed With Failures"
                if result.failed_count
                else "Cache Cleanup Completed"
            )
            st.session_state["video_cache_cleanup_message"] = (
                "warning" if result.failed_count else "success",
                tr(message_key).format(
                    count=result.deleted_count,
                    size=_format_file_size(result.deleted_size),
                    failed=result.failed_count,
                ),
            )
            # Streamlit 은 위젯을 만든 뒤 같은 이름의 session_state 를 고치는 것을 허용하지 않는다.
            # nonce 를 증가시켜 다음 fragment rerun 에서 체크되지 않은 새 위젯이 만들어지게 해,
            # 정리가 끝난 뒤에도 위험한 확인 상태가 남아 있는 것을 막는다.
            st.session_state["video_cache_cleanup_confirm_nonce"] = confirm_nonce + 1
            _get_video_cache_stats.clear()
            st.rerun(scope="fragment")


# -----------------------------------------------------------------------------
# 설정 및 프롬프트 팝업
# -----------------------------------------------------------------------------


# 설정은 자주 하는 작업이 아니므로 중간 크기 Dialog 를 써서 메인 페이지의 세로 공간을 오래
# 차지하지 않게 하고, 읽기 좋은 줄 너비를 유지해 넓은 화면에서 팝업이 너무 헐거워 보이지 않게 한다.
# Dialog 는 fragment 동작을 물려받아 내부 위젯 조작 시 팝업만 다시 그린다. 함수 끝에서 설정을
# 따로 저장하고, 닫을 때 콜백으로 페이지 전체를 동기화해 생성 흐름이 최신 Provider 와 화면
# 설정을 읽도록 보장한다.
@st.dialog(
    tr("Settings"),
    width="medium",
    on_dismiss=_dismiss_settings_dialog,
)
def _render_settings_dialog():
    with st.container():
        # 예전 hide_config 는 옛 기본 설정 패널을 숨기는 용도였다. 고정 설정 진입점으로 바뀐 뒤로는
        # 사용자에게 보이는 의미가 없으므로 일괄로 false 로 옮겨, 예전 설정이 이후 버전에 영향을
        # 주지 않게 한다.
        config.app["hide_config"] = False
        (
            middle_config_panel,
            right_config_panel,
            cache_config_panel,
            left_config_panel,
        ) = st.tabs(
            [
                tr("LLM Settings Tab"),
                tr("Material API Tab"),
                tr("Cache Management Tab"),
                tr("Interface Settings Tab"),
            ]
        )

        # 왼쪽 패널 - 로그 설정
        with left_config_panel:
            hide_log = st.checkbox(
                tr("Hide Log"),
                value=config.ui.get("hide_log", False),
                key="hide_log_checkbox",
            )
            config.ui["hide_log"] = hide_log

        _render_cache_management_settings(cache_config_panel)

        # 가운데 패널 - LLM 설정

        with middle_config_panel:
            # 드롭다운 순서, 기본 label, 안정적인 provider id 는 모두 Registry 에서 온다. locale 은
            # 표시 문구만 덮어쓰며, Main.py 가 Provider 목록을 두 번째로 관리하지 않게 한다.
            llm_provider_ids = [
                provider.provider_id for provider in LLM_PROVIDER_REGISTRY
            ]
            llm_provider_labels = {
                provider.provider_id: get_llm_provider_label(provider)
                for provider in LLM_PROVIDER_REGISTRY
            }
            saved_llm_provider = config.app.get(
                "llm_provider", DEFAULT_LLM_PROVIDER_ID
            ).lower()
            if saved_llm_provider not in llm_provider_ids:
                saved_llm_provider = DEFAULT_LLM_PROVIDER_ID

            llm_provider = stable_selectbox(
                tr("LLM Provider"),
                options=llm_provider_ids,
                default_value=saved_llm_provider,
                key="llm_provider_select",
                format_func=lambda provider_id: llm_provider_labels[provider_id],
            )
            # 설정 폼과 Provider 설명을 나란히 배치해, 긴 설명이 좁은 열에서 줄바꿈되는 것을 줄이고
            # 기본 설정 패널의 가로 공간도 충분히 활용한다.
            llm_form_panel, llm_help_panel = st.columns(
                [0.9, 1.1],
                gap="large",
                vertical_alignment="top",
            )
            llm_helper = llm_help_panel.container()
            config.app["llm_provider"] = llm_provider
            llm_provider_spec = get_llm_provider(llm_provider)
            if llm_provider_spec is None:
                # 정상적인 경우 드롭다운 옵션은 모두 Registry 에서 오므로 이 분기로 들어오지 않는다.
                # 손상된 session state 나 이후 연동 누락을 진단할 수 있게 명확한 오류를 남긴다.
                raise RuntimeError(f"unsupported llm provider: {llm_provider}")

            llm_api_key = config.app.get(llm_provider_spec.config_key("api_key"), "")
            llm_base_url = (
                config.app.get(llm_provider_spec.config_key("base_url"), "")
                or llm_provider_spec.default_base_url
            )
            llm_default_base_url = llm_provider_spec.default_base_url
            llm_model_name = llm_provider_spec.resolve_model_name(
                config.app.get(llm_provider_spec.config_key("model_name"), "")
            )

            provider_tip_context = {}
            if llm_provider == "ollama":
                llm_default_base_url = config.get_default_ollama_base_url()
                if not llm_base_url:
                    llm_base_url = llm_default_base_url
                docker_hint = ""
                if config.is_running_in_container():
                    docker_hint = tr_optional(
                        "llm_provider_tips.ollama.docker_hint",
                        fallback_language="en",
                    )
                provider_tip_context["docker_hint"] = docker_hint

            tips = get_llm_provider_tips(llm_provider, **provider_tip_context)
            if tips:
                with llm_helper:
                    st.info(tips)

            st_llm_api_key = llm_api_key
            if llm_provider_spec.show_api_key:
                st_llm_api_key = llm_form_panel.text_input(
                    tr("API Key"),
                    value=llm_api_key,
                    type="password",
                    key=f"{llm_provider}_api_key_input",
                )

            st_llm_base_url = llm_base_url
            if llm_provider_spec.show_base_url:
                st_llm_base_url = llm_form_panel.text_input(
                    tr("Base Url"),
                    value=llm_base_url,
                    key=f"{llm_provider}_base_url_input",
                )
            st_llm_model_name = ""
            if llm_provider == "groq":
                effective_api_key = st_llm_api_key or llm_api_key
                effective_base_url = st_llm_base_url or llm_base_url
                groq_models = get_groq_model_ids(
                    api_key=effective_api_key,
                    base_url=effective_base_url,
                )

                if groq_models:
                    selected_index = 0
                    if llm_model_name in groq_models:
                        selected_index = groq_models.index(llm_model_name)

                    st_llm_model_name = llm_form_panel.selectbox(
                        tr("Model Name"),
                        options=groq_models,
                        index=selected_index,
                        key="groq_model_name_select",
                    )
                else:
                    st_llm_model_name = llm_form_panel.text_input(
                        tr("Model Name"),
                        value=llm_model_name,
                        key="groq_model_name_input",
                    )
                    if effective_api_key:
                        llm_form_panel.caption(tr("Groq Model List Load Failed"))
                    else:
                        llm_form_panel.caption(
                            tr("Groq API Key Required for Model List")
                        )
            else:
                st_llm_model_name = llm_form_panel.text_input(
                    tr("Model Name"),
                    value=llm_model_name,
                    key=f"{llm_provider}_model_name_input",
                )
            # 입력란은 Registry 기본값을 보여 주지만, 설정에는 실제 사용자 재정의 값만 저장한다.
            # 그래야 기본 모델이나 Base URL 이 바뀌었을 때 직접 설정하지 않은 사용자는 자동으로 따라간다.
            config.app[llm_provider_spec.config_key("api_key")] = st_llm_api_key
            config.app[llm_provider_spec.config_key("base_url")] = (
                normalize_provider_override(
                    st_llm_base_url,
                    llm_default_base_url,
                )
            )
            config.app[llm_provider_spec.config_key("model_name")] = (
                normalize_provider_override(
                    st_llm_model_name,
                    llm_provider_spec.default_model,
                )
            )

            # Provider 전용 필드도 Registry 가 선언한다. 예를 들어 Cloudflare AI Gateway 는 Account ID 가
            # 필요하다. 앞으로 비슷한 필드를 추가할 때 Main.py 에 판정을 더 넣지 않아도 된다.
            for field in llm_provider_spec.extra_fields:
                field_config_key = llm_provider_spec.config_key(field.config_suffix)
                field_value = llm_form_panel.text_input(
                    tr(field.label_key),
                    value=(config.app.get(field_config_key, "") or field.default_value),
                    type="password" if field.secret else "default",
                    key=f"{llm_provider}_{field.config_suffix}_input",
                )
                config.app[field_config_key] = normalize_provider_override(
                    field_value,
                    field.default_value,
                )

            if llm_form_panel.button(
                tr("Test LLM Connection"),
                key="test_llm_connection_button",
                use_container_width=True,
                type="secondary",
                icon=":material/network_check:",
            ):
                with llm_form_panel.spinner(tr("Testing LLM Connection")):
                    with config.runtime_config_lock():
                        connection_ok, connection_error, connection_elapsed = (
                            llm.test_connection()
                        )

                if connection_ok:
                    llm_form_panel.success(
                        tr("LLM Connection Test Succeeded").format(
                            provider=llm_provider_labels[llm_provider],
                            model=st_llm_model_name or "-",
                            elapsed=f"{connection_elapsed:.2f}",
                        )
                    )
                else:
                    llm_form_panel.error(
                        tr("LLM Connection Test Failed").format(error=connection_error)
                    )

        # 오른쪽 패널 - API 키 설정
        with right_config_panel:
            pexels_api_key = _get_material_api_keys("pexels_api_keys")
            pexels_api_key = st.text_input(
                tr("Pexels API Key"),
                value=pexels_api_key,
                type="password",
                key="pexels_api_keys_input",
            )
            _save_material_api_keys("pexels_api_keys", pexels_api_key)

            pixabay_api_key = _get_material_api_keys("pixabay_api_keys")
            pixabay_api_key = st.text_input(
                tr("Pixabay API Key"),
                value=pixabay_api_key,
                type="password",
                key="pixabay_api_keys_input",
            )
            _save_material_api_keys("pixabay_api_keys", pixabay_api_key)

            coverr_api_key = _get_material_api_keys("coverr_api_keys")
            coverr_api_key = st.text_input(
                tr("Coverr API Key"),
                value=coverr_api_key,
                type="password",
                key="coverr_api_keys_input",
            )
            _save_material_api_keys("coverr_api_keys", coverr_api_key)

    config.save_config()


# -----------------------------------------------------------------------------
# 메인 생성 폼: 대본, 영상, 오디오, 자막 패널
# -----------------------------------------------------------------------------


def _render_script_settings(panel, params):
    """대본 설정을 그리고 생성 파라미터를 갱신한다."""
    with panel:
        with st.container(border=True):
            st.write(tr("Video Script Settings"))
            params.video_subject = st.text_input(
                tr("Video Subject"),
                placeholder=tr("Video Subject Placeholder"),
                key="video_subject",
            ).strip()

            video_languages = [
                (tr("Auto Detect"), ""),
            ]
            for code in support_locales:
                video_languages.append((code, code))

            selected_language_code = stable_selectbox(
                tr("Script Language"),
                options=[value for _, value in video_languages],
                default_value="",
                key="script_language_select",
                format_func=lambda value: dict(
                    (v, label) for label, v in video_languages
                )[value],
            )
            params.video_language = selected_language_code

            # key 가 붙은 국소 컨테이너로 접기 진입점 스타일의 적용 범위를 한정한다. expander 의 기본
            # 상호작용은 유지하면서, 페이지 상단의 '기본 설정' 같은 다른 접기 영역이 스타일에 휘말리지
            # 않게 하기 위해서다.
            with st.container(key="advanced_settings_script"):
                with st.expander(tr("Advanced Script Settings"), expanded=False):
                    st.session_state.setdefault("paragraph_number_input", 1)
                    params.paragraph_number = st.slider(
                        tr("Script Paragraph Number"),
                        min_value=llm.MIN_SCRIPT_PARAGRAPH_NUMBER,
                        max_value=llm.MAX_SCRIPT_PARAGRAPH_NUMBER,
                        key="paragraph_number_input",
                    )
                    params.video_script_prompt = st.text_area(
                        tr("Custom Script Requirements"),
                        height=100,
                        max_chars=llm.MAX_SCRIPT_PROMPT_LENGTH,
                        placeholder=tr("Custom Script Requirements Placeholder"),
                        key="video_script_prompt",
                    ).strip()

                    # 라벨은 위젯을 만들기 전에 확정한다. format_func 안에서 tr() 을 부르면
                    # 화면 실행 밖에서 위젯 상태를 읽을 때 예외가 나고, 그러면 선택값이
                    # 표시 라벨과 매칭되지 않는다.
                    script_style_labels = {
                        name: tr(f"Script Style {name}")
                        for name in sorted(llm.SCRIPT_STYLE_PROMPTS)
                    }
                    # 위젯 key 에는 언어가 붙는다. 언어를 바꾸면 새 key 가 기본값으로
                    # 시작해 고른 스타일이 사라지는데, 시스템 프롬프트는 그대로 남아
                    # 화면 표시와 실제로 쓰이는 프롬프트가 어긋난다. 언어와 무관한
                    # 정규 값을 따로 두고 위젯을 거기서 되살린다.
                    params.script_style = stable_selectbox(
                        tr("Script Style"),
                        options=sorted(llm.SCRIPT_STYLE_PROMPTS),
                        default_value=st.session_state.get(
                            "script_style", llm.DEFAULT_SCRIPT_STYLE
                        ),
                        key="script_style_select",
                        format_func=script_style_labels.__getitem__,
                        # 스타일을 바꾸면 아래 프롬프트도 그 스타일의 기본값으로 따라간다.
                        # 그러지 않으면 고른 스타일과 실제로 쓰이는 프롬프트가 어긋난다.
                        on_change=reset_script_system_prompt,
                    )
                    st.session_state["script_style"] = params.script_style

                    system_prompt = st.text_area(
                        tr("Custom System Prompt"),
                        height=240,
                        max_chars=llm.MAX_SCRIPT_SYSTEM_PROMPT_LENGTH,
                        key="custom_system_prompt",
                    ).strip()
                    # 기본 내용은 서비스 계층이 한곳에서 관리한다. 화면은 기본 프롬프트를 그대로 보여
                    # 주지만, 사용자가 실제로 고쳤을 때만 작업과 함께 전달한다. 지난 작업에 예전 버전의
                    # 기본 규칙이 굳어 버리는 것을 막기 위해서다.
                    params.custom_system_prompt = (
                        ""
                        if system_prompt
                        == llm.script_style_prompt(params.script_style).strip()
                        else system_prompt
                    )

                    restore_prompt_col, preview_prompt_col = st.columns(2)
                    if restore_prompt_col.button(
                        tr("Restore Default System Prompt"),
                        key="restore_default_system_prompt",
                        icon=":material/restart_alt:",
                        on_click=reset_script_system_prompt,
                        use_container_width=True,
                    ):
                        st.toast(tr("Default System Prompt Restored"))
                    if preview_prompt_col.button(
                        tr("Preview Final Prompt"),
                        key="preview_final_script_prompt",
                        icon=":material/preview:",
                        use_container_width=True,
                    ):
                        render_script_prompt_preview(
                            llm.build_script_prompt(
                                video_subject=params.video_subject,
                                language=params.video_language,
                                paragraph_number=params.paragraph_number,
                                video_script_prompt=params.video_script_prompt,
                                custom_system_prompt=params.custom_system_prompt,
                                script_style=params.script_style,
                            )
                        )

            if st.button(
                tr("Generate Video Script and Keywords"),
                key="auto_generate_script",
                use_container_width=True,
                type="secondary",
                icon=":material/auto_awesome:",
            ):
                if not params.video_subject:
                    # 영상 주제는 대본 생성의 필수 입력이다. 미리 막으면 의미 없는 모델 호출을 피할 수 있다.
                    st.toast(tr("Please Enter the Video Subject First"))
                    st.warning(tr("Please Enter the Video Subject First"))
                else:
                    with st.spinner(tr("Generating Video Script and Keywords")):
                        with config.runtime_config_lock():
                            script = llm.generate_script(
                                video_subject=params.video_subject,
                                language=params.video_language,
                                paragraph_number=params.paragraph_number,
                                video_script_prompt=params.video_script_prompt,
                                custom_system_prompt=params.custom_system_prompt,
                                script_style=params.script_style,
                            )
                            terms = llm.generate_terms(
                                params.video_subject,
                                script,
                                amount=8 if params.match_materials_to_script else 5,
                                match_script_order=params.match_materials_to_script,
                            )
                        if "Error: " in script:
                            st.error(tr(script))
                        elif "Error: " in terms:
                            st.error(tr(terms))
                        else:
                            st.session_state["video_script"] = script
                            st.session_state["video_terms"] = ", ".join(terms)
            params.video_script = st.text_area(
                tr("Video Script"),
                help=tr("Video Script Help"),
                height=180,
                key="video_script",
            )
            if st.button(
                tr("Generate Video Keywords"),
                key="auto_generate_terms",
                use_container_width=True,
                type="secondary",
                icon=":material/auto_awesome:",
            ):
                if not params.video_script:
                    # 영상 키워드는 대본에서 뽑아내야 하므로, 대본이 비어 있으면 미리 안내하고 모델 호출을 건너뛴다.
                    st.toast(tr("Please Enter the Video Subject"))
                    st.warning(tr("Please Enter the Video Subject"))
                else:
                    with st.spinner(tr("Generating Video Keywords")):
                        with config.runtime_config_lock():
                            terms = llm.generate_terms(
                                params.video_subject,
                                params.video_script,
                                amount=8 if params.match_materials_to_script else 5,
                                match_script_order=params.match_materials_to_script,
                            )
                        if "Error: " in terms:
                            st.error(tr(terms))
                        else:
                            st.session_state["video_terms"] = ", ".join(terms)

            params.video_terms = st.text_area(
                tr("Video Keywords"),
                help=tr("Video Keywords Help"),
                key="video_terms",
            )


def _render_video_settings(panel, params):
    """영상 설정을 그리고 이번에 고른 로컬 소재를 반환한다."""
    uploaded_files = []
    with panel:
        with st.container(border=True):
            st.write(tr("Video Settings"))
            video_concat_modes = [
                (tr("Sequential"), "sequential"),
                (tr("Random"), "random"),
            ]
            video_sources = [
                (tr("Pexels"), "pexels"),
                (tr("Pixabay"), "pixabay"),
                (tr("Coverr"), "coverr"),
                (tr("Local file"), "local"),
            ]

            saved_video_source_name = config.app.get("video_source", "pexels")

            params.video_source = stable_selectbox(
                tr("Video Source"),
                options=[value for _, value in video_sources],
                default_value=saved_video_source_name,
                key="video_source_select",
                format_func=lambda value: dict(
                    (v, label) for label, v in video_sources
                )[value],
            )
            config.app["video_source"] = params.video_source

            if params.video_source == "local":
                # Streamlit 의 파일 형식 검증은 확장자 대소문자를 구분하므로, 여기서 두 형태를 모두 허용한다.
                local_file_types = sorted(
                    extension.removeprefix(".")
                    for extension in LOCAL_MATERIAL_EXTENSIONS
                )
                uploaded_files = st.file_uploader(
                    tr("Upload Local Files"),
                    type=local_file_types
                    + [file_type.upper() for file_type in local_file_types],
                    accept_multiple_files=True,
                    key="local_video_materials_uploader",
                )

            # 대본 순서 매칭은 키워드 생성부터 최종 합성까지 서술 순서를 유지하므로, 켜져 있을 때는
            # 순차 이어붙이기가 실제 실행 로직과 맞는 유일한 선택이다. 위젯 값을 맞춰 두면 화면에
            # '무작위 이어붙이기' 가 계속 보이는 일이 없고, 사용자의 원래 선택은 남아 있다가 끄면
            # 자동으로 복원된다.
            sync_script_order_concat_mode()
            selected_concat_mode = stable_selectbox(
                tr("Video Concat Mode"),
                options=[value for _, value in video_concat_modes],
                default_value=VideoConcatMode.random.value,
                key="video_concat_mode_select",
                format_func=lambda value: dict(
                    (v, label) for label, v in video_concat_modes
                )[value],
                disabled=bool(st.session_state.get("match_materials_to_script", False)),
            )
            params.video_concat_mode = VideoConcatMode(selected_concat_mode)

            params.match_materials_to_script = st.checkbox(
                tr("Match Materials to Script Order"),
                help=tr("Match Materials to Script Order Help"),
                key="match_materials_to_script",
                on_change=sync_script_order_concat_mode,
            )
            config.app["match_materials_to_script"] = params.match_materials_to_script

            # 영상 전환 모드
            video_transition_modes = [
                (tr("None"), VideoTransitionMode.none.value),
                (tr("Shuffle"), VideoTransitionMode.shuffle.value),
                (tr("FadeIn"), VideoTransitionMode.fade_in.value),
                (tr("FadeOut"), VideoTransitionMode.fade_out.value),
                (tr("SlideIn"), VideoTransitionMode.slide_in.value),
                (tr("SlideOut"), VideoTransitionMode.slide_out.value),
                (tr("ZoomIn"), VideoTransitionMode.zoom_in.value),
                (tr("ZoomOut"), VideoTransitionMode.zoom_out.value),
            ]
            selected_transition_mode = stable_selectbox(
                tr("Video Transition Mode"),
                options=[value for _, value in video_transition_modes],
                default_value=VideoTransitionMode.none.value,
                key="video_transition_mode_select",
                format_func=lambda value: dict(
                    (v, label) for label, v in video_transition_modes
                )[value],
            )
            params.video_transition_mode = VideoTransitionMode(selected_transition_mode)

            video_aspect_ratios = [
                (tr("Portrait"), VideoAspect.portrait.value),
                (tr("Landscape"), VideoAspect.landscape.value),
            ]
            # Coverr 라이브러리는 99% 가 16:9 가로라, 기본값을 세로로 두면 화면이 검은 여백으로 둘러싸인다.
            # source 별 위젯 key 를 써서 각 source 가 aspect 선택을 따로 기억하게 한다.
            #   - coverr 로 처음 전환하면 → 기본값 Landscape(index=1)
            #   - 다른 source 는 Portrait(index=0) 을 그대로 쓴다
            #   - 특정 source 에서 사용자가 aspect 를 직접 바꿨다면 session_state 가 기억하고,
            #     다음에 같은 source 로 돌아왔을 때 그 선택을 존중해 다시 덮어쓰지 않는다.
            default_aspect_index = 1 if params.video_source == "coverr" else 0
            selected_aspect_ratio = stable_selectbox(
                tr("Video Ratio"),
                options=[value for _, value in video_aspect_ratios],
                default_value=video_aspect_ratios[default_aspect_index][1],
                key=f"video_aspect_for_{params.video_source}",
                format_func=lambda value: dict(
                    (v, label) for label, v in video_aspect_ratios
                )[value],
            )
            params.video_aspect = VideoAspect(selected_aspect_ratio)

            params.video_clip_duration = stable_selectbox(
                tr("Clip Duration"),
                options=[2, 3, 4, 5, 6, 7, 8, 9, 10],
                default_value=3,
                key="video_clip_duration_select",
                help=tr("Clip Duration Help"),
            )
            clip_speed_key = localized_widget_key("video_clip_speed_slider")
            # session_state 는 예전 작업, API 파라미터, 옛 페이지 상태에서 왔을 수 있다. 위젯을 만들기
            # 전에 한꺼번에 정규화해, 유효한 선택은 남기면서 slider 가 항상 0.5~2.0 범위의 유한한
            # 부동소수점 값을 받도록 보장한다.
            st.session_state[clip_speed_key] = utils.normalize_clip_speed(
                st.session_state.get(clip_speed_key, 1.0)
            )
            params.video_clip_speed = st.slider(
                tr("Clip Speed"),
                min_value=0.5,
                max_value=2.0,
                step=0.05,
                format="%.2fx",
                key=clip_speed_key,
                help=tr("Clip Speed Help"),
            )
            params.video_count = stable_selectbox(
                tr("Number of Videos Generated Simultaneously"),
                options=[1, 2, 3, 4, 5],
                default_value=1,
                key="video_count_select",
            )

            video_codec_options = [
                (tr("Default Video Encoder"), DEFAULT_VIDEO_CODEC_OPTION),
                ("libx264 (CPU)", "libx264"),
                ("NVIDIA NVENC (h264_nvenc)", "h264_nvenc"),
                ("AMD AMF (h264_amf)", "h264_amf"),
                ("Intel QSV (h264_qsv)", "h264_qsv"),
                ("Windows MediaFoundation (h264_mf)", "h264_mf"),
                ("macOS VideoToolbox (h264_videotoolbox)", "h264_videotoolbox"),
            ]
            saved_video_codec = config.app.get(
                "video_codec", DEFAULT_VIDEO_CODEC_OPTION
            )
            saved_video_codec_values = [item[1] for item in video_codec_options]
            if saved_video_codec not in saved_video_codec_values:
                # 예전 버전이나 수동 설정이 유효하지 않은 값을 남겼을 수 있다. UI 는 사용자를 대신해
                # 특정 인코더를 고정하지 않고 '기본값' 으로 되돌린다. 백엔드는 안정 정책에 따라
                # 계속 libx264 로 해석한다.
                saved_video_codec = DEFAULT_VIDEO_CODEC_OPTION
            selected_video_codec = stable_selectbox(
                tr("Video Encoder"),
                options=saved_video_codec_values,
                default_value=saved_video_codec,
                key="video_encoder_select",
                format_func=lambda value: dict(
                    (v, label) for label, v in video_codec_options
                )[value],
                help=tr("Video Encoder Help"),
            )
            if selected_video_codec == DEFAULT_VIDEO_CODEC_OPTION:
                # 기본 모드에서는 구체적인 인코더를 저장하지 않아, 설정이 '프로젝트 기본값을 따름' 을 나타내게 한다.
                config.app.pop("video_codec", None)
            else:
                config.app["video_codec"] = selected_video_codec
    return uploaded_files


def _estimate_voiceover_duration_range(
    text: str, voice_rate: float
) -> tuple[float, float] | None:
    """
    전체 나레이션 길이를 로컬에서 추정해 보수적인 상·하한 초를 반환한다.

    이 추정은 사용자가 유료 TTS 를 호출하기 전에 대본 분량을 가늠하는 데만 쓰이며 작업 실행에는
    관여하지 않는다. 한국어·중국어·일본어는 글자 속도로, 공백으로 단어를 나누는 다른 언어는 단어
    속도로 추정하고 흔한 문장 부호의 쉼을 더한다. Provider, 음색, 어조에 따라 실제와 차이가 나므로
    화면에는 정확한 척하는 단일 값이 아니라 구간을 보여 줘야 한다.
    """
    normalized_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized_text:
        return None

    script_chars = re.findall(
        r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]",
        normalized_text,
    )
    remaining_text = re.sub(
        r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]",
        " ",
        normalized_text,
    )
    words = re.findall(r"\b[\w]+(?:[-'’][\w]+)*\b", remaining_text, re.UNICODE)
    punctuation_count = len(re.findall(r"[,，.。!?！？;；:：]", normalized_text))

    # 초당 4.2 자, 초당 2.6 단어는 일상적인 해설 속도에 가깝다. 문장 부호는 0.12 초의 가벼운 쉼으로 더한다.
    # voice_rate 는 추정 보정값일 뿐이다. 일부 생성형 TTS 는 배속을 엄격히 지키지 않으므로 최종적으로
    # ±15% 구간을 남겨, 사용자가 이 값을 서버의 실제 결과와 같다고 오해하지 않게 한다.
    base_seconds = len(script_chars) / 4.2 + len(words) / 2.6 + punctuation_count * 0.12
    if base_seconds <= 0:
        return None

    normalized_rate = max(float(voice_rate or 1.0), 0.1)
    estimated_seconds = base_seconds / normalized_rate
    return (
        round(max(estimated_seconds * 0.85, 1.0), 1),
        round(max(estimated_seconds * 1.15, 1.0), 1),
    )


def _get_voice_preview_sample(voice_name: str) -> str:
    """현재 음색에 맞는 짧은 미리듣기 문구를 반환한다. 사용자의 전체 영상 대본은 쓰지 않는다."""
    # ElevenLabs 음색에 명확한 언어 필드가 없을 때는 표시 이름의 베트남어 문자로 미리듣기 문구를
    # 고른다. 확연히 맞지 않는 언어로 음색을 판단하는 것을 피하기 위해서다.
    if voice.is_elevenlabs_voice(voice_name):
        parts = voice_name.split(":", 2)
        display = parts[2] if len(parts) >= 3 else ""
        vietnamese_chars = set("àáâãèéêìíòóôõùúýăđơưÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯ")
        if any(char in vietnamese_chars for char in display):
            return "Xin chào, đây là đoạn âm thanh thử nghiệm giọng nói."
    return tr("Voice Example")


def _voice_preview_fingerprint(
    *,
    preview_type: str,
    content: str,
    tts_server: str,
    voice_name: str,
    voice_rate: float,
    voice_volume: float,
    provider_signature: dict,
) -> str:
    """미리듣기 캐시 지문을 만든다. 나레이션 파라미터가 하나라도 바뀌면 예전 미리듣기 결과가 자동으로 무효화된다."""
    payload = {
        "preview_type": preview_type,
        "content": content,
        "tts_server": tts_server,
        "voice_name": voice_name,
        "voice_rate": voice_rate,
        "voice_volume": voice_volume,
        "provider_signature": provider_signature,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _credential_signature(value: str) -> str:
    """
    캐시 무효화 판정에만 쓰는 자격 증명 요약값을 만든다.

    이 요약값은 설정, 로그, 작업 파일에 쓰이지 않는다. 사용자가 API 키를 바꾸면 요약값도 달라져
    현재 나레이션 서비스를 다시 호출하게 되므로, 예전 미리듣기 캐시 때문에 유효하지 않은 새 자격
    증명이 쓸 만해 보이는 일이 없다.
    """
    normalized_value = str(value or "")
    if not normalized_value:
        return ""
    return hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()


def _get_voice_preview_provider_signature(tts_server: str) -> dict:
    """
    미리듣기 결과에 영향을 주는 비민감 Provider 설정을 반환한다.

    API 키는 단방향 요약값으로만 캐시 지문에 참여하며, 원본 자격 증명은 캐시나 로그에 들어가지
    않는다. 모델, 서비스 주소, 지역, 자격 증명이 바뀌면 반드시 미리듣기를 다시 만들어야 한다.
    그러지 않으면 화면이 예전 Provider 설정으로 만든 오디오를 계속 재생해, 사용자가 지금 설정이
    적용됐다고 잘못 판단할 수 있다.
    """
    if tts_server == "azure-tts-v2":
        return {
            "speech_region": config.azure.get("speech_region", ""),
            "credential": _credential_signature(config.azure.get("speech_key", "")),
        }
    if tts_server == "siliconflow":
        return {
            "credential": _credential_signature(config.siliconflow.get("api_key", ""))
        }
    if tts_server == "gemini-tts":
        return {
            "credential": _credential_signature(config.app.get("gemini_api_key", ""))
        }
    if tts_server == "mimo-tts":
        return {"credential": _credential_signature(config.app.get("mimo_api_key", ""))}
    if tts_server == "elevenlabs":
        return {
            "model_id": config.elevenlabs.get("model_id", ""),
            "credential": _credential_signature(config.elevenlabs.get("api_key", "")),
        }
    if tts_server == "chatterbox":
        return {
            "base_url": config.chatterbox.get("base_url", ""),
            "model_id": config.chatterbox.get("model_id", ""),
            "credential": _credential_signature(config.chatterbox.get("api_key", "")),
        }
    return {}


def _synthesize_voice_preview(
    *,
    content: str,
    preview_type: str,
    selected_tts_server: str,
    voice_name: str,
    voice_rate: float,
    voice_volume: float,
) -> dict | None:
    """미리듣기를 한 번 생성해 메모리 캐시로 옮긴다. 임시 파일은 세션을 넘겨 오래 남지 않는다."""
    if selected_tts_server == "chatterbox":
        _sync_chatterbox_config_from_session_state()

    temp_dir = utils.storage_dir("temp", create=True)
    audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")
    logger.info(
        f"generating {preview_type} voice preview: "
        f"voice={voice_name}, rate={voice_rate}, volume={voice_volume}, "
        f"text_length={len(content)}"
    )
    try:
        with config.try_runtime_config_lock() as lock_acquired:
            if not lock_acquired:
                return {"busy": True}
            sub_maker = voice.tts(
                text=content,
                voice_name=voice_name,
                voice_rate=voice_rate,
                voice_file=audio_file,
                voice_volume=voice_volume,
            )
        if not sub_maker or not os.path.exists(audio_file):
            logger.error(f"{preview_type} voice preview did not produce an audio file")
            return None

        with open(audio_file, "rb") as file:
            audio_bytes = file.read()
        if not audio_bytes:
            logger.error(f"voice preview audio file is empty: {audio_file}")
            return None

        duration = voice.get_audio_duration(audio_file)
        if (
            not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            logger.warning(
                f"voice preview duration is unavailable: "
                f"preview_type={preview_type}, voice={voice_name}"
            )
            duration = None

        return {
            "audio_bytes": audio_bytes,
            "mime_type": _detect_audio_mime(audio_file, audio_bytes),
            "duration": duration,
            "preview_type": preview_type,
            "sub_maker": sub_maker,
        }
    finally:
        # 브라우저 플레이어는 메모리의 바이트를 쓰므로 파일은 읽자마자 정리해도 된다. 자주 미리듣기를
        # 해도 임시 파일이 쌓이지 않게 하기 위해서다.
        try:
            os.remove(audio_file)
        except FileNotFoundError:
            pass
        except OSError as exc:
            # 정리 실패가 실제 TTS 응답이나 예외를 덮어써서는 안 되지만, 권한이나 읽기 전용 파일
            # 시스템 같은 환경 문제를 짚을 수 있게 경로와 시스템 오류는 남겨야 한다.
            logger.warning(
                f"failed to delete voice preview file {audio_file}: {str(exc)}"
            )


def _render_voice_preview(params, friendly_names, selected_tts_server, voice_name):
    """비용이 적은 짧은 미리듣기, 전체 대본 길이 추정, 필요 시 전체 나레이션 미리보기를 그린다."""
    if not friendly_names:
        return

    script_content = str(params.video_script or "").strip()
    estimated_range = _estimate_voiceover_duration_range(
        script_content,
        params.voice_rate,
    )
    if estimated_range:
        st.caption(
            tr("Estimated Voiceover Duration").format(
                min=estimated_range[0],
                max=estimated_range[1],
            )
        )
    else:
        st.caption(tr("Voiceover Script Required"))

    sample_content = _get_voice_preview_sample(voice_name)
    provider_signature = _get_voice_preview_provider_signature(selected_tts_server)
    preview_columns = st.columns(2)
    short_preview_requested = preview_columns[0].button(
        tr("Play Voice"),
        key="play_voice_button",
        icon=":material/graphic_eq:",
        use_container_width=True,
    )
    full_preview_requested = preview_columns[1].button(
        tr("Generate Full Voiceover Preview"),
        key="generate_full_voiceover_preview_button",
        icon=":material/article:",
        help=tr("Full Voiceover Preview Cost Hint"),
        use_container_width=True,
        disabled=not bool(script_content),
    )

    preview_type = ""
    preview_content = ""
    if short_preview_requested:
        preview_type = "sample"
        preview_content = sample_content
    elif full_preview_requested:
        preview_type = "full"
        preview_content = script_content

    sample_fingerprint = _voice_preview_fingerprint(
        preview_type="sample",
        content=sample_content,
        tts_server=selected_tts_server,
        voice_name=voice_name,
        voice_rate=params.voice_rate,
        voice_volume=params.voice_volume,
        provider_signature=provider_signature,
    )
    full_fingerprint = (
        _voice_preview_fingerprint(
            preview_type="full",
            content=script_content,
            tts_server=selected_tts_server,
            voice_name=voice_name,
            voice_rate=params.voice_rate,
            voice_volume=params.voice_volume,
            provider_signature=provider_signature,
        )
        if script_content
        else ""
    )

    if preview_type:
        requested_fingerprint = (
            sample_fingerprint if preview_type == "sample" else full_fingerprint
        )
        cached_preview = st.session_state.get("voice_preview_audio")
        if (
            not cached_preview
            or cached_preview.get("fingerprint") != requested_fingerprint
        ):
            try:
                with st.spinner(tr("Synthesizing Voice")):
                    preview_result = _synthesize_voice_preview(
                        content=preview_content,
                        preview_type=preview_type,
                        selected_tts_server=selected_tts_server,
                        voice_name=voice_name,
                        voice_rate=params.voice_rate,
                        voice_volume=params.voice_volume,
                    )
            except Exception as exc:
                logger.exception(f"failed to generate {preview_type} voice preview")
                st.error(tr("Voice Preview Failed").format(error=str(exc)))
            else:
                if preview_result and preview_result.get("busy"):
                    st.warning(tr("Voice Preview Busy"))
                elif preview_result:
                    preview_result["fingerprint"] = requested_fingerprint
                    st.session_state["voice_preview_audio"] = preview_result
                else:
                    st.error(tr("Voice Preview No Audio"))

    cached_preview = st.session_state.get("voice_preview_audio")
    valid_fingerprints = {sample_fingerprint, full_fingerprint}
    if (
        cached_preview
        and cached_preview.get("fingerprint") in valid_fingerprints
        and cached_preview.get("audio_bytes")
    ):
        st.audio(
            cached_preview["audio_bytes"],
            format=cached_preview.get("mime_type", "audio/mp3"),
        )
        if cached_preview.get("preview_type") == "full":
            duration = cached_preview.get("duration")
            if isinstance(duration, (int, float)) and duration > 0:
                st.caption(
                    tr("Actual Voiceover Duration").format(duration=f"{duration:.1f}")
                )
            else:
                st.warning(tr("Voice Preview Duration Unavailable"))


def _get_reusable_full_voice_preview(params, voice_mode: str) -> dict | None:
    """
    현재 생성 파라미터와 완전히 일치하는 전체 미리듣기 캐시를 반환한다.

    전체 대본 미리듣기만 재사용하며, 짧은 음색 샘플은 절대 정식 작업에 들어갈 수 없다. 지문은 대본,
    Provider, 음색, 속도, 음량, 비민감 설정 요약값을 모두 덮는다. 어떤 파라미터든 바뀌면 자연스럽게
    일반 TTS 흐름으로 되돌아간다. 자막 타임라인과 유효한 길이도 필수 조건이다. 오디오만 재사용하면
    Edge 자막 경로가 SubMaker 를 잃기 때문이다.
    """
    if voice_mode != VOICE_MODE_TTS:
        return None

    script_content = str(params.video_script or "").strip()
    selected_tts_server = config.ui.get("tts_server", "azure-tts-v1")
    if (
        not script_content
        or not params.voice_name
        # 정식 영상은 MoviePy 합성 단계에서 나레이션 음량을 한꺼번에 적용하는데, 일부 Provider 는
        # TTS 단계에서 음량 게인을 직접 넣는다. 기본값이 아닌 음량에서 미리듣기를 재사용하면 게인이
        # 두 번 적용될 수 있으므로, 보수적으로 원래 흐름으로 되돌린다. 소수 상황 때문에 Provider
        # 별 예외 처리를 들이지 않기 위해서다.
        or not math.isclose(float(params.voice_volume), 1.0)
    ):
        return None

    expected_fingerprint = _voice_preview_fingerprint(
        preview_type="full",
        content=script_content,
        tts_server=selected_tts_server,
        voice_name=params.voice_name,
        voice_rate=params.voice_rate,
        voice_volume=params.voice_volume,
        provider_signature=_get_voice_preview_provider_signature(selected_tts_server),
    )
    cached_preview = st.session_state.get("voice_preview_audio")
    if (
        not cached_preview
        or cached_preview.get("fingerprint") != expected_fingerprint
        or cached_preview.get("preview_type") != "full"
        or not cached_preview.get("audio_bytes")
        or cached_preview.get("sub_maker") is None
    ):
        return None

    duration = cached_preview.get("duration")
    if (
        not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        return None

    return {
        "audio_bytes": bytes(cached_preview["audio_bytes"]),
        "duration": float(duration),
        "sub_maker": cached_preview["sub_maker"],
        "script": script_content,
        "voice_name": params.voice_name,
        "voice_rate": float(params.voice_rate),
        "voice_volume": float(params.voice_volume),
    }


def _render_elevenlabs_api_key_input(label_key):
    """
    ElevenLabs TTS 와 배경음악이 공유하는 단일 API 키 입력 상태를 그린다.

    같은 페이지에서 TTS 와 배경음악에 위젯 key 를 따로 쓰면 Streamlit 이 각각 예전 값을 붙들고,
    나중에 그려진 입력란이 공유 설정을 덮어쓴다. 여기서는 key 하나로 통일하고 환경 변수 되채우기,
    설정 갱신, 음색 캐시 무효화를 한곳에서 처리해, 화면 표시와 백그라운드 작업이 항상 같은 값을
    읽도록 보장한다.
    """
    configured_key = str(config.elevenlabs.get("api_key", "") or "").strip()
    effective_key = configured_key or os.getenv("ELEVENLABS_API_KEY", "").strip()
    entered_key = st.text_input(
        tr(label_key),
        value=effective_key,
        type="password",
        key="elevenlabs_api_key_input",
    ).strip()

    if entered_key != effective_key:
        for cache_key in list(st.session_state.keys()):
            if str(cache_key).startswith("elevenlabs_voices_"):
                del st.session_state[cache_key]

    # 환경 변수는 현재 프로세스에만 쓰이며, 사용자가 고치지 않았는데 config.toml 로 자동 복사되지 않는다.
    # 이미 설정이 있거나 사용자가 직접 입력을 고쳤을 때만 로컬 설정을 갱신해 Sonilo 와 동작을 맞춘다.
    if configured_key or entered_key != effective_key:
        config.elevenlabs["api_key"] = entered_key
    return entered_key


def _render_background_music_settings(params, elevenlabs_api_key_rendered=False):
    """배경음악 소스와 음량 설정을 그리고, 이번에 저장할 업로드 파일을 반환한다."""
    uploaded_bgm_file = None
    st.divider()
    bgm_options = [
        (tr("No Background Music"), ""),
        (tr("Random Background Music"), "random"),
        (tr("Custom Background Music"), "custom"),
        (tr("Sonilo Background Music"), "sonilo"),
        (tr("ElevenLabs Background Music"), "elevenlabs"),
    ]
    selected_bgm_type = stable_selectbox(
        tr("Background Music Source"),
        options=[value for _, value in bgm_options],
        default_value="random",
        key="bgm_type_select",
        format_func=lambda value: dict((v, label) for label, v in bgm_options)[value],
    )
    params.bgm_type = selected_bgm_type
    if params.bgm_type == "sonilo":
        configured_key = str(config.app.get("sonilo_api_key", "") or "").strip()
        effective_key = configured_key or os.getenv("SONILO_API_KEY", "").strip()
        entered_key = st.text_input(
            tr("Sonilo API Key"),
            value=effective_key,
            type="password",
            key="sonilo_api_key_input",
        ).strip()
        # 이미 설정된 키를 비밀번호 입력란에 그대로 채워 달라는 요구가 있었다. 설정 값이 환경 변수보다
        # 우선한다. 사용자가 입력을 실제로 고쳤거나 원래 설정을 쓰고 있을 때만 되쓰기해, 아무 조작도
        # 없는데 환경 변수의 키가 config.toml 로 복사되는 것을 막는다.
        if configured_key or entered_key != effective_key:
            config.app["sonilo_api_key"] = entered_key
    elif params.bgm_type == "elevenlabs":
        if elevenlabs_api_key_rendered:
            # TTS 영역에서 공유 입력란을 이미 그렸다면 두 번째 위젯을 만들지 않는다. 독립된 두
            # session_state 값이 서로 덮어쓰는 것을 막기 위해서다. 안내 문구로 사용자가 위쪽의
            # 공용 설정을 찾을 수 있게 한다.
            st.caption(tr("ElevenLabs API Key Help"))
        else:
            _render_elevenlabs_api_key_input("ElevenLabs Music API Key")

    params.bgm_volume = stable_selectbox(
        tr("Background Music Volume"),
        options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        default_value=0.2,
        key="bgm_volume_select",
        format_func=lambda value: f"{int(value * 100)}%",
        disabled=not params.bgm_type,
    )
    bgm_enabled = bgm_service.should_use_bgm(
        params.bgm_type, params.bgm_volume
    )

    if params.bgm_type == "custom":
        uploaded_bgm_file = st.file_uploader(
            tr("Upload Background Music"),
            type=[
                extension.removeprefix(".")
                for extension in bgm_service.SUPPORTED_BGM_EXTENSIONS
            ],
            accept_multiple_files=False,
            key="custom_bgm_uploader",
            help=tr("Upload Background Music Help"),
            # Streamlit 은 기본적으로 위젯에 전역 200MB 상한을 표시한다. 여기서는 서비스 계층의
            # 30MB 하드 제한과 반드시 맞춰야, 화면에서는 고를 수 있는데 제출할 때야 서버가
            # 거부하는 일이 없다.
            max_upload_size=bgm_service.MAX_BGM_UPLOAD_BYTES // (1024 * 1024),
        )
        if uploaded_bgm_file is not None and bgm_enabled:
            try:
                safe_name = bgm_service.sanitize_upload_filename(
                    uploaded_bgm_file.name
                )
                # Streamlit 은 음량 같은 아무 위젯이나 조작해도 페이지를 다시 실행한다. 내용 해시로
                # 업로드 파일을 구분하고 전체 디코딩 결과를 현재 세션에 캐시한다. 이름과 크기가
                # 같다는 이유만으로 예전 결과를 잘못 쓰지 않으면서, rerun 마다 FFmpeg 를 반복
                # 호출하지도 않기 위해서다.
                validation_key = (
                    safe_name,
                    uploaded_bgm_file.size,
                    hashlib.sha256(uploaded_bgm_file.getbuffer()).hexdigest(),
                )
                cached_validation = st.session_state.get("custom_bgm_validation")
                if (
                    not cached_validation
                    or cached_validation.get("key") != validation_key
                ):
                    try:
                        bgm_service.validate_bgm_upload(
                            uploaded_bgm_file.name, uploaded_bgm_file
                        )
                    except bgm_service.BgmUploadError as exc:
                        cached_validation = {
                            "key": validation_key,
                            "error": str(exc),
                            "error_type": "upload",
                        }
                        # 같은 파일 지문의 실패 결과도 세션 캐시에 들어가므로, 여기서는 검증을 실제로
                        # 처음 실행할 때만 한 번 기록한다. 일반 위젯 rerun 으로 로그가 도배되는 것을
                        # 막기 위해서다.
                        logger.warning(
                            "WebUI background music validation rejected: "
                            f"name={safe_name}, error={str(exc)}"
                        )
                    except bgm_service.BgmServiceError as exc:
                        cached_validation = {
                            "key": validation_key,
                            "error": str(exc),
                            "error_type": "service",
                        }
                        logger.error(
                            "WebUI background music validation failed: "
                            f"name={safe_name}, error={str(exc)}"
                        )
                    else:
                        cached_validation = {
                            "key": validation_key,
                            "error": "",
                            "error_type": "",
                        }
                    st.session_state["custom_bgm_validation"] = cached_validation

                if cached_validation.get("error"):
                    if cached_validation.get("error_type") == "service":
                        raise bgm_service.BgmServiceError(
                            cached_validation["error"]
                        )
                    raise bgm_service.BgmUploadError(cached_validation["error"])
            except bgm_service.BgmUploadError:
                # 잘못된 파일이 직전의 유효한 업로드 이름을 그대로 쓰면 안 된다. 그러면 작업 파라미터가
                # 여전히 예전 BGM 을 가리킬 수 있다. UploadedFile 반환값은 남겨 둬, 사용자가 생성을
                # 눌렀을 때 최종 서버 검증에 걸리게 한다. 배경음악 없는 영상이 조용히 만들어지는
                # 것보다 낫다.
                params.bgm_file = ""
                st.error(tr("Invalid Background Music"))
            except bgm_service.BgmServiceError:
                params.bgm_file = ""
                st.error(tr("Background Music Validation Failed"))
            else:
                # 전체 디코딩 검증을 통과한 뒤에야 플레이어와 '준비 완료' 를 보여 준다. 파일은 여전히
                # 생성을 눌렀을 때만 저장되므로, 미리듣기만 하거나 나중에 파일을 지워도 storage/bgm 이
                # 더럽혀지지 않는다.
                uploaded_mime_type = str(
                    getattr(uploaded_bgm_file, "type", "") or ""
                )
                preview_mime_type = (
                    uploaded_mime_type
                    if uploaded_mime_type.startswith("audio/")
                    else mimetypes.guess_type(safe_name)[0] or "audio/mpeg"
                )
                st.audio(uploaded_bgm_file, format=preview_mime_type)
                st.info(f"{tr('Background Music Ready')}: {safe_name}")
                params.bgm_file = safe_name

        custom_bgm_file = st.text_input(
            tr("Custom Background Music File"),
            key="custom_bgm_file_input",
            disabled=uploaded_bgm_file is not None,
        )
        if uploaded_bgm_file is None and custom_bgm_file and bgm_enabled:
            # 파일명은 서비스 계층이 storage/bgm 이나 resource/songs 로 매핑한 뒤 검증한다.
            # UI 는 이 두 화이트리스트 디렉터리 밖의 임의 경로를 받지 않는다.
            params.bgm_file = custom_bgm_file.strip()
        elif not bgm_enabled:
            # 업로드 위젯은 사용자가 고른 파일을 그대로 들고 있다가, 음량을 올린 다음 rerun 에서
            # 자동으로 전체 검증한다. 현재 작업 파라미터는 반드시 비워, 0 음량 작업이 그 파일을
            # 저장하거나 해석하지 않게 한다.
            params.bgm_file = ""

    if params.bgm_type == "sonilo":
        params.video_music_prompt = st.text_input(
            tr("Sonilo Music Prompt"),
            key="sonilo_bgm_prompt_input",
            max_chars=sonilo_service.MAX_PROMPT_LENGTH,
            help=tr("Sonilo Music Prompt Help"),
        ).strip()
        if params.video_count > 1:
            st.warning(tr("Sonilo Multiple Videos Warning"))
        if st.button(
            tr("Test Sonilo Connection"),
            key="test_sonilo_connection_button",
            use_container_width=True,
        ):
            try:
                sonilo_service.test_connection()
            except sonilo_service.SoniloError as exc:
                logger.warning(f"Sonilo connection test failed: {exc}")
                st.error(tr("Sonilo Connection Test Failed").format(error=str(exc)))
            else:
                st.success(tr("Sonilo Connection Test Succeeded"))
    elif params.bgm_type == "elevenlabs":
        params.video_music_prompt = st.text_input(
            tr("ElevenLabs Music Prompt"),
            key="elevenlabs_music_prompt_input",
            max_chars=elevenlabs_music_service.MAX_PROMPT_LENGTH,
            help=tr("ElevenLabs Music Prompt Help"),
        ).strip()
        if params.video_count > 1:
            st.warning(tr("ElevenLabs Multiple Videos Warning"))
        if st.button(
            tr("Test ElevenLabs Connection"),
            key="test_elevenlabs_music_connection_button",
            use_container_width=True,
        ):
            try:
                elevenlabs_music_service.test_connection()
            except elevenlabs_music_service.ElevenLabsPaidPlanRequiredError:
                st.error(tr("ElevenLabs Paid Plan Required"))
            except elevenlabs_music_service.ElevenLabsMusicError as exc:
                logger.warning(f"ElevenLabs connection test failed: {exc}")
                st.error(tr("ElevenLabs Connection Test Failed").format(error=str(exc)))
            else:
                st.success(tr("ElevenLabs Connection Test Succeeded"))
    if params.bgm_type == "sonilo" and bgm_enabled and not sonilo_service.is_enabled():
        # 음량이 0 이면 작업 계층이 Sonilo 배경음악을 만들지도 섞지도 않으므로 키를 안내할 필요가 없다.
        # 이 판정은 작업 진입점과 서비스 계층 규칙을 공유해, 화면 안내와 실제 실행 조건이 갈라지지 않게 한다.
        st.warning(tr("Sonilo API Key Required"))
    elif (
        params.bgm_type == "elevenlabs"
        and bgm_enabled
        and not elevenlabs_music_service.is_enabled()
    ):
        st.warning(tr("ElevenLabs API Key Required"))
    return uploaded_bgm_file


def _render_audio_settings(panel, params):
    """오디오 설정을 그리고 업로드 오디오와 현재 나레이션 모드를 반환한다."""
    with panel:
        with st.container(border=True):
            st.write(tr("Audio Settings"))

            # 나레이션 방식은 오디오 설정의 최상위 상태로, 자동 나레이션·사용자 업로드·나레이션 없음을
            # 명확히 구분한다. 예전 설정에 voice_mode 가 없으면 기존 tts_server 의 '나레이션 없음'
            # sentinel 로 호환을 유지한다.
            saved_tts_server = config.ui.get("tts_server", "azure-tts-v1")
            saved_voice_mode = config.ui.get("voice_mode")
            if saved_voice_mode not in {
                VOICE_MODE_TTS,
                VOICE_MODE_UPLOAD,
                VOICE_MODE_NONE,
            }:
                saved_voice_mode = (
                    VOICE_MODE_NONE
                    if saved_tts_server == voice.NO_VOICE_NAME
                    else VOICE_MODE_TTS
                )
            voice_mode_options = [VOICE_MODE_TTS, VOICE_MODE_UPLOAD, VOICE_MODE_NONE]
            voice_mode_labels = {
                VOICE_MODE_TTS: tr("Automatic Voiceover"),
                VOICE_MODE_UPLOAD: tr("Upload Voiceover"),
                VOICE_MODE_NONE: tr("No Voiceover"),
            }
            voice_mode = stable_segmented_control(
                tr("Voiceover Mode"),
                options=voice_mode_options,
                default_value=saved_voice_mode,
                key="voice_mode_control",
                format_func=lambda value: voice_mode_labels[value],
                width="stretch",
            )
            config.ui["voice_mode"] = voice_mode
            tts_mode_enabled = voice_mode == VOICE_MODE_TTS

            # Provider 드롭다운은 자동 나레이션 서비스를 고르는 역할만 한다. 나레이션 없음은 위쪽 모드가
            # 이미 제어하므로 TTS Provider 목록에 섞지 않는다. 두 진입점이 같은 상태를 나타내는 것을
            # 막기 위해서다.
            tts_servers = [
                ("azure-tts-v1", "Azure TTS V1"),
                ("azure-tts-v2", "Azure TTS V2"),
                ("siliconflow", "SiliconFlow TTS"),
                ("gemini-tts", "Google Gemini TTS"),
                ("mimo-tts", "Xiaomi MiMo TTS"),
                ("elevenlabs", "ElevenLabs TTS"),
                ("chatterbox", "Chatterbox TTS"),
            ]

            tts_server_values = [server_value for server_value, _ in tts_servers]
            if saved_tts_server not in tts_server_values:
                saved_tts_server = "azure-tts-v1"

            if tts_mode_enabled:
                selected_tts_server = stable_selectbox(
                    tr("Voiceover Service"),
                    options=tts_server_values,
                    default_value=saved_tts_server,
                    key="tts_server_select",
                    format_func=lambda value: dict(
                        (v, label) for v, label in tts_servers
                    )[value],
                )
            else:
                # 자동 나레이션이 아닌 모드에서는 TTS 위젯을 그리지 않되 직전 선택은 남겨, 돌아왔을 때 계속 쓸 수 있게 한다.
                selected_tts_server = saved_tts_server

            config.ui["tts_server"] = selected_tts_server

            # 서비스 설명을 Provider 선택 바로 뒤에 둬, 무엇을 준비해야 하는지 먼저 알린 다음 음색과
            # 자격 증명 설정으로 넘어가게 한다. 설명이 없는 Provider 에는 빈 안내 블록을 그리지 않는다.
            if tts_mode_enabled:
                provider_tips = get_tts_provider_tips(selected_tts_server)
                if provider_tips:
                    st.info(provider_tips)

            # 선택한 TTS 서버에 맞는 음성 목록을 가져온다
            filtered_voices = []
            saved_voice_name = config.ui.get("voice_name", "")
            elevenlabs_api_key_rendered = False

            if not tts_mode_enabled:
                # 오디오 업로드와 나레이션 없음 모드에서는 원격 음색을 불러오지 않아, 의미 없는 네트워크 요청과 화면 잡음을 줄인다.
                filtered_voices = []
            elif selected_tts_server == "siliconflow":
                # SiliconFlow 의 음성 목록을 가져온다
                filtered_voices = voice.get_siliconflow_voices()
            elif selected_tts_server == "gemini-tts":
                # Gemini TTS 의 음성 목록을 가져온다
                filtered_voices = voice.get_gemini_voices()
            elif selected_tts_server == "mimo-tts":
                # Xiaomi MiMo TTS 의 사전 정의 음색 목록을 가져온다
                filtered_voices = voice.get_mimo_voices()
            elif selected_tts_server == "elevenlabs":
                # Read from session_state first so the API key is available before
                # the Play Voice button runs (which is earlier in the script than
                # the API key text_input widget).
                saved_elevenlabs_api_key = st.session_state.get(
                    "elevenlabs_api_key_input",
                    config.elevenlabs.get("api_key", ""),
                )
                if saved_elevenlabs_api_key:
                    config.elevenlabs["api_key"] = saved_elevenlabs_api_key
                cache_key = f"elevenlabs_voices_{saved_elevenlabs_api_key}"
                if cache_key not in st.session_state:
                    st.session_state[cache_key] = voice.get_elevenlabs_voices(
                        saved_elevenlabs_api_key
                    )
                filtered_voices = st.session_state[cache_key]
            elif selected_tts_server == "chatterbox":
                # 자체 호스팅 Chatterbox 서비스의 사전 정의 음색 ([chatterbox] voices 설정에서 온다)
                _sync_chatterbox_config_from_session_state()
                filtered_voices = voice.get_chatterbox_voices()
            else:
                # Azure 의 음성 목록을 가져온다
                all_voices = voice.get_all_azure_voices(filter_locals=None)

                # 선택한 TTS 서버에 맞게 음성을 거른다
                for v in all_voices:
                    if selected_tts_server == "azure-tts-v2":
                        # V2 버전의 음성 이름에는 "v2" 가 들어 있다
                        if "V2" in v:
                            filtered_voices.append(v)
                    else:
                        # V1 버전의 음성 이름에는 "v2" 가 없다
                        if "V2" not in v:
                            filtered_voices.append(v)

            def _friendly(v):
                if voice.is_no_voice(v):
                    return tr("No Voice Selected")
                if voice.is_elevenlabs_voice(v):
                    parts = v.split(":", 2)
                    return parts[2] if len(parts) >= 3 else v
                if voice.is_chatterbox_voice(v):
                    name = v.split(":", 1)[1] if ":" in v else v
                    return name.replace("-Female", "").replace("-Male", "")
                return (
                    v.replace("Female", tr("Female"))
                    .replace("Male", tr("Male"))
                    .replace("Neural", "")
                )

            friendly_names = {v: _friendly(v) for v in filtered_voices}

            saved_voice_name_index = 0

            # 저장된 음성이 지금 걸러 낸 음성 목록에 있는지 확인한다
            if saved_voice_name in friendly_names:
                saved_voice_name_index = list(friendly_names.keys()).index(
                    saved_voice_name
                )
            else:
                # 없으면 현재 UI 언어에 맞춰 기본 음성을 고른다
                for i, v in enumerate(filtered_voices):
                    if v.lower().startswith(st.session_state["ui_language"].lower()):
                        saved_voice_name_index = i
                        break

            # 맞는 음성을 찾지 못하면 첫 번째 음성을 쓴다
            if saved_voice_name_index >= len(friendly_names) and friendly_names:
                saved_voice_name_index = 0

            # 고를 수 있는 음성이 있는지 확인한다
            if tts_mode_enabled and friendly_names:
                voice_name = stable_selectbox(
                    tr("Voiceover Voice"),
                    options=list(friendly_names.keys()),
                    default_value=list(friendly_names.keys())[saved_voice_name_index],
                    key=f"speech_synthesis_select_{selected_tts_server}",
                    format_func=lambda value: friendly_names[value],
                )

                params.voice_name = voice_name
                if not voice.is_no_voice(voice_name):
                    # 자리표시자 sentinel 은 자동이 아닌 모드에서 비활성 표시용으로만 쓰며, 사용자가
                    # 마지막으로 실제 고른 음색을 덮어쓰지 않는다. 자동 나레이션으로 돌아오면 원래
                    # 설정이 복원된다.
                    config.ui["voice_name"] = voice_name
            elif tts_mode_enabled:
                # 고를 수 있는 음성이 없으면 안내 문구를 보여 준다
                st.warning(
                    tr(
                        "No voices available for the selected TTS server. Please select another server."
                    )
                )
                voice_name = ""
                params.voice_name = ""
                config.ui["voice_name"] = ""
            else:
                # 자동이 아닌 나레이션 모드에서는 음색 위젯을 그리지 않고 저장 값만 재사용해 파라미터 구조를 안정적으로 유지한다.
                voice_name = saved_voice_name or voice.NO_VOICE_NAME
                params.voice_name = voice_name

            # V2 버전을 골랐거나 음성이 V2 음성이면 서비스 지역과 API 키 입력란을 보여 준다
            if tts_mode_enabled and (
                selected_tts_server == "azure-tts-v2"
                or (voice_name and voice.is_azure_v2_voice(voice_name))
            ):
                saved_azure_speech_region = config.azure.get("speech_region", "")
                saved_azure_speech_key = config.azure.get("speech_key", "")
                azure_speech_region = st.text_input(
                    tr("Speech Region"),
                    value=saved_azure_speech_region,
                    key="azure_speech_region_input",
                )
                azure_speech_key = st.text_input(
                    tr("Speech Key"),
                    value=saved_azure_speech_key,
                    type="password",
                    key="azure_speech_key_input",
                )
                config.azure["speech_region"] = azure_speech_region
                config.azure["speech_key"] = azure_speech_key

            if tts_mode_enabled and selected_tts_server == "gemini-tts":
                # Gemini TTS 는 Gemini LLM 과 같은 키를 공유한다. 오디오 패널에 직접 진입점을 둬,
                # 사용자가 음성 설정을 끝내려고 LLM Provider 를 먼저 바꿀 필요가 없게 한다.
                gemini_tts_api_key = st.text_input(
                    tr("Gemini API Key"),
                    value=config.app.get("gemini_api_key", ""),
                    type="password",
                    key="gemini_tts_api_key_input",
                )
                config.app["gemini_api_key"] = gemini_tts_api_key

            # SiliconFlow 를 골랐을 때 API 키 입력란과 안내 문구를 보여 준다
            if tts_mode_enabled and (
                selected_tts_server == "siliconflow"
                or (voice_name and voice.is_siliconflow_voice(voice_name))
            ):
                saved_siliconflow_api_key = config.siliconflow.get("api_key", "")

                siliconflow_api_key = st.text_input(
                    tr("SiliconFlow API Key"),
                    value=saved_siliconflow_api_key,
                    type="password",
                    key="siliconflow_api_key_input",
                )

                config.siliconflow["api_key"] = siliconflow_api_key

            # Xiaomi MiMo TTS 를 골랐을 때는 MiMo LLM provider 의 API 키를 재사용한다.
            # 그래야 사용자가 MiMo 로 대본과 음성을 함께 만들 때 키를 한 벌만 관리하면 된다.
            if tts_mode_enabled and (
                selected_tts_server == "mimo-tts"
                or (voice_name and voice.is_mimo_voice(voice_name))
            ):
                saved_mimo_api_key = config.app.get("mimo_api_key", "")

                mimo_api_key = st.text_input(
                    tr("MiMo API Key"),
                    value=saved_mimo_api_key,
                    type="password",
                    key="mimo_tts_api_key_input",
                )

                config.app["mimo_api_key"] = mimo_api_key

            # ElevenLabs API key section
            if tts_mode_enabled and (
                selected_tts_server == "elevenlabs"
                or (voice_name and voice.is_elevenlabs_voice(voice_name))
            ):
                _render_elevenlabs_api_key_input(
                    "ElevenLabs API Key",
                )
                elevenlabs_api_key_rendered = True

                _elevenlabs_models = [
                    "eleven_multilingual_v2",
                    "eleven_flash_v2_5",
                    "eleven_v3",
                ]
                saved_elevenlabs_model = config.elevenlabs.get(
                    "model_id", "eleven_multilingual_v2"
                )
                if saved_elevenlabs_model not in _elevenlabs_models:
                    saved_elevenlabs_model = "eleven_multilingual_v2"
                elevenlabs_model = stable_selectbox(
                    tr("ElevenLabs Model"),
                    options=_elevenlabs_models,
                    default_value=saved_elevenlabs_model,
                    key="elevenlabs_model_select",
                )
                config.elevenlabs["model_id"] = elevenlabs_model

            # Chatterbox API settings section (self-hosted, OpenAI-compatible)
            if tts_mode_enabled and (
                selected_tts_server == "chatterbox"
                or (voice_name and voice.is_chatterbox_voice(voice_name))
            ):
                chatterbox_base_url = st.text_input(
                    tr("Chatterbox Base URL"),
                    value=config.chatterbox.get("base_url")
                    or DEFAULT_CHATTERBOX_BASE_URL,
                    key="chatterbox_base_url_input",
                    placeholder=tr("Chatterbox Base URL Placeholder"),
                )
                config.chatterbox["base_url"] = (chatterbox_base_url or "").strip()

                chatterbox_api_key = st.text_input(
                    tr("Chatterbox API Key"),
                    value=config.chatterbox.get("api_key", ""),
                    type="password",
                    key="chatterbox_api_key_input",
                )
                config.chatterbox["api_key"] = chatterbox_api_key

                chatterbox_model = st.text_input(
                    tr("Chatterbox Model"),
                    value=config.chatterbox.get("model_id") or DEFAULT_CHATTERBOX_MODEL,
                    key="chatterbox_model_input",
                )
                config.chatterbox["model_id"] = (
                    chatterbox_model or DEFAULT_CHATTERBOX_MODEL
                ).strip()

                _saved_chatterbox_voices = (
                    _parse_chatterbox_voices(config.chatterbox.get("voices"))
                    or DEFAULT_CHATTERBOX_VOICES
                )
                if isinstance(_saved_chatterbox_voices, list):
                    _saved_chatterbox_voices = ", ".join(_saved_chatterbox_voices)
                chatterbox_voices = st.text_input(
                    tr("Chatterbox Voices"),
                    value=str(_saved_chatterbox_voices or ""),
                    key="chatterbox_voices_input",
                    placeholder=tr("Chatterbox Voices Placeholder"),
                )
                config.chatterbox["voices"] = _parse_chatterbox_voices(
                    chatterbox_voices
                )

            # 세 모드 모두 이번 작업에 실제로 필요한 위젯만 그린다. 자동 나레이션은 음량과 속도를
            # 조절할 수 있고, 오디오 업로드는 파일과 음량만 필요하며, 나레이션 없음은 의미 없는
            # 설정을 보여 주지 않는다.
            params.voice_name = (
                voice.NO_VOICE_NAME if voice_mode == VOICE_MODE_NONE else voice_name
            )
            params.voice_volume = 1.0
            params.voice_rate = 1.0
            uploaded_audio_file = None

            if tts_mode_enabled:
                voice_control_cols = st.columns(2)
                with voice_control_cols[0]:
                    params.voice_volume = stable_selectbox(
                        tr("Voiceover Volume"),
                        options=[0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0],
                        default_value=1.0,
                        key="voice_volume_select",
                        format_func=lambda value: f"{int(value * 100)}%",
                        help=tr("Voiceover Volume Help"),
                    )

                with voice_control_cols[1]:
                    params.voice_rate = stable_selectbox(
                        tr("Voiceover Speed"),
                        options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
                        default_value=1.0,
                        key="voice_rate_select",
                        format_func=lambda value: f"{value:.1f}×",
                        help=tr("Voiceover Speed Help"),
                    )

                # 미리듣기는 반드시 음량·속도 위젯 뒤에 있어야, 호출이 현재 위젯 값을 쓰게 된다.
                _render_voice_preview(
                    params,
                    friendly_names,
                    selected_tts_server,
                    voice_name,
                )
            elif voice_mode == VOICE_MODE_UPLOAD:
                custom_audio_file_types = sorted(
                    extension.removeprefix(".") for extension in CUSTOM_AUDIO_EXTENSIONS
                )
                uploaded_audio_file = st.file_uploader(
                    tr("Upload Voiceover File"),
                    type=custom_audio_file_types
                    + [file_type.upper() for file_type in custom_audio_file_types],
                    accept_multiple_files=False,
                    key="custom_audio_file_uploader",
                    help=tr("Upload Voiceover File Help"),
                )
                params.voice_volume = stable_selectbox(
                    tr("Voiceover Volume"),
                    options=[0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0],
                    default_value=1.0,
                    key="voice_volume_select",
                    format_func=lambda value: f"{int(value * 100)}%",
                    help=tr("Voiceover Volume Help"),
                )
                if uploaded_audio_file:
                    st.audio(uploaded_audio_file, format="audio/mp3")
                    st.info(
                        tr(
                            "Custom audio will be used directly. TTS synthesis will be skipped for this task."
                        )
                    )
            uploaded_bgm_file = _render_background_music_settings(
                params,
                elevenlabs_api_key_rendered=elevenlabs_api_key_rendered,
            )
    return uploaded_audio_file, uploaded_bgm_file, voice_mode


def _render_subtitle_settings(panel, params):
    """자막 설정을 그리고 생성 파라미터를 갱신한다."""
    with panel:
        with st.container(border=True):
            st.write(tr("Subtitle Settings"))
            st.session_state.setdefault(
                "subtitle_enabled_checkbox",
                DEFAULT_SUBTITLE_SETTINGS["subtitle_enabled"],
            )
            params.subtitle_enabled = st.checkbox(
                tr("Enable Subtitles"),
                key="subtitle_enabled_checkbox",
            )
            subtitle_settings_disabled = not params.subtitle_enabled
            font_names = get_all_fonts()
            saved_font_name = config.ui.get(
                "font_name", DEFAULT_SUBTITLE_SETTINGS["font_name"]
            )
            saved_font_name_index = 0
            if saved_font_name in font_names:
                saved_font_name_index = font_names.index(saved_font_name)
            params.font_name = stable_selectbox(
                tr("Font"),
                options=font_names,
                default_value=font_names[saved_font_name_index] if font_names else "",
                key="font_name_select",
                disabled=subtitle_settings_disabled,
            )
            config.ui["font_name"] = params.font_name

            subtitle_positions = [
                (tr("Top"), "top"),
                (tr("Center"), "center"),
                (tr("Bottom"), "bottom"),
                (tr("Custom"), "custom"),
            ]
            saved_subtitle_position = config.ui.get(
                "subtitle_position", DEFAULT_SUBTITLE_SETTINGS["subtitle_position"]
            )
            saved_position_index = 2
            for i, (_, pos_value) in enumerate(subtitle_positions):
                if pos_value == saved_subtitle_position:
                    saved_position_index = i
                    break
            selected_subtitle_position = stable_selectbox(
                tr("Position"),
                options=[value for _, value in subtitle_positions],
                default_value=subtitle_positions[saved_position_index][1],
                key="subtitle_position_select",
                format_func=lambda value: dict(
                    (v, label) for label, v in subtitle_positions
                )[value],
                disabled=subtitle_settings_disabled,
            )
            params.subtitle_position = selected_subtitle_position
            config.ui["subtitle_position"] = params.subtitle_position

            if params.subtitle_position == "custom":
                saved_custom_position = config.ui.get(
                    "custom_position", DEFAULT_SUBTITLE_SETTINGS["custom_position"]
                )
                st.session_state.setdefault(
                    "custom_position_input", str(saved_custom_position)
                )
                custom_position = st.text_input(
                    tr("Custom Position (% from top)"),
                    key="custom_position_input",
                    disabled=subtitle_settings_disabled,
                )
                try:
                    params.custom_position = float(custom_position)
                    if params.custom_position < 0 or params.custom_position > 100:
                        st.error(tr("Please enter a value between 0 and 100"))
                    else:
                        config.ui["custom_position"] = params.custom_position
                except ValueError:
                    st.error(tr("Please enter a valid number"))

            # 색상 라벨은 언어에 따라 길이가 꽤 다르다. 색상 선택기에 적당한 폭을 남겨 라벨이
            # 줄바꿈되지 않게 하면서, 글자 크기 슬라이더에도 조작하기 충분한 공간을 남긴다.
            font_cols = st.columns([0.42, 0.58])
            with font_cols[0]:
                saved_text_fore_color = config.ui.get(
                    "text_fore_color", DEFAULT_SUBTITLE_SETTINGS["text_fore_color"]
                )
                st.session_state.setdefault("font_color_picker", saved_text_fore_color)
                params.text_fore_color = st.color_picker(
                    tr("Font Color"),
                    key="font_color_picker",
                    disabled=subtitle_settings_disabled,
                )
                config.ui["text_fore_color"] = params.text_fore_color

            with font_cols[1]:
                saved_font_size = config.ui.get(
                    "font_size", DEFAULT_SUBTITLE_SETTINGS["font_size"]
                )
                st.session_state.setdefault("font_size_slider", saved_font_size)
                params.font_size = st.slider(
                    tr("Font Size"),
                    30,
                    100,
                    key="font_size_slider",
                    disabled=subtitle_settings_disabled,
                )
                config.ui["font_size"] = params.font_size

            stroke_cols = st.columns([0.42, 0.58])
            with stroke_cols[0]:
                st.session_state.setdefault(
                    "stroke_color_picker", DEFAULT_SUBTITLE_SETTINGS["stroke_color"]
                )
                params.stroke_color = st.color_picker(
                    tr("Stroke Color"),
                    key="stroke_color_picker",
                    disabled=subtitle_settings_disabled,
                )
            with stroke_cols[1]:
                st.session_state.setdefault(
                    "stroke_width_slider", DEFAULT_SUBTITLE_SETTINGS["stroke_width"]
                )
                params.stroke_width = st.slider(
                    tr("Stroke Width"),
                    0.0,
                    10.0,
                    key="stroke_width_slider",
                    disabled=subtitle_settings_disabled,
                )

            # 배경 스위치의 현지화된 이름은 대체로 색상 라벨보다 길므로, 스위치에 공간을 조금 더 준다.
            subtitle_bg_cols = st.columns([0.55, 0.45])
            saved_subtitle_background_enabled = config.ui.get(
                "subtitle_background_enabled",
                DEFAULT_SUBTITLE_SETTINGS["subtitle_background_enabled"],
            )
            st.session_state.setdefault(
                "subtitle_background_enabled_checkbox",
                saved_subtitle_background_enabled,
            )
            with subtitle_bg_cols[0]:
                subtitle_background_enabled = st.checkbox(
                    tr("Enable Subtitle Background"),
                    key="subtitle_background_enabled_checkbox",
                    disabled=subtitle_settings_disabled,
                )
            config.ui["subtitle_background_enabled"] = subtitle_background_enabled

            # 배경색과 둥근 모서리 스타일은 모두 자막 배경 스위치에 딸려 있다. 하위 위젯은 항상
            # 페이지에 남겨 두고 상위 스위치가 꺼지면 함께 비활성화한다. 하나는 사라지고 다른 하나는
            # 비활성화되어 레이아웃이 튀는 것을 막기 위해서다. 색상 값은 UI 설정에 그대로 남아, 배경을
            # 다시 켜면 이전 선택을 복원할 수 있다. 생성 서비스로 넘기는 파라미터는 False 로 설정해,
            # 꺼진 상태에서 배경이 실제로 그려지지 않도록 보장한다.
            saved_subtitle_background_color = config.ui.get(
                "subtitle_background_color",
                DEFAULT_SUBTITLE_SETTINGS["subtitle_background_color"],
            )
            st.session_state.setdefault(
                "subtitle_background_color_picker",
                saved_subtitle_background_color,
            )
            with subtitle_bg_cols[1]:
                selected_subtitle_background_color = st.color_picker(
                    tr("Subtitle Background Color"),
                    key="subtitle_background_color_picker",
                    disabled=subtitle_settings_disabled
                    or not subtitle_background_enabled,
                )
            config.ui["subtitle_background_color"] = selected_subtitle_background_color
            params.text_background_color = (
                selected_subtitle_background_color
                if subtitle_background_enabled
                else False
            )

            saved_rounded_subtitle_background = config.ui.get(
                "rounded_subtitle_background",
                DEFAULT_SUBTITLE_SETTINGS["rounded_subtitle_background"],
            )
            # 배경이 꺼져 있으면 둥근 배경에 그릴 바탕색이 없다. 여기서는 위젯을 비활성화하되 원래
            # 설정은 남겨, 다음에 자막 배경을 다시 켰을 때 이전에 저장된 둥근 모서리 선호를 계속
            # 쓸 수 있게 한다.
            rounded_background_disabled = (
                subtitle_settings_disabled or not subtitle_background_enabled
            )
            st.session_state.setdefault(
                "rounded_subtitle_background_checkbox",
                saved_rounded_subtitle_background,
            )
            selected_rounded_subtitle_background = st.checkbox(
                tr("Rounded Subtitle Background"),
                help=tr("Rounded Subtitle Background Help"),
                disabled=rounded_background_disabled,
                key="rounded_subtitle_background_checkbox",
            )
            params.rounded_subtitle_background = (
                selected_rounded_subtitle_background
                if subtitle_background_enabled
                else False
            )
            if not subtitle_settings_disabled and subtitle_background_enabled:
                config.ui["rounded_subtitle_background"] = (
                    selected_rounded_subtitle_background
                )

            if video.subtitle_colors_are_indistinguishable(params):
                # 같은 색 설정도 사용자의 정당한 선택이므로 자막 설정 영역에서 가까이 안내만 하고
                # 생성을 막지는 않는다. 실제로 어떻게 보일지는 사용자가 판단해 계속할지 정하면 된다.
                st.warning(tr("Subtitle Colors Are Indistinguishable"))

            subtitle_preview_text = params.video_script or params.video_subject
            selected_font_path = os.path.join(font_dir, params.font_name)
            if (
                params.subtitle_enabled
                and subtitle_preview_text
                and not video.subtitle_font_supports_text(
                    selected_font_path, subtitle_preview_text
                )
            ):
                st.warning(tr("Subtitle Font Does Not Support Text"))

            if st.button(
                tr("Restore Default Subtitle Settings"),
                key="restore_default_subtitle_settings",
                icon=":material/restart_alt:",
                on_click=reset_subtitle_settings,
                use_container_width=True,
            ):
                st.toast(tr("Default Subtitle Settings Restored"))


def _render_generation_controls(
    params, uploaded_files, uploaded_audio_file, uploaded_bgm_file, voice_mode
):
    """
    생성에 필요한 조건을 검증하고 작업을 제출한 뒤 로그와 결과물을 그린다.

    이번 페이지 실행에서 새 작업을 성공적으로 제출했는지 반환한다. 제출 전에 이미 설정을 저장했으므로
    호출자는 이 값을 보고 페이지 끝의 중복 저장을 건너뛴다. 백그라운드 장시간 작업이 설정 락을 먼저
    쥔 뒤 Streamlit 메인 스크립트를 막는 것을 피하기 위해서다. 메인 스크립트가 제때 끝나야 주기
    Fragment 가 진행률과 작업 로그를 계속 갱신할 수 있다.
    """
    restore_upload_requirements = st.session_state.get(
        "task_restore_upload_requirements", {}
    )
    has_local_materials = bool(
        uploaded_files or st.session_state.get("local_video_materials", [])
    )
    has_custom_audio = bool(uploaded_audio_file)
    unmet_restore_requirements = _get_unmet_restore_upload_requirements(
        restore_upload_requirements,
        video_source=params.video_source,
        voice_name=params.voice_name or "",
        has_local_materials=has_local_materials,
        has_custom_audio=has_custom_audio,
        voice_mode=voice_mode,
    )
    if "local_materials" in unmet_restore_requirements:
        st.warning(tr("Task Restore Local Materials Warning"))
    if "custom_audio" in unmet_restore_requirements:
        st.warning(tr("Task Restore Custom Audio Warning"))
    if restore_upload_requirements and not unmet_restore_requirements:
        # 사용자가 파일을 다시 올렸거나 소재 출처·음색을 직접 바꿨다. 이 시점에는 지난 작업의 업로드
        # 의존성이 명확히 처리된 것이므로 표시를 지워, 이후 일반 생성에서 예전 안내가 계속 보이지 않게 한다.
        st.session_state.pop("task_restore_upload_requirements", None)

    start_button = st.button(
        tr("Generate Video"),
        use_container_width=True,
        type="primary",
        key="generate_video_button",
        on_click=_prepare_generation_task,
    )
    render_onboarding_tour()
    if start_button:
        config.save_config()
        task_id = st.session_state.get("pending_generation_task_id") or str(uuid4())
        _add_active_generation_task(
            task_id,
            subject=params.video_subject or params.video_script or task_id,
        )
        if not params.video_subject and not params.video_script:
            _remove_active_generation_task(task_id)
            st.error(tr("Video Script and Subject Cannot Both Be Empty"))
            st.stop()

        if params.video_source not in ["pexels", "pixabay", "coverr", "local"]:
            _remove_active_generation_task(task_id)
            st.error(tr("Please Select a Valid Video Source"))
            st.stop()

        if params.video_source == "pexels" and not config.app.get(
            "pexels_api_keys", ""
        ):
            _remove_active_generation_task(task_id)
            st.error(tr("Please Enter the Pexels API Key"))
            st.stop()

        if params.video_source == "pixabay" and not config.app.get(
            "pixabay_api_keys", ""
        ):
            _remove_active_generation_task(task_id)
            st.error(tr("Please Enter the Pixabay API Key"))
            st.stop()

        if params.video_source == "coverr" and not config.app.get(
            "coverr_api_keys", ""
        ):
            _remove_active_generation_task(task_id)
            st.error(tr("Please Enter the Coverr API Key"))
            st.stop()

        if (
            params.bgm_type == "sonilo"
            and bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)
            and not sonilo_service.is_enabled()
        ):
            _remove_active_generation_task(task_id)
            st.error(tr("Sonilo API Key Required"))
            st.stop()

        if (
            params.bgm_type == "elevenlabs"
            and bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)
            and not elevenlabs_music_service.is_enabled()
        ):
            _remove_active_generation_task(task_id)
            st.error(tr("ElevenLabs API Key Required"))
            st.stop()

        if params.video_source == "local" and not has_local_materials:
            # 로컬 소재가 비어 있는데도 계속 진행하면 TTS/자막을 먼저 만든 뒤 소재 전처리 단계에서야
            # 실패한다. 작업을 시작하기 전에 막으면 의미 없는 API 호출과 중간 파일을 피할 수 있다.
            _remove_active_generation_task(task_id)
            st.error(tr("Please Upload Local Materials First"))
            st.stop()

        if voice_mode == VOICE_MODE_UPLOAD and not uploaded_audio_file:
            # 오디오 업로드는 사용자가 명시적으로 고른 나레이션 방식이므로, 파일이 없다고 조용히 TTS 로
            # 되돌아가서는 안 된다. 작업을 시작하기 전에 막아, 사용자의 선택과 다른 결과물이 나오지 않게 한다.
            _remove_active_generation_task(task_id)
            st.error(tr("Please Upload Voiceover File First"))
            st.stop()

        if "custom_audio" in unmet_restore_requirements:
            # 지난 사용자 오디오는 자동으로 다시 채울 수 없다. 사용자가 아직 다시 올리지도 않고 음색을
            # 직접 바꾸지도 않았다면 조용히 TTS 로 되돌아가는 것을 막아야 한다. 그러지 않으면 다시
            # 생성한 결과의 음성이 원래 작업과 달라진다.
            _remove_active_generation_task(task_id)
            st.error(tr("Task Restore Custom Audio Warning"))
            st.stop()

        if uploaded_bgm_file and bgm_service.should_use_bgm(
            params.bgm_type, params.bgm_volume
        ):
            try:
                saved_bgm_name = bgm_service.save_bgm_upload(
                    uploaded_bgm_file.name, uploaded_bgm_file
                )
            except bgm_service.BgmUploadError as exc:
                _remove_active_generation_task(task_id)
                logger.warning(f"WebUI background music upload rejected: {str(exc)}")
                st.error(tr("Invalid Background Music"))
                st.stop()
            except bgm_service.BgmServiceError as exc:
                _remove_active_generation_task(task_id)
                logger.error(f"WebUI background music upload failed: {str(exc)}")
                st.error(tr("Background Music Validation Failed"))
                st.stop()
            # 저장에 성공하면 작업 파라미터에는 파일명만 쓴다. 영상 서비스가 BGM 화이트리스트 디렉터리
            # 두 곳에서 다시 해석하므로, 서버 절대 경로를 저장하거나 사용자에게 보여 줄 필요가 없다.
            params.bgm_file = saved_bgm_name
        elif uploaded_bgm_file:
            # 음량이 0 이면 영상 서비스가 어떤 BGM 도 쓰지 않으므로, 미리 들어 본 업로드 파일을
            # storage 에 저장하지 않는다. 나중에 음량을 올린 뒤 생성을 다시 누르면 그때 저장된다.
            params.bgm_file = ""

        if uploaded_audio_file:
            task_dir = utils.task_dir(task_id)
            try:
                custom_audio_path = _build_uploaded_file_path(
                    uploaded_audio_file,
                    task_dir,
                    CUSTOM_AUDIO_EXTENSIONS,
                    "custom-audio",
                )
            except ValueError:
                _remove_active_generation_task(task_id)
                st.error(tr("Unsupported Upload File Type"))
                st.stop()
            with open(custom_audio_path, "wb") as f:
                f.write(uploaded_audio_file.getbuffer())
            params.custom_audio_file = custom_audio_path

        if uploaded_files:
            local_videos_dir = utils.storage_dir("local_videos", create=True)
            # 다시 업로드할 때는 이번에 고른 소재를 기준으로 삼아, 예전 소재가 계속 덧붙는 것을 막는다.
            params.video_materials = []
            persisted_local_materials = []
            for file in uploaded_files:
                try:
                    file_path = _build_uploaded_file_path(
                        file,
                        local_videos_dir,
                        LOCAL_MATERIAL_EXTENSIONS,
                        "material",
                    )
                except ValueError:
                    _remove_active_generation_task(task_id)
                    st.error(tr("Unsupported Upload File Type"))
                    st.stop()
                with open(file_path, "wb") as f:
                    f.write(file.getbuffer())
                    m = MaterialInfo()
                    m.provider = "local"
                    m.url = file_path
                    params.video_materials.append(m)
                    persisted_local_materials.append(
                        {
                            "provider": m.provider,
                            "url": m.url,
                            "duration": m.duration,
                        }
                    )
            # 이미 올려 로컬에 저장한 영상 소재를 세션에 기록해, 이후 대본만 고칠 때 그대로 재사용할 수 있게 한다.
            st.session_state["local_video_materials"] = persisted_local_materials
        elif (
            params.video_source == "local" and st.session_state["local_video_materials"]
        ):
            # 사용자가 파일을 다시 올리지 않았다면, 마지막으로 디스크에 저장된 로컬 소재 목록을 재사용한다.
            params.video_materials = []
            for material in st.session_state["local_video_materials"]:
                m = MaterialInfo()
                m.provider = material.get("provider", "local")
                m.url = material.get("url", "")
                m.duration = material.get("duration", 0)
                if m.url:
                    params.video_materials.append(m)

        reusable_voice_preview = _get_reusable_full_voice_preview(
            params,
            voice_mode,
        )
        if reusable_voice_preview:
            # 미리듣기 캐시는 현재 Streamlit 세션에만 존재한다. 제출 전에 오디오를 대상 작업 디렉터리에
            # 써 두면 백그라운드 스레드는 그 작업 자신의 파일만 읽는다. 페이지가 rerun 되거나 브라우저를
            # 닫거나 사용자가 다른 음색을 미리 들어도 이미 큐에 들어간 생성 작업에는 영향이 없다.
            preview_audio_file = os.path.join(
                utils.task_dir(task_id),
                "audio.mp3",
            )
            with open(preview_audio_file, "wb") as file:
                file.write(reusable_voice_preview.pop("audio_bytes"))
            reusable_voice_preview["audio_file"] = preview_audio_file
            logger.info(
                f"reuse full voice preview for task: "
                f"task_id={task_id}, duration={reusable_voice_preview['duration']:.2f}s"
            )

        try:
            st.toast(tr("Generating Video"))
            logger.info(tr("Start Generating Video"))
            logger.info(utils.to_json(params))
            webui_task.submit_generation(
                task_id=task_id,
                params=params,
                capture_logs=not config.ui.get("hide_log", False),
                voice_preview=reusable_voice_preview,
            )
        except Exception:
            _remove_active_generation_task(task_id)
            st.error(tr("Video Generation Failed"))
            st.stop()

        st.session_state["current_generation_task_id"] = task_id
        logger.info(f"WebUI generation task submitted: task_id={task_id}")

    _render_current_generation_task()
    return start_button


def _render_application():
    """상단 바, 팝업, 생성 폼, 작업 결과를 정해진 순서로 그린다."""
    _render_top_bar()

    if st.session_state.get("settings_dialog_open", False):
        _render_settings_dialog()

    restore_applied = _apply_pending_task_restore()
    restore_candidate_id = st.session_state.get("task_restore_candidate_id")
    if restore_candidate_id:
        _render_task_restore_dialog(restore_candidate_id)
    restore_succeeded = st.session_state.pop("task_restore_succeeded", False)
    if restore_applied or restore_succeeded:
        st.success(tr("Task Configuration Loaded"))

    with st.container(key="main_settings_grid"):
        panel = st.columns(4)
    left_panel = panel[0]
    middle_panel = panel[1]
    audio_panel = panel[2]
    right_panel = panel[3]

    params = VideoParams(video_subject="")
    params.match_materials_to_script = bool(
        st.session_state.get("match_materials_to_script", False)
    )
    _render_script_settings(left_panel, params)

    uploaded_files = _render_video_settings(middle_panel, params)
    uploaded_audio_file, uploaded_bgm_file, voice_mode = _render_audio_settings(
        audio_panel, params
    )

    _render_subtitle_settings(right_panel, params)

    generation_submitted = _render_generation_controls(
        params,
        uploaded_files,
        uploaded_audio_file,
        uploaded_bgm_file,
        voice_mode,
    )

    # 생성 분기는 백그라운드 스레드를 시작하기 전에 이미 설정을 저장했다. 여기서 다시 저장해도
    # 이득이 없을뿐더러, runtime_config_lock 을 쥔 장시간 작업과 경쟁해 현재 Streamlit 스크립트가
    # 영상이 끝날 때까지 막히고 로그 Fragment 도 돌지 못하게 될 수 있다. 일반 페이지 상호작용에서는
    # 기존대로 저장한다.
    if not generation_submitted:
        config.save_config()


_render_application()
