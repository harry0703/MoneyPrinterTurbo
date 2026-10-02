import pytest
from pydantic import ValidationError
from app.models.schema import TaskVideoRequest, VideoParams, SubtitleRequest


@pytest.mark.parametrize(
    "model,required",
    [
        (TaskVideoRequest, {"video_subject": "coffee"}),
        (SubtitleRequest, {"video_script": "coffee"}),
    ],
)
@pytest.mark.parametrize(
    "field,value",
    [
        ("font_size", 0),
        ("font_size", -1),
        ("stroke_width", -1.0),
        ("stroke_width", float("inf")),
    ],
)
def test_invalid_subtitle_render_values_rejected_before_generation(
    model, required, field, value
):
    with pytest.raises(ValidationError):
        model(**required, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("custom_position", -1.0),
        ("custom_position", 101.0),
        ("custom_position", float("nan")),
    ],
)
def test_invalid_video_render_values_rejected_before_generation(field, value):
    with pytest.raises(ValidationError):
        TaskVideoRequest(video_subject="coffee", **{field: value})


def test_valid_render_boundaries_and_optional_thread_default_remain_usable():
    params = VideoParams(
        video_subject="coffee",
        font_size=1,
        stroke_width=0,
        custom_position=100,
        n_threads=None,
    )
    assert params.font_size == 1 and params.n_threads is None
    assert (
        SubtitleRequest(video_script="coffee", font_size=1, stroke_width=0).stroke_width
        == 0
    )
