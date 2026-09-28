import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.schema import VideoParams
from app.services import task, video


class FakeClip:
    size = (1080, 1920)
    w, h = size

    def __init__(self, duration):
        self.duration = duration

    def close(self):
        pass

    def subclipped(self, start, end):
        return FakeClip(end - start)

    def with_speed_scaled(self, factor):
        return FakeClip(self.duration / factor)


@pytest.fixture
def render_batch(tmp_path):
    def run(*, sources, duration=5.9, match=True, count=3, speed=1,
            source="pexels", subtitle_enabled=True, voice_name="test-voice",
            fail_first=False):
        task_id = "allocation-test"
        manifest = tmp_path / "script.json"
        manifest.write_text(json.dumps({"material_sources": [
            {"local_file": name, "search_term": term}
            for name, (term, _) in sources.items()
        ]}), encoding="utf-8")
        params = VideoParams(
            video_subject="test", video_source=source, video_count=count,
            match_materials_to_script=match, video_clip_duration=3,
            video_clip_speed=speed, bgm_type="", subtitle_enabled=subtitle_enabled,
            voice_name=voice_name,
        )
        writes = 0

        def write_clip(*args, **kwargs):
            nonlocal writes
            writes += 1
            if fail_first and writes == 1:
                raise OSError("Unreadable source frames")

        with (
            patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
            patch.object(video, "AudioFileClip", return_value=FakeClip(duration)),
            patch.object(video, "_open_video_clip_quietly",
                         side_effect=lambda name: FakeClip(sources[name][1])),
            patch.object(video, "_write_videofile_with_codec_fallback", side_effect=write_clip),
            patch.object(video, "concat_video_clips_with_ffmpeg"),
            patch.object(video, "delete_files"),
            patch.object(video, "generate_video") as final_render,
            patch.object(task.sm.state, "update_task"),
        ):
            result = task.generate_final_videos(
                task_id, params, list(sources), "audio.mp3",
                "subtitle.srt" if subtitle_enabled else "", duration,
            )
        return SimpleNamespace(
            selections=json.loads(manifest.read_text()).get("material_selections", []),
            warnings=result[2], outputs=result[0], final_render=final_render,
        )
    return run


@pytest.mark.parametrize("subtitle_enabled,voice_name", [
    (True, "zh-CN-XiaoxiaoNeural"), (False, "en-US-JennyNeural"),
])
def test_matched_batch_rotates_candidates_in_keyword_order(
    render_batch, subtitle_enabled, voice_name,
):
    sources = {
        f"{term}-{index}.mp4": (term, 6)
        for index in range(3) for term in ("room", "window")
    }
    result = render_batch(sources=sources, subtitle_enabled=subtitle_enabled,
                          voice_name=voice_name)
    assert [item["local_files"] for item in result.selections] == [
        [f"room-{index}.mp4", f"window-{index}.mp4"] for index in range(3)
    ]
    assert result.warnings == []
    assert len(result.outputs) == 3
    assert result.final_render.call_count == 3


@pytest.mark.parametrize("source", ["pexels", "pixabay", "coverr", "local"])
def test_random_batch_uses_new_sources_before_reuse(render_batch, source):
    sources = {f"clip-{i}.mp4": ("room", 12) for i in range(6)}
    result = render_batch(sources=sources, match=False, source=source)
    selected = [name for item in result.selections for name in item["local_files"]]
    assert len(selected) == len(set(selected)) == 6
    assert result.warnings == []


def test_shortage_reuses_only_exhausted_keyword_candidates(render_batch):
    sources = {
        "room-0.mp4": ("room", 6), "window.mp4": ("window", 6),
        "room-1.mp4": ("room", 6), "room-2.mp4": ("room", 6),
    }
    result = render_batch(sources=sources)
    assert [item["local_files"] for item in result.selections] == [
        [f"room-{i}.mp4", "window.mp4"] for i in range(3)
    ]
    assert result.warnings == [
        {"code": "batch_materials_reused", "video_index": i, "count": 1}
        for i in (2, 3)
    ]


@pytest.mark.parametrize("speed,expected_first_count", [(0.5, 2), (2, 4)])
def test_allocation_tracks_actual_duration_and_speed(render_batch, speed, expected_first_count):
    sources = {f"clip-{i}.mp4": ("room", 3) for i in range(8)}
    result = render_batch(sources=sources, duration=5.9, speed=speed, count=2)
    first, second = [item["local_files"] for item in result.selections]
    assert len(first) == expected_first_count
    assert set(first).isdisjoint(second)
    assert result.warnings == []


def test_safety_margin_does_not_consume_trimmed_source(render_batch):
    sources = {f"clip-{i}.mp4": ("room", 3) for i in range(4)}
    result = render_batch(sources=sources, duration=6, count=2)
    assert [item["local_files"] for item in result.selections] == [
        ["clip-0.mp4", "clip-1.mp4"], ["clip-2.mp4", "clip-3.mp4"],
    ]
    assert result.warnings == []


def test_short_sources_and_looping_still_fill_narration(render_batch):
    sources = {"short.mp4": ("room", 1), "long.mp4": ("window", 3)}
    result = render_batch(sources=sources, count=2)
    assert result.selections[0]["local_files"] == [
        "short.mp4", "long.mp4", "short.mp4", "long.mp4",
    ]
    assert result.warnings == [
        {"code": "batch_materials_reused", "video_index": 2, "count": 2},
    ]


def test_failed_clip_does_not_count_as_used(render_batch):
    sources = {f"clip-{i}.mp4": ("room", 3) for i in range(3)}
    result = render_batch(sources=sources, count=2, fail_first=True)
    assert [item["local_files"] for item in result.selections] == [
        ["clip-1.mp4", "clip-2.mp4"], ["clip-0.mp4", "clip-1.mp4"],
    ]
    assert result.warnings == [
        {"code": "batch_materials_reused", "video_index": 2, "count": 1},
    ]


def test_single_output_preserves_existing_selection(render_batch):
    result = render_batch(sources={"clip.mp4": ("room", 6)}, count=1)
    assert result.selections == []
    assert result.warnings == []


def test_generated_video_sources_do_not_receive_batch_allocation(tmp_path):
    for source in ("wavespeed", "loomloom", "volcengine_seedance"):
        with (
            patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
            patch.object(video, "combine_videos") as combine,
            patch.object(video, "generate_video"),
            patch.object(task.sm.state, "update_task"),
        ):
            task.generate_final_videos(
                "test", VideoParams(video_subject="test", video_source=source,
                                    video_count=2, bgm_type=""),
                ["clip.mp4"], "audio.mp3", "", 6,
            )
        assert all("source_usage" not in call.kwargs for call in combine.call_args_list)


def test_random_allocation_keeps_unique_sources_ahead_of_extra_slices():
    clips = [video.SubClippedVideoClip(name, start, start + 3, source_file_path=name)
             for name in ("used.mp4", "new.mp4") for start in (0, 3)]
    ordered = video._prioritize_unique_source_clips(
        clips, video.VideoConcatMode.random,
        source_usage={"used.mp4": 1},
    )
    assert [clip.source_file_path for clip in ordered] == [
        "new.mp4", "used.mp4", "new.mp4", "used.mp4",
    ]


def test_missing_manifest_falls_back_to_ungrouped_allocation(tmp_path):
    with patch.object(task.utils, "task_dir", return_value=str(tmp_path)):
        assert task._get_material_source_groups("missing", ["clip.mp4"]) == {}
