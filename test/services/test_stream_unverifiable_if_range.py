from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.v1 import video as controller


@pytest.mark.parametrize('validator', ['"older-video-revision"', 'Tue, 01 Jan 2019 00:00:00 GMT'])
def test_stream_returns_complete_video_for_unverifiable_if_range(tmp_path, validator):
    payload = b'complete current video fixture'
    (tmp_path / 'clip.mp4').write_bytes(payload)
    with patch.dict(config.app, {'api_key': ''}), patch.object(controller.utils, 'task_dir', return_value=str(tmp_path)):
        response = TestClient(asgi.get_application()).get('/api/v1/stream/clip.mp4', headers={
            'Range': 'bytes=9-', 'If-Range': validator,
        })
    assert response.status_code == 200
    assert response.content == payload
    assert 'content-range' not in response.headers
    assert response.headers['content-length'] == str(len(payload))


def test_stream_keeps_unconditional_partial_request(tmp_path):
    (tmp_path / 'clip.mp4').write_bytes(b'0123456789')
    with patch.dict(config.app, {'api_key': ''}), patch.object(controller.utils, 'task_dir', return_value=str(tmp_path)):
        response = TestClient(asgi.get_application()).get('/api/v1/stream/clip.mp4', headers={'Range': 'bytes=3-'})
    assert response.status_code == 206
    assert response.content == b'3456789'
