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
