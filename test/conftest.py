"""
Test runtime workaround for a root-owned ``storage/`` directory.

The repository's ``storage/`` directory may be owned by root in some
environments, which causes ``PermissionError`` when tests create per-task
directories under ``storage/tasks``. This conftest redirects
``utils.storage_dir`` and ``utils.task_dir`` to a writable temporary location
for the test process.

Scope note (macOS regression fix): the redirect is applied via an autouse
fixture that saves the production originals and restores them after each
test. Module-level global replacement leaked the temp paths into
CLI material-path and task download-URL tests, which assert on real
production locations. The fixture keeps the root-owned ``storage/``
workaround working while guaranteeing no leak between tests, and production
code paths outside tests are never modified.

Symlink note (macOS /var vs /private/var): ``tempfile.mkdtemp`` may return
a path through a symlink (macOS TMPDIR lives under ``/var``, which links
to ``/private/var``). The root is canonicalized with ``os.path.realpath``
at creation so every test-scoped path is already in canonical form; that
matches what ``file_security.resolve_path_within_directory`` returns
(it realpaths) and keeps ``relpath``-based URL building consistent.
Path-sensitive assertions must still compare ``os.path.realpath`` on BOTH
sides — never assume the temp path is already canonical.
"""
import os
import shutil
import tempfile

import pytest

from app.utils import utils

_test_storage_root = os.path.realpath(tempfile.mkdtemp(prefix="mpt_test_storage_"))

# Capture production originals at import time so the fixture can restore them.
_ORIGINAL_STORAGE_DIR = utils.storage_dir
_ORIGINAL_TASK_DIR = utils.task_dir


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


@pytest.fixture(autouse=True)
def _isolated_test_storage(monkeypatch):
    """Redirect storage/task dirs to temp for each test, then restore."""
    monkeypatch.setattr(utils, "storage_dir", _test_storage_dir)
    monkeypatch.setattr(utils, "task_dir", _test_task_dir)
    yield
    # monkeypatch automatically restores _ORIGINAL_STORAGE_DIR/_ORIGINAL_TASK_DIR.


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_storage_root():
    """Remove the mkdtemp tree once the whole test session finishes."""
    yield
    shutil.rmtree(_test_storage_root, ignore_errors=True)


def _production_storage_dir(sub_dir: str = "", create: bool = False) -> str:
    """Expose the pre-patch production implementation for path-sensitive tests."""
    return _ORIGINAL_STORAGE_DIR(sub_dir, create=create)


def _production_task_dir(sub_dir: str = "") -> str:
    """Expose the pre-patch production implementation for path-sensitive tests.

    NOTE: ``utils.task_dir`` delegates to the module-global ``storage_dir``
    name at call time, so calling ``_ORIGINAL_TASK_DIR`` directly while the
    fixture is active would still resolve through the patched temp redirect.
    Recompute from ``_ORIGINAL_STORAGE_DIR`` instead to guarantee the real
    production path.
    """
    d = os.path.join(_ORIGINAL_STORAGE_DIR(), "tasks")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    return d
