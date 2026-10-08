import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app import asgi
from app.config import config
from app.models.schema import AudioRequest, SubtitleRequest, TaskVideoRequest
from app.services import state as sm


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", '"NaN"', '"Infinity"'])
@pytest.mark.parametrize("path", ["/api/v1/videos", "/api/v1/audio", "/api/v1/subtitle"])
@pytest.mark.parametrize("field", ["voice_rate", "voice_volume", "bgm_volume"])
def test_nonfinite_audio_values_fail_before_background_work(path, field, number):
    with (
        patch.dict(config.app, {"api_key": ""}),
        patch.object(sm, "state", sm.MemoryState()),
        patch("app.controllers.v1.video.task_manager.add_task") as schedule,
        TestClient(asgi.get_application(), raise_server_exceptions=False) as client,
    ):
        response = client.post(path, content='{"video_subject":"test","video_script":"hello","' + field + '":' + number + '}', headers={"content-type": "application/json"})
    assert response.status_code == 400
    body = response.json()
    assert body["data"][0]["loc"] == ["body", field]
    json.dumps(body, allow_nan=False)
    schedule.assert_not_called()


@pytest.mark.parametrize("model", [TaskVideoRequest, AudioRequest, SubtitleRequest])
@pytest.mark.parametrize("value", [None, 0, 0.2, 1, 2])
def test_existing_finite_and_optional_audio_values_remain_valid(model, value):
    params = model(video_subject="test", video_script="hello", voice_rate=value, voice_volume=value, bgm_volume=value)
    assert params.voice_rate == value
    assert params.voice_volume == value
    assert params.bgm_volume == value
