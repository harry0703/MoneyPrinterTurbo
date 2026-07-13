import io
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from loguru import logger
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import bgm


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _valid_wav_bytes() -> bytes:
    """生成一个很短的标准 WAV，避免测试依赖仓库外部音频或系统录音文件。"""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 800)
    return output.getvalue()


class TestWebuiBackgroundMusic(unittest.TestCase):
    def _open_custom_bgm_panel(self):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30).run()
        source_select = next(
            item for item in app.selectbox if item.label == "背景音乐来源"
        )
        source_select.set_value("自定义背景音乐").run()
        return app

    @staticmethod
    def _uploader(app):
        return next(item for item in app.file_uploader if item.label == "上传背景音乐")

    def test_invalid_audio_shows_error_without_ready_state_or_player(self):
        app = self._open_custom_bgm_panel()
        with patch.object(logger, "warning") as warning:
            self._uploader(app).set_value(
                ("invalid.m4a", b"not-a-decodable-audio-file", "audio/mp4")
            ).run()
            # 非法文件留在上传控件时，音量调整会触发 Streamlit rerun。缓存命中
            # 只能重绘错误，不能重复执行校验或重复记录 warning。
            next(
                item for item in app.selectbox if item.label == "背景音乐音量"
            ).set_value(0.4).run()

        rejection_logs = [
            call
            for call in warning.call_args_list
            if "WebUI background music validation rejected" in str(call)
        ]
        self.assertEqual([str(item.value) for item in app.exception], [])
        self.assertTrue(any("有效" in item.value for item in app.error))
        self.assertEqual(
            [item.value for item in app.info if "背景音乐已就绪" in item.value],
            [],
        )
        self.assertEqual(len(app.get("audio")), 0)
        self.assertEqual(len(rejection_logs), 1)

    def test_valid_audio_shows_ready_state_and_reuses_validation_cache(self):
        app = self._open_custom_bgm_panel()
        self._uploader(app).set_value(
            ("valid.wav", _valid_wav_bytes(), "audio/wav")
        ).run()

        # 首次校验通过后，把服务函数改成显式失败；如果音量 rerun 错误地再次
        # 调用 FFmpeg，AppTest 会收到 AssertionError，从而稳定保护缓存行为。
        with patch.object(
            bgm,
            "validate_bgm_upload",
            side_effect=AssertionError("validation repeated during rerun"),
        ):
            next(
                item for item in app.selectbox if item.label == "背景音乐音量"
            ).set_value(0.4).run()

        self.assertEqual([str(item.value) for item in app.exception], [])
        self.assertEqual([item.value for item in app.error], [])
        self.assertEqual(
            [item.value for item in app.info if "背景音乐已就绪" in item.value],
            ["背景音乐已就绪: valid.wav"],
        )
        self.assertEqual(len(app.get("audio")), 1)

    def test_service_failure_is_not_reported_as_invalid_user_audio(self):
        app = self._open_custom_bgm_panel()
        with patch.object(
            bgm,
            "validate_bgm_upload",
            side_effect=bgm.BgmServiceError("FFmpeg unavailable"),
        ):
            self._uploader(app).set_value(
                ("valid.wav", _valid_wav_bytes(), "audio/wav")
            ).run()

        self.assertEqual([str(item.value) for item in app.exception], [])
        self.assertTrue(any("无法校验" in item.value for item in app.error))
        self.assertEqual(len(app.get("audio")), 0)


if __name__ == "__main__":
    unittest.main()
