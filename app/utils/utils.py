import os
import threading
from typing import Any
from loguru import logger
import json
from uuid import uuid4
import urllib3

from app.models import const

urllib3.disable_warnings()


def get_response(status: int, data: Any = None, message: str = ""):
    obj = {
        'status': status,
    }
    if data:
        obj['data'] = data
    if message:
        obj['message'] = message
    return obj


def to_json(obj):
    # 定义一个辅助函数来处理不同类型的对象
    def serialize(o):
        # 如果对象是可序列化类型，直接返回
        if isinstance(o, (int, float, bool, str)) or o is None:
            return o
        # 如果对象是二进制数据，转换为base64编码的字符串
        elif isinstance(o, bytes):
            return "*** binary data ***"
        # 如果对象是字典，递归处理每个键值对
        elif isinstance(o, dict):
            return {k: serialize(v) for k, v in o.items()}
        # 如果对象是列表或元组，递归处理每个元素
        elif isinstance(o, (list, tuple)):
            return [serialize(item) for item in o]
        # 如果对象是自定义类型，尝试返回其__dict__属性
        elif hasattr(o, '__dict__'):
            return serialize(o.__dict__)
        # 其他情况返回None（或者可以选择抛出异常）
        else:
            return None

    # 使用serialize函数处理输入对象
    serialized_obj = serialize(obj)

    # 序列化处理后的对象为JSON字符串
    return json.dumps(serialized_obj, ensure_ascii=False, indent=4)


def get_uuid(remove_hyphen: bool = False):
    u = str(uuid4())
    if remove_hyphen:
        u = u.replace("-", "")
    return u


def root_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def storage_dir(sub_dir: str = ""):
    d = os.path.join(root_dir(), "storage")
    if sub_dir:
        d = os.path.join(d, sub_dir)
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
    d = resource_dir(f"fonts")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def song_dir(sub_dir: str = ""):
    d = resource_dir(f"songs")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def public_dir(sub_dir: str = ""):
    d = resource_dir(f"public")
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
            logger.error(f"run_in_background error: {e}")

    thread = threading.Thread(target=run)
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
    for char in s:
        if char not in const.PUNCTUATIONS:
            txt += char
        else:
            result.append(txt.strip())
            txt = ""
    return result
