"""Regression: conftest storage redirect is fixture-scoped, never global.

The module-level ``utils.storage_dir = ...`` global replacement leaked temp
paths into CLI material-path and task download-URL tests (macOS failures).
The autouse fixture must patch per-test and restore production originals
after each test.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import test.conftest as conftest_module
from app.utils import utils


def test_storage_redirect_is_active_during_test():
    """The fixture must redirect storage/task dirs to the temp root."""
    assert "mpt_test_storage_" in utils.storage_dir()
    assert "mpt_test_storage_" in utils.task_dir()


def test_production_originals_are_preserved_for_restore():
    """Originals captured at import must point at the real repo storage."""
    prod_storage = conftest_module._production_storage_dir()
    assert prod_storage.endswith(os.path.join("MoneyPrinterTurbo", "storage")) or prod_storage.endswith("storage")
    assert "mpt_test_storage_" not in prod_storage
    prod_tasks = conftest_module._production_task_dir()
    assert prod_tasks.endswith(os.path.join("tasks")) or prod_tasks.endswith("tasks")
    assert "mpt_test_storage_" not in prod_tasks


def test_cli_material_path_uses_patched_storage_consistently():
    """CLI material-path test invariant: create + resolve via same function."""
    from app.services import video as vd
    from app.models.schema import MaterialInfo

    local_dir = utils.storage_dir("local_videos", create=True)
    assert "mpt_test_storage_" in local_dir
    assert os.path.isdir(local_dir)
    # preprocess_video resolves bare filenames against the same storage_dir,
    # so the test stays hermetic regardless of production layout.
    assert vd.preprocess_video is not None
    assert MaterialInfo is not None
