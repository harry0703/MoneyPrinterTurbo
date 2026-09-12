"""显式启用的真实服务测试；普通 CI 不需要安装或访问 Kokoro。

启动本机服务后，设置 MPT_KOKORO_TEST_BASE_URL=http://127.0.0.1:8880/v1
运行本文件。测试只合成短文本，不调用 LLM、素材平台或发布接口。
"""

import os

import pytest

from app.config import config
from app.services import voice


BASE_URL = os.environ.get("MPT_KOKORO_TEST_BASE_URL", "")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="requires an explicitly configured Kokoro test server")


@pytest.fixture
def live_config(monkeypatch):
    monkeypatch.setattr(config, "kokoro", {"base_url": BASE_URL, "api_key": "",
                                          "model_id": "kokoro", "voices": []})


def test_live_voice_discovery(live_config):
    options = voice.get_kokoro_voices(fallback=False)
    assert "kokoro:af_heart" in options
    assert "kokoro:zf_xiaobei" in options
    assert all(option.startswith("kokoro:") and "{" not in option for option in options)


@pytest.mark.parametrize("speaker, text", [
    ("af_heart", "Artificial intelligence is changing everyday life."),
    ("zf_xiaobei", "人工智能正在改变我们的生活。合理使用技术，让每个人受益。"),
    ("ff_siwis", "Bonjour ! L'intelligence artificielle nous aide à apprendre."),
    ("ef_dora", "La inteligencia artificial mejora nuestra vida cotidiana."),
    ("if_sara", "L'intelligenza artificiale migliora la vita di ogni giorno."),
    ("pf_dora", "A inteligência artificial melhora a nossa vida."),
    ("hf_alpha", "नमस्ते। कृत्रिम बुद्धिमत्ता हमारे जीवन को बेहतर बनाती है।"),
])
def test_live_audio_and_subtitles(live_config, tmp_path, speaker, text):
    output = tmp_path / "audio.mp3"
    maker = voice.tts(text, f"kokoro:{speaker}", 1, str(output))
    assert maker is not None
    assert output.stat().st_size > 100
    assert voice.get_audio_duration(str(output)) > 0
    subtitle = tmp_path / "subtitle.srt"
    voice.create_subtitle(maker, text, str(subtitle))
    assert "-->" in subtitle.read_text(encoding="utf-8")
    assert sorted(path.suffix for path in tmp_path.iterdir()) == [".mp3", ".srt"]
