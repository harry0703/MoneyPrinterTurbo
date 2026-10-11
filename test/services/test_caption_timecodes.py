"""Native caption publication and final rendering must retain spoken timecodes."""

import pytest
from edge_tts import SubMaker

from app.services import subtitle, voice


CAPTIONS = [
    "Jump to the recording.",
    "Jump to 00:01:23,456 in the recording.",
    "Show 00:01:23,456 --> 00:01:25,456 in the log.",
]


@pytest.mark.parametrize("text", CAPTIONS)
def test_speech_caption_publication_preserves_timecodes(tmp_path, text):
    maker = SubMaker()
    maker.feed({
        "type": "SentenceBoundary", "offset": 0,
        "duration": 8000000, "text": text,
    })
    destination = tmp_path / "speech.srt"
    voice.create_subtitle(maker, text, str(destination), word_level=True)

    assert destination.is_file()
    assert subtitle.file_to_subtitles(str(destination)) == [
        (1, "00:00:00,000 --> 00:00:00,800", text)
    ]
