import tempfile
from pathlib import Path
from urllib.parse import urlsplit, unquote
import pytest
from app.controllers.v1.video import _task_file_to_uri

@pytest.mark.parametrize("filename", ["two words.mp4", "episode#1.mp4", "50% complete.mp3", "字幕.srt"])
@pytest.mark.parametrize("endpoint", ["", "https://example.test/output"])
def test_task_artifact_uri_preserves_filename(filename, endpoint):
    with tempfile.TemporaryDirectory() as root:
        output = Path(root) / "task-1" / filename
        output.parent.mkdir()
        output.write_bytes(b"artifact")
        uri = _task_file_to_uri(str(output), endpoint, root, "request")
        parsed = urlsplit(uri)
        assert not parsed.query and not parsed.fragment
        assert " " not in parsed.path and "% " not in parsed.path
        assert unquote(parsed.path).endswith("/tasks/task-1/" + filename)

def test_remote_artifact_uri_is_not_reencoded():
    uri = "https://example.test/video.mp4?signature=unchanged%20value"
    assert _task_file_to_uri(uri, "", "/unused", "request") == uri
