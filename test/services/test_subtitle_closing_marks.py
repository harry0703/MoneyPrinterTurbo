import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.services import voice
from app.utils import utils


@pytest.mark.parametrize(
    "script,lines",
    [
        (
            'He said, "I am leaving tonight." She replied, "Then go!" Nobody spoke.',
            ['He said', '"I am leaving tonight."', 'She replied', '"Then go!"', "Nobody spoke"],
        ),
        ("He said 'hi.' Then left.", ["He said 'hi.'", "Then left"]),
        ("(He left the room.) Nobody spoke.", ["(He left the room.)", "Nobody spoke"]),
        ('"Wait..." he said.', ['"Wait..."', "he said"]),
        ('"Really?!" she asked.', ['"Really?!"', "she asked"]),
        ("“Hi!” he said. “Bye.”", ["“Hi!”", "he said", "“Bye.”"]),
        ('He said "Go!", then left.', ['He said "Go!"', "then left"]),
        ("他说「你好。」然后走了。", ["他说「你好。」", "然后走了"]),
        # A curly closing quote closes its quotation even when a word follows it.
        ("她喊：“快走！”她转身离开。", ["她喊", "“快走！”", "她转身离开"]),
        ("He said: “Go now!”Then left.", ["He said", "“Go now!”", "Then left"]),
        ("He said, ‘hi.’Then left.", ["He said", "‘hi.’", "Then left"]),
    ],
)
def test_script_split_keeps_a_closing_mark_with_the_line_it_closes(script, lines):
    assert utils.split_string_by_punctuations(script) == lines


@pytest.mark.parametrize(
    "script,lines",
    [
        # A quote mark that opens a quotation stays with the words it opens, with or
        # without a space after it.
        ('He said:"Go" now.', ["He said", '"Go" now']),
        ('He said:" Go now!" Then left.', ["He said", '" Go now!"', "Then left"]),
        ("It said:' Go now.' Then left.", ["It said", "' Go now.'", "Then left"]),
        ("她喊：“快走！她转身离开。", ["她喊", "“快走", "她转身离开"]),
        # An apostrophe is not a quote mark.
        ("It's fine, 'ok.' Then.", ["It's fine", "'ok.'", "Then"]),
        ("Rock.’n roll.", ["Rock", "’n roll"]),
        ("Dogs. 'Tis fine.", ["Dogs", "'Tis fine"]),
        ('Wait...what', ["Wait", "what"]),
        ("Plain sentence. Another one!", ["Plain sentence", "Another one"]),
    ],
)
def test_script_split_still_ends_a_line_at_its_stop_without_a_closing_mark(script, lines):
    assert utils.split_string_by_punctuations(script) == lines


def test_subtitles_do_not_start_with_the_quote_the_line_before_closes(tmp_path):
    # Word boundaries Edge TTS (edge-tts 7.3.1) returned for this script with
    # en-US-JennyNeural: quote marks and full stops are not words.
    text = 'He said, "I am leaving tonight." She replied, "Then go!" Nobody spoke.'
    words = "He said I am leaving tonight She replied Then go Nobody spoke".split()
    cues = [
        SimpleNamespace(
            content=word,
            start=timedelta(seconds=index * 0.5),
            end=timedelta(seconds=index * 0.5 + 0.4),
        )
        for index, word in enumerate(words)
    ]
    subtitle_file = tmp_path / "voice.mp3.srt"

    voice.create_subtitle(SimpleNamespace(cues=cues), text, str(subtitle_file))

    blocks = subtitle_file.read_text(encoding="utf-8").strip().split("\n\n")
    assert [block.split("\n", 2)[2] for block in blocks] == [
        "He said",
        '"I am leaving tonight."',
        "She replied",
        '"Then go!"',
        "Nobody spoke",
    ]


@pytest.mark.parametrize("mark", [".", "…", "!"])
@pytest.mark.parametrize("opening,closing", [("", ""), ('"', '"'), ("“", "”")])
def test_script_split_reads_a_long_run_of_stops_once(mark, opening, closing):
    # Reading the rest of the run at every stop took seconds for a run this long. The
    # bound is far above what linear code needs, so a slow machine still passes.
    run = mark * 20_000
    script = f"{opening}Wait{run}{closing} he said."

    started = time.perf_counter()
    lines = utils.split_string_by_punctuations(script)
    elapsed = time.perf_counter() - started

    assert lines == [f"{opening}Wait{run}{closing}" if closing else "Wait", "he said"]
    assert elapsed < 1.0
