import base64
import json
from unittest.mock import patch

import pytest
import requests

from app.services import sonilo


class ChunkedResponse(requests.Response):
    def __init__(self, chunks):
        super().__init__()
        self.chunks = chunks
        self.consumed = 0

    def iter_content(self, chunk_size=1, decode_unicode=False):
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk


@pytest.mark.parametrize("terminated", [True, False])
def test_oversized_sonilo_event_rejected_before_json_or_entire_response(tmp_path, terminated):
    limit = 64
    # Last chunk must not be consumed: even an unterminated line is bounded.
    response = ChunkedResponse([b"x" * 33, b"x" * 33 + (b"\n" if terminated else b""), b"tail"])
    with (
        patch.object(sonilo, "MAX_STREAM_EVENT_BYTES", limit, create=True),
        patch.object(sonilo, "_parse_event") as parse,
        pytest.raises(sonilo.SoniloError, match="event.*limit"),
    ):
        sonilo._stream_audio(response, str(tmp_path / "staged.m4a"))
    parse.assert_not_called()
    assert response.consumed == 2


def test_sonilo_split_and_multiple_events_preserve_audio(tmp_path):
    audio = b"fixture-audio"
    event = json.dumps({"type": "audio_chunk", "data": base64.b64encode(audio).decode()}).encode()
    complete = b'{"type":"complete"}'
    response = ChunkedResponse([event[:10], event[10:] + b"\r\n\n" + complete[:5], complete[5:]])
    target = tmp_path / "staged.m4a"
    assert sonilo._stream_audio(response, str(target)) == (len(audio), "")
    assert target.read_bytes() == audio
