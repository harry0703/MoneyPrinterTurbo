import pytest

from app.utils.subtitle_writer import write_subtitle_file


@pytest.mark.parametrize("content", ["Transcription failed --> retry later", "1\nstart --> end\nA caption\n"])
def test_arrow_prose_cannot_replace_existing_captions(tmp_path, content):
    destination = tmp_path / "captions.srt"
    original = "1\n00:00:00,000 --> 00:00:01,000\nExisting caption\n"
    destination.write_text(original, encoding="utf-8")
    assert write_subtitle_file(str(destination), content) is False
    assert destination.read_text(encoding="utf-8") == original
    assert list(tmp_path.iterdir()) == [destination]


def test_real_timing_header_can_publish_caption_text_containing_arrows(tmp_path):
    destination = tmp_path / "captions.srt"
    content = "1\n00:00:00,000 --> 00:00:01,000\nleft --> right\n"
    assert write_subtitle_file(str(destination), content) is True
    assert destination.read_text(encoding="utf-8") == content
