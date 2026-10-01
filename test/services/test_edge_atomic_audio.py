import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import voice


@pytest.mark.parametrize("failure", ["no-audio", "no-timing", "interrupted"])
def test_edge_failure_preserves_previous_narration_and_cleans_staging(failure):
    def stream(_communicate, on_chunk, **_kwargs):
        if failure != "no-audio":
            on_chunk({"type": "audio", "data": b"partial-new-audio"})
        if failure == "interrupted":
            raise TimeoutError("lost stream")

    submaker = SimpleNamespace(get_srt=lambda: "" if failure == "no-timing" else "timing")
    with (
        tempfile.TemporaryDirectory() as temp_dir,
        patch.object(voice, "create_edge_tts_communicate"),
        patch.object(voice.edge_tts, "SubMaker", return_value=submaker),
        patch.object(voice, "stream_edge_tts_chunks", side_effect=stream),
    ):
        target = Path(temp_dir) / "voice.mp3"
        target.write_bytes(b"previous-good-audio")
        assert voice.azure_tts_v1("Hello", "en-US-AriaNeural-Female", 1.0, str(target)) is None
        assert target.read_bytes() == b"previous-good-audio"
        assert sorted(item.name for item in Path(temp_dir).iterdir()) == ["voice.mp3"]


def test_edge_success_replaces_narration_with_matching_submaker():
    submaker = SimpleNamespace(get_srt=lambda: "matching-new-timing")
    def stream(_communicate, on_chunk, **_kwargs):
        on_chunk({"type": "audio", "data": b"complete-new-audio"})
    with (
        tempfile.TemporaryDirectory() as temp_dir,
        patch.object(voice, "create_edge_tts_communicate"),
        patch.object(voice.edge_tts, "SubMaker", return_value=submaker),
        patch.object(voice, "stream_edge_tts_chunks", side_effect=stream),
    ):
        target = Path(temp_dir) / "voice.mp3"
        target.write_bytes(b"previous-good-audio")
        assert voice.azure_tts_v1("Hello", "en-US-AriaNeural-Female", 1.0, str(target)) is submaker
        assert target.read_bytes() == b"complete-new-audio"
        assert sorted(item.name for item in Path(temp_dir).iterdir()) == ["voice.mp3"]
