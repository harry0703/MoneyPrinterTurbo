"""
Test runtime workaround for a root-owned ``storage/`` directory.

The repository's ``storage/`` directory is owned by root in this environment,
which causes ``PermissionError`` when tests create per-task directories under
``storage/tasks``. This conftest redirects ``utils.storage_dir`` and
``utils.task_dir`` to a writable temporary location for the test process.

This is purely a local testing convenience and does not change production code
paths outside of tests.
"""
import os
import tempfile

from app.utils import utils

_test_storage_root = tempfile.mkdtemp(prefix="mpt_test_storage_")


def _test_storage_dir(sub_dir: str = "", create: bool = False) -> str:
    d = _test_storage_root
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if create and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    return d


def _test_task_dir(sub_dir: str = "") -> str:
    d = os.path.join(_test_storage_root, "tasks")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    return d


utils.storage_dir = _test_storage_dir  # type: ignore[assignment]
utils.task_dir = _test_task_dir  # type: ignore[assignment]
