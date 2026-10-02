from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.controllers.v1 import llm as controller
from app.models.exception import HttpException
from app.models.schema import VideoScriptRequest, VideoTermsRequest


@pytest.mark.parametrize(
    "service,handler,body,failed",
    [
        (
            "generate_script",
            controller.generate_video_script,
            VideoScriptRequest(video_subject="Coffee"),
            "Error: quota exhausted",
        ),
        (
            "generate_script",
            controller.generate_video_script,
            VideoScriptRequest(video_subject="Coffee"),
            "",
        ),
        ("generate_terms", controller.generate_video_terms, VideoTermsRequest(), []),
    ],
)
def test_provider_failure_does_not_return_success(service, handler, body, failed):
    request = SimpleNamespace(headers={"x-task-id": "request-1"})
    with patch.object(controller.llm, service, return_value=failed):
        with pytest.raises(HttpException) as raised:
            handler(request, body)
    assert raised.value.status_code == 503
    assert "unavailable" in raised.value.message
