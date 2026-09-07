import json
import locale
import os
import re
from pathlib import Path
import threading
from typing import Any
from uuid import UUID, uuid4

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
        if is_uuid(sub_dir):
            d = os.path.join(d, resolve_task_storage_name(sub_dir))
        else:
            d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def slugify_task_title(title: str, max_length: int = 64) -> str:
    title = (title or "").strip()
    if not title:
        return "video-task"

    title = title.lower()
    title = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    title = re.sub(r"[-\s]+", "-", title, flags=re.UNICODE).strip("-_")
    if not title:
        return "video-task"
    return title[:max_length].rstrip("-_") or "video-task"


def build_task_title(
    video_subject: str = "", video_script: str = "", fallback_title: str = ""
) -> str:
    if video_subject and video_subject.strip():
        return video_subject.strip()

    script_lines = split_string_by_punctuations(video_script or "")
    if script_lines:
        return script_lines[0].strip()

    if fallback_title and fallback_title.strip():
        return fallback_title.strip()

    return "video-task"


def resolve_task_storage_name(task_id: str, task_title: str = "") -> str:
    normalized_task_id = str(UUID(str(task_id)))
    tasks_root = os.path.join(storage_dir(), "tasks")
    direct_name = normalized_task_id
    direct_path = os.path.join(tasks_root, direct_name)
    if os.path.isdir(direct_path):
        return direct_name

    suffix = f"__{normalized_task_id}"
    if os.path.isdir(tasks_root):
        for entry in os.listdir(tasks_root):
            if entry.endswith(suffix) and os.path.isdir(os.path.join(tasks_root, entry)):
                return entry

    if task_title:
        return f"{slugify_task_title(task_title)}__{normalized_task_id}"

    return direct_name


def ensure_task_dir(task_id: str, task_title: str = "") -> str:
    d = os.path.join(storage_dir(), "tasks", resolve_task_storage_name(task_id, task_title))
    os.makedirs(d, exist_ok=True)
    return d


def rename_task_dir(task_id: str, task_title: str = "") -> str:
    if not task_title:
        return ensure_task_dir(task_id)

    normalized_task_id = str(UUID(str(task_id)))
    tasks_root = os.path.join(storage_dir(), "tasks")
    current_name = resolve_task_storage_name(normalized_task_id)
    target_name = f"{slugify_task_title(task_title)}__{normalized_task_id}"
    current_path = os.path.join(tasks_root, current_name)
    target_path = os.path.join(tasks_root, target_name)

    if current_name == target_name:
        os.makedirs(target_path, exist_ok=True)
        return target_path

    if not os.path.exists(current_path):
        os.makedirs(target_path, exist_ok=True)
        return target_path

    if os.path.exists(target_path):
        return target_path

    os.replace(current_path, target_path)
    return target_path


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

        if char not in const.PUNCTUATIONS:
            txt += char
        else:
            result.append(txt.strip())
            txt = ""
    result.append(txt.strip())
    # filter empty string
    result = list(filter(None, result))
    return result


def md5(text):
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()


def get_system_locale():
    try:
        loc = locale.getdefaultlocale()
        # zh_CN, zh_TW return zh
        # en_US, en_GB return en
        language_code = loc[0].split("_")[0]
        return language_code
    except Exception:
        return "en"


def load_locales(i18n_dir):
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
