import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.v1 import video as controller
from app.models import const
from app.services.state import MemoryState


def test_concurrent_task_deletions_do_not_return_server_error():
    state = MemoryState()
    state.update_task('task-1', state=const.TASK_STATE_COMPLETE)
    with TemporaryDirectory() as directory:
        target = Path(directory, 'task-1')
        target.mkdir()
        (target / 'final.mp4').write_bytes(b'fixture')
        barrier = Barrier(2)
        remove_lock = Lock()
        exists = controller.os.path.exists
        remove = shutil.rmtree

        def synchronized_exists(path):
            result = exists(path)
            if Path(path) == target:
                barrier.wait(timeout=5)
            return result

        def sequential_removal(path, *args, **kwargs):
            # Both requests passed exists(); serialize the actual removals so
            # the second deterministically sees the missing task directory.
            with remove_lock:
                return remove(path, *args, **kwargs)

        with (
            patch.dict(config.app, {'api_key': ''}),
            patch.object(controller.sm, 'state', state),
            patch.object(controller.utils, 'task_dir', return_value=directory),
            patch.object(controller.os.path, 'exists', side_effect=synchronized_exists),
            patch.object(controller.shutil, 'rmtree', side_effect=sequential_removal),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            client = TestClient(asgi.get_application(), raise_server_exceptions=False)
            responses = list(executor.map(lambda _: client.delete('/api/v1/tasks/task-1'), range(2)))
        assert sorted(response.status_code for response in responses) == [200, 200]
        assert not target.exists()
        assert state.get_task('task-1') is None


@pytest.mark.parametrize('error', [PermissionError('denied'), OSError('disk failure'), FileNotFoundError('child disappeared')])
def test_delete_preserves_state_when_directory_still_exists(error):
    state = MemoryState()
    state.update_task('task-1', state=const.TASK_STATE_COMPLETE)
    with TemporaryDirectory() as directory:
        target = Path(directory, 'task-1')
        target.mkdir()
        with (
            patch.dict(config.app, {'api_key': ''}),
            patch.object(controller.sm, 'state', state),
            patch.object(controller.utils, 'task_dir', return_value=directory),
            patch.object(controller.shutil, 'rmtree', side_effect=error),
        ):
            response = TestClient(asgi.get_application(), raise_server_exceptions=False).delete('/api/v1/tasks/task-1')
        assert response.status_code == 500
        assert target.is_dir()
        assert state.get_task('task-1') is not None
