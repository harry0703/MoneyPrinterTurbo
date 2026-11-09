"""Sequential concatenation plays the rest of each clip before it repeats footage."""

from unittest.mock import patch

import pytest

from app.models.schema import VideoConcatMode
from app.services import video


class FakeAudioClip:
    def __init__(self, duration):
        self.duration = duration

    def close(self):
        pass


class FakeVideoClip:
    size = (1080, 1920)
    w, h = size

    def __init__(self, name, duration, segment=None):
        self.name = name
        self.duration = duration
        # The (source, start, end) range of the source that this clip shows.
        self.segment = segment

    def subclipped(self, start, end):
        return FakeVideoClip(self.name, end - start, (self.name, start, end))

    def close(self):
        pass


@pytest.fixture
def combine(tmp_path, monkeypatch):
    """Return the source ranges encoded as clips, and the ranges the join plays."""
    monkeypatch.setitem(video.config.app, "video_clip_concurrency", 1)

    def run(sources, audio_duration, mode=VideoConcatMode.sequential, **options):
        encoded = {}
        joined = []

        def encode(clip, clip_file, **_kwargs):
            encoded[clip_file] = clip.segment

        def concat(clip_files, **_kwargs):
            joined.extend(encoded[clip_file] for clip_file in clip_files)

        with (
            patch.object(video, "AudioFileClip", return_value=FakeAudioClip(audio_duration)),
            patch.object(video, "_open_video_clip_quietly",
                         side_effect=lambda name: FakeVideoClip(name, sources[name])),
            patch.object(video, "_write_videofile_with_codec_fallback", side_effect=encode),
            patch.object(video, "concat_video_clips_with_ffmpeg", side_effect=concat),
        ):
            video.combine_videos(
                str(tmp_path / "combined.mp4"), list(sources), "audio.mp3",
                video_concat_mode=mode, max_clip_duration=3, **options,
            )
        return list(encoded.values()), joined

    return run


def test_one_long_clip_plays_on_instead_of_repeating_its_opening(combine):
    encoded, joined = combine({"a.mp4": 20}, audio_duration=11.9)
    expected = [("a.mp4", 0, 3), ("a.mp4", 3, 6), ("a.mp4", 6, 9), ("a.mp4", 9, 12)]
    assert encoded == expected
    assert joined == expected


def test_clips_take_turns_with_their_next_slices(combine):
    encoded, joined = combine({"a.mp4": 7, "b.mp4": 3, "c.mp4": 9}, audio_duration=17.9)
    expected = [
        ("a.mp4", 0, 3), ("b.mp4", 0, 3), ("c.mp4", 0, 3),
        ("a.mp4", 3, 6), ("c.mp4", 3, 6),
        ("a.mp4", 6, 7), ("c.mp4", 6, 9),
    ]
    assert encoded == expected
    assert joined == expected


def test_footage_repeats_only_after_every_slice_has_played(combine):
    encoded, joined = combine({"a.mp4": 4, "b.mp4": 3}, audio_duration=9.9)
    assert encoded == [("a.mp4", 0, 3), ("b.mp4", 0, 3), ("a.mp4", 3, 4)]
    assert joined == [*encoded, ("a.mp4", 0, 3)]


def test_first_slices_that_cover_the_audio_play_alone(combine):
    encoded, joined = combine({"a.mp4": 9, "b.mp4": 9}, audio_duration=5.9)
    assert encoded == joined == [("a.mp4", 0, 3), ("b.mp4", 0, 3)]


def test_first_slices_that_cover_the_audio_but_not_its_margin_loop_as_before(combine):
    # A later slice would start after the 11.95 s narration and be cut away.
    encoded, joined = combine(
        {"a.mp4": 9, "b.mp4": 9, "c.mp4": 9, "d.mp4": 9}, audio_duration=11.95,
    )
    first_slices = [("a.mp4", 0, 3), ("b.mp4", 0, 3), ("c.mp4", 0, 3), ("d.mp4", 0, 3)]
    assert encoded == first_slices
    assert joined == [*first_slices, ("a.mp4", 0, 3)]


def test_later_slices_follow_the_batch_order_of_the_first_slices(combine):
    encoded, joined = combine(
        {"a.mp4": 6, "b.mp4": 6}, audio_duration=11.9, source_usage={"a.mp4": 1},
    )
    expected = [("b.mp4", 0, 3), ("a.mp4", 0, 3), ("b.mp4", 3, 6), ("a.mp4", 3, 6)]
    assert encoded == expected
    assert joined == expected


def test_random_mode_still_plays_every_slice_once_before_it_loops(combine):
    encoded, joined = combine(
        {"a.mp4": 9}, audio_duration=20, mode=VideoConcatMode.random,
    )
    assert sorted(encoded) == [("a.mp4", 0, 3), ("a.mp4", 3, 6), ("a.mp4", 6, 9)]
    assert joined == encoded * 2 + encoded[:1]
