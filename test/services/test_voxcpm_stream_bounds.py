import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.config import config
from app.services import voice


def response_for(chunks):
    # Both interfaces let the unchanged parser exercise the same hostile bytes.
    return SimpleNamespace(iter_content=lambda **kw: iter(chunks), iter_lines=lambda **kw: (line for chunk in chunks for line in chunk.split(b"\n")))


def test_unterminated_sse_line_is_rejected_before_reading_more(monkeypatch):
    monkeypatch.setattr(voice, "_VOXCPM_SSE_MAX_EVENT_BYTES", 12, raising=False)
    def chunks():
        yield b"data: " + b"x" * 20
        raise AssertionError("must stop at the first oversized chunk")
    response = SimpleNamespace(iter_content=lambda **kw: chunks(), iter_lines=lambda **kw: chunks())
    with pytest.raises(ValueError, match="size limit"):
        list(voice._iter_voxcpm_sse_events(response))


def test_multiline_event_cannot_bypass_aggregate_limit(monkeypatch):
    monkeypatch.setattr(voice, "_VOXCPM_SSE_MAX_EVENT_BYTES", 32, raising=False)
    with pytest.raises(ValueError, match="size limit"):
        list(voice._iter_voxcpm_sse_events(response_for([b'data: {"value":\ndata: "' + b"x" * 24 + b'"}\n\n'])))


def test_utf8_fragmented_multiline_crlf_and_trailing_events(monkeypatch):
    monkeypatch.setattr(voice, "_VOXCPM_SSE_MAX_EVENT_BYTES", 256, raising=False)
    content = ': keepalive\r\nevent: speech\r\ndata: {"type":"speech.audio.delta",\r\ndata: "note":"é"}\r\n\r\ndata: {"type":"speech.audio.done"}'.encode("utf-8")
    split = content.index(b"\xc3") + 1
    assert list(voice._iter_voxcpm_sse_events(response_for([content[:split], content[split:]]))) == [{"type":"speech.audio.delta", "note":"é"}, {"type":"speech.audio.done"}]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_sse_line_endings_at_every_transport_split(monkeypatch, ending):
    monkeypatch.setattr(voice, "_VOXCPM_SSE_MAX_EVENT_BYTES", 256)
    content = ending.join([
        b": keepalive",
        b'event: speech',
        b'data: {"type":"speech.audio.delta",',
        'data: "note":"é"}'.encode("utf-8"),
        b"",
        b'data: {"type":"speech.audio.done"}',
        b"",
        b"",
    ])
    expected = [{"type": "speech.audio.delta", "note": "é"},
                {"type": "speech.audio.done"}]
    for split in range(len(content) + 1):
        chunks = [content[:split], b"", content[split:]]
        assert list(voice._iter_voxcpm_sse_events(response_for(chunks))) == expected
    assert list(voice._iter_voxcpm_sse_events(
        response_for([content[i:i + 1] for i in range(len(content))])
    )) == expected


def test_split_crlf_does_not_dispatch_a_multiline_event_early():
    chunks = [b'data: {"type":\r', b"", b'\ndata: "speech.audio.done"}\r', b'\n\r', b'\n']
    assert list(voice._iter_voxcpm_sse_events(response_for(chunks))) == [
        {"type": "speech.audio.done"}
    ]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_line_ending_variants_keep_the_aggregate_event_limit(monkeypatch, ending):
    monkeypatch.setattr(voice, "_VOXCPM_SSE_MAX_EVENT_BYTES", 32)
    content = ending.join([b'data: {"value":', b'data: "' + b"x" * 24 + b'"}', b"", b""])
    with pytest.raises(ValueError, match="size limit"):
        list(voice._iter_voxcpm_sse_events(response_for([content])))


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_line_endings_through_real_chunked_http(ending):
    body = ending.join([
        b'data: {"type":"speech.audio.delta",',
        'data: "note":"é"}'.encode("utf-8"),
        b"",
        b'data: {"type":"speech.audio.done"}',
        b"",
        b"",
    ])

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            for byte in body:
                self.wfile.write(b"1\r\n" + bytes([byte]) + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with voice.requests.get(
            f"http://127.0.0.1:{server.server_port}/events", stream=True, timeout=5
        ) as response:
            assert list(voice._iter_voxcpm_sse_events(response)) == [
                {"type": "speech.audio.delta", "note": "é"},
                {"type": "speech.audio.done"},
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_assembled_audio_limit_stops_decode_and_preserves_previous_file(monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "_VOXCPM_TTS_MAX_AUDIO_BYTES", 5, raising=False)
    monkeypatch.setattr(config, "voxcpm", {"api_key":"test", "model_id":"test"})
    read_past_limit = Mock()
    def chunks():
        for audio in [b"123", b"456"]:
            yield ("data: " + json.dumps({"type":"speech.audio.delta", "audio":base64.b64encode(audio).decode()}) + "\n\n").encode()
        read_past_limit()
        yield b'data: {"type":"speech.audio.done"}\n\n'
    response = SimpleNamespace(status_code=200, close=Mock(), iter_content=lambda **kw:chunks(), iter_lines=lambda **kw:(line for chunk in chunks() for line in chunk.split(b"\n")))
    post=Mock(return_value=response)
    monkeypatch.setattr(voice.requests,"post",post)
    decode=Mock(side_effect=AssertionError("oversized audio must not decode"))
    monkeypatch.setattr("pydub.AudioSegment.from_file",decode)
    target = tmp_path / "previous.mp3"
    target.write_bytes(b"last good narration")
    assert voice.voxcpm_tts("hello", "default", str(target)) is None
    post.assert_called_once()
    response.close.assert_called_once()
    decode.assert_not_called()
    read_past_limit.assert_not_called()
    assert target.read_bytes()==b"last good narration"
