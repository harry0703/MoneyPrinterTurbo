"""Real ASGI HEAD requests through the authenticated artifact router."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.v1 import video as controller


@pytest.fixture
def client(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "final.mp4").write_bytes(b"ten bytes!")
    (task / "empty.mp4").touch()
    with patch.dict(config.app, {"api_key": ""}), patch.object(
        controller.utils, "task_dir", return_value=str(tmp_path)
    ):
        yield TestClient(asgi.get_application())


@pytest.mark.parametrize("endpoint", ["stream", "download"])
def test_metadata_without_body_matches_get(client, endpoint):
    url = f"/api/v1/{endpoint}/task/final.mp4"
    head = client.head(url)
    full = client.get(url)
    assert head.status_code == full.status_code == 200
    assert head.content == b""
    for key in ("content-length", "content-type", "accept-ranges"):
        assert head.headers[key] == full.headers[key]
    assert head.headers["content-length"] == "10"


@pytest.mark.parametrize("endpoint", ["stream", "download"])
@pytest.mark.parametrize("range_header", ["bytes=1-3", "bytes=99-", "not a range"])
def test_head_ignores_range_for_metadata(client, endpoint, range_header):
    response = client.head(
        f"/api/v1/{endpoint}/task/final.mp4", headers={"Range": range_header}
    )
    assert response.status_code == 200
    assert response.headers["content-length"] == "10"
    assert "content-range" not in response.headers
    assert response.content == b""


@pytest.mark.parametrize("endpoint", ["stream", "download"])
def test_empty_artifact_metadata(client, endpoint):
    response = client.head(f"/api/v1/{endpoint}/task/empty.mp4")
    assert response.status_code == 200
    assert response.headers["content-length"] == "0"
    assert response.content == b""


@pytest.mark.parametrize("endpoint", ["stream", "download"])
def test_head_retains_authentication_and_missing_file_status(client, endpoint):
    with patch.dict(config.app, {"api_key": "head-test-key"}):
        assert client.head(f"/api/v1/{endpoint}/task/final.mp4").status_code == 401
    response = client.head(f"/api/v1/{endpoint}/task/missing.mp4")
    assert response.status_code == 404
    assert response.content == b""


@pytest.mark.parametrize("endpoint", ["stream", "download"])
def test_head_retains_path_boundary(client, endpoint):
    response = client.head(f"/api/v1/{endpoint}/%2E%2E%2Foutside.mp4")
    assert response.status_code == 403
    assert response.content == b""
