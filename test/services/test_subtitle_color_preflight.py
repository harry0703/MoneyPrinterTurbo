from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import asgi
from app.config import config
from app.controllers.v1 import video as controller
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task


@pytest.mark.parametrize("field", ["text_fore_color", "stroke_color", "text_background_color"])
def test_http_rejects_invalid_active_color_before_queue(field):
    with patch.dict(config.app, {"api_key": ""}), patch.object(sm, "state", sm.MemoryState()), patch.object(controller.task_manager, "add_task") as queued:
        with TestClient(asgi.app) as client:
            response = client.post("/api/v1/videos", json={"video_subject": "Coffee", field: "#gg0000"})
        assert response.status_code == 400
        assert field in response.json()["message"]
        queued.assert_not_called()
        assert sm.state.list_task_ids() == []


@pytest.mark.parametrize("field", ["text_fore_color", "stroke_color", "text_background_color"])
def test_pipeline_rejects_invalid_color_before_generation(field):
    params = VideoParams(video_subject="Coffee", **{field: "not-a-color"})
    with patch.object(sm, "state", sm.MemoryState()), patch.object(task.llm, "generate_script", side_effect=RuntimeError("generation boundary reached")) as provider:
        task.start("bad-color", params)
        provider.assert_not_called()
        failure = sm.state.get_task("bad-color")
        assert failure["failed_stage"] == "preflight"
        assert field in failure["error"]


@pytest.mark.parametrize("colors", [
    {"text_fore_color": "RebeccaPurple", "stroke_color": "rgb(1, 2, 3)", "text_background_color": "hsl(0, 100%, 50%)"},
    {"text_fore_color": "#abcd", "stroke_color": "#12345678", "text_background_color": "rgba(1, 2, 3, 0)"},
    {"text_fore_color": None, "stroke_color": None, "text_background_color": False},
    {"text_background_color": True},
    {"stroke_width": 0, "stroke_color": "not-used"},
])
def test_http_preserves_supported_pillow_colors_and_unused_stroke(colors):
    # Verify accepted color syntax against the actual renderer's Pillow consumer.
    image = Image.new("RGBA", (32, 32))
    draw = ImageDraw.Draw(image)
    draw.text((0, 0), "A", fill=colors.get("text_fore_color", "white"), stroke_width=int(colors.get("stroke_width", 1)), stroke_fill=colors.get("stroke_color", "black"))
    background = colors.get("text_background_color", False)
    if isinstance(background, str):
        Image.new("RGBA", (1, 1), background)
    with patch.dict(config.app, {"api_key": ""}), patch.object(sm, "state", sm.MemoryState()), patch.object(controller.task_manager, "add_task") as queued:
        with TestClient(asgi.app) as client:
            response = client.post("/api/v1/videos", json={"video_subject": "Coffee", **colors})
        assert response.status_code == 200
        queued.assert_called_once()


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/v1/videos", {"video_subject": "Coffee", "subtitle_enabled": False}),
    ("/api/v1/subtitle", {"video_script": "Coffee"}),
])
def test_http_does_not_validate_colors_that_will_not_render(endpoint, payload):
    with patch.dict(config.app, {"api_key": ""}), patch.object(sm, "state", sm.MemoryState()), patch.object(controller.task_manager, "add_task") as queued:
        with TestClient(asgi.app) as client:
            response = client.post(endpoint, json={**payload, "text_fore_color": "unused-color"})
        assert response.status_code == 200
        queued.assert_called_once()
