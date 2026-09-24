"""任务目录中持久化文件的安全读写。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from loguru import logger

from app.utils import utils


def _script_file(task_id: str) -> Path:
    """返回任务脚本清单路径，并复用统一的任务目录创建逻辑。"""
    return Path(utils.task_dir(task_id)) / "script.json"


def _write_json_atomic(target: Path, payload: Mapping[str, Any]) -> None:
    """
    在目标目录内原子写入 JSON，避免进程中断留下半个文件。

    临时文件和目标文件必须位于同一目录，才能保证 ``os.replace`` 在常见
    本地文件系统和 Docker 挂载目录中保持原子替换语义。写入成功前不会修改
    现有文件；异常时只清理本次创建的临时文件，并把错误交给调用方决定是否
    影响主流程。
    """
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                payload,
                temp_file,
                ensure_ascii=False,
                indent=4,
                default=lambda value: value.__dict__,
            )
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_script_data(task_id: str, payload: Mapping[str, Any]) -> None:
    """创建或完整替换任务的 ``script.json`` 清单。"""
    _write_json_atomic(_script_file(task_id), payload)


def _task_file(task_id: str, file_name: str) -> Path:
    """返回任务目录内的附加清单路径，并复用统一的任务目录创建逻辑。"""
    return Path(utils.task_dir(task_id)) / file_name


def _shot_plan_file(task_id: str) -> Path:
    """返回任务镜头计划路径，并复用统一的任务目录创建逻辑。"""
    return _task_file(task_id, "shot_plan.json")


def write_task_json(task_id: str, file_name: str, payload: Mapping[str, Any]) -> None:
    """在任务目录内原子写入一个附加 JSON 清单。"""
    _write_json_atomic(_task_file(task_id, file_name), payload)


def write_shot_plan_data(task_id: str, payload: Mapping[str, Any]) -> None:
    """创建或完整替换任务的 ``shot_plan.json`` 镜头计划。"""
    _write_json_atomic(_shot_plan_file(task_id), payload)


def read_shot_plan_data(task_id: str) -> Mapping[str, Any] | None:
    """读取任务镜头计划，文件不存在时返回 ``None``。"""
    try:
        with _shot_plan_file(task_id).open("r", encoding="utf-8") as plan_file:
            return json.load(plan_file)
    except FileNotFoundError:
        return None


def patch_shot_plan_data(task_id: str, **updates: Any) -> bool:
    """
    在保留原有字段的前提下补充镜头计划，失败时返回 ``False``。

    镜头计划编辑属于辅助操作，不能因为文件权限或历史文件损坏阻断主流程。
    """
    try:
        target = _shot_plan_file(task_id)
        with target.open("r", encoding="utf-8") as plan_file:
            payload = json.load(plan_file)
        if not isinstance(payload, dict):
            raise ValueError("shot plan data must be a JSON object")

        payload.update(updates)
        _write_json_atomic(target, payload)
        return True
    except FileNotFoundError:
        logger.debug(
            f"skip shot plan update because shot_plan.json does not exist: "
            f"task_id={task_id}"
        )
        return False
    except Exception as exc:
        logger.warning(
            "failed to update task shot plan: "
            f"task_id={task_id}, fields={sorted(updates)}, "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return False


def patch_script_data(task_id: str, **updates: Any) -> bool:
    """
    在保留原有字段的前提下补充任务清单，失败时返回 ``False``。

    素材来源属于辅助诊断信息，不能因为文件权限、磁盘瞬时异常或历史文件损坏
    阻断视频生成。因此该入口会记录完整异常并降级；首次创建任务清单仍使用
    ``write_script_data``，由主流程决定基础任务数据写入失败时如何处理。
    """
    try:
        target = _script_file(task_id)
        with target.open("r", encoding="utf-8") as script_file:
            payload = json.load(script_file)
        if not isinstance(payload, dict):
            raise ValueError("task script data must be a JSON object")

        payload.update(updates)
        _write_json_atomic(target, payload)
        return True
    except FileNotFoundError:
        # ``download_videos`` 也可能被测试、脚本或第三方代码独立调用，此时没有
        # 任务清单属于正常场景，不应制造警告或为了辅助记录创建残缺文件。
        logger.debug(
            f"skip task script update because script.json does not exist: "
            f"task_id={task_id}"
        )
        return False
    except Exception as exc:
        logger.warning(
            "failed to update task script data: "
            f"task_id={task_id}, fields={sorted(updates)}, "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return False
