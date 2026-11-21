"""默认渲染后端必须原样转发参数，并保持进度、素材统计和 BGM 结果语义。"""

import inspect

import pytest

from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import render_backend, video


def test_local_backend_forwards_every_combine_argument(monkeypatch):
    calls = []

    def fake_combine(**kwargs):
        calls.append(kwargs)
        return "combined.mp4"

    monkeypatch.setattr(video, "combine_videos", fake_combine)
    progress = lambda value: None
    source_usage = {"a.mp4": 1}
    source_groups = {"a.mp4": "pexels"}
    used_video_paths = ["a.mp4"]

    result = render_backend.LocalMoviePyBackend().combine_videos(
        combined_video_path="out.mp4",
        video_paths=["a.mp4"],
        audio_file="voice.mp3",
        video_aspect=VideoAspect.landscape,
        video_concat_mode=VideoConcatMode.sequential,
        video_transition_mode=VideoTransitionMode.fade_in,
        max_clip_duration=3,
        threads=4,
        clip_speed=1.5,
        video_fit_mode=VideoFitMode.contain,
        source_usage=source_usage,
        source_groups=source_groups,
        used_video_paths=used_video_paths,
        progress_callback=progress,
    )

    assert result == "combined.mp4"
    # 参数不丢不改，批量素材统计和进度回调才能继续由调用方持有。
    assert calls == [{
        "combined_video_path": "out.mp4",
        "video_paths": ["a.mp4"],
        "audio_file": "voice.mp3",
        "video_aspect": VideoAspect.landscape,
        "video_concat_mode": VideoConcatMode.sequential,
        "video_transition_mode": VideoTransitionMode.fade_in,
        "max_clip_duration": 3,
        "threads": 4,
        "clip_speed": 1.5,
        "video_fit_mode": VideoFitMode.contain,
        "source_usage": source_usage,
        "source_groups": source_groups,
        "used_video_paths": used_video_paths,
        "progress_callback": progress,
    }]


def test_local_backend_keeps_bgm_result_and_forwards_override(monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return False

    monkeypatch.setattr(video, "generate_video", fake_generate)
    params = VideoParams(video_subject="test")

    result = render_backend.LocalMoviePyBackend().generate_video(
        video_path="combined.mp4",
        audio_path="voice.mp3",
        subtitle_path="subtitle.srt",
        output_file="final.mp4",
        params=params,
        bgm_file_override="music.mp3",
    )

    assert result is False
    assert captured["params"] is params
    assert captured["bgm_file_override"] == "music.mp3"
    assert captured["output_file"] == "final.mp4"


def _call_shape(function):
    parameters = list(inspect.signature(function).parameters.values())
    if parameters and parameters[0].name == "self":
        parameters = parameters[1:]
    return [
        (parameter.name, parameter.kind, parameter.default)
        for parameter in parameters
    ]


@pytest.mark.parametrize("name", ["combine_videos", "generate_video"])
def test_protocol_signatures_match_the_video_module(name):
    # 接口必须跟随 video 模块，避免以后加参数时远程后端拿不到新参数。
    assert _call_shape(getattr(render_backend.RenderBackend, name)) == _call_shape(
        getattr(video, name)
    )


def test_local_backend_does_not_invent_omitted_options(monkeypatch):
    calls = []

    def fake_combine(**kwargs):
        calls.append(kwargs)
        return "combined.mp4"

    monkeypatch.setattr(video, "combine_videos", fake_combine)
    render_backend.LocalMoviePyBackend().combine_videos(
        combined_video_path="out.mp4",
        video_paths=["a.mp4"],
        audio_file="voice.mp3",
    )

    # 批量分配关闭时 task.py 不传 source_usage；透传不能补出这个键。
    assert calls == [{
        "combined_video_path": "out.mp4",
        "video_paths": ["a.mp4"],
        "audio_file": "voice.mp3",
    }]
