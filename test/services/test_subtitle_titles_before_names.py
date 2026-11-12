from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from edge_tts import SubMaker
from edge_tts.srt_composer import Subtitle

from app.services import subtitle, voice
from app.utils import utils


@pytest.mark.parametrize(
    "script,lines",
    [
        (
            "Mt. Everest is the highest mountain on Earth.",
            ["Mt. Everest is the highest mountain on Earth"],
        ),
        (
            "According to Dr. Matthew Walker, adults need seven to nine hours of sleep.",
            [
                "According to Dr. Matthew Walker",
                "adults need seven to nine hours of sleep",
            ],
        ),
        (
            "Mr. and Mrs. Smith live in Boston. Ms. Lee teaches math.",
            ["Mr. and Mrs. Smith live in Boston", "Ms. Lee teaches math"],
        ),
        (
            "Prof. Stephen Hawking wrote A Brief History of Time.",
            ["Prof. Stephen Hawking wrote A Brief History of Time"],
        ),
        ("El Dr. García trabaja en Madrid.", ["El Dr. García trabaja en Madrid"]),
    ],
)
def test_script_split_keeps_a_title_with_the_name_after_it(script, lines):
    assert utils.split_string_by_punctuations(script) == lines


@pytest.mark.parametrize(
    "script,lines",
    [
        # "St." and "Jr." can end a sentence, and so can "ms" for milliseconds. A
        # title at the end of the script ends its line too.
        (
            "Visit our new shop on Main St. We open at 9 a.m. every day.",
            ["Visit our new shop on Main St", "We open at 9 a.m", "every day"],
        ),
        (
            "This is the story of Martin Luther King Jr. He changed history.",
            ["This is the story of Martin Luther King Jr", "He changed history"],
        ),
        (
            "The delay is only 5 ms. That is fast.",
            ["The delay is only 5 ms", "That is fast"],
        ),
        ("Thank you for watching, Dr.", ["Thank you for watching", "Dr"]),
    ],
)
def test_script_split_still_ends_a_line_where_a_sentence_can_end(script, lines):
    assert utils.split_string_by_punctuations(script) == lines


# Word boundaries Edge TTS (edge-tts 7.3.1) returned for these scripts with
# en-US-JennyNeural, with their start and end times in seconds. Each title is a
# word of its own, read with no pause before the name after it.
CASES = [
    (
        "Mt. Everest is the highest mountain on Earth. It is 8,849 meters tall.",
        [
            ("Mt.", 0.1, 0.475),
            ("Everest", 0.4875, 0.975),
            ("is", 0.9875, 1.1),
            ("the", 1.1125, 1.1875),
            ("highest", 1.2, 1.5875),
            ("mountain", 1.6, 1.925),
            ("on", 1.9375, 2.0625),
            ("Earth", 2.075, 2.4375),
            ("It", 3.3, 3.45),
            ("is", 3.4625, 3.6375),
            ("8,849", 3.65, 5.4125),
            ("meters", 5.425, 5.7625),
            ("tall", 5.775, 6.2375),
        ],
        [
            (
                "00:00:00,100 --> 00:00:02,438",
                "Mt. Everest is the highest mountain on Earth",
            ),
            ("00:00:03,300 --> 00:00:06,238", "It is 8,849 meters tall"),
        ],
    ),
    (
        "According to Dr. Matthew Walker, adults need seven to nine hours of sleep.",
        [
            ("According", 0.1, 0.525),
            ("to", 0.5375, 0.625),
            ("Dr.", 0.6375, 1.0),
            ("Matthew", 1.0125, 1.3625),
            ("Walker", 1.375, 1.8625),
            ("adults", 2.1, 2.45),
            ("need", 2.4625, 2.675),
            ("seven", 2.6875, 3.0125),
            ("to", 3.025, 3.125),
            ("nine", 3.1375, 3.4125),
            ("hours", 3.425, 3.6875),
            ("of", 3.7, 3.775),
            ("sleep", 3.7875, 4.2625),
        ],
        [
            ("00:00:00,100 --> 00:00:01,862", "According to Dr. Matthew Walker"),
            (
                "00:00:02,100 --> 00:00:04,262",
                "adults need seven to nine hours of sleep",
            ),
        ],
    ),
    (
        "Mr. and Mrs. Smith live in Boston. Ms. Lee teaches math at the local school.",
        [
            ("Mr.", 0.1, 0.4875),
            ("and", 0.5, 0.5875),
            ("Mrs.", 0.6, 0.925),
            ("Smith", 0.9375, 1.2625),
            ("live", 1.275, 1.4625),
            ("in", 1.475, 1.575),
            ("Boston", 1.5875, 2.225),
            ("Ms.", 3.0875, 3.3625),
            ("Lee", 3.375, 3.4875),
            ("teaches", 3.5, 3.9),
            ("math", 3.9125, 4.25),
            ("at", 4.2625, 4.3625),
            ("the", 4.375, 4.45),
            ("local", 4.4625, 4.7875),
            ("school", 4.8, 5.325),
        ],
        [
            ("00:00:00,100 --> 00:00:02,225", "Mr. and Mrs. Smith live in Boston"),
            (
                "00:00:03,088 --> 00:00:05,325",
                "Ms. Lee teaches math at the local school",
            ),
        ],
    ),
    (
        "To millions of kids, he was simply Mr. Rogers. He spoke slowly and kindly.",
        [
            ("To", 0.1, 0.2375),
            ("millions", 0.25, 0.6625),
            ("of", 0.675, 0.775),
            ("kids", 0.7875, 1.275),
            ("he", 1.4625, 1.55),
            ("was", 1.5625, 1.7),
            ("simply", 1.7125, 2.05),
            ("Mr.", 2.0625, 2.4125),
            ("Rogers", 2.425, 3.0875),
            ("He", 3.95, 4.125),
            ("spoke", 4.1375, 4.425),
            ("slowly", 4.4375, 4.875),
            ("and", 4.8875, 5.025),
            ("kindly", 5.0375, 5.6375),
        ],
        [
            ("00:00:00,100 --> 00:00:01,275", "To millions of kids"),
            ("00:00:01,462 --> 00:00:03,088", "he was simply Mr. Rogers"),
            ("00:00:03,950 --> 00:00:05,638", "He spoke slowly and kindly"),
        ],
    ),
    (
        # Here "St." is the street at the end of the first sentence, and Edge
        # pauses after it as after any sentence.
        "Visit our new shop on Main St. We open at 9 a.m. every day.",
        [
            ("Visit", 0.1, 0.4125),
            ("our", 0.425, 0.5375),
            ("new", 0.55, 0.6875),
            ("shop", 0.7, 1.0125),
            ("on", 1.025, 1.1625),
            ("Main", 1.175, 1.375),
            ("St.", 1.3875, 1.975),
            ("We", 2.8375, 3.05),
            ("open", 3.0625, 3.375),
            ("at", 3.3875, 3.525),
            ("9 a.m.", 3.5375, 4.175),
            ("every", 4.1875, 4.45),
            ("day", 4.4625, 4.8875),
        ],
        [
            ("00:00:00,100 --> 00:00:01,975", "Visit our new shop on Main St"),
            ("00:00:02,838 --> 00:00:04,175", "We open at 9 a.m"),
            ("00:00:04,188 --> 00:00:04,888", "every day"),
        ],
    ),
]


def _edge_sub_maker(words):
    sub_maker = SubMaker()
    for index, (word, start, end) in enumerate(words, 1):
        sub_maker.cues.append(
            Subtitle(
                index=index,
                start=timedelta(seconds=start),
                end=timedelta(seconds=end),
                content=word,
            )
        )
    return sub_maker


def _legacy_sub_maker(words):
    # Azure TTS v2 fills `subs` and `offset` (in 100 ns units) word by word.
    sub_maker = voice.ensure_legacy_submaker_fields(SubMaker())
    for word, start, end in words:
        sub_maker.subs.append(word)
        sub_maker.offset.append((round(start * 10_000_000), round(end * 10_000_000)))
    return sub_maker


def _srt(captions):
    return "".join(
        f"{index}\n{timing}\n{text}\n\n"
        for index, (timing, text) in enumerate(captions, 1)
    )


@pytest.mark.parametrize("make_sub_maker", [_edge_sub_maker, _legacy_sub_maker])
@pytest.mark.parametrize("script,words,captions", CASES)
def test_tts_words_give_a_title_and_its_name_one_subtitle(
    tmp_path, script, words, captions, make_sub_maker
):
    subtitle_file = tmp_path / "subtitle.srt"

    voice.create_subtitle(make_sub_maker(words), script, str(subtitle_file))

    assert subtitle_file.read_text(encoding="utf-8") == _srt(captions)


def test_whisper_subtitles_give_a_title_and_its_name_one_subtitle(tmp_path):
    """
    create() ends a Whisper cue at each word that ends with a punctuation mark,
    so a transcript that writes "Dr." ends one there. correct() then gives the
    title and the name the one script line that holds them.
    """
    words = [
        SimpleNamespace(start=0.0, end=0.52, word=" According"),
        SimpleNamespace(start=0.52, end=0.62, word=" to"),
        SimpleNamespace(start=0.62, end=1.0, word=" Dr."),
        SimpleNamespace(start=1.0, end=1.36, word=" Matthew"),
        SimpleNamespace(start=1.36, end=1.86, word=" Walker,"),
        SimpleNamespace(start=2.1, end=2.44, word=" adults"),
        SimpleNamespace(start=2.44, end=2.68, word=" need"),
        SimpleNamespace(start=2.68, end=3.0, word=" seven"),
        SimpleNamespace(start=3.0, end=3.12, word=" to"),
        SimpleNamespace(start=3.12, end=3.4, word=" nine"),
        SimpleNamespace(start=3.4, end=3.68, word=" hours"),
        SimpleNamespace(start=3.68, end=3.78, word=" of"),
        SimpleNamespace(start=3.78, end=4.26, word=" sleep."),
    ]
    fake_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (
            [SimpleNamespace(start=0.0, end=4.26, words=words)],
            SimpleNamespace(language="en", language_probability=0.99),
        )
    )
    subtitle_file = tmp_path / "subtitle.srt"
    with (
        patch.object(subtitle, "model", fake_model),
        patch.object(subtitle, "WhisperModel", object()),
    ):
        subtitle.create("audio.mp3", str(subtitle_file))
    assert [item[2] for item in subtitle.file_to_subtitles(str(subtitle_file))] == [
        "According to Dr",
        "Matthew Walker",
        "adults need seven to nine hours of sleep",
    ]

    subtitle.correct(
        str(subtitle_file),
        "According to Dr. Matthew Walker, adults need seven to nine hours of sleep.",
    )

    assert subtitle.file_to_subtitles(str(subtitle_file)) == [
        (1, "00:00:00,000 --> 00:00:01,860", "According to Dr. Matthew Walker"),
        (
            2,
            "00:00:02,100 --> 00:00:04,260",
            "adults need seven to nine hours of sleep",
        ),
    ]
