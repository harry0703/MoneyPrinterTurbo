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
import unicodedata
from uuid import uuid4

from loguru import logger

from app import paths
from app.models import const


def get_response(status: int, data: Any = None, message: str = ""):
    obj = {
        "status": status,
    }
    if data is not None:
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
    """Normalize clip playback speed to the safe range supported by the WebUI."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default

    # NaN bypasses ordinary comparisons and propagates when MoviePy computes duration; infinity isn't
    # valid user input either. Both fall back to the default, so neither the API nor internal direct calls produce
    # an invalid timeline. Zero and negative values can't represent a normal playback speed either.
    if not math.isfinite(speed) or speed <= 0:
        return default

    return min(max(speed, _CLIP_SPEED_MIN), _CLIP_SPEED_MAX)


def root_dir():
    return str(paths.runtime_root())


def storage_dir(sub_dir: str = "", create: bool = False):
    d = os.path.join(root_dir(), "storage")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if create:
        os.makedirs(d, exist_ok=True)

    return d


def resource_dir(sub_dir: str = ""):
    return str(paths.resource_directory(sub_dir))


def task_dir(sub_dir: str = ""):
    d = os.path.join(storage_dir(), "tasks")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    os.makedirs(d, exist_ok=True)
    return d


def font_dir(sub_dir: str = ""):
    d = resource_dir("fonts")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    os.makedirs(d, exist_ok=True)
    return d


def song_dir(sub_dir: str = ""):
    d = resource_dir("songs")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    os.makedirs(d, exist_ok=True)
    return d


def public_dir(sub_dir: str = ""):
    d = resource_dir("public")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    os.makedirs(d, exist_ok=True)
    return d


def get_ffmpeg_binary() -> str:
    """
    Resolve the FFmpeg executable the current process should use.

    Why this exists:
    1. Video encoding, silent audio generation and pydub audio transcoding all depend on FFmpeg;
    2. Windows portable packages, Docker and user-defined install directories often have inconsistent PATHs;
    3. Centralized resolution lets all callers use the same priority, reducing field issues where one pipeline works
       and another can't find FFmpeg.

    Priority:
    1. IMAGEIO_FFMPEG_EXE: the explicit config convention of MoviePy/imageio;
    2. ffmpeg on the system PATH;
    3. The bundled binary provided by the imageio-ffmpeg dependency;
    4. The string "ffmpeg" as a fallback, letting subprocess surface a more specific error at runtime.
    """
    configured_ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE")
    if configured_ffmpeg:
        # Expand the home-directory shorthand ("~") and any
        # environment-variable references ("$VAR" / "${VAR}") before
        # handing the value to subprocess. The check_ffmpeg_ready
        # probe and every FFmpeg call would otherwise fail on the
        # first run for any user who set the variable to a path
        # under their home directory. Absolute paths are unaffected.
        expanded_ffmpeg = os.path.expanduser(os.path.expandvars(configured_ffmpeg))
        if expanded_ffmpeg != configured_ffmpeg:
            # MoviePy/imageio-ffmpeg read IMAGEIO_FFMPEG_EXE directly
            # from os.environ, so write the expanded path back before
            # MoviePy resolves it; otherwise the pre-check passes but
            # ColorClip.write_videofile() still fails with
            # FileNotFoundError on the raw value (issue #1662).
            os.environ["IMAGEIO_FFMPEG_EXE"] = expanded_ffmpeg
        return expanded_ffmpeg

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
    Probe whether FFmpeg is usable before actually starting video generation.

    Why this exists:
    Previously a missing/unusable FFmpeg only surfaced during video composition, silent track generation and similar steps, as
    ``RuntimeError: No ffmpeg exe could be found`` or a subprocess error,
    so users often only saw the error for the first time after the task had run more than halfway, and the error itself
    didn't point to any solution. Here a probe runs early in the shared task pipeline (``_run_pipeline`` in
    app/services/task.py), giving an actionable English hint as early as possible (consistent with the wording of other
    logger.warning calls in the project); the API, CLI and WebUI all go through
    this pipeline, so it takes effect uniformly across all three paths.

    Only a lightweight ``-version`` call is made, which doesn't trigger downloads or change the main flow;
    callers must treat the return value as a hard precondition — the imageio-ffmpeg==0.6.0 pinned by the project
    doesn't automatically download a usable binary when actually used, so a failed check must make
    stages that need FFmpeg stop immediately, rather than running until video composition to fail.
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
    # Round once to whole milliseconds and derive every field from that value.
    # Truncating float products such as 2.01 * 1000 == 2009.999... wrote cue
    # boundaries one millisecond early.
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
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


# Thai and Lao letters, vowel signs and tone marks. The repetition marks ๆ and ໆ
# and the abbreviation marks ฯ and ຯ are left out: a space next to them is inside
# a sentence, as in "เด็ก ๆ ชอบ" and "กรุงเทพฯ เป็น".
_THAI_OR_LAO_LETTER = (
    r"[\u0E01-\u0E2E\u0E30-\u0E3A\u0E40-\u0E45\u0E47-\u0E4E"
    r"\u0E81-\u0EAE\u0EB0-\u0EBD\u0EC0-\u0EC4\u0EC8-\u0ECE\u0EDC-\u0EDF]"
)
# Thai and Lao separate sentences with a space instead of a full stop. A space
# next to a number or a word in Latin letters is part of the sentence.
_THAI_OR_LAO_SENTENCE_SPACE = re.compile(
    rf"(?<={_THAI_OR_LAO_LETTER})\s+(?={_THAI_OR_LAO_LETTER})"
)
# Titles that stand before a name, as in "Mr. Smith", "Dr. Walker" and "Mt. Everest". "St." and
# "Jr." are left out: they can end a sentence, as in "Our shop is on Main St. We open at 9."
_TITLE_BEFORE_NAME = re.compile(r"(?<!\w)(?:Mr|Mrs|Ms|Dr|Prof|Mt)$")


def split_string_by_punctuations(s, *, split_thai_and_lao_sentences=True):
    result = []
    txt = ""
    if split_thai_and_lao_sentences:
        # A space that ends a Thai or Lao sentence ends the line like a line break.
        s = _THAI_OR_LAO_SENTENCE_SPACE.sub("\n", s)

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

        if (
            char == "."
            and previous_char.isalpha()
            and next_char.isalpha()
            and unicodedata.east_asian_width(previous_char) != "W"
            and unicodedata.east_asian_width(next_char) != "W"
        ):
            # Edge TTS reads "U.S.", "e.g.", "9 a.m." and "example.com" as one word each. Next to a
            # Chinese, Japanese or Korean character the dot still ends the sentence, as in "很好.我们".
            txt += char
            continue

        if (
            char == "."
            and previous_char.isalpha()
            and next_char.isdigit()
            and unicodedata.east_asian_width(previous_char) != "W"
        ):
            # Edge TTS usually returns "No.1", "Vol.2" and "Fig.3" as one word. After a Chinese,
            # Japanese or Korean character the dot still ends the sentence, as in "很好.2025年".
            txt += char
            continue

        if char == "." and next_char == " " and _TITLE_BEFORE_NAME.search(txt):
            # "Dr. Smith" and "Mt. Everest" stay in one line: the dot of a title before a name
            # ends no sentence, and a line break there showed "Dr" or "Mt" alone as a subtitle.
            txt += char
            continue

        if char in (":", "：") and previous_char.isdigit() and next_char.isdigit():
            # Edge TTS returns a clock time such as "10:30" or "10：30" as one word, so it is no line break.
            txt += char
            continue

        if char in (",", "，", "、") and previous_char.isdigit() and next_char.isdigit():
            # Commas and enumeration commas between digits aren't sentence breaks, e.g. "1,000 years", "1，299元", "第1、2名".
            # Edge TTS word boundaries usually return such numbers as one continuous piece of content;
            # if it were split here into "1" and "000 years", later subtitle aggregation couldn't match the original script,
            # and no subtitles would be generated for the whole section.
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
# Match every tag (in square or round brackets) containing a pause keyword, whether or not its argument is valid,
# so invalid tags (e.g. [pause: -2s], [pause: nope], [pause: 0s]) are fully removed before synthesis and never leak to TTS.
# Chinese input methods type brackets as full-width （）, ［］ or 【】; if only half-width ones were recognized, `（停顿：2秒）` would be read aloud verbatim.
# `\b` can't be used after the keyword: CJK characters and digits are both `\w`, so the common form without a colon,
# `[停顿3秒]`, would fail to match for lack of a word boundary and the tag text would be read aloud. Here only a letter immediately
# after the keyword is forbidden (digits are allowed), so ordinary text like `[paused]` or `[暂停一下]` still isn't misdetected.
PAUSE_TAG_PATTERN = re.compile(
    rf"[\[\(（［【]\s*(?:{PAUSE_TAG_KEYWORDS})(?![^\W\d])"
    rf"(?:\s*[:：]?\s*([^\]\)）］】]*?))?\s*[\]\)）］】]",
    re.IGNORECASE,
)

# Pause duration safety thresholds (unit: seconds):
# the minimum effective pause is 0.1 seconds (100ms), and smaller requests are validated and corrected to 0.1s;
# pause tags of 0 seconds or less, or non-numeric ones, are treated as invalid and removed directly, neither read aloud nor producing silence;
# the maximum pause is 10.0 seconds, and anything longer is safely truncated.
MIN_PAUSE_DURATION_SECONDS = 0.1
MAX_PAUSE_DURATION_SECONDS = 10.0


def has_pause_tags(text: str) -> bool:
    """Check whether the text contains pause tags."""
    if not text:
        return False
    return bool(PAUSE_TAG_PATTERN.search(text))


def remove_pause_tags(text: str) -> str:
    """
    Remove all pause tags (both valid and invalid) from script text.

    For subtitle sentence splitting, LLM keyword extraction, or when passing the text to TTS for pronunciation, such non-spoken markers must be removed,
    so invalid or unhandled tags aren't read aloud or used as visual search terms.
    """
    if not text:
        return ""
    cleaned = PAUSE_TAG_PATTERN.sub(" ", text)
    # Collapse consecutive horizontal spaces, keeping newlines
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def parse_script_with_pauses(text: str) -> list[tuple[str, Any]]:
    """
    Parse text and pause tags in a script.

    Consecutive pause tags are automatically merged into one pause segment;
    invalid tags (e.g. non-numeric arguments, durations of 0 or less) are removed and ignored, never passed to TTS as speech;
    pauses shorter than MIN_PAUSE_DURATION_SECONDS (0.1s/100ms) are validated and raised to 0.1s;
    pauses longer than MAX_PAUSE_DURATION_SECONDS (10.0s) are capped at the safe limit.

    Returns:
        Ordered list of tuples, in the form [("speech", "text"), ("pause", 2.0), ...]
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
            # When no argument is given, the default pause is 1.0 seconds
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

        # Consecutive pause tags are merged into one pause segment, avoiding fragmented silent files
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


# Emoji are pictures, not words: Edge TTS reads their names aloud ("chart
# increasing") and the subtitle fonts draw them as boxes. These are the code
# points drawn as emoji even without U+FE0F (Emoji_Presentation in Unicode's
# emoji-data.txt), with whole pictograph blocks so that new emoji are covered.
_EMOJI_CHARACTERS = (
    r"\U0001F1E6-\U0001F1FF"  # regional indicators: two of them make a flag
    r"\U0001F300-\U0001F64F"  # pictographs, skin tones and smileys
    r"\U0001F680-\U0001F6FF\U0001F7E0-\U0001F7EB\U0001F7F0"
    r"\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF"
    r"\U0001F004\U0001F0CF\U0001F18E\U0001F191-\U0001F19A\U0001F201\U0001F21A"
    r"\U0001F22F\U0001F232-\U0001F236\U0001F238-\U0001F23A\U0001F250\U0001F251"
    r"\u231A\u231B\u23E9-\u23EC\u23F0\u23F3\u25FD\u25FE\u2614\u2615\u2648-\u2653"
    r"\u267F\u2693\u26A1\u26AA\u26AB\u26BD\u26BE\u26C4\u26C5\u26CE\u26D4\u26EA"
    r"\u26F2\u26F3\u26F5\u26FA\u26FD\u2705\u270A\u270B\u2728\u274C\u274E"
    r"\u2753-\u2755\u2757\u2795-\u2797\u27B0\u27BF\u2B1B\u2B1C\u2B50\u2B55"
)
# One emoji: an emoji character, a symbol followed by the emoji variation
# selector U+FE0F (a heart or an arrow drawn as emoji; Unicode counts the
# information sign U+2139 as a letter), or a symbol such as a hand sign joined
# to a skin tone or to another emoji. Then come its skin tone, selectors, flag
# tags and zero-width-joined parts. A digit, # or * followed by U+FE0F is plain
# text or a keycap, and a keycap keeps its digit: "1" + U+FE0F + U+20E3 is "1".
_EMOJI = (
    rf"(?:[{_EMOJI_CHARACTERS}]|(?:[^\w\s#*]|\u2139)\uFE0F"
    rf"|[\u2600-\u27BF](?=[\u200D\U0001F3FB-\U0001F3FF]))"
    rf"(?:[{_EMOJI_CHARACTERS}\uFE0E\uFE0F\U000E0020-\U000E007F]|\u200D[^\w\s]\uFE0F?)*"
)
# A row of emoji, spaces between them included, and the space or tab on each
# side of it.
_EMOJI_PATTERN = re.compile(rf"([ \t]?)(?:{_EMOJI})+(?:[ \t]+(?:{_EMOJI})+)*([ \t]?)")
_EMOJI_KEYCAP_PATTERN = re.compile(r"([0-9#*])\uFE0F?\u20E3")
# No space is left after an opening mark or before a closing mark.
_OPENING_MARKS = "([{«¡¿（「『【《"
_CLOSING_MARKS = ".,!?;:)]}”’»…，。！？；：、）」』】》"
# Straight quotes open and close a quotation, and so do “ and ‘: they close a
# German one, which opens with „ or ‚ („So gut“), and open an English one.
_QUOTE_MARKS = "\"'„“‚‘"
# A quote mark or a line break. An apostrophe in a word, as in don't, is not a
# quote mark.
_QUOTE_MARK_PATTERN = re.compile(r"[\n\"„“‚‘]|(?<!\w)'(?!(?i:s|t|m|d|ll|re|ve)\b)|'(?!\w)")
_CLOSING_QUOTE = {'"': '"', "'": "'", "„": "“", "‚": "‘"}
# Chinese and Japanese characters: these languages put no spaces between words.
_CHINESE_OR_JAPANESE = re.compile(
    r"[\u2E80-\u312F\u3190-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF\U00020000-\U0003FFFF]"
)


def _replace_keycap(match: re.Match) -> str:
    # A keycap keeps its digit, and a letter or digit right after it stays
    # apart: three keycaps in a row become "3 2 1", not "321".
    following = match.string[match.end() : match.end() + 1]
    if following.isalnum() and not _CHINESE_OR_JAPANESE.match(following):
        return match.group(1) + " "
    return match.group(1)


def _find_opening_quotes(text: str) -> set[int]:
    # The positions of the quote marks that open a quotation, pairing the quotes
    # of each line from its start.
    opening = set()
    awaited = set()  # the marks that close the quotations still open
    for match in _QUOTE_MARK_PATTERN.finditer(text):
        mark, index = match.group(), match.start()
        if mark == "\n":
            awaited.clear()
        elif mark in awaited:
            awaited.remove(mark)
        elif mark == "'" and text[index - 1 : index].isalnum():
            continue  # an apostrophe after a word: "the dogs' toys"
        else:
            opening.add(index)
            if mark in _CLOSING_QUOTE:
                awaited.add(_CLOSING_QUOTE[mark])
    return opening


def _replace_emoji(match: re.Match, opening_quotes: set[int]) -> str:
    # The words on each side of an emoji stay apart: "Let's go 👉 now",
    # "Big news 🚀Launching" and "I love🍕pizza" keep one space where the emoji
    # was. No space is left at the start or end of a line, after an opening
    # mark or before a closing mark ("Ready to grow 📈?" becomes "Ready to
    # grow?"), or between Chinese or Japanese characters. A quote mark is an
    # opening or a closing mark depending on how the quotes of its line pair up.
    text = match.string
    previous = text[match.start() - 1] if match.start() else "\n"
    following = text[match.end()] if match.end() < len(text) else "\n"
    space_before, space_after = match.groups()
    if space_before and space_after:
        return space_after
    after_opening = (
        previous.isspace()
        or previous in _OPENING_MARKS
        or match.start() - 1 in opening_quotes
    )
    before_closing = (
        following.isspace()
        or following in _CLOSING_MARKS
        or (following in _QUOTE_MARKS and match.end() not in opening_quotes)
    )
    if space_before:
        return "" if before_closing else space_before
    if space_after:
        return "" if after_opening else space_after
    if after_opening or before_closing:
        return ""
    if _CHINESE_OR_JAPANESE.search(previous + following):
        return ""
    return " "


def remove_emoji(text: str) -> str:
    """
    Remove emoji from a script before it is spoken or turned into subtitles.

    Symbols that are text by default, such as ★ ♪ → © ™, are kept.
    """
    if not text:
        return ""
    text = _EMOJI_KEYCAP_PATTERN.sub(_replace_keycap, text)
    opening_quotes = _find_opening_quotes(text)
    return _EMOJI_PATTERN.sub(lambda match: _replace_emoji(match, opening_quotes), text)


def normalize_script_for_subtitle_matching(video_script: str) -> str:
    """
    Clean script text before subtitle matching.

    Users may manually enter Markdown separators, heading emphasis or formatting symbols like `_`.
    These characters usually don't appear in TTS/Whisper recognition results; if they kept taking part in
    line-by-line subtitle matching, the number of script lines would exceed the real number of subtitle lines, which could eventually produce
    `00:00:00,000 --> 00:00:00,000`, making the SRT impossible to import into editing software.
    Emoji are left out as well: tts() does not speak them.
    """
    video_script = remove_emoji(remove_pause_tags(video_script or ""))
    underscore_count = video_script.count("_")
    video_script = video_script.replace("_", "")
    cleaned_lines = []
    removed_separator_lines = 0
    for line in video_script.splitlines():
        line = line.strip()
        # Markdown separators or emphasis symbols on their own line aren't read aloud by TTS and must be removed from
        # the script lines, so subtitle aggregation doesn't get stuck on such "unspeakable" target lines.
        # Neither is a line without a letter or digit: "* * *", "———", "• • •".
        if line and not re.sub(r"[_\W]+", "", line):
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
    Choose the UI language by priority: "saved setting, browser language, default language".

    Browsers usually return a locale with a region, e.g. ``zh-CN`` or ``pt-BR``. Language files use
    base codes like ``zh`` and ``pt``, so a full match is tried first, then the language code before the hyphen.
    The function stays pure logic, so browser context and config writes aren't coupled into the utility layer, making it easy to test.
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

    # A normal project always includes English; an empty language set is kept as a fallback, so a corrupted language directory doesn't make page
    # initialization raise outright, and later translation functions keep showing the raw key for diagnosis.
    return supported[0] if supported else default_language


@lru_cache(maxsize=8)
def load_locales(i18n_dir):
    # The WebUI makes Streamlit re-run the script on every interaction, and language files don't change at runtime,
    # so the parsed result is cached, avoiding repeatedly reading and parsing all i18n JSON files.
    _locales = {}
    for root, dirs, files in os.walk(i18n_dir):
        for file in files:
            if file.endswith(".json"):
                lang = file.split(".")[0]
                with open(os.path.join(root, file), "r", encoding="utf-8-sig") as f:
                    _locales[lang] = json.loads(f.read())
    return _locales


def parse_extension(filename):
    return Path(filename).suffix.lower().lstrip('.')
