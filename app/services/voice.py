import asyncio
import json
import os
import re
import subprocess
import unicodedata
from typing import Union
from xml.sax.saxutils import unescape

import edge_tts  # noqa: F401 (kept for `voice.edge_tts` back-compat access, e.g. in tests)
import requests  # noqa: F401 (kept for `voice.requests` back-compat access, e.g. in tests)
from edge_tts import SubMaker
from loguru import logger
from moviepy.video.tools import subtitles
from moviepy.audio.io.AudioFileClip import AudioFileClip

from app.config import config  # noqa: F401 (kept for `voice.config` back-compat access, e.g. in tests)
from app.utils import utils

# Provider implementations live in dedicated ``voice_<provider>.py`` modules;
# this module stays a thin facade so ``voice.<name>`` keeps working for every
# caller (WebUI, task pipeline, tests) exactly as before the split.
from app.services.voice_common import (  # noqa: F401
    convert_rate_to_percent,
    ensure_file_path_exists,
    ensure_legacy_submaker_fields,
    is_azure_v2_voice,
    mktimestamp,
    parse_voice_name,
    populate_legacy_submaker_with_full_text,
)
from app.services.voice_edge import azure_tts_v1  # noqa: F401
from app.services.voice_azure_v2 import azure_tts_v2  # noqa: F401
from app.services.voice_siliconflow import (  # noqa: F401
    get_siliconflow_voices,
    is_siliconflow_voice,
    siliconflow_tts,
)
from app.services.voice_gemini import (  # noqa: F401
    GEMINI_TTS_VOICES,
    gemini_tts,
    get_gemini_voices,
    is_gemini_voice,
    parse_gemini_voice_name,
)
from app.services.voice_mimo import (  # noqa: F401
    get_mimo_voices,
    is_mimo_voice,
    mimo_tts,
)
from app.services.voice_minimax import (  # noqa: F401
    MINIMAX_TTS_CN_URL,
    MINIMAX_TTS_DEFAULT_MODEL,
    MINIMAX_TTS_DEFAULT_VOICE,
    MINIMAX_TTS_GLOBAL_URL,
    MINIMAX_TTS_MODELS,
    get_minimax_tts_api_key,
    get_minimax_tts_endpoint,
    get_minimax_voice_catalog,
    get_minimax_voices,
    is_minimax_voice,
    minimax_tts,
)
from app.services.voice_elevenlabs import (  # noqa: F401
    elevenlabs_tts,
    get_elevenlabs_api_key,
    get_elevenlabs_voices,
    is_elevenlabs_voice,
)
from app.services.voice_chatterbox import (  # noqa: F401
    chatterbox_tts,
    get_chatterbox_voices,
    is_chatterbox_voice,
)
from app.services.voice_fish_audio import (  # noqa: F401
    FISH_AUDIO_DEFAULT_MODEL,
    FISH_AUDIO_MODELS,
    fish_audio_tts,
    get_fish_audio_api_key,
    get_fish_audio_voices,
    is_fish_audio_voice,
)

NO_VOICE_NAME = "no-voice"
# `none` 是 PR #981 里曾使用过的无配音标识。这里短期兼容这个值，避免
# 已经手动调用过该分支的 API 用户升级后立即失效；WebUI 和新代码统一使用
# 更明确的 `no-voice`。
_NO_VOICE_ALIASES = {NO_VOICE_NAME, "none"}


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
        # 应用过滤条件
        if filter_locals and any(
            name.lower().startswith(fl.lower()) for fl in filter_locals
        ):
            voices.append(f"{name}-{gender}")
        elif not filter_locals:
            voices.append(f"{name}-{gender}")

    voices.sort()
    return voices


def is_no_voice(voice_name: str | None) -> bool:
    """
    判断用户是否明确选择了“无配音”模式。

    这里刻意不把空字符串当成无配音：空 voice 更可能是配置损坏、旧版本
    WebUI 状态丢失或接口参数缺失。只有明确的 sentinel 才进入静音分支，
    这样可以避免把真实错误伪装成正常生成。
    """
    return str(voice_name or "").strip().lower() in _NO_VOICE_ALIASES


def estimate_no_voice_duration(text: str) -> float:
    """
    为无配音模式估算一个稳定的视频时间轴长度。

    无配音仍需要一个音频占位来驱动现有素材裁剪、字幕时间轴和最终合成。
    估算策略尽量简单：
    1. 中文等 CJK 字符按约 4.2 字/秒估算；
    2. 英文/数字按约 2.7 词/秒估算；
    3. 其他语种文字按约 4.0 字符/秒兜底估算，覆盖俄语、阿拉伯语、
       日文假名、韩文等非 ASCII 文本；
    4. 每个断句补一点停顿，让字幕切换不至于过于紧凑；
    5. 最少 3 秒，避免极短脚本生成 0 秒音频。
    """
    normalized_text = (text or "").strip()
    if not normalized_text:
        return 3.0

    cjk_chars = len(re.findall(r"[一-鿿]", normalized_text))
    words = len(re.findall(r"[A-Za-z0-9]+", normalized_text))
    ascii_word_chars = sum(len(word) for word in re.findall(r"[A-Za-z0-9]+", normalized_text))
    other_text_chars = 0
    for char in normalized_text:
        # Unicode category 以 L 开头表示各语种字母，N 表示数字。前面已经单独
        # 统计了 CJK 和 ASCII 单词，这里只统计剩余文字，避免英文被重复计时。
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
    生成 MP3 静音音频，作为“无配音”模式的时间轴占位。

    使用 FFmpeg 的 anullsrc 直接生成静音，比先构造临时 WAV 再转码更少中间
    文件。失败时返回 False，让上层按普通 TTS 失败路径处理并记录日志。
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
        # 从voice_name中提取模型和声音
        # 格式: siliconflow:model:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 3:
            model = parts[1]
            # 移除性别后缀，例如 "alex-Male" -> "alex"
            voice_with_gender = parts[2]
            voice = voice_with_gender.split("-")[0]
            # 构建完整的voice参数，格式为 "model:voice"
            full_voice = f"{model}:{voice}"
            return siliconflow_tts(
                text, model, full_voice, voice_rate, voice_file, voice_volume
            )
        else:
            logger.error(f"Invalid siliconflow voice name format: {voice_name}")
            return None
    elif is_gemini_voice(voice_name):
        # 从voice_name中提取声音名称
        # 格式: gemini:voice-Style；也继续兼容旧的 gemini:voice-Gender。
        voice = parse_gemini_voice_name(voice_name)
        if voice:
            return gemini_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid gemini voice name format: {voice_name}")
            return None
    elif is_mimo_voice(voice_name):
        # 从voice_name中提取声音名称
        # 格式: mimo:voice-Gender；如果调用方已执行 parse_voice_name，
        # 则可能是 mimo:voice。两种格式都兼容。
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            return mimo_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid mimo voice name format: {voice_name}")
            return None
    elif is_minimax_voice(voice_name):
        voice_id = voice_name.split(":", 1)[1].strip()
        if voice_id:
            return minimax_tts(text, voice_id, voice_rate, voice_file, voice_volume)
        logger.error(f"Invalid MiniMax voice name format: {voice_name}")
        return None
    elif is_elevenlabs_voice(voice_name):
        # 格式: elevenlabs:{voice_id}:{name}
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_id = parts[1]
            return elevenlabs_tts(text, voice_id, voice_file, voice_rate, voice_volume)
        else:
            logger.error(f"Invalid elevenlabs voice name format: {voice_name}")
            return None
    elif is_chatterbox_voice(voice_name):
        # 格式: chatterbox:<voice>，voice 可带显示用的 -Female/-Male 后缀
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
    elif is_fish_audio_voice(voice_name):
        parts = voice_name.split(":")
        reference_id = parts[1] if len(parts) >= 2 else "default"
        if reference_id == "default":
            reference_id = None
        return fish_audio_tts(text, voice_file, voice_rate, voice_volume, reference_id=reference_id)
    return azure_tts_v1(text, voice_name, voice_rate, voice_file)


def _format_text(text: str) -> str:
    """
    清理字幕对齐前的脚本文本。

    这里不能只在 LLM 生成阶段处理，因为用户也可能手动粘贴脚本，或通过
    API 直接传入包含 Markdown 标记的文本。TTS 通常不会朗读 `---`、
    `___`、`***` 这类分隔符行，也不会朗读 `_` 这种强调标记；如果字幕
    对齐仍保留这些字符，`create_subtitle()` 会一直等待不存在的 cue，
    最终导致字幕文件缺失并在 Whisper fallback 校正时补出全 0 时间轴。
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
    返回统一的 SRT 行格式化函数。

    这里单独拆成一个小工具，是为了让 edge_tts 7.x 的 cues 路径
    和项目原有的 legacy `subs/offset` 路径共用同一套字幕落盘格式，
    避免两套逻辑各自产生细微格式差异。
    """

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n{start_t} --> {end_t}\n{sub_text}\n"

    return formatter


# 阿拉伯语变音符号和 Tatweel 拉长符在 edge-tts 返回文本中可能出现，
# 这些字符不影响语义，但会导致脚本文本和字幕 cue 字符串精确匹配失败。
_ARABIC_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟـۖ-ۭ]")


def _normalize_arabic(text: str) -> str:
    """统一阿拉伯语常见字母变体，提升字幕 cue 与脚本行的匹配容错率。

    edge-tts 对阿拉伯语可能返回与原脚本不同的字母形态，例如把 أ/إ/آ
    归一成 ا，或者携带变音符号。这里仅在最后一层匹配兜底中使用，
    不改变原始字幕文本，避免影响最终展示内容。
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
    尝试把当前累计的字幕文本，与脚本中的某一条标准断句匹配起来。

    这里复用了项目原有的“按标点拆脚本，再逐段比对”的思路：
    1. 优先精确匹配；
    2. 再做一次去标点和 Markdown `_` 格式符后的匹配；
    3. 最后做一次阿拉伯语字符形态归一化匹配。

    这样可以兼容：
    - TTS 返回里可能缺失或单独拆分的标点；
    - 中文场景下词边界和脚本文本不完全一一对应的情况。
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

    # 最后一层阿拉伯语容错：edge-tts 返回的字母形态、变音符号或 Tatweel
    # 可能和脚本不同。只在常规匹配失败后归一化比较，非阿拉伯语文本不会受影响。
    current_ar = re.sub(r"[_\W]+", "", _normalize_arabic(current_text))
    target_ar = re.sub(r"[_\W]+", "", _normalize_arabic(target_line))
    if current_ar and current_ar == target_ar:
        return target_line.strip()

    return ""


def _write_subtitle_items(sub_items: list[str], subtitle_file: str) -> bool:
    """
    将已经聚合好的字幕段写入到 SRT 文件，并做一次基本可读性验证。

    返回值：
    - `True`：字幕文件成功落盘且可被 moviepy 解析；
    - `False`：字幕文件写入或解析失败。
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
    将 edge_tts 7.x 的细粒度 `cues` 聚合为按脚本断句的 SRT 片段。

    背景：
    edge_tts 7.x 的 `SubMaker.get_srt()` 更偏向逐词/逐短语的时间轴。
    对英文做逐词高亮尚可，但中文短视频字幕如果直接照搬，会出现
    “金钱 / 是 / 一种 / 社会 / 工具” 这种阅读体验很差的效果。

    实现策略：
    1. 逐个消费 cues 中的 `content`；
    2. 累积成一段候选文本；
    3. 当候选文本与脚本里当前目标断句匹配时，收敛为一个完整字幕段；
    4. 使用第一条 cue 的开始时间和最后一条 cue 的结束时间，保证时间轴连续。
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
    将项目原有 `subs/offset` 结构聚合为按脚本断句的 SRT 片段。

    这部分保留了原来的核心思路，只是拆成独立函数，便于与 edge_tts 7.x
    的 cues 聚合逻辑共享同一套断句匹配与落盘流程。
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
    优化字幕文件
    1. 将字幕文件按照标点符号分割成多行
    2. 逐行匹配字幕文件中的文本
    3. 生成新的字幕文件
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
    获取音频时长
    """
    # 优先兼容 edge_tts 7.x 的 cues 结构；
    # 如果是项目里其他 TTS 手工填充的旧结构，则继续读取 offset。
    if hasattr(sub_maker, "cues") and sub_maker.cues:
        return sub_maker.cues[-1].end.total_seconds()

    legacy_offsets = getattr(sub_maker, "offset", [])
    if not legacy_offsets:
        return 0.0
    return legacy_offsets[-1][1] / 10000000

def _get_audio_duration_from_file(audio_file: str) -> float:
    """
    获取音频文件时长（支持 mp3/m4a/wav/aac 等 ffmpeg 可解码的格式）
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
    获取音频时长
    如果是SubMaker对象，则从SubMaker中获取时长
    如果是音频文件路径，则从音频文件中获取时长（支持 mp3/m4a/wav 等格式）
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
            "zh-CN-XiaoxiaoMultilingualNeural",
            # 女性
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural",
            # 男性
            "zh-CN-YunyangNeural",
            "zh-CN-YunxiNeural",
        ]
        text = "静夜思是唐代诗人李白创作的一首五言古诗。这首诗描绘了诗人在寂静的夜晚，看到窗前的明月，不禁想起远方的家乡和亲人"

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
