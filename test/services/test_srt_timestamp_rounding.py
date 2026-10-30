import pytest

from app.utils import utils


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (1.001, "00:00:01,001"),
        (2.01, "00:00:02,010"),
        (4.02, "00:00:04,020"),
        (59.9996, "00:01:00,000"),
        (3725.5, "01:02:05,500"),
        (0, "00:00:00,000"),
    ],
)
def test_srt_timestamps_round_to_the_nearest_millisecond(seconds, expected):
    assert utils.time_convert_seconds_to_hmsm(seconds) == expected


def test_every_exact_millisecond_round_trips():
    # faster-whisper word times are decimal values; none of them may be
    # written one millisecond early because of binary float truncation.
    for total_ms in range(0, 120_000):
        formatted = utils.time_convert_seconds_to_hmsm(total_ms / 1000)
        assert int(formatted[-3:]) == total_ms % 1000, formatted


def test_text_to_srt_writes_rounded_cue_boundaries():
    cue = utils.text_to_srt(1, "Hi", 1.005, 2.01)

    assert "00:00:01,005 --> 00:00:02,010" in cue
