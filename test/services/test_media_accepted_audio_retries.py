from unittest.mock import Mock

from pydub import AudioSegment
import pytest
import requests

from app.services import voice


@pytest.fixture
def accepted_audio():
    response = requests.Response()
    response.status_code = 200
    with AudioSegment.silent(duration=200).export(format='mp3') as encoded:
        response._content = encoded.read()
    return response


def invoke(provider, output):
    if provider == 'siliconflow':
        return voice.siliconflow_tts('Hello world.', 'test-model', 'test-voice', 1.0, str(output))
    return voice._openai_compatible_tts(
        'test-provider', 'http://127.0.0.1:9999/v1', '', 'test-model', 'test-voice',
        'Hello world.', 1.0, str(output),
    )


@pytest.mark.parametrize('provider', ['siliconflow', 'compatible'])
def test_accepted_audio_publication_failure_does_not_repeat_post(tmp_path, monkeypatch, accepted_audio, provider):
    output = tmp_path / 'voice.mp3'
    output.write_bytes(b'previous complete narration')
    post = Mock(return_value=accepted_audio)
    monkeypatch.setattr(voice.requests, 'post', post)
    monkeypatch.setitem(voice.config.siliconflow, 'api_key', 'test-local-key')

    def cannot_publish(*args):
        raise OSError('destination is unavailable')

    monkeypatch.setattr(voice.os, 'replace', cannot_publish)
    assert invoke(provider, output) is None
    assert post.call_count == 1
    assert output.read_bytes() == b'previous complete narration'
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize('provider', ['siliconflow', 'compatible'])
def test_connect_timeout_keeps_existing_retry_and_success_policy(tmp_path, monkeypatch, accepted_audio, provider):
    output = tmp_path / 'voice.mp3'
    post = Mock(side_effect=[requests.ConnectTimeout('before connection'), accepted_audio])
    monkeypatch.setattr(voice.requests, 'post', post)
    monkeypatch.setitem(voice.config.siliconflow, 'api_key', 'test-local-key')

    assert invoke(provider, output) is not None
    assert post.call_count == 2
    assert voice.get_audio_duration(str(output)) > 0
    assert list(tmp_path.iterdir()) == [output]
