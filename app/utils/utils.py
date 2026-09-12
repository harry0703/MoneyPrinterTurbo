import json
import math
import os
import re
import shutil
import subprocess
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
    """将片段播放速度归一化到 WebUI 支持的安全范围。"""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default

    # NaN 会绕过普通的大小比较，并在 MoviePy 计算 duration 时传播；无穷值也不
    # 是合法用户输入。两者统一回退默认值，保证 API 和内部直接调用都不会生成
    # 无效时间线。零值和负值同样无法表示正常播放速度。
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
    解析当前进程应该使用的 FFmpeg 可执行文件。

    增加原因：
    1. 视频编码、静音音频生成、pydub 音频转码都依赖 FFmpeg；
    2. Windows 便携包、Docker 和用户自定义安装目录经常出现 PATH 不一致；
    3. 集中解析可以让所有调用方使用同一套优先级，减少某条链路能跑、
       另一条链路找不到 FFmpeg 的现场问题。

    优先级：
    1. IMAGEIO_FFMPEG_EXE：MoviePy/imageio 约定的显式配置；
    2. 系统 PATH 中的 ffmpeg；
    3. imageio-ffmpeg 依赖提供的内置二进制；
    4. 字符串 "ffmpeg" 兜底，交给 subprocess 在运行时暴露更具体错误。
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


_FFMPEG_INSTALL_HINT = (
    "Install FFmpeg on your system, or set app.ffmpeg_path in config.toml to "
    "the full path of an ffmpeg executable (e.g. downloaded from "
    "https://www.gyan.dev/ffmpeg/builds/)."
)


def check_ffmpeg_ready(timeout: int = 10) -> bool:
    """
    在真正开始生成视频之前提前探测 FFmpeg 是否可用。

    增加原因：
    此前 FFmpeg 缺失/不可用只会在视频合成、静音音轨生成等环节里，以
    ``RuntimeError: No ffmpeg exe could be found`` 或 subprocess 报错的形式
    出现，用户往往要等到任务跑了大半才第一次看到这个报错，且报错本身
    不会指向任何解决办法。这里在共享任务流水线（app/services/task.py 的
    ``_run_pipeline``）里提前做一次探测，尽早给出可操作的英文提示（与项目
    里其他 logger.warning 的用语习惯保持一致），API、CLI、WebUI 都会经过
    这条流水线，因此三条路径能统一生效。

    仅做一次轻量的 ``-version`` 调用，不会触发下载或改变主流程；
    调用方需要把返回值当作硬性前置条件——项目锁定的 imageio-ffmpeg==0.6.0
    并不会在真正使用时自动补下载一个可用的二进制，因此检测失败必须让
    需要 FFmpeg 的阶段直接终止，而不是继续跑到视频合成才失败。
    """
    ffmpeg_bin = get_ffmpeg_binary()
    try:
        completed = subprocess.run(
            [ffmpeg_bin, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning(
            f"no usable ffmpeg executable found (tried: {ffmpeg_bin}). "
            f"{_FFMPEG_INSTALL_HINT}"
        )
        return False
    except Exception as exc:
        logger.warning(
            f"failed to probe ffmpeg ({ffmpeg_bin}): {exc}. {_FFMPEG_INSTALL_HINT}"
        )
        return False

    if completed.returncode != 0:
        logger.warning(
            f"ffmpeg ({ffmpeg_bin}) probe exited with status {completed.returncode}; "
            f"video generation may fail later. {_FFMPEG_INSTALL_HINT}"
        )
        return False

    logger.info(f"ffmpeg check passed, using: {ffmpeg_bin}")
    return True


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
            # 英文数字里的千分位逗号不是断句符，例如 "1,000 years"。
            # Edge TTS 的 word boundary 通常会把这种数字整体作为连续内容返回；
            # 如果这里拆成 "1" 和 "000 years"，后续字幕聚合会无法匹配脚本原文，
            # 进而错误回退到 Whisper。
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


PAUSE_TAG_KEYWORDS = (
    r"pause|pausa|silence|silencio|silêncio|silenzio|stille|"
    r"пауза|тишина|停顿|暂停|静音|ポーズ|一時停止|無音|일시중지|정지"
)
# 匹配所有包含停顿关键词的标签（方括号或圆括号），无论其参数合法与否均匹配，
# 以确保非法标签（如 [pause: -2s]、[pause: nope]、[pause: 0s]）在合成前被彻底清除而不会泄漏给 TTS
PAUSE_TAG_PATTERN = re.compile(
    rf"[\[\(]\s*(?:{PAUSE_TAG_KEYWORDS})\b(?:\s*[:：]?\s*([^\]\)]*?))?\s*[\]\)]",
    re.IGNORECASE,
)

# 停顿时长安全阈值（单位：秒）：
# 最小有效停顿为 0.1 秒（100ms），小于此值的请求会被校验并修正为 0.1s；
# 小于等于 0 秒或非法非数字的停顿标签会被判定为无效标签并直接移除，不朗读也不生成静音；
# 最大停顿上限为 10.0 秒，超过部分会被安全截断。
MIN_PAUSE_DURATION_SECONDS = 0.1
MAX_PAUSE_DURATION_SECONDS = 10.0


def has_pause_tags(text: str) -> bool:
    """检查文本中是否包含停顿/暂停标签。"""
    if not text:
        return False
    return bool(PAUSE_TAG_PATTERN.search(text))


def remove_pause_tags(text: str) -> str:
    """
    移除脚本文本中的所有停顿/暂停标签（包括有效与无效标签）。

    在字幕分句、LLM关键词提取或作为发音文本传递给 TTS 时，必须将此类非发音标记清除，
    避免非法或未处理的标签被朗读或作为视觉搜索词。
    """
    if not text:
        return ""
    cleaned = PAUSE_TAG_PATTERN.sub(" ", text)
    # 合并连续水平空格，保留换行
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def parse_script_with_pauses(text: str) -> list[tuple[str, Any]]:
    """
    解析脚本中的文本与停顿标签。

    连续停顿标签会自动合并为一个停顿段；
    非法标签（如非数字参数、小于等于 0 的时长）会被直接移除并忽略，绝不会作为台词传给 TTS；
    小于 MIN_PAUSE_DURATION_SECONDS (0.1s/100ms) 的过小停顿会被校验并提升至 0.1s；
    超过 MAX_PAUSE_DURATION_SECONDS (10.0s) 的过长停顿会被限制在安全上限内。

    Returns:
        有序元组列表，形式为 [("speech", "文案"), ("pause", 2.0), ...]
    """
    if not text:
        return []

    segments: list[tuple[str, Any]] = []
    last_idx = 0

    for match in PAUSE_TAG_PATTERN.finditer(text):
        start, end = match.span()
        if start > last_idx:
            speech_text = text[last_idx:start].strip()
            if speech_text:
                segments.append(("speech", speech_text))

        raw_arg = match.group(1)
        if raw_arg is None or not raw_arg.strip():
            # 未指定参数时，默认停顿 1.0 秒
            duration = 1.0
        else:
            raw_arg_str = raw_arg.strip()
            num_match = re.match(
                r"^([+-]?\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|ms|msec|msecs|秒|毫秒)?$",
                raw_arg_str,
                re.IGNORECASE,
            )
            if not num_match:
                logger.warning(
                    f"invalid pause tag value '{raw_arg_str}', tag removed and ignored"
                )
                last_idx = end
                continue

            val = float(num_match.group(1))
            unit = (num_match.group(2) or "s").lower()
            duration = val / 1000.0 if ("ms" in unit or "毫秒" in unit) else val

        if duration <= 0:
            logger.warning(
                f"invalid non-positive pause duration {duration}s, tag removed and ignored"
            )
            last_idx = end
            continue

        if duration < MIN_PAUSE_DURATION_SECONDS:
            logger.warning(
                f"pause duration {duration:.3f}s is below minimum limit of {MIN_PAUSE_DURATION_SECONDS}s (100ms), "
                f"clamped to {MIN_PAUSE_DURATION_SECONDS}s"
            )
            duration = MIN_PAUSE_DURATION_SECONDS

        if duration > MAX_PAUSE_DURATION_SECONDS:
            logger.warning(
                f"pause duration {duration}s exceeds maximum limit of {MAX_PAUSE_DURATION_SECONDS}s, "
                f"clamped to {MAX_PAUSE_DURATION_SECONDS}s"
            )
            duration = MAX_PAUSE_DURATION_SECONDS

        # 连续出现的停顿标签合并为一个停顿段，避免生成碎片化静音文件
        if segments and segments[-1][0] == "pause":
            merged_duration = min(
                segments[-1][1] + duration, MAX_PAUSE_DURATION_SECONDS
            )
            segments[-1] = ("pause", merged_duration)
        else:
            segments.append(("pause", duration))

        last_idx = end

    if last_idx < len(text):
        speech_text = text[last_idx:].strip()
        if speech_text:
            segments.append(("speech", speech_text))

    return segments


def normalize_script_for_subtitle_matching(video_script: str) -> str:
    """
    清理字幕匹配前的脚本文本。

    用户可能手动输入 Markdown 分隔符、标题强调或 `_` 这类格式符号。
    这些字符通常不会出现在 TTS/Whisper 的识别结果里；如果继续参与
    字幕逐行匹配，脚本行数量会大于真实字幕行数量，最终可能补出
    `00:00:00,000 --> 00:00:00,000`，导致剪辑软件无法导入 SRT。
    """
    video_script = remove_pause_tags(video_script or "")
    underscore_count = video_script.count("_")
    video_script = video_script.replace("_", "")
    cleaned_lines = []
    removed_separator_lines = 0
    for line in video_script.splitlines():
        line = line.strip()
        # Markdown 分隔符或强调符号单独成行时不会被 TTS 朗读，必须从
        # 脚本行里移除，避免字幕聚合卡在这类“不可发声”的目标行上。
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
    按“已保存设置、浏览器语言、默认语言”的优先级选择界面语言。

    浏览器通常返回带地区的 locale，例如 ``zh-CN``、``pt-BR``。语言文件使用
    ``zh``、``pt`` 这类基础代码，因此先尝试完整匹配，再回退到连字符前的语言
    代码。函数保持纯逻辑，避免把浏览器上下文和配置写入耦合到工具层，便于测试。
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

    # 正常项目始终包含英文；保留空语言集合兜底，避免损坏的语言目录让页面
    # 初始化直接抛异常，后续翻译函数会继续显示原始 key 以便诊断。
    return supported[0] if supported else default_language


@lru_cache(maxsize=8)
def load_locales(i18n_dir):
    # WebUI 每次交互都会触发 Streamlit 重新执行脚本，语言文件运行期不会变化，
    # 因此缓存解析结果，避免反复读取和解析所有 i18n JSON 文件。
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
