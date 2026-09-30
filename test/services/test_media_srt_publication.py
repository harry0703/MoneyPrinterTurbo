import builtins
from types import SimpleNamespace

import pytest

from app.services import subtitle, task, voice


CUE = '1\n00:00:00,000 --> 00:00:01,000\nOld transcript\n\n'


def test_edge_generation_does_not_reuse_previous_task_captions(tmp_path, monkeypatch):
    destination = tmp_path / 'subtitle.srt'
    destination.write_text(CUE, encoding='utf-8')
    monkeypatch.setattr(task.utils, 'task_dir', lambda *args, **kwargs: str(tmp_path))
    monkeypatch.setitem(task.config.app, 'subtitle_provider', 'edge')
    params = SimpleNamespace(subtitle_enabled=True, subtitle_display_mode='sentence')
    maker = SimpleNamespace(cues=[], subs=[], offset=[])

    assert task.generate_subtitle('retry', params, 'Different narration.', maker, 'audio.mp3') == ''
    assert destination.read_text(encoding='utf-8') == CUE
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize('writer', ['voice', 'correction', 'whisper'])
def test_failed_caption_write_preserves_complete_existing_srt(tmp_path, monkeypatch, writer):
    destination = tmp_path / 'subtitle.srt'
    destination.write_text(CUE, encoding='utf-8')
    original = builtins.open

    class PartialWrite:
        def __init__(self, file):
            self.file = file
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.file.close()
        def write(self, text):
            self.file.write(text[:5])
            self.file.flush()
            raise OSError('disk full during caption write')

    def open_file(filename, mode='r', *args, **kwargs):
        file = original(filename, mode, *args, **kwargs)
        if mode == 'w' and str(filename).endswith('.srt'):
            return PartialWrite(file)
        return file

    monkeypatch.setattr(builtins, 'open', open_file)
    if writer == 'voice':
        assert voice._write_subtitle_items([CUE], str(destination)) is False
    elif writer == 'correction':
        with pytest.raises(OSError):
            subtitle.correct(str(destination), 'Changed transcript.')
    else:
        word = SimpleNamespace(word='Changed', start=0.0, end=1.0)
        segment = SimpleNamespace(words=[word], text='Changed', start=0.0, end=1.0)
        info = SimpleNamespace(language='en', language_probability=1.0)
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: (iter([segment]), info))
        monkeypatch.setattr(subtitle, 'WhisperModel', object())
        monkeypatch.setattr(subtitle, 'model', model)
        with pytest.raises(OSError):
            subtitle.create('local-audio.mp3', str(destination))
    assert destination.read_text(encoding='utf-8') == CUE
    assert list(tmp_path.iterdir()) == [destination]


def test_subtitle_cleanup_error_does_not_hide_primary_write_failure(tmp_path, monkeypatch):
    from app.utils import subtitle_writer

    destination = tmp_path / 'subtitle.srt'
    destination.write_text(CUE, encoding='utf-8')
    staged = None

    def cannot_cleanup(*args):
        raise PermissionError('temporary captions are busy')

    monkeypatch.setattr(subtitle_writer.os, 'remove', cannot_cleanup)
    with pytest.raises(OSError, match='disk full during caption write'):
        with subtitle_writer.staged_subtitle_file(str(destination)) as staged:
            with builtins.open(staged, 'w', encoding='utf-8') as output:
                output.write('partial captions')
            raise OSError('disk full during caption write')
    assert destination.read_text(encoding='utf-8') == CUE
    assert staged != str(destination)
    with builtins.open(staged, encoding='utf-8') as output:
        assert output.read() == 'partial captions'
