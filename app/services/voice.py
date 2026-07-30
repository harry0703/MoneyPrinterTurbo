import asyncio
import base64
import io
import inspect
import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import unicodedata
from datetime import datetime
from typing import Union
from xml.sax.saxutils import escape, unescape

import edge_tts
import requests
from edge_tts import SubMaker
from loguru import logger
from moviepy.video.tools import subtitles
from moviepy.audio.io.AudioFileClip import AudioFileClip
from openai import OpenAI

from app.config import config
from app.utils import utils

_DEFAULT_EDGE_TTS_TIMEOUT_SECONDS = 30.0
_MIMO_DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
_MIMO_DEFAULT_TTS_MODEL = "mimo-v2.5-tts"
NO_VOICE_NAME = "no-voice"
# `none` 은 PR #981 에서 쓰던 '나레이션 없음' 식별자다. 이 분기를 직접 호출해 본 API
# 사용자가 업그레이드 직후 바로 깨지지 않도록 당분간 이 값도 받아 준다. WebUI 와 새 코드는
# 더 명확한 `no-voice` 로 통일한다.
_NO_VOICE_ALIASES = {NO_VOICE_NAME, "none"}


def _configure_pydub_ffmpeg(audio_segment_cls):
    configured_ffmpeg = utils.get_ffmpeg_binary()
    if configured_ffmpeg:
        audio_segment_cls.converter = configured_ffmpeg


def mktimestamp(time_unit: float) -> str:
    """
    edge_tts 가 쓰는 100 나노초 시간 단위를 자막 타임스탬프로 변환한다.

    edge_tts 7.x 는 예전 버전의 `mktimestamp` 를 더 이상 내보내지 않는다. 하지만 이 프로젝트의
    예전 자막 경로는 Azure v2, Gemini, SiliconFlow 처럼 직접 구성한 자막 타임라인을 지원하려면
    이 포맷 함수가 필요하므로, 같은 동작을 하는 구현을 여기에 둔다.
    """
    hour = math.floor(time_unit / 10**7 / 3600)
    minute = math.floor((time_unit / 10**7 / 60) % 60)
    seconds = (time_unit / 10**7) % 60
    return f"{hour:02d}:{minute:02d}:{seconds:06.3f}"


def get_siliconflow_voices() -> list[str]:
    """
    SiliconFlow 의 음성 목록을 가져온다.

    Returns:
        음성 목록. 형식은 ["siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex", ...]
    """
    # SiliconFlow 의 음성 목록과 대응 성별 (표시용)
    voices_with_gender = [
        ("FunAudioLLM/CosyVoice2-0.5B", "alex", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "anna", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "bella", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "benjamin", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "charles", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "claire", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "david", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "diana", "Female"),
    ]

    # siliconflow: 접두사를 붙이고 표시용 이름으로 형식을 맞춘다
    return [
        f"siliconflow:{model}:{voice}-{gender}"
        for model, voice, gender in voices_with_gender
    ]


def get_gemini_voices() -> list[str]:
    """
    Gemini TTS 의 음성 목록을 가져온다.

    Returns:
        음성 목록. 형식은 ["gemini:Zephyr-Female", "gemini:Puck-Male", ...]
    """
    # Gemini TTS 가 지원하는 음성 목록
    voices_with_gender = [
        ("Zephyr", "Female"),
        ("Puck", "Male"), 
        ("Charon", "Male"),
        ("Kore", "Female"),
        ("Fenrir", "Male"),
        ("Aoede", "Female"),
        ("Thalia", "Female"),
        ("Sage", "Male"),
        ("Echo", "Female"),
        ("Harmony", "Female"),
        ("Lux", "Female"),
        ("Nova", "Female"),
        ("Vale", "Male"),
        ("Orion", "Male"),
        ("Atlas", "Male"),
    ]
    
    # gemini: 접두사를 붙이고 표시용 이름으로 형식을 맞춘다
    return [
        f"gemini:{voice}-{gender}"
        for voice, gender in voices_with_gender
    ]


def get_mimo_voices() -> list[str]:
    """
    Xiaomi MiMo V2.5 TTS 의 사전 정의 음색 목록을 가져온다.

    지금은 공식 문서의 `mimo-v2.5-tts` 사전 정의 음색 모드만 연결한다. 음색 디자인
    `mimo-v2.5-tts-voicedesign` 과 음색 복제 `mimo-v2.5-tts-voiceclone` 은 별도 입력 폼과
    소재 업로드 흐름이 필요하므로, 일반 TTS 드롭다운에 섞지 않는다. 사용자가 voice id 하나만
    고르면 모든 고급 기능이 되는 줄 오해하지 않게 하기 위해서다.

    아래 음색 id 는 MiMo API 에 그대로 보내는 값이므로 번역하지 않는다.
    """
    voices_with_gender = [
        ("mimo_default", "Female"),
        ("冰糖", "Female"),   # bintang / 얼음사탕
        ("茉莉", "Female"),   # moli / 재스민
        ("苏打", "Male"),     # suda / 소다
        ("白桦", "Male"),     # baihua / 자작나무
        ("Mia", "Female"),
        ("Chloe", "Female"),
        ("Milo", "Male"),
        ("Dean", "Male"),
    ]

    return [f"mimo:{voice}-{gender}" for voice, gender in voices_with_gender]


def get_elevenlabs_voices(api_key: str) -> list[str]:
    if not api_key:
        return []
    try:
        url = "https://api.elevenlabs.io/v2/voices"
        params = {"is_favorite": "true", "page_size": 100}
        headers = {"xi-api-key": api_key}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(
                f"ElevenLabs voices fetch failed with status {response.status_code}: {response.text}"
            )
            return []
        data = response.json()
        voices = data.get("voices", [])
        return [
            f"elevenlabs:{v['voice_id']}:{v['name']}"
            for v in voices
            if v.get("voice_id") and v.get("name") and v.get("status") != "disabled"
        ]
    except Exception as e:
        logger.warning(f"ElevenLabs voices fetch failed: {str(e)}")
        return []


def get_chatterbox_voices() -> list[str]:
    """Return the configured Chatterbox voices.

    Chatterbox is self-hosted, so there is no global voice catalog. Operators
    list the voice names exposed by their server via ``[chatterbox] voices``
    (a TOML array, or a comma-separated string). Each entry is normalised to
    the ``chatterbox:<name>`` format used by the TTS dispatcher.
    """
    voices = config.chatterbox.get("voices", []) or []
    if isinstance(voices, str):
        voices = [v.strip() for v in voices.split(",") if v.strip()]
    result = []
    for v in voices:
        v = str(v).strip()
        if not v:
            continue
        result.append(v if v.startswith("chatterbox:") else f"chatterbox:{v}")
    if not result:
        # keep the dropdown usable even before any voice is configured
        result = ["chatterbox:default-Female"]
    return result


_AZURE_VOICES_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "data", "azure_voices.json"
)
_azure_voices_cache = None


def _load_azure_voices() -> list[dict]:
    global _azure_voices_cache
    if _azure_voices_cache is None:
        with open(_AZURE_VOICES_DATA_FILE, "r", encoding="utf-8") as f:
            _azure_voices_cache = json.load(f)
    return _azure_voices_cache


def get_all_azure_voices(filter_locals=None) -> list[str]:
    voices = []
    for item in _load_azure_voices():
        name = item["name"]
        gender = item["gender"]
        # 필터 조건을 적용한다
        if filter_locals and any(
            name.lower().startswith(fl.lower()) for fl in filter_locals
        ):
            voices.append(f"{name}-{gender}")
        elif not filter_locals:
            voices.append(f"{name}-{gender}")

    voices.sort()
    return voices


def parse_voice_name(name: str):
    # zh-CN-XiaoyiNeural-Female
    # zh-CN-YunxiNeural-Male
    # zh-CN-XiaoxiaoMultilingualNeural-V2-Female
    name = name.replace("-Female", "").replace("-Male", "").strip()
    return name


def is_azure_v2_voice(voice_name: str):
    voice_name = parse_voice_name(voice_name)
    if voice_name.endswith("-V2"):
        return voice_name.replace("-V2", "").strip()
    return ""


def is_siliconflow_voice(voice_name: str):
    """SiliconFlow 음성인지 확인한다."""
    return voice_name.startswith("siliconflow:")


def is_gemini_voice(voice_name: str):
    """Gemini TTS 음성인지 확인한다."""
    return voice_name.startswith("gemini:")


def is_mimo_voice(voice_name: str):
    """Xiaomi MiMo TTS 음성인지 확인한다."""
    return voice_name.startswith("mimo:")


def is_elevenlabs_voice(voice_name: str) -> bool:
    return (voice_name or "").startswith("elevenlabs:")


def is_chatterbox_voice(voice_name: str) -> bool:
    return (voice_name or "").startswith("chatterbox:")


def is_no_voice(voice_name: str | None) -> bool:
    """
    사용자가 '나레이션 없음' 모드를 명시적으로 골랐는지 판정한다.

    여기서 빈 문자열을 '나레이션 없음' 으로 보지 않는 것은 의도적이다. voice 가 비어 있는 것은
    설정 손상, 예전 WebUI 상태 유실, 파라미터 누락일 가능성이 더 크다. 명확한 sentinel 값일
    때만 무음 분기로 들어가야, 진짜 오류가 정상 생성처럼 위장되지 않는다.
    """
    return str(voice_name or "").strip().lower() in _NO_VOICE_ALIASES


def estimate_no_voice_duration(text: str) -> float:
    """
    나레이션 없음 모드에서 쓸 안정적인 영상 타임라인 길이를 추정한다.

    나레이션이 없어도 기존 소재 자르기, 자막 타임라인, 최종 합성을 돌리려면 오디오 자리표시자가
    필요하다. 추정 전략은 최대한 단순하게 잡았다.
    1. 한자 등 CJK 문자는 초당 약 4.2 자로 추정한다.
    2. 영문/숫자는 초당 약 2.7 단어로 추정한다.
    3. 그 밖의 언어 문자는 초당 약 4.0 자로 추정해, 러시아어·아랍어·일본어 가나·한글 같은
       비 ASCII 텍스트를 덮는다.
    4. 문장이 끊길 때마다 약간의 쉼을 더해 자막 전환이 너무 촘촘해지지 않게 한다.
    5. 최소 3 초를 보장해, 아주 짧은 대본이 0 초 오디오를 만들지 않게 한다.
    """
    normalized_text = (text or "").strip()
    if not normalized_text:
        return 3.0

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", normalized_text))
    words = len(re.findall(r"[A-Za-z0-9]+", normalized_text))
    ascii_word_chars = sum(len(word) for word in re.findall(r"[A-Za-z0-9]+", normalized_text))
    other_text_chars = 0
    for char in normalized_text:
        # Unicode category 가 L 로 시작하면 각 언어의 문자, N 이면 숫자다. 앞에서 CJK 와 ASCII
        # 단어는 따로 셌으므로, 여기서는 남은 문자만 세어 영어가 두 번 계산되지 않게 한다.
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            other_text_chars += 1
    other_text_chars = max(other_text_chars - cjk_chars - ascii_word_chars, 0)
    sentence_count = max(len(utils.split_string_by_punctuations(normalized_text)), 1)

    cjk_duration = cjk_chars / 4.2
    word_duration = words / 2.7
    other_text_duration = other_text_chars / 4.0
    pause_duration = max(sentence_count - 1, 0) * 0.35
    return max(3.0, cjk_duration + word_duration + other_text_duration + pause_duration)


def generate_silent_audio(duration_seconds: float, output_file: str) -> bool:
    """
    '나레이션 없음' 모드의 타임라인 자리표시자로 쓸 MP3 무음 오디오를 만든다.

    FFmpeg 의 anullsrc 로 무음을 바로 만들면, 임시 WAV 를 만든 뒤 변환하는 것보다 중간 파일이
    적다. 실패하면 False 를 반환해 상위 계층이 일반 TTS 실패 경로대로 처리하고 로그를 남기게 한다.
    """
    ensure_file_path_exists(output_file)
    duration_seconds = max(float(duration_seconds or 0), 0.1)
    ffmpeg_binary = utils.get_ffmpeg_binary()
    command = [
        ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        f"{duration_seconds:.3f}",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "4",
        output_file,
    ]

    logger.info(
        f"generating silent audio for no-voice mode, duration: {duration_seconds:.2f}s"
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.error(
            "failed to generate silent audio: "
            f"{(result.stderr or result.stdout or '').strip()}"
        )
        return False
    if not os.path.exists(output_file) or os.path.getsize(output_file) <= 0:
        logger.error(
            "silent audio output file is missing or empty, "
            f"file: {output_file}, duration: {duration_seconds:.2f}s"
        )
        return False
    return True


def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    if is_no_voice(voice_name):
        duration_seconds = estimate_no_voice_duration(text)
        if not generate_silent_audio(duration_seconds, voice_file):
            return None

        sub_maker = ensure_legacy_submaker_fields(SubMaker())
        return populate_legacy_submaker_with_full_text(
            sub_maker=sub_maker,
            text=text,
            audio_duration_seconds=duration_seconds,
        )

    if is_azure_v2_voice(voice_name):
        return azure_tts_v2(
            text,
            voice_name,
            voice_file,
            voice_rate=voice_rate,
        )
    elif is_siliconflow_voice(voice_name):
        # voice_name 에서 모델과 음성을 뽑아낸다
        # 형식: siliconflow:model:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 3:
            model = parts[1]
            # 성별 접미사를 제거한다. 예: "alex-Male" -> "alex"
            voice_with_gender = parts[2]
            voice = voice_with_gender.split("-")[0]
            # 전체 voice 파라미터를 만든다. 형식은 "model:voice"
            full_voice = f"{model}:{voice}"
            return siliconflow_tts(
                text, model, full_voice, voice_rate, voice_file, voice_volume
            )
        else:
            logger.error(f"Invalid siliconflow voice name format: {voice_name}")
            return None
    elif is_gemini_voice(voice_name):
        # voice_name 에서 음성 이름을 뽑아낸다
        # 형식: gemini:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 2:
            # 성별 접미사를 제거한다. 예: "Zephyr-Female" -> "Zephyr"
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            return gemini_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid gemini voice name format: {voice_name}")
            return None
    elif is_mimo_voice(voice_name):
        # voice_name 에서 음성 이름을 뽑아낸다
        # 형식: mimo:voice-Gender. 호출자가 parse_voice_name 을 이미 실행했다면
        # mimo:voice 형태일 수도 있다. 두 형식 모두 지원한다.
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            return mimo_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid mimo voice name format: {voice_name}")
            return None
    elif is_elevenlabs_voice(voice_name):
        # 형식: elevenlabs:{voice_id}:{name}
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_id = parts[1]
            return elevenlabs_tts(text, voice_id, voice_file, voice_rate, voice_volume)
        else:
            logger.error(f"Invalid elevenlabs voice name format: {voice_name}")
            return None
    elif is_chatterbox_voice(voice_name):
        # 형식: chatterbox:<voice>. voice 에는 표시용 -Female/-Male 접미사가 붙을 수 있다
        parts = voice_name.split(":", 1)
        if len(parts) >= 2 and parts[1].strip():
            chatterbox_voice = parts[1].strip()
            if chatterbox_voice.endswith(("-Female", "-Male")):
                chatterbox_voice = chatterbox_voice.rsplit("-", 1)[0]
            return chatterbox_tts(
                text, chatterbox_voice, voice_file, voice_rate, voice_volume
            )
        else:
            logger.error(f"Invalid chatterbox voice name format: {voice_name}")
            return None
    return azure_tts_v1(text, voice_name, voice_rate, voice_file)


def convert_rate_to_percent(rate: float) -> str:
    # edge-tts requires a sign-prefixed percentage (e.g. "+0%", "-20%").
    # Rounding can yield 0 for rates near but not equal to 1.0 (e.g. 1.004,
    # 0.997); those must still be returned as "+0%", not the unsigned "0%"
    # which edge-tts rejects with ValueError: Invalid rate '0%'.
    # API 나 배치 호출이 0, 0.0, None, 변환할 수 없는 빈 값을 넘길 수 있다. 이런 값은 유효한
    # 말하기 속도가 아니어서 그대로 계산하면 -100% 가 되거나 예외가 난다. 여기서 일괄로 정상
    # 속도로 되돌려, 극단적으로 느린 오디오가 만들어지거나 경계 입력에서 TTS 흐름이 실패하는
    # 것을 막는다.
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    if rate <= 0:
        rate = 1.0
    percent = round((rate - 1.0) * 100)
    if percent >= 0:
        return f"+{percent}%"
    return f"{percent}%"


def ensure_file_path_exists(file_path: str) -> None:
    """
    출력 파일이 놓일 디렉터리가 반드시 존재하도록 보장한다.

    여기에 방어 계층을 따로 둔 이유는, edge_tts 7.x 가 네트워크 요청을 보내기도 전에 대상
    오디오 파일을 먼저 열기 때문이다. 디렉터리가 없으면 로컬 파일 경로 때문에 곧바로 오류가
    나서 실제 TTS 동작 결과가 가려진다.
    """
    dir_path = os.path.dirname(file_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def ensure_legacy_submaker_fields(sub_maker: SubMaker) -> SubMaker:
    """
    아직 예전 자막 구조를 쓰는 호출자를 위해 호환 필드를 채워 준다.

    edge_tts 7.x 의 `SubMaker` 는 주로 `cues/get_srt()` 를 노출하지만, 이 프로젝트의 Azure v2,
    Gemini, SiliconFlow 경로는 여전히 `subs/offset` 을 직접 읽고 쓴다. 여기서 한곳에 채워 둬,
    edge_tts 를 올린 뒤 이 비 edge 경로들이 함께 깨지지 않게 한다.
    """
    if not hasattr(sub_maker, "subs"):
        sub_maker.subs = []
    if not hasattr(sub_maker, "offset"):
        sub_maker.offset = []
    return sub_maker


def populate_legacy_submaker_with_full_text(
    sub_maker: SubMaker, text: str, audio_duration_seconds: float
) -> SubMaker:
    """
    전체 텍스트로 프로젝트가 예전부터 쓰던 `subs/offset` 자막 구조를 채운다.

    배경:
    1. edge_tts 7.x 의 `SubMaker` 는 예전 버전의 `create_sub()` 를 더 이상 제공하지 않는다.
    2. 프로젝트의 Gemini, SiliconFlow 같은 비 edge 경로는 여전히 `subs/offset` 을 가진 객체를
       반환해야 한다. 이후 오디오 길이 계산과 자막 생성을 한곳에서 처리하기 위해서다.
    3. 단어 단위 경계를 얻을 수 없는 TTS 서비스에 대해서는 최소한 대본 문장 단위로는 나눠야
       한다. 그래야 이후 `subtitle_provider=edge` 의 병합 로직이 계속 동작하고, 전체 텍스트가
       대본 문장과 줄 단위로 매칭되지 않아 Whisper 로 되돌아가는 일이 없다.

    Args:
        sub_maker: 호환 필드를 채워 넣을 자막 객체
        text: 원본 대본 텍스트
        audio_duration_seconds: 오디오 총 길이 (초)

    Returns:
        호환 자막 데이터가 채워진 SubMaker 객체
    """
    sub_maker = ensure_legacy_submaker_fields(sub_maker)

    # 예전 값을 비운다. 호출자가 객체를 재사용할 때 오래된 데이터가 겹쳐 쌓이지 않게 하기 위해서다.
    sub_maker.subs = []
    sub_maker.offset = []

    normalized_text = (text or "").strip()
    if not normalized_text:
        return sub_maker

    audio_duration_100ns = max(int(audio_duration_seconds * 10000000), 1)

    # Gemini / SiliconFlow 같은 경로에서 단어 단위 경계를 얻지 못할 때도, 프로젝트가 원래 쓰던
    # '문장 부호로 나누고 글자 수 비율로 길이를 배분하는' 전략을 최대한 그대로 따른다. 그래야
    # create_subtitle() 이 대본 문장과 매칭되고, 다시 Whisper 로 되돌아가지 않는다.
    sentences = utils.split_string_by_punctuations(normalized_text)
    if not sentences:
        sentences = [normalized_text]

    total_chars = sum(len(sentence) for sentence in sentences)
    if total_chars <= 0:
        sub_maker.subs.append(normalized_text)
        sub_maker.offset.append((0, audio_duration_100ns))
        return sub_maker

    current_offset = 0
    for index, sentence in enumerate(sentences):
        cleaned_sentence = sentence.strip()
        if not cleaned_sentence:
            continue

        # 앞쪽 문장들은 글자 수 비율로 길이를 배분하고, 마지막 문장이 남은 길이를 모두 가져간다.
        # 정수 반올림 때문에 총 길이가 줄거나 자막 종료 시각이 오디오보다 짧아지는 것을 막는다.
        if index == len(sentences) - 1:
            sentence_end = audio_duration_100ns
        else:
            sentence_chars = len(cleaned_sentence)
            sentence_duration = max(
                int(audio_duration_100ns * (sentence_chars / total_chars)),
                1,
            )
            sentence_end = min(current_offset + sentence_duration, audio_duration_100ns)

        sub_maker.subs.append(cleaned_sentence)
        sub_maker.offset.append((current_offset, sentence_end))
        current_offset = sentence_end

    return sub_maker


def create_edge_tts_communicate(
    text: str, voice_name: str, rate_str: str
) -> edge_tts.Communicate:
    """
    현재 설치된 edge_tts 버전에 맞춰 Communicate 객체를 만든다.

    배경:
    1. 메인 코드는 이미 edge_tts 7.x 로 올렸고, `boundary` 파라미터로 더 세밀한 경계 이벤트를 받는다.
    2. 그런데 Windows 포터블 패키지 업데이트가 실패하면 현장 환경은 예전 edge_tts 에 머물 수 있다.
    3. 예전 `Communicate.__init__()` 은 `boundary` 를 받지 않아
       `unexpected keyword argument 'boundary'` 를 곧바로 던지고 TTS 경로 전체가 실패한다.

    그래서 여기서는 생성자 시그니처로 현재 버전이 지원하는 파라미터를 먼저 탐지한 뒤 `boundary`
    를 넘길지 정한다. 같은 코드가 예전 의존성과 새 의존성 모두에서 동작하게 하기 위해서다.
    """
    communicate_kwargs = {"rate": rate_str}
    communicate_signature = inspect.signature(edge_tts.Communicate)

    if "boundary" in communicate_signature.parameters:
        communicate_kwargs["boundary"] = "WordBoundary"

    return edge_tts.Communicate(text, voice_name, **communicate_kwargs)


def get_edge_tts_timeout_seconds() -> Union[float, None]:
    """
    Azure TTS V1 의 단일 스트리밍 요청 타임아웃을 가져온다.

    배경:
    Edge consumer TTS 는 네트워크가 막혔거나 서버가 요청을 제한하거나 voice 와 텍스트 언어가
    맞지 않을 때 `stream_sync()` 안에서 오래 멈출 수 있고, 로그는 `start` 에서 더 나아가지 않는다.
    여기서 기본 타임아웃을 둬 WebUI 작업이 오래도록 아무 반응이 없는 상황을 막는다.

    사용법:
    - 기본값은 30 초로, 일반적인 숏폼 대본의 첫 패킷 대기 시간을 덮는다.
    - 느린 네트워크나 프록시 환경이라면 `config.toml` 에서 다음을 설정할 수 있다
      `edge_tts_timeout = 60`；
    - 0 이나 음수로 설정하면 타임아웃을 명시적으로 끄며, 완전한 하위 호환을 유지한다.
    """
    raw_timeout = config.app.get(
        "edge_tts_timeout", _DEFAULT_EDGE_TTS_TIMEOUT_SECONDS
    )
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        logger.warning(
            "invalid edge_tts_timeout: "
            f"{raw_timeout}, fallback to {_DEFAULT_EDGE_TTS_TIMEOUT_SECONDS}s"
        )
        timeout_seconds = _DEFAULT_EDGE_TTS_TIMEOUT_SECONDS

    if timeout_seconds <= 0:
        return None

    return timeout_seconds


def _stream_edge_tts_sync_with_timeout(
    communicate, on_chunk, timeout_seconds: float
) -> None:
    """
    전체 타임아웃을 걸고 edge_tts 7.x 의 동기 스트림을 소비한다.

    이렇게 구현한 이유:
    `stream_sync()` 자체가 블로킹 반복자여서, 네트워크 계층이 멈추면 메인 스레드가 제때 회복할 수
    없다. 여기서는 블로킹 반복을 데몬 스레드에 넣고 메인 스레드가 Queue 로 chunk 를 받는다.
    타임아웃에 도달하면 곧바로 TimeoutError 를 던져, 바깥의 재시도와 오류 로그가 계속 동작하게 한다.

    주의:
    데몬 스레드는 마지막 방어 수단으로만 쓴다. Azure TTS V1 의 재시도 3 회를 따라 소수의 스레드가
    남을 수 있고, 프로세스가 끝나면 자동으로 회수된다. WebUI 작업이 영원히 멈추는 것보다는
    통제하기 쉬운 실패 방식이다.
    """
    stream_queue = queue.Queue()
    done_marker = object()

    def _produce_chunks():
        try:
            for chunk in communicate.stream_sync():
                stream_queue.put(("chunk", chunk))
            stream_queue.put(("done", done_marker))
        except Exception as e:
            stream_queue.put(("error", e))

    thread = threading.Thread(target=_produce_chunks, daemon=True)
    thread.start()

    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise TimeoutError(
                f"edge_tts stream timed out after {timeout_seconds:g}s"
            )

        try:
            item_type, payload = stream_queue.get(
                timeout=min(0.5, remaining_seconds)
            )
        except queue.Empty:
            continue

        if item_type == "chunk":
            on_chunk(payload)
        elif item_type == "error":
            raise payload
        elif item_type == "done":
            return


def stream_edge_tts_chunks(
    communicate, on_chunk, timeout_seconds: Union[float, None] = None
) -> None:
    """
    edge_tts 의 동기 스트림과 예전 비동기 스트림을 한곳에서 소비한다.

    edge_tts 7.x 는 `stream_sync()` 를 제공해 동기 함수 안에서 바로 반복할 수 있다. 그보다 이전
    버전은 보통 비동기 `stream()` 만 있다. 예전 의존성이 남아 있는 환경에서도 `azure_tts_v1()`
    이 계속 동작하도록 여기에 스트리밍 호환 계층을 하나 둔다.

    Args:
        communicate: edge_tts.Communicate 인스턴스
        on_chunk: 이벤트 블록을 하나 받을 때마다 실행할 콜백
        timeout_seconds: 단일 스트리밍 요청의 전체 타임아웃. None 이면 타임아웃을 쓰지 않는다.
    """
    if hasattr(communicate, "stream_sync"):
        if timeout_seconds:
            _stream_edge_tts_sync_with_timeout(
                communicate, on_chunk, timeout_seconds
            )
            return

        for chunk in communicate.stream_sync():
            on_chunk(chunk)
        return

    if not hasattr(communicate, "stream"):
        raise AttributeError("edge_tts communicate object has no stream method")

    async def _consume_async_stream():
        async for chunk in communicate.stream():
            on_chunk(chunk)

    # 외부 컨텍스트를 재사용하지 않고 독립적인 이벤트 루프를 명시적으로 만든다. 동기 호출 스택에서
    # '현재 스레드에 이벤트 루프가 없다' 거나 루프를 스레드 간에 재사용하는 문제를 피하기 위해서다.
    loop = asyncio.new_event_loop()
    try:
        if timeout_seconds:
            loop.run_until_complete(
                asyncio.wait_for(_consume_async_stream(), timeout=timeout_seconds)
            )
        else:
            loop.run_until_complete(_consume_async_stream())
    finally:
        loop.close()


def azure_tts_v1(
    text: str, voice_name: str, voice_rate: float, voice_file: str
) -> Union[SubMaker, None]:
    voice_name = parse_voice_name(voice_name)
    text = text.strip()
    rate_str = convert_rate_to_percent(voice_rate)
    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

            # 여기서는 edge_tts 7.x 와, 예전 포터블 패키지에 남아 있을 수 있는 오래된 의존성을
            # 함께 지원한다.
            # 1. 새 버전은 `boundary` 와 `stream_sync()` 를 지원한다
            # 2. 예전 버전은 `boundary` 를 지원하지 않고 보통 비동기 `stream()` 만 노출한다
            ensure_file_path_exists(voice_file)
            communicate = create_edge_tts_communicate(text, voice_name, rate_str)
            sub_maker = edge_tts.SubMaker()
            timeout_seconds = get_edge_tts_timeout_seconds()

            with open(voice_file, "wb") as file:
                def _handle_chunk(chunk):
                    chunk_type = chunk["type"]
                    if chunk_type == "audio":
                        file.write(chunk["data"])
                    elif chunk_type in ["WordBoundary", "SentenceBoundary"]:
                        # 7.x 의 동기 스트림이든 예전 비동기 스트림이든, 이벤트 구조에 경계 정보가
                        # 남아 있으면 모두 SubMaker 에 넘긴다. 이후 자막 경로가 기존 로직을
                        # 그대로 타도록 보장하기 위해서다.
                        sub_maker.feed(chunk)

                stream_edge_tts_chunks(
                    communicate, _handle_chunk, timeout_seconds=timeout_seconds
                )

            if not sub_maker.get_srt():
                logger.warning("failed, sub_maker.get_srt() is empty")
                continue

            logger.info(f"completed, output file: {voice_file}")
            return sub_maker
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
            # TTS 스트리밍 쓰기가 첫 패킷 전에 타임아웃되거나 네트워크 오류가 나면 0 바이트 오디오
            # 파일이 남는다. 이런 파일은 재생할 수도 없고 이후 원인 파악을 헷갈리게 하므로, 실패
            # 후에는 빈 파일만 정리한다. 데이터가 일부라도 쓰였다면 서버 응답 내용을 분석할 수
            # 있게 파일을 그대로 남긴다.
            if os.path.exists(voice_file) and os.path.getsize(voice_file) == 0:
                try:
                    os.remove(voice_file)
                except Exception as remove_error:
                    logger.warning(
                        "failed to remove empty tts file: "
                        f"{voice_file}, error: {str(remove_error)}"
                    )
    return None


def siliconflow_tts(
    text: str,
    model: str,
    voice: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    SiliconFlow API 로 음성을 생성한다.

    Args:
        text: 음성으로 변환할 텍스트
        model: 모델 이름. 예: "FunAudioLLM/CosyVoice2-0.5B"
        voice: 음성 이름. 예: "FunAudioLLM/CosyVoice2-0.5B:alex"
        voice_rate: 말하기 속도. 범위 [0.25, 4.0]
        voice_file: 출력 오디오 파일 경로
        voice_volume: 음량. 범위 [0.6, 5.0]. SiliconFlow 의 게인 범위 [-10, 10] 으로 변환해야 한다

    Returns:
        SubMaker 객체 또는 None
    """
    text = text.strip()
    api_key = config.siliconflow.get("api_key", "")

    if not api_key:
        logger.error("SiliconFlow API key is not set")
        return None

    # voice_volume 을 SiliconFlow 의 게인 범위로 변환한다
    # voice_volume 기본값은 1.0 이고, 이는 gain 0 에 대응한다
    gain = voice_volume - 1.0
    # gain 이 [-10, 10] 범위 안에 있도록 보장한다
    gain = max(-10, min(10, gain))

    url = "https://api.siliconflow.cn/v1/audio/speech"

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "sample_rate": 32000,
        "stream": False,
        "speed": voice_rate,
        "gain": gain,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for i in range(3):  # 3 회 시도
        try:
            logger.info(
                f"start siliconflow tts, model: {model}, voice: {voice}, try: {i + 1}"
            )

            response = requests.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                # 오디오 파일을 저장한다
                with open(voice_file, "wb") as f:
                    f.write(response.content)

                # 여기서도 프로젝트의 기존 자막 구조를 그대로 쓰므로 예전 필드를 채워야 한다.
                sub_maker = ensure_legacy_submaker_fields(SubMaker())

                # 오디오 파일의 실제 길이를 가져온다
                try:
                    # moviepy 로 오디오 길이를 가져와 본다
                    from moviepy import AudioFileClip

                    audio_clip = AudioFileClip(voice_file)
                    audio_duration = audio_clip.duration
                    audio_clip.close()

                    # 오디오 길이를 100 나노초 단위로 바꾼다 (edge_tts 호환)
                    audio_duration_100ns = int(audio_duration * 10000000)

                    # 텍스트를 나눠 더 정확한 자막을 만든다
                    # 텍스트를 문장 부호 기준으로 문장 단위로 나눈다
                    sentences = utils.split_string_by_punctuations(text)

                    if sentences:
                        # 각 문장의 대략적인 길이를 계산한다 (글자 수 비율로 배분)
                        total_chars = sum(len(s) for s in sentences)
                        char_duration = (
                            audio_duration_100ns / total_chars if total_chars > 0 else 0
                        )

                        current_offset = 0
                        for sentence in sentences:
                            if not sentence.strip():
                                continue

                            # 현재 문장의 길이를 계산한다
                            sentence_chars = len(sentence)
                            sentence_duration = int(sentence_chars * char_duration)

                            # SubMaker 에 추가한다
                            sub_maker.subs.append(sentence)
                            sub_maker.offset.append(
                                (current_offset, current_offset + sentence_duration)
                            )

                            # 오프셋을 갱신한다
                            current_offset += sentence_duration
                    else:
                        # 나눌 수 없으면 전체 텍스트를 자막 하나로 쓴다
                        sub_maker.subs = [text]
                        sub_maker.offset = [(0, audio_duration_100ns)]

                except Exception as e:
                    logger.warning(f"Failed to create accurate subtitles: {str(e)}")
                    # 단순한 자막으로 되돌린다
                    sub_maker.subs = [text]
                    # 오디오 파일의 실제 길이를 쓰고, 가져올 수 없으면 10 초로 가정한다
                    sub_maker.offset = [
                        (
                            0,
                            audio_duration_100ns
                            if "audio_duration_100ns" in locals()
                            else 10000000,
                        )
                    ]

                logger.success(f"siliconflow tts succeeded: {voice_file}")
                logger.debug(
                    "siliconflow subtitle timeline generated, "
                    f"subs: {len(sub_maker.subs)}, offsets: {len(sub_maker.offset)}"
                )
                return sub_maker
            else:
                logger.error(
                    f"siliconflow tts failed with status code {response.status_code}: {response.text}"
                )
        except Exception as e:
            logger.error(f"siliconflow tts failed: {str(e)}")

    return None


def _build_azure_v2_ssml(text: str, voice_name: str, voice_rate: float) -> str:
    """Azure Speech V2 가 쓰는 SSML 을 만들고, 말하기 속도 파라미터를 안전하게 정규화한다."""
    try:
        normalized_rate = float(voice_rate)
    except (TypeError, ValueError):
        normalized_rate = 1.0
    normalized_rate = max(0.25, min(4.0, normalized_rate))

    voice_locale_parts = voice_name.split("-", 2)
    voice_locale = (
        "-".join(voice_locale_parts[:2])
        if len(voice_locale_parts) >= 2
        else "en-US"
    )
    escaped_text = escape(text)
    escaped_voice_name = escape(voice_name, {'"': "&quot;"})
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xml:lang="{voice_locale}">'
        f'<voice name="{escaped_voice_name}">'
        f'<prosody rate="{normalized_rate:g}">{escaped_text}</prosody>'
        "</voice></speak>"
    )


def azure_tts_v2(
    text: str,
    voice_name: str,
    voice_file: str,
    voice_rate: float = 1.0,
) -> Union[SubMaker, None]:
    voice_name = is_azure_v2_voice(voice_name)
    if not voice_name:
        logger.error(f"invalid voice name: {voice_name}")
        raise ValueError(f"invalid voice name: {voice_name}")
    text = text.strip()
    ssml = _build_azure_v2_ssml(text, voice_name, voice_rate)

    def _format_duration_to_offset(duration) -> int:
        if isinstance(duration, str):
            time_obj = datetime.strptime(duration, "%H:%M:%S.%f")
            milliseconds = (
                (time_obj.hour * 3600000)
                + (time_obj.minute * 60000)
                + (time_obj.second * 1000)
                + (time_obj.microsecond // 1000)
            )
            return milliseconds * 10000

        if isinstance(duration, int):
            return duration

        return 0

    for i in range(3):
        try:
            logger.info(
                f"start, voice name: {voice_name}, rate: {voice_rate}, try: {i + 1}"
            )

            import azure.cognitiveservices.speech as speechsdk

            sub_maker = ensure_legacy_submaker_fields(SubMaker())

            def speech_synthesizer_word_boundary_cb(evt: speechsdk.SessionEventArgs):
                # print('WordBoundary event:')
                # print('\tBoundaryType: {}'.format(evt.boundary_type))
                # print('\tAudioOffset: {}ms'.format((evt.audio_offset + 5000)))
                # print('\tDuration: {}'.format(evt.duration))
                # print('\tText: {}'.format(evt.text))
                # print('\tTextOffset: {}'.format(evt.text_offset))
                # print('\tWordLength: {}'.format(evt.word_length))

                duration = _format_duration_to_offset(str(evt.duration))
                offset = _format_duration_to_offset(evt.audio_offset)
                sub_maker.subs.append(evt.text)
                sub_maker.offset.append((offset, offset + duration))

            # Creates an instance of a speech config with specified subscription key and service region.
            speech_key = config.azure.get("speech_key", "")
            service_region = config.azure.get("speech_region", "")
            if not speech_key or not service_region:
                logger.error("Azure speech key or region is not set")
                return None

            audio_config = speechsdk.audio.AudioOutputConfig(
                filename=voice_file, use_default_speaker=True
            )
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, region=service_region
            )
            speech_config.speech_synthesis_voice_name = voice_name
            # speech_config.set_property(property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestSentenceBoundary,
            #                            value='true')
            speech_config.set_property(
                property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary,
                value="true",
            )

            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
            )
            speech_synthesizer = speechsdk.SpeechSynthesizer(
                audio_config=audio_config, speech_config=speech_config
            )
            speech_synthesizer.synthesis_word_boundary.connect(
                speech_synthesizer_word_boundary_cb
            )

            # speak_text_async() 는 말하기 속도 파라미터를 지원하지 않는다. SSML prosody 를 쓰면
            # 미리듣기와 정식 생성 모두 WebUI/API 가 넘긴 voice_rate 대로 속도가 조정된다.
            result = speech_synthesizer.speak_ssml_async(ssml).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.success(f"azure v2 speech synthesis succeeded: {voice_file}")
                return sub_maker
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                logger.error(
                    f"azure v2 speech synthesis canceled: {cancellation_details.reason}"
                )
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    logger.error(
                        f"azure v2 speech synthesis error: {cancellation_details.error_details}"
                    )
            logger.info(f"completed, output file: {voice_file}")
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
    return None


def gemini_tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    Google Gemini TTS 로 음성을 생성한다.

    Args:
        text: 변환할 텍스트
        voice_name: 음성 이름. 예: "Zephyr", "Puck"
        voice_rate: 말하기 속도 (현재 사용하지 않음)
        voice_file: 출력 오디오 파일 경로
        voice_volume: 오디오 음량 (현재 사용하지 않음)

    Returns:
        SubMaker 객체 또는 None
    """
    import base64
    import io
    from pydub import AudioSegment
    from google import genai
    from google.genai import types
    _configure_pydub_ffmpeg(AudioSegment)
    
    try:
        api_key = config.app.get("gemini_api_key", "")
        if not api_key:
            logger.error("Gemini API key is not set")
            return None

        logger.info(f"start, voice name: {voice_name}, try: 1")

        generation_config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )

        # google-genai 는 통합 Client 로 텍스트 모델과 TTS 모델을 호출한다. 컨텍스트 매니저가
        # 요청이 끝난 뒤 HTTP 연결을 놓아주며, 기존 PCM 변환과 자막 타임라인 로직은 그대로 둔다.
        with genai.Client(api_key=api_key) as client:
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config=generation_config,
            )

        # 응답을 확인한다
        if not response.candidates or not response.candidates[0].content:
            logger.error("No audio content received from Gemini TTS")
            return None
            
        # 오디오 데이터를 가져온다
        audio_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                break
                
        if not audio_data:
            logger.error("No audio data found in response")
            return None
            
        # 오디오 데이터는 이미 원시 바이트라 base64 디코딩이 필요 없다
        if isinstance(audio_data, str):
            # 문자열이면 base64 디코딩이 필요하다
            audio_bytes = base64.b64decode(audio_data)
        else:
            # 이미 바이트면 그대로 쓴다
            audio_bytes = audio_data
        
        # 여러 오디오 형식을 시도한다. Gemini 는 서로 다른 형식을 반환할 수 있다
        audio_segment = None
        
        # Gemini 는 Linear PCM 형식을 반환하므로 문서의 파라미터대로 해석한다
        try:
            audio_segment = AudioSegment.from_file(
                io.BytesIO(audio_bytes), 
                format="raw",
                frame_rate=24000,  # Gemini TTS 기본 샘플레이트
                channels=1,        # 모노
                sample_width=2     # 16-bit
            )
        except Exception as e:
            logger.error(f"Failed to load PCM audio: {e}")
            return None
        
        # API, CLI, 테스트가 아직 존재하지 않는 중첩 디렉터리를 출력 위치로 넘길 수 있다. 여기서
        # 파일을 실제로 쓰기 전에 상위 디렉터리를 만들어, 성공한 Gemini 요청이 로컬 경로가 없다는
        # 이유로 마지막에 결과를 잃는 일을 막고, 이 provider 가 다른 TTS 구현과 같게 동작하게 한다.
        ensure_file_path_exists(voice_file)

        # pydub 은 열린 출력 파일 객체를 반환한다. 배치로 생성할 때 직접 닫지 않으면 파일 디스크립터가
        # 계속 쌓이고, Windows 에서 이후 오디오 파일을 덮어쓰거나 삭제할 때 실패할 확률이 높아진다.
        exported_audio = audio_segment.export(voice_file, format="mp3")
        exported_audio.close()
        
        logger.info(f"completed, output file: {voice_file}")
        
        # Gemini 는 edge_tts 같은 단어 단위 경계 이벤트를 주지 않는다. 그래서 여기서는 프로젝트의
        # 기존 `subs/offset` 호환 구조로 되돌려, 최소한 이후 자막과 길이 계산 경로가 계속
        # 동작하도록 보장한다.
        sub_maker = ensure_legacy_submaker_fields(SubMaker())
        audio_duration = len(audio_segment) / 1000.0  # 초 단위로 변환
        return populate_legacy_submaker_with_full_text(
            sub_maker=sub_maker,
            text=text,
            audio_duration_seconds=audio_duration,
        )
        
    except ImportError as e:
        logger.error(f"Missing required package for Gemini TTS: {str(e)}. Please install: pip install pydub")
        return None
    except Exception as e:
        logger.error(f"Gemini TTS failed, error: {str(e)}")
        return None


def mimo_tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    Xiaomi MiMo V2.5 TTS 로 음성을 생성한다.

    공식 엔드포인트는 OpenAI Chat Completions 와 호환되지만, TTS 에는 중요한 차이가 둘 있다.
    1. 합성할 텍스트는 반드시 `assistant` 메시지에 넣어야 한다.
    2. 오디오는 `message.audio.data` 의 base64 문자열로 반환된다.

    MiMo 는 현재 단어 단위 타임라인을 돌려주지 않는다. 그래서 프로젝트에 이미 있는 legacy
    SubMaker 대비책을 재사용해, 최종 오디오 길이와 대본 문장 분리로 자막 타임라인을 만든다.
    """
    from pydub import AudioSegment

    text = (text or "").strip()
    if not text:
        logger.error("MiMo TTS text is empty")
        return None

    api_key = config.app.get("mimo_api_key", "")
    if not api_key:
        logger.error("MiMo API key is not set")
        return None

    base_url = config.app.get("mimo_base_url", "") or _MIMO_DEFAULT_BASE_URL
    model_name = config.app.get("mimo_tts_model_name", "") or _MIMO_DEFAULT_TTS_MODEL
    style_prompt = config.app.get(
        "mimo_tts_style_prompt",
        "자연스럽고 또렷한, 숏폼 나레이션에 어울리는 톤으로 읽어 주세요.",
    )

    _configure_pydub_ffmpeg(AudioSegment)

    for i in range(3):
        try:
            logger.info(
                f"start mimo tts, model: {model_name}, voice: {voice_name}, try: {i + 1}"
            )
            ensure_file_path_exists(voice_file)

            client = OpenAI(api_key=api_key, base_url=base_url)
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": style_prompt},
                    {"role": "assistant", "content": text},
                ],
                audio={
                    "format": "wav",
                    "voice": voice_name,
                },
            )

            if not completion or not getattr(completion, "choices", None):
                raise ValueError("MiMo TTS returned empty response")

            message = completion.choices[0].message
            audio = getattr(message, "audio", None)
            audio_data = None
            if isinstance(audio, dict):
                audio_data = audio.get("data")
            elif audio is not None:
                audio_data = getattr(audio, "data", None)

            if not audio_data:
                raise ValueError("MiMo TTS returned empty audio data")

            audio_bytes = base64.b64decode(audio_data)
            audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")

            output_format = utils.parse_extension(voice_file) or "mp3"
            if output_format == "wav":
                with open(voice_file, "wb") as f:
                    f.write(audio_bytes)
            else:
                audio_segment.export(voice_file, format=output_format)

            audio_duration = len(audio_segment) / 1000.0
            sub_maker = ensure_legacy_submaker_fields(SubMaker())
            logger.success(f"mimo tts succeeded: {voice_file}")
            logger.debug(
                "mimo subtitle timeline generated, "
                f"duration: {audio_duration:.3f}s, output_format: {output_format}"
            )
            return populate_legacy_submaker_with_full_text(
                sub_maker=sub_maker,
                text=text,
                audio_duration_seconds=audio_duration,
            )
        except Exception as e:
            logger.error(f"mimo tts failed: {str(e)}")

    return None


def elevenlabs_tts(
    text: str,
    voice_id: str,
    voice_file: str,
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
    model_id: str = "",
) -> Union[SubMaker, None]:
    text = (text or "").strip()
    if not text:
        logger.error("ElevenLabs TTS text is empty")
        return None

    api_key = config.elevenlabs.get("api_key", "")
    if not api_key:
        logger.error("ElevenLabs API key is not set")
        return None

    if not model_id:
        model_id = config.elevenlabs.get("model_id", "eleven_multilingual_v2")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    # Errors where retrying will never help (auth/access/validation failures).
    _NON_RETRYABLE_CODES = {401, 403, 422}
    _NON_RETRYABLE_STATUSES = {"voice_disabled", "voice_access_denied", "unauthorized"}

    for i in range(3):
        try:
            logger.info(f"start elevenlabs tts, voice_id: {voice_id}, try: {i + 1}")
            ensure_file_path_exists(voice_file)

            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code != 200:
                error_status = ""
                try:
                    detail = response.json().get("detail", {})
                    if isinstance(detail, dict):
                        error_status = detail.get("status", "")
                except Exception:
                    pass

                if response.status_code in _NON_RETRYABLE_CODES or error_status in _NON_RETRYABLE_STATUSES:
                    logger.error(
                        f"ElevenLabs TTS failed (non-retryable) — voice_id: {voice_id}, "
                        f"status: {response.status_code}, error: {error_status or response.text[:200]}. "
                        "Please select a different ElevenLabs voice."
                    )
                    return None

                logger.error(
                    f"elevenlabs tts failed with status {response.status_code}: {response.text[:200]}"
                )
                continue

            with open(voice_file, "wb") as f:
                f.write(response.content)

            audio_clip = AudioFileClip(voice_file)
            audio_duration = audio_clip.duration
            audio_clip.close()

            sub_maker = ensure_legacy_submaker_fields(SubMaker())
            logger.success(f"elevenlabs tts succeeded: {voice_file}")
            return populate_legacy_submaker_with_full_text(
                sub_maker=sub_maker,
                text=text,
                audio_duration_seconds=audio_duration,
            )
        except Exception as e:
            logger.error(f"elevenlabs tts failed: {str(e)}")

    return None


def chatterbox_tts(
    text: str,
    voice: str,
    voice_file: str,
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
    model_id: str = "",
) -> Union[SubMaker, None]:
    """Generate speech with a self-hosted Chatterbox TTS server.

    Chatterbox (Resemble AI, MIT) is an open-source, locally hosted TTS model
    with zero-shot voice cloning — a self-hostable alternative to ElevenLabs.
    This talks to an OpenAI-compatible ``/audio/speech`` endpoint, so it works
    with the common community servers (e.g. devnen/Chatterbox-TTS-Server,
    travisvn/chatterbox-tts-api). Configure ``[chatterbox] base_url`` (and an
    optional ``api_key``).

    Like ElevenLabs, Chatterbox does not return word-level timestamps, so the
    subtitle path falls back to the full-text SubMaker. For tighter subtitle
    sync set ``subtitle_provider = "whisper"``.
    """
    text = (text or "").strip()
    if not text:
        logger.error("Chatterbox TTS text is empty")
        return None

    base_url = (config.chatterbox.get("base_url", "") or "").strip().rstrip("/")
    if not base_url:
        logger.error(
            "Chatterbox base_url is not set, please configure [chatterbox] base_url in config.toml"
        )
        return None

    api_key = config.chatterbox.get("api_key", "")
    if not model_id:
        model_id = config.chatterbox.get("model_id", "chatterbox") or "chatterbox"

    url = f"{base_url}/audio/speech"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model_id,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        # OpenAI speech API accepts speed 0.25-4.0; MoneyPrinterTurbo's rate is a
        # 1.0-centred multiplier, so it maps directly (clamped to the valid range).
        "speed": max(0.25, min(4.0, float(voice_rate or 1.0))),
    }
    # voice_volume is accepted for parity with the other TTS providers but is
    # intentionally not sent: the OpenAI /audio/speech contract has no volume
    # field, so Chatterbox servers ignore it. Adjust loudness via voice_rate
    # (speed) or in post-processing instead.

    for i in range(3):
        try:
            logger.info(f"start chatterbox tts, voice: {voice}, try: {i + 1}")
            ensure_file_path_exists(voice_file)

            response = requests.post(url, json=payload, headers=headers, timeout=120)
            if response.status_code != 200:
                logger.error(
                    f"chatterbox tts failed with status {response.status_code}: {response.text[:200]}"
                )
                continue

            with open(voice_file, "wb") as f:
                f.write(response.content)

            audio_clip = AudioFileClip(voice_file)
            audio_duration = audio_clip.duration
            audio_clip.close()

            sub_maker = ensure_legacy_submaker_fields(SubMaker())
            logger.success(f"chatterbox tts succeeded: {voice_file}")
            return populate_legacy_submaker_with_full_text(
                sub_maker=sub_maker,
                text=text,
                audio_duration_seconds=audio_duration,
            )
        except Exception as e:
            logger.error(f"chatterbox tts failed: {str(e)}")

    return None


def _format_text(text: str) -> str:
    """
    자막 정렬 전에 대본 텍스트를 정리한다.

    LLM 생성 단계에서만 처리해서는 안 된다. 사용자가 대본을 직접 붙여 넣거나 API 로 Markdown
    표기가 들어간 텍스트를 바로 넘길 수 있기 때문이다. TTS 는 보통 `---`, `___`, `***` 같은
    구분선 줄을 읽지 않고 `_` 같은 강조 표기도 읽지 않는다. 자막 정렬에 이런 문자가 그대로
    남아 있으면 `create_subtitle()` 이 존재하지 않는 cue 를 계속 기다리고, 결국 자막 파일이
    없어지며 Whisper 대체 보정에서 전부 0 인 타임라인이 채워진다.
    """
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    return utils.normalize_script_for_subtitle_matching(text)


def _build_subtitle_formatter():
    """
    통일된 SRT 줄 포맷 함수를 반환한다.

    작은 도구로 따로 뺀 것은, edge_tts 7.x 의 cues 경로와 프로젝트의 기존 legacy `subs/offset`
    경로가 같은 자막 저장 형식을 공유하게 하기 위해서다. 두 로직이 각자 미묘하게 다른 형식을
    만들어 내는 것을 막는다.
    """

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n{start_t} --> {end_t}\n{sub_text}\n"

    return formatter


# 아랍어 발음 부호와 Tatweel 늘임표가 edge-tts 반환 텍스트에 나타날 수 있다. 이 문자들은
# 의미에는 영향을 주지 않지만, 대본 텍스트와 자막 cue 문자열의 정확한 매칭을 실패하게 만든다.
_ARABIC_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u0640\u06D6-\u06ED]")


def _normalize_arabic(text: str) -> str:
    """아랍어에서 흔한 글자 변형을 통일해, 자막 cue 와 대본 줄의 매칭 허용 범위를 넓힌다.

    edge-tts 는 아랍어에 대해 원본 대본과 다른 글자 형태를 반환할 수 있다. 예를 들어 أ/إ/آ 를
    ا 로 통일하거나 발음 부호를 붙인다. 여기서는 마지막 매칭 대비책에서만 쓰며, 원본 자막
    텍스트는 바꾸지 않아 최종 표시 내용에 영향을 주지 않는다.
    """
    text = _ARABIC_DIACRITICS.sub("", text)
    for src, dst in (
        ("أإآٱ", "ا"),
        ("ىئ", "ي"),
        ("ة", "ه"),
        ("ؤ", "و"),
    ):
        for ch in src:
            text = text.replace(ch, dst)
    return text


def _match_script_line(script_lines: list[str], current_text: str, sub_index: int) -> str:
    """
    지금까지 쌓인 자막 텍스트를, 대본의 표준 문장 하나와 매칭해 본다.

    프로젝트가 원래 쓰던 '문장 부호로 대본을 나눈 뒤 구간별로 비교하는' 방식을 그대로 재사용한다.
    1. 정확 일치를 먼저 시도한다.
    2. 문장 부호와 Markdown `_` 서식 기호를 제거한 뒤 다시 매칭한다.
    3. 마지막으로 아랍어 글자 형태를 정규화해 매칭한다.

    이렇게 하면 다음 경우를 모두 지원할 수 있다.
    - TTS 반환에서 문장 부호가 빠지거나 따로 떨어져 나오는 경우
    - CJK 처럼 단어 경계와 대본 텍스트가 정확히 일대일로 대응하지 않는 경우
    """
    if len(script_lines) <= sub_index:
        return ""

    target_line = script_lines[sub_index]
    if current_text == target_line:
        return target_line.strip()

    current_text_normalized = re.sub(r"[_\W]+", "", current_text)
    target_line_normalized = re.sub(r"[_\W]+", "", target_line)
    if current_text_normalized == target_line_normalized:
        return target_line.strip()

    # 마지막 아랍어 허용 계층. edge-tts 가 반환하는 글자 형태, 발음 부호, Tatweel 이 대본과 다를
    # 수 있다. 일반 매칭이 실패한 뒤에만 정규화해 비교하므로 아랍어가 아닌 텍스트는 영향을 받지 않는다.
    current_ar = re.sub(r"[_\W]+", "", _normalize_arabic(current_text))
    target_ar = re.sub(r"[_\W]+", "", _normalize_arabic(target_line))
    if current_ar and current_ar == target_ar:
        return target_line.strip()

    return ""


def _write_subtitle_items(sub_items: list[str], subtitle_file: str) -> bool:
    """
    이미 병합된 자막 구간을 SRT 파일에 쓰고, 기본적인 읽기 검증을 한 번 한다.

    반환값:
    - `True`: 자막 파일이 저장됐고 moviepy 로 해석할 수 있다.
    - `False`: 자막 파일 쓰기나 해석이 실패했다.
    """
    try:
        ensure_file_path_exists(subtitle_file)
        with open(subtitle_file, "w", encoding="utf-8") as file:
            file.write("\n".join(sub_items) + "\n")

        sbs = subtitles.file_to_subtitles(subtitle_file, encoding="utf-8")
        duration = max([tb for ((ta, tb), txt) in sbs]) if sbs else 0
        logger.info(
            f"completed, subtitle file created: {subtitle_file}, duration: {duration}"
        )
        return True
    except Exception as e:
        logger.error(f"failed, error: {str(e)}")
        if os.path.exists(subtitle_file):
            os.remove(subtitle_file)
        return False


def _build_subtitle_items_from_edge_cues(
    sub_maker: SubMaker, script_lines: list[str]
) -> list[str]:
    """
    edge_tts 7.x 의 잘게 쪼개진 `cues` 를 대본 문장 단위 SRT 구간으로 병합한다.

    배경:
    edge_tts 7.x 의 `SubMaker.get_srt()` 는 단어/짧은 구 단위 타임라인에 가깝다. 영어를 단어 단위로
    강조하는 데는 쓸 만하지만, 숏폼 자막에 그대로 옮기면 '돈 / 은 / 하나의 / 사회적 / 도구' 처럼
    읽기 매우 불편한 결과가 나온다.

    구현 전략:
    1. cues 의 `content` 를 하나씩 소비한다.
    2. 후보 텍스트로 누적한다.
    3. 후보 텍스트가 대본의 현재 목표 문장과 맞으면 완전한 자막 구간 하나로 확정한다.
    4. 첫 cue 의 시작 시각과 마지막 cue 의 종료 시각을 써서 타임라인이 끊기지 않게 한다.
    """
    formatter = _build_subtitle_formatter()
    sub_items = []
    sub_index = 0
    current_text = ""
    current_start_time = None

    for cue in sub_maker.cues:
        cue_text = unescape(cue.content)
        if current_start_time is None:
            current_start_time = int(cue.start.total_seconds() * 10000000)

        current_end_time = int(cue.end.total_seconds() * 10000000)
        current_text += cue_text

        matched_text = _match_script_line(script_lines, current_text, sub_index)
        if not matched_text:
            continue

        sub_index += 1
        sub_items.append(
            formatter(
                idx=sub_index,
                start_time=current_start_time,
                end_time=current_end_time,
                sub_text=matched_text,
            )
        )
        current_text = ""
        current_start_time = None

    if current_text.strip():
        logger.warning(
            f"edge cues still have unmatched text after aggregation: {current_text}"
        )

    return sub_items


def _build_subtitle_items_from_legacy_submaker(
    sub_maker: SubMaker, script_lines: list[str]
) -> list[str]:
    """
    프로젝트의 기존 `subs/offset` 구조를 대본 문장 단위 SRT 구간으로 병합한다.

    핵심 방식은 원래대로 유지하고 독립 함수로만 분리했다. edge_tts 7.x 의 cues 병합 로직과
    같은 문장 매칭·저장 흐름을 공유하기 위해서다.
    """
    formatter = _build_subtitle_formatter()
    start_time = -1.0
    sub_items = []
    sub_index = 0
    sub_line = ""

    legacy_offsets = getattr(sub_maker, "offset", [])
    legacy_subs = getattr(sub_maker, "subs", [])
    for _, (offset, sub) in enumerate(zip(legacy_offsets, legacy_subs)):
        current_start_time, current_end_time = offset
        if start_time < 0:
            start_time = current_start_time

        sub_line += unescape(sub)
        matched_text = _match_script_line(script_lines, sub_line, sub_index)
        if not matched_text:
            continue

        sub_index += 1
        sub_items.append(
            formatter(
                idx=sub_index,
                start_time=start_time,
                end_time=current_end_time,
                sub_text=matched_text,
            )
        )
        start_time = -1.0
        sub_line = ""

    if sub_line.strip():
        logger.warning(
            f"legacy subtitle items still have unmatched text after aggregation: {sub_line}"
        )

    return sub_items


def create_subtitle(sub_maker: SubMaker, text: str, subtitle_file: str):
    """
    자막 파일을 다듬는다.
    1. 자막 파일을 문장 부호 기준으로 여러 줄로 나눈다
    2. 자막 파일의 텍스트를 줄 단위로 매칭한다
    3. 새 자막 파일을 만든다
    """
    text = _format_text(text)
    script_lines = utils.split_string_by_punctuations(text)
    try:
        if hasattr(sub_maker, "cues") and sub_maker.cues:
            sub_items = _build_subtitle_items_from_edge_cues(sub_maker, script_lines)
        else:
            sub_items = _build_subtitle_items_from_legacy_submaker(
                sub_maker, script_lines
            )

        if len(sub_items) != len(script_lines):
            logger.warning(
                f"failed, sub_items len: {len(sub_items)}, script_lines len: {len(script_lines)}"
            )
            return

        _write_subtitle_items(sub_items, subtitle_file)
    except Exception as e:
        logger.error(f"failed, error: {str(e)}")


def _get_audio_duration_from_submaker(sub_maker: SubMaker):
    """
    오디오 길이를 가져온다.
    """
    # edge_tts 7.x 의 cues 구조를 우선 지원한다.
    # 프로젝트의 다른 TTS 가 직접 채운 예전 구조라면 계속 offset 을 읽는다.
    if hasattr(sub_maker, "cues") and sub_maker.cues:
        return sub_maker.cues[-1].end.total_seconds()

    legacy_offsets = getattr(sub_maker, "offset", [])
    if not legacy_offsets:
        return 0.0
    return legacy_offsets[-1][1] / 10000000

def _get_audio_duration_from_file(audio_file: str) -> float:
    """
    오디오 파일 길이를 가져온다 (mp3/m4a/wav/aac 등 ffmpeg 로 디코딩 가능한 형식 지원)
    """
    if not os.path.exists(audio_file):
        logger.error(f"audio file does not exist: {audio_file}")
        return 0.0

    try:
        # Use moviepy (ffmpeg) to read the duration of any supported audio format
        with AudioFileClip(audio_file) as audio:
            return audio.duration  # Duration in seconds
    except Exception as e:
        logger.error(f"Failed to get audio duration from file: {str(e)}")
        return 0.0

def get_audio_duration(target: Union[str, SubMaker]) -> float:
    """
    오디오 길이를 가져온다.
    SubMaker 객체면 SubMaker 에서 길이를 가져온다.
    오디오 파일 경로면 오디오 파일에서 길이를 가져온다 (mp3/m4a/wav 등 지원)
    """
    if isinstance(target, SubMaker):
        return _get_audio_duration_from_submaker(target)
    elif isinstance(target, str):
        return _get_audio_duration_from_file(target)
    else:
        logger.error(f"Invalid target type: {type(target)}")
        return 0.0

if __name__ == "__main__":
    voice_name = "zh-CN-XiaoxiaoMultilingualNeural-V2-Female"
    voice_name = parse_voice_name(voice_name)
    voice_name = is_azure_v2_voice(voice_name)
    print(voice_name)

    voices = get_all_azure_voices()
    print(len(voices))

    async def _do():
        temp_dir = utils.storage_dir("temp")

        voice_names = [
            "ko-KR-HyunsuMultilingualNeural",
            # 여성
            "ko-KR-SunHiNeural",
            # 남성
            "ko-KR-InJoonNeural",
        ]
        text = """
        봄날의 꽃바다가 한 폭의 그림처럼 눈앞에 펼쳐집니다. 만물이 깨어나는 계절, 대지는 화려한 색의 옷을 갈아입습니다.
        노란 개나리와 연분홍 벚꽃이 차례로 피어나고, 그 사이로 봄바람이 지나갑니다. 짧지만 선명한 이 계절은 해마다 우리에게
        같은 질문을 남깁니다. 올해의 봄을 어떻게 기억할 것인가.
        """

        text = """
        What is the meaning of life? This question has puzzled philosophers, scientists, and thinkers of all kinds for centuries. Throughout history, various cultures and individuals have come up with their interpretations and beliefs around the purpose of life. Some say it's to seek happiness and self-fulfillment, while others believe it's about contributing to the welfare of others and making a positive impact in the world. Despite the myriad of perspectives, one thing remains clear: the meaning of life is a deeply personal concept that varies from one person to another. It's an existential inquiry that encourages us to reflect on our values, desires, and the essence of our existence.
        """

        text = "[Opening scene: A sunny day in a suburban neighborhood. A young boy named Alex, around 8 years old, is playing in his front yard with his loyal dog, Buddy.]\n\n[Camera zooms in on Alex as he throws a ball for Buddy to fetch. Buddy excitedly runs after it and brings it back to Alex.]\n\nAlex: Good boy, Buddy! You're the best dog ever!\n\n[Buddy barks happily and wags his tail.]\n\n[As Alex and Buddy continue playing, a series of potential dangers loom nearby, such as a stray dog approaching, a ball rolling towards the street, and a suspicious-looking stranger walking by.]\n\nAlex: Uh oh, Buddy, look out!\n\n[Buddy senses the danger and immediately springs into action. He barks loudly at the stray dog, scaring it away. Then, he rushes to retrieve the ball before it reaches the street and gently nudges it back towards Alex. Finally, he stands protectively between Alex and the stranger, growling softly to warn them away.]\n\nAlex: Wow, Buddy, you're like my superhero!\n\n[Just as Alex and Buddy are about to head inside, they hear a loud crash from a nearby construction site. They rush over to investigate and find a pile of rubble blocking the path of a kitten trapped underneath.]\n\nAlex: Oh no, Buddy, we have to help!\n\n[Buddy barks in agreement and together they work to carefully move the rubble aside, allowing the kitten to escape unharmed. The kitten gratefully nuzzles against Buddy, who responds with a friendly lick.]\n\nAlex: We did it, Buddy! We saved the day again!\n\n[As Alex and Buddy walk home together, the sun begins to set, casting a warm glow over the neighborhood.]\n\nAlex: Thanks for always being there to watch over me, Buddy. You're not just my dog, you're my best friend.\n\n[Buddy barks happily and nuzzles against Alex as they disappear into the sunset, ready to face whatever adventures tomorrow may bring.]\n\n[End scene.]"

        text = _format_text(text)
        lines = utils.split_string_by_punctuations(text)
        print(lines)

        for voice_name in voice_names:
            voice_file = f"{temp_dir}/tts-{voice_name}.mp3"
            subtitle_file = f"{temp_dir}/tts.mp3.srt"
            sub_maker = azure_tts_v2(
                text=text, voice_name=voice_name, voice_file=voice_file
            )
            create_subtitle(sub_maker=sub_maker, text=text, subtitle_file=subtitle_file)
            audio_duration = get_audio_duration(sub_maker)
            print(f"voice: {voice_name}, audio duration: {audio_duration}s")

    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        loop.run_until_complete(_do())
    finally:
        loop.close()
