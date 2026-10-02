from unittest.mock import patch
import wave

import numpy as np
import pytest
from edge_tts import SubMaker
import subprocess

from app.models.schema import AudioRequest, VideoParams
from app.services import task as tm
from app.services.state import MemoryState


def _write_narration(voice_file, **kwargs):
    # Replace the provider network boundary with a real one-second PCM signal.
    samples = np.rint(3000 * np.sin(2 * np.pi * 440 * np.arange(24000) / 24000)).astype('<i2')
    with wave.open(voice_file, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(samples.tobytes())
    maker = SubMaker()
    maker.duration = 1.0
    return maker


def _rms(filename):
    decoded = subprocess.run([tm.utils.get_ffmpeg_binary(), '-nostdin', '-v', 'error', '-i', str(filename), '-f', 's16le', '-ac', '1', '-ar', '24000', 'pipe:1'], check=True, capture_output=True)
    frames = np.frombuffer(decoded.stdout, dtype='<i2').astype(float) / 32768
    return float(np.sqrt(np.mean(frames ** 2))), len(frames) / 24000


@pytest.mark.parametrize('gain', [0.0, 0.5, 2.0])
def test_audio_only_export_applies_requested_volume_to_real_pcm(tmp_path, gain):
    params = AudioRequest(video_script='A narration.', voice_volume=gain)
    with (patch.object(tm.sm, 'state', MemoryState()),
          patch.object(tm.utils, 'task_dir', return_value=str(tmp_path)),
          patch.object(tm.utils, 'check_ffmpeg_ready', return_value=True),
          patch.object(tm, 'save_script_data'),
          patch.object(tm, 'generate_terms', return_value=['narration']),
          patch.object(tm.voice, 'tts', side_effect=_write_narration)):
        result = tm.start('audio-volume', params, stop_at='audio')
    assert 'audio_file' in result, result
    actual, duration = _rms(result['audio_file'])
    expected = 3000 / 32768 / np.sqrt(2) * gain
    assert actual == pytest.approx(expected, abs=0.004)
    assert duration == pytest.approx(1.0, abs=0.1)


def test_full_video_keeps_unscaled_narration_for_its_existing_mixer(tmp_path):
    params = VideoParams(video_subject='Narration', video_script='A narration.', voice_volume=2.0, subtitle_enabled=False)
    observed = []
    def render(*args):
        observed.append(_rms(args[3])[0])
        return ['video.mp4'], ['combined.mp4'], []
    with (patch.object(tm.sm, 'state', MemoryState()),
          patch.object(tm.utils, 'task_dir', return_value=str(tmp_path)),
          patch.object(tm.utils, 'check_ffmpeg_ready', return_value=True),
          patch.object(tm, 'save_script_data'),
          patch.object(tm, 'generate_terms', return_value=['narration']),
          patch.object(tm.voice, 'tts', side_effect=_write_narration),
          patch.object(tm, 'generate_subtitle', return_value=''),
          patch.object(tm, 'get_video_materials', return_value=['material.mp4']),
          patch.object(tm, 'generate_final_videos', side_effect=render),
          patch.object(tm.upload_post.upload_post_service, 'is_configured', return_value=False)):
        result = tm.start('video-volume', params)
    assert result['videos'] == ['video.mp4']
    assert observed == pytest.approx([3000 / 32768 / np.sqrt(2)], abs=0.004)


@pytest.mark.parametrize("filename", ["original.wav", "audio.mp3"])
def test_custom_narration_export_preserves_input_bytes_on_retry(tmp_path, filename):
    source = tmp_path / filename
    _write_narration(str(source))
    original = source.read_bytes()
    task_dir = tmp_path
    params = VideoParams(video_subject='Narration', video_script='A narration.', voice_volume=0.5,
                         custom_audio_file=str(source))
    with (patch.object(tm.sm, 'state', MemoryState()),
          patch.object(tm.utils, 'task_dir', return_value=str(task_dir)),
          patch.object(tm.utils, 'check_ffmpeg_ready', return_value=True),
          patch.object(tm, 'save_script_data'),
          patch.object(tm, 'generate_terms', return_value=['narration'])):
        results = [tm.start('custom-volume', params, stop_at='audio', allow_server_file_input=True) for _ in range(2)]
    assert source.read_bytes() == original
    for result in results:
        assert result['audio_file'] != str(source)
        actual, duration = _rms(result['audio_file'])
        assert actual == pytest.approx(3000 / 32768 / np.sqrt(2) * 0.5, abs=0.004)
        assert duration == pytest.approx(1.0, abs=0.1)
