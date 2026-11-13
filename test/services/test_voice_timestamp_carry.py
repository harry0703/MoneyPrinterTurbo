import pytest

from app.services import voice


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (59.9996, "00:01:00.000"),
        (119.9999, "00:02:00.000"),
        (3599.9996, "01:00:00.000"),
        (1.2345, "00:00:01.234"),
        (61.5, "00:01:01.500"),
        (0, "00:00:00.000"),
    ],
)
def test_timestamp_rounding_carries_into_minutes_and_hours(seconds, expected):
    assert voice.mktimestamp(seconds * 10**7) == expected


def test_subtitle_formatter_never_writes_sixty_seconds():
    formatter = voice._build_subtitle_formatter()

    cue = formatter(1, 0, 59.9996 * 10**7, "Hello")

    assert cue == "1\n00:00:00,000 --> 00:01:00,000\nHello\n"
