from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config


def _post(path, content):
    with (
        patch.dict(config.app, {"api_key": ""}),
        patch("app.controllers.v1.video.task_manager.add_task") as schedule,
        patch("app.controllers.v1.llm.llm.generate_script") as generate,
        TestClient(asgi.get_application(), raise_server_exceptions=False) as client,
    ):
        response = client.post(
            path, content=content, headers={"content-type": "application/json"}
        )
    schedule.assert_not_called()
    generate.assert_not_called()
    return response


@pytest.mark.parametrize(
    "content, expected",
    [
        (
            '{"video_subject": "sea", "paragraph_number": 0}',
            "body.paragraph_number: Input should be greater than or equal to 1",
        ),
        ('{"video_subject": ', "body.18: JSON decode error"),
    ],
)
def test_validation_message_describes_the_rejected_field(content, expected):
    # Out-of-range values and malformed JSON used to be reported as
    # "field required", pointing clients at a field that was present.
    response = _post("/api/v1/scripts", content)

    assert response.status_code == 400
    body = response.json()
    assert body["message"] == expected
    assert body["data"][0]["msg"] in expected


def test_missing_field_message_still_says_field_required():
    response = _post("/api/v1/videos", "{}")

    assert response.status_code == 400
    assert response.json()["message"] == "body.video_subject: Field required"
