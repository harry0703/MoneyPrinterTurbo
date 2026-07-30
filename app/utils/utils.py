import json
import math
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path
import threading
from typing import Any, Iterable
from uuid import uuid4

from loguru import logger

from app.models import const


def get_response(status: int, data: Any = None, message: str = ""):
    obj = {
        "status": status,
    }
    if data:
        obj["data"] = data
    if message:
        obj["message"] = message
    return obj


def to_json(obj):
    try:
        # Define a helper function to handle different types of objects
        def serialize(o):
            # If the object is a serializable type, return it directly
            if isinstance(o, (int, float, bool, str)) or o is None:
                return o
            # If the object is binary data, convert it to a base64-encoded string
            elif isinstance(o, bytes):
                return "*** binary data ***"
            # If the object is a dictionary, recursively process each key-value pair
            elif isinstance(o, dict):
                return {k: serialize(v) for k, v in o.items()}
            # If the object is a list or tuple, recursively process each element
            elif isinstance(o, (list, tuple)):
                return [serialize(item) for item in o]
            # If the object is a custom type, attempt to return its __dict__ attribute
            elif hasattr(o, "__dict__"):
                return serialize(o.__dict__)
            # Return None for other cases (or choose to raise an exception)
            else:
                return None

        # Use the serialize function to process the input object
        serialized_obj = serialize(obj)

        # Serialize the processed object into a JSON string
        return json.dumps(serialized_obj, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"failed to serialize object to json: {str(e)}")
        return None


def get_uuid(remove_hyphen: bool = False):
    u = str(uuid4())
    if remove_hyphen:
        u = u.replace("-", "")
    return u


_CLIP_SPEED_MIN = 0.5
_CLIP_SPEED_MAX = 2.0


def normalize_clip_speed(value, default: float = 1.0) -> float:
    """클립 재생 속도를 WebUI 가 지원하는 안전한 범위로 정규화한다."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default

    # NaN 은 일반적인 대소 비교를 빠져나가고 MoviePy 가 duration 을 계산할 때 전파된다.
    # 무한대도 정상적인 사용자 입력이 아니다. 둘 다 기본값으로 되돌려, API 와 내부 직접
    # 호출 모두 잘못된 타임라인을 만들지 않게 한다. 0 과 음수도 정상 재생 속도를 나타낼 수 없다.
    if not math.isfinite(speed) or speed <= 0:
        return default

    return min(max(speed, _CLIP_SPEED_MIN), _CLIP_SPEED_MAX)


def root_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def storage_dir(sub_dir: str = "", create: bool = False):
    d = os.path.join(root_dir(), "storage")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if create and not os.path.exists(d):
        os.makedirs(d)

    return d


def resource_dir(sub_dir: str = ""):
    d = os.path.join(root_dir(), "resource")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    return d


def task_dir(sub_dir: str = ""):
    d = os.path.join(storage_dir(), "tasks")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def font_dir(sub_dir: str = ""):
    d = resource_dir("fonts")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def song_dir(sub_dir: str = ""):
    d = resource_dir("songs")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def public_dir(sub_dir: str = ""):
    d = resource_dir("public")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def get_ffmpeg_binary() -> str:
    """
    현재 프로세스가 사용할 FFmpeg 실행 파일을 해석한다.

    이 함수를 둔 이유:
    1. 영상 인코딩, 무음 오디오 생성, pydub 오디오 변환이 모두 FFmpeg 에 의존한다.
    2. Windows 포터블 패키지, Docker, 사용자 지정 설치 디렉터리에서 PATH 가 자주 어긋난다.
    3. 한곳에서 해석하면 모든 호출자가 같은 우선순위를 쓰게 되어, 어떤 경로에서는 돌고
       다른 경로에서는 FFmpeg 를 못 찾는 현장 문제를 줄일 수 있다.

    우선순위:
    1. IMAGEIO_FFMPEG_EXE: MoviePy/imageio 가 정한 명시적 설정
    2. 시스템 PATH 의 ffmpeg
    3. imageio-ffmpeg 의존성이 제공하는 내장 바이너리
    4. 문자열 "ffmpeg" 로 대비. subprocess 가 실행 시점에 더 구체적인 오류를 드러내게 한다.
    """
    configured_ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE")
    if configured_ffmpeg:
        return configured_ffmpeg

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg

        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_ffmpeg:
            return bundled_ffmpeg
    except Exception as exc:
        logger.warning(f"failed to resolve bundled ffmpeg binary: {str(exc)}")

    return "ffmpeg"


def run_in_background(func, *args, **kwargs):
    def run():
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"run_in_background error: {e}", exc_info=True)

    thread = threading.Thread(target=run, daemon=False)
    thread.start()
    return thread


def time_convert_seconds_to_hmsm(seconds) -> str:
    hours = int(seconds // 3600)
    seconds = seconds % 3600
    minutes = int(seconds // 60)
    milliseconds = int(seconds * 1000) % 1000
    seconds = int(seconds % 60)
    return "{:02d}:{:02d}:{:02d},{:03d}".format(hours, minutes, seconds, milliseconds)


def text_to_srt(idx: int, msg: str, start_time: float, end_time: float) -> str:
    start_time = time_convert_seconds_to_hmsm(start_time)
    end_time = time_convert_seconds_to_hmsm(end_time)
    srt = """%d
%s --> %s
%s
        """ % (
        idx,
        start_time,
        end_time,
        msg,
    )
    return srt


def str_contains_punctuation(word):
    for p in const.PUNCTUATIONS:
        if p in word:
            return True
    return False


def split_string_by_punctuations(s):
    result = []
    txt = ""

    previous_char = ""
    next_char = ""
    for i in range(len(s)):
        char = s[i]
        if char == "\n":
            result.append(txt.strip())
            txt = ""
            continue

        if i > 0:
            previous_char = s[i - 1]
        if i < len(s) - 1:
            next_char = s[i + 1]

        if char == "." and previous_char.isdigit() and next_char.isdigit():
            # # In the case of "withdraw 10,000, charged at 2.5% fee", the dot in "2.5" should not be treated as a line break marker
            txt += char
            continue

        if char == "," and previous_char.isdigit() and next_char.isdigit():
            # 영어 숫자의 천 단위 쉼표는 문장 분리 기호가 아니다. 예: "1,000 years".
            # Edge TTS 의 word boundary 는 보통 이런 숫자를 하나의 연속된 덩어리로 반환한다.
            # 여기서 "1" 과 "000 years" 로 쪼개면 이후 자막 병합이 대본 원문과 매칭되지 않아
            # 잘못 Whisper 로 되돌아가게 된다.
            txt += char
            continue

        if char not in const.PUNCTUATIONS:
            txt += char
        else:
            result.append(txt.strip())
            txt = ""
    result.append(txt.strip())
    # filter empty string
    result = list(filter(None, result))
    return result


def normalize_script_for_subtitle_matching(video_script: str) -> str:
    """
    자막 매칭 전에 대본 텍스트를 정리한다.

    사용자가 Markdown 구분선, 제목 강조, `_` 같은 서식 기호를 직접 입력할 수 있다.
    이런 문자는 보통 TTS/Whisper 인식 결과에 나타나지 않는다. 그대로 자막 줄 단위
    매칭에 참여시키면 대본 줄 수가 실제 자막 줄 수보다 많아지고, 결국
    `00:00:00,000 --> 00:00:00,000` 이 채워져 편집 프로그램이 SRT 를 불러오지 못할 수 있다.
    """
    video_script = video_script or ""
    underscore_count = video_script.count("_")
    video_script = video_script.replace("_", "")
    cleaned_lines = []
    removed_separator_lines = 0
    for line in video_script.splitlines():
        line = line.strip()
        # Markdown 구분선이나 강조 기호가 단독 줄을 이루면 TTS 가 읽지 않는다. 대본 줄에서
        # 제거해야 자막 병합이 이런 '소리 낼 수 없는' 목표 줄에서 멈추지 않는다.
        if re.fullmatch(r"[-*_]{3,}", line):
            removed_separator_lines += 1
            continue
        cleaned_lines.append(line)

    normalized_script = "\n".join(cleaned_lines).strip()
    if underscore_count or removed_separator_lines:
        logger.debug(
            "normalized script for subtitle matching, "
            f"removed underscores: {underscore_count}, "
            f"removed markdown separator lines: {removed_separator_lines}"
        )
    return normalized_script


def md5(text):
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()


def resolve_ui_language(
    saved_language: str | None,
    browser_locale: str | None,
    supported_languages: Iterable[str],
    default_language: str = "en",
) -> str:
    """
    '저장된 설정 → 브라우저 언어 → 기본 언어' 우선순위로 화면 언어를 고른다.

    브라우저는 보통 지역이 붙은 locale 을 반환한다. 예: ``ko-KR``, ``pt-BR``. 언어 파일은
    ``ko``, ``pt`` 같은 기본 코드를 쓰므로, 먼저 완전 일치를 시도한 뒤 하이픈 앞의 언어
    코드로 되돌린다. 함수는 순수 로직으로 유지해, 브라우저 컨텍스트와 설정 쓰기가
    유틸 계층에 얽히지 않게 하고 테스트도 쉽게 만든다.
    """
    supported = [str(language).strip() for language in supported_languages]
    supported_by_lower = {
        language.lower(): language for language in supported if language
    }

    def match_language(value: str | None) -> str | None:
        normalized = str(value or "").strip().replace("_", "-").lower()
        if not normalized:
            return None
        if normalized in supported_by_lower:
            return supported_by_lower[normalized]
        base_language = normalized.split("-", 1)[0]
        return supported_by_lower.get(base_language)

    saved_match = match_language(saved_language)
    if saved_match:
        return saved_match

    browser_match = match_language(browser_locale)
    if browser_match:
        return browser_match

    default_match = match_language(default_language)
    if default_match:
        return default_match

    # 정상적인 프로젝트에는 항상 영어가 들어 있다. 빈 언어 집합에 대한 대비를 남겨 둬,
    # 언어 디렉터리가 손상됐을 때 페이지 초기화가 곧바로 예외를 던지지 않게 한다.
    # 이후 번역 함수는 진단하기 쉽도록 원본 key 를 그대로 표시한다.
    return supported[0] if supported else default_language


@lru_cache(maxsize=8)
def load_locales(i18n_dir):
    # WebUI 는 상호작용할 때마다 Streamlit 이 스크립트를 다시 실행하게 만든다. 언어 파일은
    # 실행 중에 바뀌지 않으므로 해석 결과를 캐시해, 모든 i18n JSON 파일을 반복해서 읽고
    # 해석하지 않게 한다.
    _locales = {}
    for root, dirs, files in os.walk(i18n_dir):
        for file in files:
            if file.endswith(".json"):
                lang = file.split(".")[0]
                with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                    _locales[lang] = json.loads(f.read())
    return _locales


def parse_extension(filename):
    return Path(filename).suffix.lower().lstrip('.')
