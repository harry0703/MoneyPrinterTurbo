import wave
from datetime import timedelta
from unittest.mock import patch

import pytest
from edge_tts import SubMaker
from edge_tts.srt_composer import Subtitle

from app.services import voice

# Word boundaries Edge TTS (edge-tts 7.3.1) returned for these scripts with
# en-US-JennyNeural and de-DE-KatjaNeural, with their start and end times in
# seconds. A date, a German date, a place name and "No. 1" come back as one
# word, across the comma or full stop at which the script split ends a line.
MOON_WORDS = [
    ("On", 0.1, 0.2625),
    ("July 20, 1969", 0.275, 2.5125),
    ("two", 2.7125, 2.925),
    ("astronauts", 2.9375, 3.525),
    ("landed", 3.5375, 3.85),
    ("on", 3.8625, 3.975),
    ("the", 3.9875, 4.05),
    ("Moon", 4.0625, 4.4875),
]
MOON_CAPTIONS = [
    ("00:00:00,100 --> 00:00:02,512", "On July 20, 1969"),
    ("00:00:02,712 --> 00:00:04,488", "two astronauts landed on the Moon"),
]

CASES = [
    (
        "On July 20, 1969, two astronauts landed on the Moon.",
        MOON_WORDS,
        MOON_CAPTIONS,
    ),
    (
        "Am 9. November 1989 fiel die Berliner Mauer. Das war ein historischer Tag.",
        [
            ("Am 9. November 1989", 0.1, 2.8625),
            ("fiel", 2.875, 3.1),
            ("die", 3.1125, 3.2125),
            ("Berliner", 3.225, 3.675),
            ("Mauer", 3.6875, 4.0625),
            ("Das", 4.925, 5.175),
            ("war", 5.1875, 5.3625),
            ("ein", 5.375, 5.5),
            ("historischer", 5.5125, 6.2),
            ("Tag", 6.2125, 6.675),
        ],
        [
            ("00:00:00,100 --> 00:00:04,062", "Am 9. November 1989 fiel die Berliner Mauer"),
            ("00:00:04,925 --> 00:00:06,675", "Das war ein historischer Tag"),
        ],
    ),
    (
        "The White House is in Washington, D.C. It has 132 rooms.",
        [
            ("The", 0.1, 0.2375),
            ("White", 0.25, 0.4875),
            ("House", 0.5, 0.8),
            ("is", 0.8125, 0.925),
            ("in", 0.9375, 1.05),
            ("Washington, D.C.", 1.0625, 2.2),
            ("It", 3.0625, 3.2),
            ("has", 3.2125, 3.375),
            ("132", 3.3875, 4.4875),
            ("rooms", 4.5, 5.0375),
        ],
        [
            ("00:00:00,100 --> 00:00:02,200", "The White House is in Washington, D.C"),
            ("00:00:03,062 --> 00:00:05,038", "It has 132 rooms"),
        ],
    ),
    (
        "This phone is the No. 1 seller in Japan. Everyone wants one.",
        [
            ("This", 0.1, 0.3625),
            ("phone", 0.375, 0.6125),
            ("is", 0.625, 0.75),
            ("the", 0.7625, 0.8375),
            ("No. 1", 0.85, 1.3875),
            ("seller", 1.4, 1.725),
            ("in", 1.7375, 1.8375),
            ("Japan", 1.85, 2.4125),
            ("Everyone", 3.275, 3.725),
            ("wants", 3.7375, 4.0125),
            ("one", 4.025, 4.4125),
        ],
        [
            ("00:00:00,100 --> 00:00:02,412", "This phone is the No. 1 seller in Japan"),
            ("00:00:03,275 --> 00:00:04,412", "Everyone wants one"),
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


@pytest.mark.parametrize("script,words,captions", CASES)
def test_edge_word_across_script_lines_keeps_subtitles(tmp_path, script, words, captions):
    subtitle_file = tmp_path / "subtitle.srt"

    voice.create_subtitle(_edge_sub_maker(words), script, str(subtitle_file))

    assert subtitle_file.read_text(encoding="utf-8") == _srt(captions)


@pytest.mark.parametrize("script,words,captions", CASES)
def test_legacy_word_timeline_across_script_lines_keeps_subtitles(
    tmp_path, script, words, captions
):
    subtitle_file = tmp_path / "subtitle.srt"

    voice.create_subtitle(_legacy_sub_maker(words), script, str(subtitle_file))

    assert subtitle_file.read_text(encoding="utf-8") == _srt(captions)


def test_word_across_script_lines_with_a_pause_tag(tmp_path):
    script = (
        "On July 20, 1969, two astronauts landed on the Moon. [pause: 1s] "
        "Millions of people watched it live on TV."
    )
    # Each part is spoken on its own; Edge TTS returns its words and audio.
    parts = {
        "On July 20, 1969, two astronauts landed on the Moon.": (MOON_WORDS, 5.35),
        "Millions of people watched it live on TV.": (
            [
                ("Millions", 0.1, 0.55),
                ("of", 0.5625, 0.65),
                ("people", 0.6625, 1.0),
                ("watched", 1.0125, 1.3375),
                ("it", 1.35, 1.4375),
                ("live", 1.45, 1.7),
                ("on", 1.7125, 1.85),
                ("TV", 1.8625, 2.3875),
            ],
            3.26,
        ),
    }

    def edge_tts(text, voice_name, voice_rate, voice_file):
        words, duration = parts[text]
        with wave.open(voice_file, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(bytes(2 * round(duration * 24000)))
        return _edge_sub_maker(words)

    with patch.object(voice, "azure_tts_v1", side_effect=edge_tts):
        sub_maker = voice.tts(
            script, "en-US-JennyNeural-Female", 1.0, str(tmp_path / "audio.mp3")
        )
    subtitle_file = tmp_path / "subtitle.srt"
    voice.create_subtitle(sub_maker, script, str(subtitle_file))

    # The second part starts after 5.35 s of speech and the 1 s pause.
    assert subtitle_file.read_text(encoding="utf-8") == _srt(
        [
            *MOON_CAPTIONS,
            ("00:00:06,450 --> 00:00:08,738", "Millions of people watched it live on TV"),
        ]
    )


def test_lines_are_kept_when_the_words_do_not_spell_the_script(tmp_path):
    # Edge TTS can return Arabic words in other letter forms or with a tatweel,
    # which the line matching accepts. These words do not spell the script
    # exactly, so no lines are joined and each sentence keeps its subtitle.
    tatweel = chr(0x0640)
    script = "أهلاً وسهلاً بك في المدرسة؟ هذا اختبار رائع، شكراً لك."
    words = [
        f"اه{tatweel}لا",
        "وسهلا",
        "بك",
        "في",
        "المدرسه",
        "هذا",
        "اختبار",
        "رائع",
        "شكرا",
        "لك",
    ]
    subtitle_file = tmp_path / "subtitle.srt"

    voice.create_subtitle(
        _edge_sub_maker(
            (word, 0.1 + index * 0.5, 0.5 + index * 0.5)
            for index, word in enumerate(words)
        ),
        script,
        str(subtitle_file),
    )

    assert subtitle_file.read_text(encoding="utf-8") == _srt(
        [
            ("00:00:00,100 --> 00:00:02,500", "أهلاً وسهلاً بك في المدرسة"),
            ("00:00:02,600 --> 00:00:04,000", "هذا اختبار رائع"),
            ("00:00:04,100 --> 00:00:05,000", "شكراً لك"),
        ]
    )
