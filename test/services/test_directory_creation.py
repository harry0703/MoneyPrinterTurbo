from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

import pytest

from app import paths
from app.utils import utils


@pytest.mark.parametrize('helper', ['storage', 'task', 'font', 'song', 'public'])
def test_directory_helpers_allow_concurrent_first_use(helper):
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / 'storage').mkdir()
        (root / 'storage' / 'tasks').mkdir()
        for name in ('fonts', 'songs', 'public'):
            (root / 'resource' / name).mkdir(parents=True)
        make_directory = utils.os.makedirs
        barrier = Barrier(2)

        def concurrent_makedirs(path, *args, **kwargs):
            barrier.wait(timeout=5)
            return make_directory(path, *args, **kwargs)

        def create():
            if helper == 'storage':
                return utils.storage_dir('first-use', create=True)
            return getattr(utils, f'{helper}_dir')('first-use')

        with (
            patch.object(paths, 'runtime_root', return_value=root),
            patch.object(utils.os, 'makedirs', side_effect=concurrent_makedirs),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [executor.submit(create) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        assert results[0] == results[1]
        assert Path(results[0]).is_relative_to(root)
        assert Path(results[0]).is_dir()


def test_storage_lookup_does_not_create_directory():
    with TemporaryDirectory() as root, patch.object(paths, 'runtime_root', return_value=Path(root)):
        result = utils.storage_dir('lookup-only')
        assert Path(result) == Path(root) / 'storage' / 'lookup-only'
        assert not Path(result).exists()


def test_directory_creation_does_not_hide_file_collision():
    with TemporaryDirectory() as root, patch.object(paths, 'runtime_root', return_value=Path(root)):
        storage = Path(root, 'storage')
        storage.mkdir()
        (storage / 'collision').write_text('keep', encoding='utf-8')
        with pytest.raises(FileExistsError):
            utils.storage_dir('collision', create=True)
        assert (storage / 'collision').read_text() == 'keep'
