import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.utils import utils


def test_sanitize_strips_path_traversal():
    assert utils.sanitize_upload_filename("../../evil.mp3") == "evil.mp3"
    assert utils.sanitize_upload_filename("a/b/c/song.mp3") == "song.mp3"
    assert utils.sanitize_upload_filename("windows\\path\\song.mp3") == "song.mp3"


def test_sanitize_rejects_empty_or_dotted():
    for bad in ["", "   ", ".", "..", "/", "../.."]:
        with pytest.raises(ValueError):
            utils.sanitize_upload_filename(bad)


def test_save_bgm_upload_writes_mp3(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "song_dir", lambda sub_dir="": str(tmp_path))
    name = utils.save_bgm_upload("my song.mp3", b"ID3fakebytes")
    assert name == "my song.mp3"
    assert (tmp_path / "my song.mp3").read_bytes() == b"ID3fakebytes"


def test_save_bgm_upload_rejects_non_mp3(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "song_dir", lambda sub_dir="": str(tmp_path))
    with pytest.raises(ValueError):
        utils.save_bgm_upload("evil.wav", b"x")


def test_save_bgm_upload_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "song_dir", lambda sub_dir="": str(tmp_path))
    name = utils.save_bgm_upload("../../evil.mp3", b"x")
    assert name == "evil.mp3"
    assert (tmp_path / "evil.mp3").exists()
