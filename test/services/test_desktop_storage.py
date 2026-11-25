import tempfile

import pytest

from app import desktop_storage, paths


def test_cyclic_storage_path_is_rejected_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MPT_HOME", str(tmp_path))
    monkeypatch.setenv("MPT_DESKTOP", "1")
    monkeypatch.setenv("MPT_DESKTOP_STORAGE_DIR", str(tmp_path / "previous-storage"))
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    loop = tmp_path / "loop"
    try:
        loop.symlink_to(loop.name, target_is_directory=True)
    except OSError:
        pytest.skip("The current user cannot create symbolic links")

    with pytest.raises((ValueError, OSError)):
        desktop_storage.save_directory(str(loop))

    desktop_storage.preference_file().write_text(str(loop), encoding="utf-8")
    default = tmp_path / "default-storage"
    desktop_storage.configure_at_startup(str(default))

    assert paths.storage_root() == default
    assert tempfile.gettempdir() == str(default / "temp")
