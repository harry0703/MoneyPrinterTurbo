import shutil
import subprocess
import sys
import weakref
from datetime import timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import config
from app.services import voice


@pytest.mark.parametrize("outcome,strict,nested", [("completed", True, False), ("completed", True, True), ("completed", False, False), ("cancelled", False, False), ("error", False, False), ("empty", False, False)])
def test_public_azure_file_output_preserves_last_success(tmp_path, outcome, strict, nested):
    """Controlled documented SDK file/callback boundary; no real Azure call."""
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    complete = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.2", "-f", "mp3", "-"], capture_output=True, check=True).stdout
    output = tmp_path / "nested" / "narration.mp3" if nested else tmp_path / "narration.mp3"
    previous = b"previous-successful-export"
    if not nested:
        output.write_bytes(previous)
    configured = []
    open_outputs = set()
    real_remove = voice.os.remove

    def remove_after_sdk_release(path):
        assert str(path) not in open_outputs, "SDK still owns the staged output"
        return real_remove(path)
    requests = []

    class AudioOutput:
        def __init__(self, filename=None, use_default_speaker=False):
            if strict and filename and use_default_speaker:
                raise ValueError("only one output argument may be selected")
            if not Path(filename).parent.is_dir():
                raise OSError("audio output parent does not exist")
            self.filename = filename
            self.output = open(filename, "wb")
            open_outputs.add(str(filename))
            configured.append(filename)

        def __del__(self):
            if hasattr(self, "output"):
                self.output.close()
                open_outputs.discard(str(self.filename))

    class SpeechConfig:
        def __init__(self, **_kwargs):
            pass

        def set_property(self, *_args, **_kwargs):
            pass

        def set_speech_synthesis_output_format(self, *_args):
            pass

    class Synthesizer:
        def __init__(self, audio_config, speech_config):
            self.audio_config = audio_config
            self.destination = Path(audio_config.filename)
            self.callback = None
            owner = weakref.ref(self)
            self.synthesis_word_boundary = SimpleNamespace(connect=lambda callback: setattr(owner(), "callback", callback))

        def speak_ssml_async(self, text):
            requests.append(text)

            def get():
                self.audio_config.output.write(complete if outcome == "completed" else b"" if outcome == "empty" else complete[:50])
                self.audio_config.output.flush()
                if outcome == "error":
                    raise OSError("controlled SDK failure after writing partial bytes")
                if self.callback and outcome == "completed":
                    self.callback(SimpleNamespace(text="Hello", duration=timedelta(seconds=0.2), audio_offset=0))
                return SimpleNamespace(reason="cancelled" if outcome == "cancelled" else "completed", cancellation_details=SimpleNamespace(reason="error", error_details="fixture"))
            return SimpleNamespace(get=get)

    sdk = ModuleType("azure.cognitiveservices.speech")
    sdk.audio = SimpleNamespace(AudioOutputConfig=AudioOutput)
    sdk.SpeechConfig = SpeechConfig
    sdk.SpeechSynthesizer = Synthesizer
    sdk.SessionEventArgs = object
    sdk.PropertyId = SimpleNamespace(SpeechServiceResponse_RequestWordBoundary="word")
    sdk.SpeechSynthesisOutputFormat = SimpleNamespace(Audio48Khz192KBitRateMonoMp3="mp3")
    sdk.ResultReason = SimpleNamespace(SynthesizingAudioCompleted="completed", Canceled="cancelled")
    sdk.CancellationReason = SimpleNamespace(Error="error")
    azure = ModuleType("azure")
    cognitive = ModuleType("azure.cognitiveservices")
    azure.cognitiveservices = cognitive
    cognitive.speech = sdk
    with patch.object(voice.os, "remove", side_effect=remove_after_sdk_release), patch.dict(sys.modules, {"azure": azure, "azure.cognitiveservices": cognitive, "azure.cognitiveservices.speech": sdk}), patch.dict(config.azure, {"speech_key": "fixture", "speech_region": "fixture"}):
        result = voice.azure_tts_v2("Hello", "en-US-AriaNeural-V2", str(output))
    if outcome == "completed":
        assert result is not None
        assert result.subs == ["Hello"]
        assert output.read_bytes() == complete
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"], capture_output=True, check=True)
    else:
        assert result is None
        assert output.read_bytes() == previous
    assert not open_outputs
    assert all(Path(path) != output for path in configured)
    assert list(output.parent.iterdir()) == [output]
    assert len(requests) == (3 if outcome in {"cancelled", "error"} else 1)
