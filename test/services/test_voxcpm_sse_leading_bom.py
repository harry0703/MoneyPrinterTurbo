from types import SimpleNamespace

import pytest

from app.services import voice


@pytest.mark.parametrize('split', [1, 2, 3, 9])
def test_voxcpm_stream_keeps_first_event_after_utf8_bom(split):
    content = b'\xef\xbb\xbfdata: {"type":"speech.audio.delta","data":"YWJj"}\n\ndata: {"type":"speech.audio.done"}\n\n'
    response = SimpleNamespace(iter_content=lambda chunk_size: iter([content[:split], content[split:]]))
    assert list(voice._iter_voxcpm_sse_events(response)) == [
        {"type": "speech.audio.delta", "data": "YWJj"},
        {"type": "speech.audio.done"},
    ]
