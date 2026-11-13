from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.v1 import video as controller


def _get(tmp_path, headers=None):
    with (
        patch.dict(config.app, {"api_key": ""}),
        patch.object(controller.utils, "task_dir", return_value=str(tmp_path)),
    ):
        return TestClient(asgi.get_application()).get(
            "/api/v1/stream/empty.srt", headers=headers or {}
        )


def test_stream_returns_empty_body_for_empty_file_without_range(tmp_path):
    # 416 only answers a Range request; a plain GET of an empty artifact is a
    # complete zero-length representation, matching /download.
    (tmp_path / "empty.srt").write_bytes(b"")

    response = _get(tmp_path)

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "0"
    assert "content-range" not in response.headers


def test_stream_still_rejects_range_on_empty_file(tmp_path):
    (tmp_path / "empty.srt").write_bytes(b"")

    response = _get(tmp_path, {"Range": "bytes=0-"})

    assert response.status_code == 416
