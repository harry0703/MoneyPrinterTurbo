from edge_tts import SubMaker

from app.services import subtitle, voice


def _timeline(script, duration=10.0):
    sub_maker = voice.ensure_legacy_submaker_fields(SubMaker())
    return voice.populate_legacy_submaker_with_full_text(sub_maker, script, duration)


def test_trailing_markdown_separator_does_not_end_last_caption_early(tmp_path):
    # Providers without word boundaries split the audio by sentence length.
    # A separator line is never spoken, so it must not take the last slice.
    script = "Only one sentence is spoken here.\n***"
    sub_maker = _timeline(script)

    assert sub_maker.subs == ["Only one sentence is spoken here"]
    assert sub_maker.offset == [(0, 100_000_000)]

    subtitle_file = tmp_path / "subtitle.srt"
    voice.create_subtitle(sub_maker, script, str(subtitle_file))
    items = subtitle.file_to_subtitles(str(subtitle_file))
    assert [(item[1], item[2]) for item in items] == [
        ("00:00:00,000 --> 00:00:10,000", "Only one sentence is spoken here")
    ]


def test_middle_markdown_separator_does_not_delay_following_caption():
    first = "This is the first narrated sentence"
    second = "This is the second one"

    with_separator = _timeline(f"{first}.\n---\n{second}.")
    without_separator = _timeline(f"{first}.\n{second}.")

    assert with_separator.subs == [first, second]
    assert with_separator.offset == without_separator.offset
