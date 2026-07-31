"""작업 디렉터리에 남기는 영속 파일의 안전한 읽기·쓰기."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from loguru import logger

from app.utils import utils


def _script_file(task_id: str) -> Path:
    """작업 스크립트 매니페스트 경로를 반환하며, 공통 작업 디렉터리 생성 로직을 재사용한다."""
    return Path(utils.task_dir(task_id)) / "script.json"


def _write_json_atomic(target: Path, payload: Mapping[str, Any]) -> None:
    """
    대상 디렉터리 안에서 JSON 을 원자적으로 쓴다. 프로세스가 중단되어도 반쯤 쓰인
    파일이 남지 않는다.

    임시 파일과 대상 파일이 같은 디렉터리에 있어야 ``os.replace`` 가 일반적인 로컬
    파일 시스템과 Docker 마운트 디렉터리에서 원자적 교체 의미를 유지한다. 쓰기가
    성공하기 전에는 기존 파일을 건드리지 않으며, 예외가 나면 이번에 만든 임시 파일만
    정리하고 오류는 호출자가 주 흐름에 반영할지 결정하도록 넘긴다.
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
    """작업의 ``script.json`` 매니페스트를 생성하거나 통째로 교체한다."""
    _write_json_atomic(_script_file(task_id), payload)


def patch_script_data(task_id: str, **updates: Any) -> bool:
    """
    기존 필드를 유지한 채 작업 매니페스트를 보완하고, 실패하면 ``False`` 를 반환한다.

    소재 출처는 진단용 보조 정보이므로 파일 권한, 일시적인 디스크 이상, 예전 파일
    손상 때문에 영상 생성이 막혀서는 안 된다. 따라서 이 진입점은 예외 전체를 기록하고
    기능을 낮춰 계속 진행한다. 매니페스트 최초 생성은 여전히 ``write_script_data`` 가
    담당하며, 기본 작업 데이터 쓰기가 실패했을 때의 처리는 주 흐름이 결정한다.
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
        # ``download_videos`` 는 테스트, 스크립트, 외부 코드에서 단독으로 호출될 수도 있다.
        # 이때 매니페스트가 없는 것은 정상이므로, 경고를 내거나 보조 기록을 남기려고
        # 불완전한 파일을 만들어서는 안 된다.
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
