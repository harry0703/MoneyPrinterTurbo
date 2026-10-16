"""脚本库：把 ``storage/tasks/*/script.json`` 里已经生成过的文案整理成可检索、可复用的列表。

每次生成都会把结果落到 ``storage/tasks/<task_id>/script.json``，结构是
``{script, search_terms, params}``。这批数据本来就在盘上，但此前只能通过「任务管理」
的「恢复配置」间接拿到：不能搜索、不能复制、也不能只把文案拿去重新生成（于是每
次复用都要重新花一次 LLM 调用）。

本模块是纯数据层，刻意不依赖 Streamlit，只负责三件事：

1. 扫描任务目录，把文案连同主题、字数、生成时间、是否已出片整理成条目；
2. 支持按关键字检索主题与文案正文；
3. 提供 ``build_form_params``，让「用这条文案生成」只填主题、文案和素材关键词，
   不再调用大模型。

这里只读不写：删除任务仍由「任务管理」负责，避免两个入口同时改动同一份产物。
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.utils import utils

# 任务 ID 直接参与路径拼接，因此必须是单个安全路径段。
_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# 与 WebUI 的任务管理保持同一套判定：只有 ``final-<序号>.<扩展名>`` 才算成片，
# combined / temp-clip 等中间文件不能代表任务已完成。
_FINAL_VIDEO_PATTERN = re.compile(
    r"^final-(?P<index>\d+)\.(?P<extension>mp4|mov|mkv|webm)$",
    re.IGNORECASE,
)

# 文案全文会整段进入界面，给一个上限避免异常大的历史文件拖垮页面。
MAX_SCRIPT_LENGTH = 20000
MAX_KEYWORD_LENGTH = 100

# 任务很多时列表页不需要一次全渲染出来。
DEFAULT_LIST_LIMIT = 200


def tasks_root() -> str:
    return utils.task_dir()


def task_script_path(task_id: str) -> Optional[str]:
    """返回任务的 script.json 路径；task_id 非法时返回 ``None``。"""
    if not _TASK_ID_PATTERN.match(str(task_id or "")):
        return None
    return os.path.join(tasks_root(), str(task_id), "script.json")


def _find_final_video(task_path: str) -> str:
    """返回任务目录中序号最小的最终成片，没有则返回空串。"""
    try:
        files = os.listdir(task_path)
    except OSError:
        return ""
    candidates = []
    for file_name in files:
        match = _FINAL_VIDEO_PATTERN.fullmatch(file_name)
        if match and os.path.isfile(os.path.join(task_path, file_name)):
            candidates.append((int(match.group("index")), file_name))
    if not candidates:
        return ""
    _, file_name = min(candidates, key=lambda item: item[0])
    return os.path.join(task_path, file_name)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _load_entry(task_id: str, task_path: str, mtime: float) -> Optional[Dict[str, Any]]:
    """读取单个任务目录，返回脚本条目；没有可用文案时返回 ``None``。"""
    script_file = os.path.join(task_path, "script.json")
    try:
        with open(script_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError:
        return None
    except (ValueError, TypeError) as exc:
        logger.warning(f"failed to parse task script data: {script_file}, {exc}")
        return None
    if not isinstance(payload, dict):
        logger.warning(f"task script data is not an object: {script_file}")
        return None

    script = payload.get("script")
    script_text = script if isinstance(script, str) else ""
    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}

    subject = _as_text(params.get("video_subject")).strip()
    if not subject:
        # 历史数据可能只有文案没有参数，用文案首句兜底，保证列表里可辨认。
        subject = script_text.strip().splitlines()[0][:60] if script_text.strip() else task_id

    search_terms = payload.get("search_terms")
    if isinstance(search_terms, (list, tuple)):
        terms = [str(item).strip() for item in search_terms if str(item).strip()]
    else:
        terms = [item.strip() for item in _as_text(search_terms).split(",") if item.strip()]

    if not script_text.strip():
        # 只生成了标题、还没出文案的任务不进脚本库。
        return None

    script_text = script_text[:MAX_SCRIPT_LENGTH]
    video_file = _find_final_video(task_path)
    video_size = 0
    if video_file:
        try:
            video_size = os.path.getsize(video_file)
        except OSError:
            video_size = 0

    return {
        "task_id": task_id,
        "subject": subject,
        "script": script_text,
        "char_count": len(script_text.replace("\n", "").replace(" ", "")),
        "search_terms": terms,
        "search_terms_text": ", ".join(terms),
        "generated_at": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        "mtime": mtime,
        "task_path": task_path,
        "video_file": video_file,
        "video_size": video_size,
        "has_video": bool(video_file),
        "video_source": _as_text(params.get("video_source")),
        "voice_name": _as_text(params.get("voice_name")),
        "video_aspect": _as_text(params.get("video_aspect")),
        "video_language": _as_text(params.get("video_language")),
    }


def list_scripts(
    keyword: str = "",
    only_with_video: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
) -> List[Dict[str, Any]]:
    """列出所有已生成文案的任务，按生成时间倒序。

    关键字同时匹配主题和文案正文，方便「我记得写过一条讲便利店的」这类查找。
    """
    root = tasks_root()
    if not os.path.isdir(root):
        return []

    try:
        with os.scandir(root) as iterator:
            directories = []
            for entry in iterator:
                if not _TASK_ID_PATTERN.match(entry.name):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    directories.append((entry.stat(follow_symlinks=False).st_mtime, entry.name))
                except OSError:
                    continue
    except OSError as exc:
        logger.warning(f"failed to scan task directory: {root}, {exc}")
        return []

    directories.sort(key=lambda item: item[0], reverse=True)
    text = str(keyword or "").strip().lower()[:MAX_KEYWORD_LENGTH]

    entries: List[Dict[str, Any]] = []
    for mtime, task_id in directories:
        task_path = os.path.join(root, task_id)
        entry = _load_entry(task_id, task_path, mtime)
        if entry is None:
            continue
        if only_with_video and not entry["has_video"]:
            continue
        if text and text not in entry["subject"].lower() and text not in entry["script"].lower():
            continue
        entries.append(entry)
        if limit and len(entries) >= int(limit):
            break
    return entries


def get_script(task_id: str) -> Optional[Dict[str, Any]]:
    """按任务 ID 取单条脚本。"""
    script_file = task_script_path(task_id)
    if script_file is None or not os.path.isfile(script_file):
        return None
    try:
        mtime = os.path.getmtime(script_file)
    except OSError:
        mtime = 0.0
    return _load_entry(str(task_id), os.path.dirname(script_file), mtime)


def build_form_params(task_id: str) -> Optional[Dict[str, str]]:
    """构造「用这条文案生成」需要的表单参数。

    只回填主题、文案和素材关键词三个字段：其余配置（画面形态、音色、字幕样式、
    配乐）保留用户当前表单里的选择，避免复用一条旧文案时被历史配置整体覆盖。
    """
    entry = get_script(task_id)
    if entry is None:
        return None
    return {
        "video_subject": entry["subject"],
        "video_script": entry["script"],
        "video_terms": entry["search_terms_text"],
    }


def summary() -> Dict[str, Any]:
    """脚本库概览：条目数、总字数、已出片数。"""
    entries = list_scripts()
    return {
        "scripts": len(entries),
        "characters": sum(entry["char_count"] for entry in entries),
        "with_video": sum(1 for entry in entries if entry["has_video"]),
    }
