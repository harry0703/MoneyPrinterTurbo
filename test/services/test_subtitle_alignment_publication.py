"""An incomplete correction must retain the transcription through publication."""

from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import task


def test_whisper_sentence_publication_preserves_timed_transcription(tmp_path):
    transcript = (
        "1\n00:00:00,100 --> 00:00:02,000\nIt runs as you so it can change memory\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nThat is the gate\n\n"
    )
    script = "It runs as you, so it can change memory. That is the gate."
    params = VideoParams(
        video_subject="alignment",
        subtitle_enabled=True,
        subtitle_display_mode="sentence",
    )

    def transcribe(audio_file, subtitle_file, word_level=False):
        assert not word_level
        Path(subtitle_file).write_text(transcript, encoding="utf-8")

    with (
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.config, "app", dict(task.config.app, subtitle_provider="whisper")
        ),
        patch.object(task.subtitle, "create", side_effect=transcribe),
    ):
        result = task.generate_subtitle(
            "alignment", params, script, None, str(tmp_path / "audio.mp3")
        )

    assert result == str(tmp_path / "subtitle.srt")
    assert Path(result).read_text(encoding="utf-8") == transcript
    assert task.subtitle.file_to_subtitles(result)[-1] == (
        2, "00:00:02,500 --> 00:00:04,000", "That is the gate"
    )
