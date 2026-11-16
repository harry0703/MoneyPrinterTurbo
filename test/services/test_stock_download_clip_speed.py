"""Stock downloads count each video by the seconds its first clip fills at the clip speed."""

import pytest

from app.config import config
from app.models.schema import MaterialInfo, VideoConcatMode, VideoParams
from app.services import material
from app.services import task as tm


def videos(name, *durations):
    return [
        MaterialInfo(
            provider="pexels",
            url=f"https://v.example/{name}{index}.mp4",
            duration=duration,
            source_info={"provider": "pexels", "asset_id": f"{name}{index}"},
        )
        for index, duration in enumerate(durations)
    ]


@pytest.fixture
def download(monkeypatch):
    """Run the material stage of a Pexels task against fake search results."""
    monkeypatch.setitem(config.app, "material_directory", "")
    monkeypatch.setitem(config.app, "material_concurrency", 1)
    monkeypatch.setattr(
        material.material_cache, "load_material_search_cache", lambda **_: None
    )
    monkeypatch.setattr(
        material.material_cache, "save_material_search_cache", lambda **_: None
    )
    monkeypatch.setattr(
        material.task_artifacts, "patch_script_data", lambda *_, **__: True
    )

    def run(results, audio_duration, **params):
        """Return the videos that get downloaded and the progress the download reports."""
        downloaded, progress = [], []

        def save_video(video_url, save_dir=""):
            downloaded.append(video_url.rsplit("/", 1)[-1].removesuffix(".mp4"))
            return video_url

        monkeypatch.setattr(
            material,
            "search_videos_pexels",
            lambda search_term, **_: results[search_term],
        )
        monkeypatch.setattr(material, "save_video", save_video)
        monkeypatch.setattr(tm, "_stage_progress_reporter", lambda *_: progress.append)
        params = VideoParams(
            video_subject="test", video_source="pexels", video_clip_duration=5, **params
        )
        tm.get_video_materials("clip-speed", params, list(results), audio_duration)
        return downloaded, progress

    return run


@pytest.mark.parametrize(
    "options",
    [
        {"video_concat_mode": VideoConcatMode.random},
        {"video_concat_mode": VideoConcatMode.sequential},
        {"match_materials_to_script": True},
    ],
    ids=["random", "sequential", "script-order"],
)
@pytest.mark.parametrize(
    ("speed", "count"), [(0.5, 5), (1.0, 5), (None, 5), (1.5, 6), (2.0, 7)]
)
def test_downloads_cover_the_narration_at_the_clip_speed(
    download, options, speed, count
):
    # A 5 s clip of a 6 s video fills 5 s at 0.5x and 1x, 4 s at 1.5x and 3 s at 2x,
    # so 20 s of narration needs 5, 6 or 7 videos. A null speed plays at 1x.
    downloaded, _ = download(
        {"city": videos("a", *[6] * 6), "night": videos("b", *[6] * 6)},
        20,
        video_clip_speed=speed,
        **options,
    )
    assert len(downloaded) == count


def test_a_long_video_still_fills_a_whole_clip_at_double_speed(download):
    # At 2x a 5 s clip plays 10 s of a video: a 12 s video fills 5 s, a 6 s one 3 s.
    downloaded, _ = download(
        {"city": videos("a", 12, 6, 12, 6, 12, 6, 12, 6)},
        22,
        video_clip_speed=2.0,
        video_concat_mode=VideoConcatMode.sequential,
    )
    assert downloaded == ["a0", "a1", "a2", "a3", "a4", "a5"]  # 5+3+5+3+5+3 = 24 s


def test_download_progress_counts_the_seconds_each_video_fills(download):
    # At 2x each 6 s video fills 3 s of the 10 s narration.
    _, progress = download(
        {"city": videos("a", *[6] * 6)},
        10,
        video_clip_speed=2.0,
        video_concat_mode=VideoConcatMode.sequential,
    )
    assert progress == [0.3, 0.6, 0.9, 1.0]
