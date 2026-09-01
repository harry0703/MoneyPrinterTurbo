import json
import os
import threading
import time
from typing import List, Optional, Dict, Any
from uuid import uuid4
from loguru import logger

from app.utils import utils

_lock = threading.Lock()


def _get_series_file_path() -> str:
    series_dir = utils.storage_dir("series", create=True)
    return os.path.join(series_dir, "series_index.json")


def _load_data() -> Dict[str, Any]:
    file_path = _get_series_file_path()
    if not os.path.exists(file_path):
        return {"series": []}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "series" not in data:
                return {"series": []}
            return data
    except Exception as e:
        logger.error(f"Failed to load series data: {e}")
        return {"series": []}


def _save_data(data: Dict[str, Any]) -> bool:
    file_path = _get_series_file_path()
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save series data: {e}")
        return False


def list_series() -> List[Dict[str, Any]]:
    with _lock:
        data = _load_data()
        return data.get("series", [])


def create_series(name: str, description: str = "") -> Dict[str, Any]:
    with _lock:
        data = _load_data()
        series_id = str(uuid4())
        now = time.time()
        new_series = {
            "id": series_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "tasks": []
        }
        data["series"].append(new_series)
        _save_data(data)
        return new_series


def get_series(series_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _load_data()
        for s in data.get("series", []):
            if s.get("id") == series_id:
                return s
        return None


def delete_series(series_id: str) -> bool:
    with _lock:
        data = _load_data()
        initial_count = len(data.get("series", []))
        data["series"] = [s for s in data.get("series", []) if s.get("id") != series_id]
        if len(data["series"]) < initial_count:
            return _save_data(data)
        return False


def add_task_to_series(series_id: str, task_id: str, title: str = "") -> bool:
    with _lock:
        data = _load_data()
        for s in data.get("series", []):
            if s.get("id") == series_id:
                tasks = s.setdefault("tasks", [])
                # Avoid duplicate task entries, update if exists
                for t in tasks:
                    if t.get("task_id") == task_id:
                        if title:
                            t["title"] = title
                        t["updated_at"] = time.time()
                        s["updated_at"] = time.time()
                        return _save_data(data)
                
                tasks.append({
                    "task_id": task_id,
                    "title": title,
                    "added_at": time.time()
                })
                s["updated_at"] = time.time()
                return _save_data(data)
        return False


def remove_task_from_series(series_id: str, task_id: str) -> bool:
    with _lock:
        data = _load_data()
        for s in data.get("series", []):
            if s.get("id") == series_id:
                tasks = s.get("tasks", [])
                initial_count = len(tasks)
                s["tasks"] = [t for t in tasks if t.get("task_id") != task_id]
                if len(s["tasks"]) < initial_count:
                    s["updated_at"] = time.time()
                    return _save_data(data)
                return False
        return False


def get_series_tasks(series_id: str) -> List[Dict[str, Any]]:
    s = get_series(series_id)
    if s:
        return s.get("tasks", [])
    return []
