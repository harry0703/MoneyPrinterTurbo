from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.v1 import video as controller


@pytest.mark.parametrize('filename,expected', [
    ('audio.mp3', 'audio/mpeg'),
    ('audio.wav', ('audio/x-wav', 'audio/wav', 'audio/vnd.wave')),
    ('subtitle.srt', 'application/x-subrip'),
    ('script.json', 'application/json'),
    ('final-1.mp4', 'video/mp4'),
    ('artifact.unknown-mpt-extension', 'application/octet-stream'),
])
def test_download_reports_artifact_media_type(filename, expected):
    with TemporaryDirectory() as directory:
        task_dir = Path(directory, 'task-1')
        task_dir.mkdir()
        payload = b'isolated download fixture'
        (task_dir / filename).write_bytes(payload)
        with (
            patch.dict(config.app, {'api_key': ''}),
            patch.object(controller.utils, 'task_dir', return_value=directory),
        ):
            response = TestClient(asgi.get_application()).get(f'/api/v1/download/task-1/{filename}')
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers['content-type'].split(';')[0] in (expected if isinstance(expected, tuple) else (expected,))
    assert filename in response.headers['content-disposition']
