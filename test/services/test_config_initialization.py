import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.config import config


def test_late_initializer_preserves_config_created_after_missing_check():
    with TemporaryDirectory() as directory:
        target = Path(directory, 'config.toml')
        example = Path(directory, 'config.example.toml')
        example.write_text('[app]\napi_key = ""\n', encoding='utf-8')
        winner = '[app]\napi_key = "already-configured"\n'
        isfile = os.path.isfile
        created = False

        def create_winner_after_check(path):
            nonlocal created
            if str(path) == str(target) and not created:
                created = True
                target.write_text(winner, encoding='utf-8')
                return False
            return isfile(path)

        with (
            patch.object(config, 'root_dir', directory),
            patch.object(config, 'config_file', str(target)),
            patch.object(config.os.path, 'isfile', side_effect=create_winner_after_check),
        ):
            result = config.load_config()
        assert result['app']['api_key'] == 'already-configured'
        assert target.read_text() == winner
        assert not list(Path(directory).glob('.config-init-*'))


def test_first_boot_publishes_only_complete_config():
    with TemporaryDirectory() as directory:
        target = Path(directory, 'config.toml')
        example = Path(directory, 'config.example.toml')
        payload = '[app]\napi_key = "complete"\n' + '# filler\n' * 1000
        example.write_text(payload, encoding='utf-8')
        link = os.link
        rename = os.rename

        def check_publication(source, destination):
            assert not target.exists()
            assert Path(source).read_text() == payload
            return (rename if os.name == 'nt' else link)(source, destination)

        with (
            patch.object(config, 'root_dir', directory),
            patch.object(config, 'config_file', str(target)),
            patch.object(config.os, 'rename' if os.name == 'nt' else 'link', side_effect=check_publication),
        ):
            assert config.load_config()['app']['api_key'] == 'complete'
        assert target.read_text() == payload
        assert not list(Path(directory).glob('.config-init-*'))


@pytest.mark.parametrize('error', [OSError(errno.EPERM, 'unsupported publication'), OSError(errno.ENOSPC, 'full disk')])
def test_initialization_failure_leaves_no_partial_config_or_temporary_file(error):
    with TemporaryDirectory() as directory:
        target = Path(directory, 'config.toml')
        example = Path(directory, 'config.example.toml')
        example.write_text('[app]\napi_key = ""\n', encoding='utf-8')
        with (
            patch.object(config, 'root_dir', directory),
            patch.object(config, 'config_file', str(target)),
            patch.object(config.os, 'rename' if os.name == 'nt' else 'link', side_effect=error),
        ):
            with pytest.raises(OSError, match='copy config.example.toml'):
                config.load_config()
        assert not target.exists()
        assert not list(Path(directory).glob('.config-init-*'))


def test_windows_publication_uses_rename_without_hardlinks():
    with TemporaryDirectory() as directory:
        target = str(Path(directory, 'config.toml'))
        example = Path(directory, 'config.example.toml')
        example.write_text('[app]\napi_key = ""\n', encoding='utf-8')
        rename = os.rename
        with (
            patch.object(config, 'config_file', target),
            patch.object(config.os, 'name', 'nt'),
            patch.object(config.os, 'rename', side_effect=rename) as renamed,
            patch.object(config.os, 'link') as linked,
        ):
            assert config._initialize_config_from_example(str(example))
        renamed.assert_called_once()
        linked.assert_not_called()
        assert Path(target).is_file()
        assert not list(Path(directory).glob('.config-init-*'))


def test_windows_destination_collision_preserves_existing_config():
    with TemporaryDirectory() as directory:
        target = Path(directory, 'config.toml')
        target.write_text('[app]\napi_key = "keep"\n', encoding='utf-8')
        example = Path(directory, 'config.example.toml')
        example.write_text('[app]\napi_key = ""\n', encoding='utf-8')
        with (
            patch.object(config, 'config_file', str(target)),
            patch.object(config.os, 'name', 'nt'),
            patch.object(config.os, 'rename', side_effect=FileExistsError),
        ):
            assert not config._initialize_config_from_example(str(example))
        assert '"keep"' in target.read_text()
        assert not list(Path(directory).glob('.config-init-*'))


def test_initializer_accepts_winner_published_after_docker_stub_check():
    with TemporaryDirectory() as directory:
        target = Path(directory, 'config.toml')
        target.mkdir()
        example = Path(directory, 'config.example.toml')
        example.write_text('[app]\napi_key = ""\n', encoding='utf-8')
        winner = '[app]\napi_key = "winning-config"\n'
        remove_directory = os.rmdir

        def publish_winner_before_stub_removal(path, *args, **kwargs):
            # Both initializers saw the empty Docker bind-mount stub. The first
            # removes it and publishes its complete regular config before the
            # second reaches rmdir, which now raises real NotADirectoryError.
            if str(path) == str(target):
                remove_directory(path)
                target.write_text(winner, encoding='utf-8')
            return remove_directory(path, *args, **kwargs)

        with (
            patch.object(config, 'root_dir', directory),
            patch.object(config, 'config_file', str(target)),
            patch.object(config.os, 'rmdir', side_effect=publish_winner_before_stub_removal),
        ):
            result = config.load_config()
        assert result['app']['api_key'] == 'winning-config'
        assert target.read_text() == winner
        assert not list(Path(directory).glob('.config-init-*'))


def test_not_a_directory_error_does_not_hide_an_unusable_config_path():
    with TemporaryDirectory() as directory:
        target = Path(directory, 'config.toml')
        target.mkdir()
        with (
            patch.object(config, 'config_file', str(target)),
            patch.object(config.os, 'rmdir', side_effect=NotADirectoryError('not a regular winner')),
        ):
            with pytest.raises(IsADirectoryError):
                config.load_config()
        assert target.is_dir()
