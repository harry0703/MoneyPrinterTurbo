import asyncio
import base64
import os
import shutil
import unittest
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils import utils
from app.services import voice as vs
from app.services import task as task_service
from pydub import AudioSegment

temp_dir = utils.storage_dir("temp")

text_en = """
What is the meaning of life? 
This question has puzzled philosophers, scientists, and thinkers of all kinds for centuries. 
Throughout history, various cultures and individuals have come up with their interpretations and beliefs around the purpose of life. 
Some say it's to seek happiness and self-fulfillment, while others believe it's about contributing to the welfare of others and making a positive impact in the world. 
Despite the myriad of perspectives, one thing remains clear: the meaning of life is a deeply personal concept that varies from one person to another. 
It's an existential inquiry that encourages us to reflect on our values, desires, and the essence of our existence.
"""

text_zh = """
预计未来3天深圳冷空气活动频繁，未来两天持续阴天有小雨，出门带好雨具；
10-11日持续阴天有小雨，日温差小，气温在13-17℃之间，体感阴凉；
12日天气短暂好转，早晚清凉；
"""

voice_rate=1.0
voice_volume=1.0
RUN_INTEGRATION_TESTS = os.environ.get("MPT_RUN_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}
                    
class TestVoiceService(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def tearDown(self):
        self.loop.close()

    def test_get_all_azure_voices(self):
        voices = vs.get_all_azure_voices()
        # 数据已从内联字符串迁移到 azure_voices.json，确保仍能完整加载
        self.assertEqual(len(voices), 331)
        # 结果应为 "Name-Gender" 格式且已排序
        self.assertEqual(voices, sorted(voices))
        for v in voices:
            self.assertTrue(v.endswith("-Male") or v.endswith("-Female"))

    def test_get_all_azure_voices_filtered(self):
        filtered = vs.get_all_azure_voices(filter_locals=["zh-CN", "en-US"])
        self.assertTrue(len(filtered) > 0)
        self.assertTrue(
            all(v.startswith(("zh-CN", "en-US")) for v in filtered)
        )

    def test_get_gemini_voices_matches_documented_catalog(self):
        voices = vs.get_gemini_voices()

        self.assertEqual(len(voices), 30)
        self.assertEqual(
            [name for name, _style in vs.GEMINI_TTS_VOICES],
            [
                "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda",
                "Orus", "Aoede", "Callirrhoe", "Autonoe", "Enceladus",
                "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome",
                "Algenib", "Rasalgethi", "Laomedeia", "Achernar", "Alnilam",
                "Schedar", "Gacrux", "Pulcherrima", "Achird",
                "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager",
                "Sulafat",
            ],
        )
        self.assertIn("gemini:Achernar-Soft", voices)
        self.assertIn("gemini:Sulafat-Warm", voices)
        self.assertFalse(any("Atlas" in voice for voice in voices))

    def test_parse_gemini_voice_name_supports_new_and_legacy_labels(self):
        self.assertEqual(
            vs.parse_gemini_voice_name("gemini:Achernar-Soft"), "Achernar"
        )
        self.assertEqual(vs.parse_gemini_voice_name("gemini:Charon-Male"), "Charon")
        self.assertEqual(vs.parse_gemini_voice_name("Charon-Male"), "")

    def test_no_voice_tts_generates_silent_audio_and_subtitle_timeline(self):
        """
        无配音模式不调用任何外部 TTS provider，只生成静音音频作为时间轴占位。
        这里 mock FFmpeg，验证请求参数、输出文件和 legacy 字幕结构都符合后续
        视频合成链路的预期。
        """

        def fake_run(command, capture_output, text, check):
            self.assertEqual(command[0], "/tmp/fake-ffmpeg")
            self.assertIn("anullsrc=r=44100:cl=mono", command)
            Path(command[-1]).write_bytes(b"fake-silent-mp3")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.utils,
            "get_ffmpeg_binary",
            return_value="/tmp/fake-ffmpeg",
        ), patch.object(vs.subprocess, "run", side_effect=fake_run):
            voice_file = str(Path(tmp_dir) / "silent.mp3")
            sub_maker = vs.tts(
                text="第一句话。Second sentence.",
                voice_name=vs.NO_VOICE_NAME,
                voice_rate=1.0,
                voice_file=voice_file,
            )

            self.assertEqual(Path(voice_file).read_bytes(), b"fake-silent-mp3")

        self.assertIsNotNone(sub_maker)
        self.assertEqual(getattr(sub_maker, "subs", []), ["第一句话", "Second sentence"])
        self.assertEqual(len(getattr(sub_maker, "offset", [])), 2)
        self.assertGreater(vs.get_audio_duration(sub_maker), 0)

    def test_get_audio_duration_accepts_non_mp3_files(self):
        """
        自定义音频（custom_audio_file）常见为 m4a/wav/aac 等非 mp3 格式。
        get_audio_duration 不应因扩展名不是 .mp3 就报 "Invalid target type" 并返回 0，
        而应交给 moviepy(ffmpeg) 读取真实时长。
        """
        for path in ("custom-audio.m4a", "voice.wav", "clip.aac"):
            with patch.object(vs.os.path, "exists", return_value=True), \
                    patch.object(vs, "AudioFileClip") as mock_afc:
                mock_afc.return_value.__enter__.return_value.duration = 28.89
                self.assertEqual(vs.get_audio_duration(path), 28.89)
                mock_afc.assert_called_once_with(path)

    def test_get_audio_duration_missing_file_returns_zero(self):
        """音频文件不存在时安全返回 0，而不是抛异常或读取失败。"""
        with patch.object(vs.os.path, "exists", return_value=False):
            self.assertEqual(vs.get_audio_duration("does-not-exist.m4a"), 0.0)

    def test_no_voice_alias_none_is_supported_temporarily(self):
        """
        兼容 PR #981 曾使用过的 none sentinel，避免少量直接调用 API 的用户
        升级后立即失效。新 UI 和新代码仍统一使用 no-voice。
        """
        self.assertTrue(vs.is_no_voice("none"))
        self.assertTrue(vs.is_no_voice(vs.NO_VOICE_NAME))
        self.assertFalse(vs.is_no_voice(""))

    def test_no_voice_duration_estimates_non_ascii_languages(self):
        """
        无配音没有真实 TTS 音频，只能根据脚本文字估算阅读时间。俄语、阿拉伯语、
        日文假名、韩文等非 ASCII 文本也必须参与估算，不能都落到最短 3 秒。
        """
        russian_text = (
            "Это длинный тестовый сценарий без озвучки. "
            "Он должен получить достаточно времени для чтения субтитров."
        )
        arabic_text = "هذا اختبار طويل بدون تعليق صوتي، ويجب أن يحصل على وقت كاف لقراءة الترجمة."

        self.assertGreater(vs.estimate_no_voice_duration(russian_text), 8.0)
        self.assertGreater(vs.estimate_no_voice_duration(arabic_text), 8.0)

    def test_generate_silent_audio_rejects_missing_output_file(self):
        """
        即使 FFmpeg 进程返回成功，也要确认输出文件真实存在且非空。这样可以把
        异常收敛在 TTS 阶段，而不是拖到后续视频合成阶段才暴露。
        """
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.utils,
            "get_ffmpeg_binary",
            return_value="/tmp/fake-ffmpeg",
        ), patch.object(
            vs.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ):
            voice_file = str(Path(tmp_dir) / "missing-silent.mp3")

            self.assertFalse(vs.generate_silent_audio(3.0, voice_file))

    def test_empty_voice_name_does_not_enable_no_voice_mode(self):
        """
        空 voice 通常意味着配置缺失或接口参数错误，不能自动切到无配音模式。
        否则用户填错 TTS 配置时也会得到一个“成功”的静音视频，定位成本更高。
        """
        sentinel = object()

        with patch.object(vs, "azure_tts_v1", return_value=sentinel) as azure_tts_v1:
            result = vs.tts(
                text="empty voice should still use the default TTS path",
                voice_name="",
                voice_rate=1.0,
                voice_file="/tmp/empty-voice.mp3",
            )

        self.assertIs(result, sentinel)
        azure_tts_v1.assert_called_once()

    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS,
        "MPT_RUN_INTEGRATION_TESTS not set",
    )
    def test_siliconflow(self):
        # SiliconFlow 的 API Key 存在 [siliconflow].api_key 中，运行时代码也是从
        # config.siliconflow 读取；这里必须使用同一配置源，避免正确配置凭据时
        # 测试仍然被误跳过。
        if not vs.config.siliconflow.get("api_key"):
            self.skipTest("siliconflow_api_key is not configured")

        voice_name = "siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male"
        voice_name = vs.parse_voice_name(voice_name)
        
        async def _do():
            parts = voice_name.split(":")
            if len(parts) >= 3:
                model = parts[1]
                # 移除性别后缀，例如 "alex-Male" -> "alex"
                voice_with_gender = parts[2]
                voice = voice_with_gender.split("-")[0]
                # 构建完整的voice参数，格式为 "model:voice"
                full_voice = f"{model}:{voice}"
                voice_file = f"{temp_dir}/tts-siliconflow-{voice}.mp3"
                subtitle_file = f"{temp_dir}/tts-siliconflow-{voice}.srt"
                sub_maker = vs.siliconflow_tts(
                    text=text_zh, model=model, voice=full_voice, voice_file=voice_file, voice_rate=voice_rate, voice_volume=voice_volume
                )
                if not sub_maker:
                    self.fail("siliconflow tts failed")
                vs.create_subtitle(sub_maker=sub_maker, text=text_zh, subtitle_file=subtitle_file)
                audio_duration = vs.get_audio_duration(sub_maker)
                print(f"voice: {voice_name}, audio duration: {audio_duration}s")
            else:
                self.fail("siliconflow invalid voice name")

        self.loop.run_until_complete(_do())
    
    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS,
        "MPT_RUN_INTEGRATION_TESTS not set",
    )
    def test_azure_tts_v1(self):
        voice_name = "zh-CN-XiaoyiNeural-Female"
        voice_name = vs.parse_voice_name(voice_name)
        print(voice_name)
        
        voice_file = f"{temp_dir}/tts-azure-v1-{voice_name}.mp3"
        subtitle_file = f"{temp_dir}/tts-azure-v1-{voice_name}.srt"
        sub_maker = vs.azure_tts_v1(
            text=text_zh, voice_name=voice_name, voice_file=voice_file, voice_rate=voice_rate
        )
        if not sub_maker:
            self.fail("azure tts v1 failed")
        vs.create_subtitle(sub_maker=sub_maker, text=text_zh, subtitle_file=subtitle_file)
        audio_duration = vs.get_audio_duration(sub_maker)
        print(f"voice: {voice_name}, audio duration: {audio_duration}s")

    def test_azure_tts_v1_supports_legacy_edge_tts_without_boundary(self):
        """
        验证 Azure TTS V1 在旧版 edge_tts 依赖残留时仍可继续工作。

        这个回归场景对应 Windows 便携包更新失败后，现场环境还停留在旧版
        edge_tts 的情况：
        1. `Communicate.__init__()` 不接受 `boundary`
        2. 只有异步 `stream()`，没有 `stream_sync()`
        """

        class _LegacyCommunicate:
            def __init__(self, text, voice, rate="+0%"):
                self.text = text
                self.voice = voice
                self.rate = rate

            async def stream(self):
                yield {"type": "audio", "data": b"legacy-audio"}
                yield {
                    "type": "WordBoundary",
                    "offset": 0,
                    "duration": 10000000,
                    "text": "legacy",
                }

        class _FakeSubMaker:
            def __init__(self):
                self.events = []

            def feed(self, chunk):
                self.events.append(chunk)

            def get_srt(self):
                if not self.events:
                    return ""
                return "1\n00:00:00,000 --> 00:00:01,000\nlegacy\n"

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.edge_tts, "Communicate", _LegacyCommunicate
        ), patch.object(vs.edge_tts, "SubMaker", _FakeSubMaker):
            voice_file = str(Path(tmp_dir) / "legacy-edge-tts.mp3")
            sub_maker = vs.azure_tts_v1(
                text="legacy edge tts compatibility",
                voice_name="zh-CN-XiaoyiNeural-Female",
                voice_file=voice_file,
                voice_rate=1.0,
            )

            self.assertIsNotNone(sub_maker)
            self.assertEqual(Path(voice_file).read_bytes(), b"legacy-audio")
            self.assertEqual(len(sub_maker.events), 1)
            self.assertEqual(sub_maker.events[0]["type"], "WordBoundary")

    def test_azure_tts_v1_times_out_hanging_stream_sync(self):
        """
        验证 Azure TTS V1 在 edge_tts 同步流卡住时能够快速失败。

        真实现场里，网络异常、服务端限流、voice 语言与文本不匹配时，
        `stream_sync()` 可能长时间不返回，导致 WebUI 任务只停在
        `start, voice name...`。这里用阻塞的 fake stream 复现该场景，
        确认超时保护会让函数结束并返回 None。
        """

        class _HangingCommunicate:
            def __init__(self, text, voice, rate="+0%", boundary=None):
                self.text = text
                self.voice = voice
                self.rate = rate
                self.boundary = boundary

            def stream_sync(self):
                time.sleep(10)
                yield {"type": "audio", "data": b"unreachable"}

        class _FakeSubMaker:
            def feed(self, chunk):
                return None

            def get_srt(self):
                return ""

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.edge_tts, "Communicate", _HangingCommunicate
        ), patch.object(vs.edge_tts, "SubMaker", _FakeSubMaker), patch.object(
            vs.config,
            "app",
            dict(vs.config.app, edge_tts_timeout=0.05),
        ):
            voice_file = Path(tmp_dir) / "hanging-edge-tts.mp3"
            started_at = time.monotonic()
            sub_maker = vs.azure_tts_v1(
                text="帮我生成一个花开花落的视频",
                voice_name="en-AU-NatashaNeural-Female",
                voice_file=str(voice_file),
                voice_rate=1.0,
            )
            elapsed = time.monotonic() - started_at
            self.assertFalse(voice_file.exists())

        self.assertIsNone(sub_maker)
        self.assertLess(elapsed, 2)

    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS,
        "MPT_RUN_INTEGRATION_TESTS not set",
    )
    def test_azure_tts_v2(self):
        if not vs.config.azure.get("speech_key") or not vs.config.azure.get("speech_region"):
            self.skipTest("Azure speech key or region is not configured")

        voice_name = "zh-CN-XiaoxiaoMultilingualNeural-V2-Female"
        voice_name = vs.parse_voice_name(voice_name)
        print(voice_name)

        async def _do():
            voice_file = f"{temp_dir}/tts-azure-v2-{voice_name}.mp3"
            subtitle_file = f"{temp_dir}/tts-azure-v2-{voice_name}.srt"
            sub_maker = vs.azure_tts_v2(
                text=text_zh,
                voice_name=voice_name,
                voice_file=voice_file,
                voice_rate=1.0,
            )
            if not sub_maker:
                self.fail("azure tts v2 failed")
            vs.create_subtitle(sub_maker=sub_maker, text=text_zh, subtitle_file=subtitle_file)
            audio_duration = vs.get_audio_duration(sub_maker)
            print(f"voice: {voice_name}, audio duration: {audio_duration}s")

        self.loop.run_until_complete(_do())

    def test_azure_tts_v2_ssml_applies_rate_and_escapes_text(self):
        """Azure V2 必须通过 SSML 应用语速，并避免用户文案破坏 XML。"""
        ssml = vs._build_azure_v2_ssml(
            text='A < B & "quoted"',
            voice_name="zh-CN-XiaoxiaoMultilingualNeural",
            voice_rate=1.8,
        )

        self.assertIn('xml:lang="zh-CN"', ssml)
        self.assertIn('rate="1.8"', ssml)
        self.assertIn("A &lt; B &amp; \"quoted\"", ssml)

    def test_tts_forwards_rate_to_azure_v2(self):
        """统一 TTS 入口不能在分发 Azure V2 时丢失 voice_rate。"""
        voice_name = "zh-CN-XiaoxiaoMultilingualNeural-V2-Female"
        with patch.object(vs, "azure_tts_v2", return_value=object()) as mock_tts:
            result = vs.tts(
                text="语速测试",
                voice_name=voice_name,
                voice_rate=1.8,
                voice_file="/tmp/azure-v2-rate.mp3",
            )

        self.assertIsNotNone(result)
        mock_tts.assert_called_once_with(
            "语速测试",
            voice_name,
            "/tmp/azure-v2-rate.mp3",
            voice_rate=1.8,
        )

    def test_tts_strips_gemini_style_metadata_before_dispatch(self):
        """Gemini 下拉框的官方风格描述不能成为 API voice_name 的一部分。"""
        sentinel = object()

        with patch.object(vs, "gemini_tts", return_value=sentinel) as gemini_tts:
            result = vs.tts(
                text="Test the updated voice catalog.",
                voice_name="gemini:Achernar-Soft",
                voice_rate=1.0,
                voice_file="/tmp/gemini-achernar.mp3",
                voice_volume=1.0,
            )

        self.assertIs(result, sentinel)
        gemini_tts.assert_called_once_with(
            "Test the updated voice catalog.",
            "Achernar",
            1.0,
            "/tmp/gemini-achernar.mp3",
            1.0,
        )

    def test_gemini_tts_uses_google_genai_and_compatible_submaker_fields(self):
        """
        验证 Gemini TTS 在 edge_tts 7.x 环境下仍会返回项目兼容的字幕结构，
        并且可以被 `subtitle_provider=edge` 的字幕生成链路直接消费，
        避免再次回退 Whisper。同时使用不存在的嵌套输出目录，覆盖 API 或
        CLI 直接调用服务时没有提前创建任务目录的边界情况。
        """

        class _InlineData:
            def __init__(self, data):
                self.data = data

        class _Part:
            def __init__(self, data):
                self.inline_data = _InlineData(data)

        class _Content:
            def __init__(self, data):
                self.parts = [_Part(data)]

        class _Candidate:
            def __init__(self, data):
                self.content = _Content(data)

        class _Response:
            def __init__(self, data):
                self.candidates = [_Candidate(data)]

        captured = {}

        class _FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                tone = (
                    AudioSegment.silent(duration=1800)
                    .set_frame_rate(24000)
                    .set_channels(1)
                    .set_sample_width(2)
                )
                return _Response(tone.raw_data)

        class _FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs
                self.models = _FakeModels()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                captured["closed"] = True

        temp_root = Path(tempfile.mkdtemp(prefix="gemini-tts-output-"))
        self.addCleanup(shutil.rmtree, temp_root, True)
        output_dir = temp_root / "nested" / "audio"
        voice_file = str(output_dir / "tts-gemini-Zephyr.mp3")
        subtitle_file = str(output_dir / "tts-gemini-Zephyr.srt")
        text = "Gemini subtitle generation should work now. Testing multiple lines."

        self.assertFalse(output_dir.exists())

        with patch("google.genai.Client", _FakeClient), patch.object(
            vs.config,
            "app",
            dict(vs.config.app, gemini_api_key="test-key"),
        ):
            sub_maker = vs.gemini_tts(
                text=text,
                voice_name="Zephyr",
                voice_rate=1.0,
                voice_file=voice_file,
            )

        self.assertIsNotNone(sub_maker)
        self.assertTrue(Path(voice_file).is_file())
        self.assertEqual(
            getattr(sub_maker, "subs", []),
            ["Gemini subtitle generation should work now", "Testing multiple lines"],
        )
        self.assertEqual(len(getattr(sub_maker, "offset", [])), 2)
        self.assertEqual(sub_maker.offset[0][0], 0)
        self.assertLess(sub_maker.offset[0][1], sub_maker.offset[1][1])
        self.assertEqual(captured["client_kwargs"], {"api_key": "test-key"})
        self.assertEqual(captured["model"], "gemini-2.5-flash-preview-tts")
        self.assertEqual(captured["contents"], text)
        self.assertEqual(captured["config"].response_modalities, ["AUDIO"])
        voice_config = captured["config"].speech_config.voice_config
        self.assertEqual(
            voice_config.prebuilt_voice_config.voice_name,
            "Zephyr",
        )
        self.assertTrue(captured["closed"])

        vs.create_subtitle(sub_maker=sub_maker, text=text, subtitle_file=subtitle_file)
        subtitle_content = Path(subtitle_file).read_text(encoding="utf-8")
        self.assertIn("Gemini subtitle generation should work now", subtitle_content)
        self.assertIn("Testing multiple lines", subtitle_content)

    def test_mimo_tts_uses_openai_compatible_audio_response(self):
        """
        验证 Xiaomi MiMo TTS 可以消费 OpenAI-compatible 的音频响应结构。

        这里用 fake OpenAI client 和 fake AudioSegment 覆盖真实网络与 ffmpeg，
        确认运行时代码会把待合成文本放到 assistant message，并把返回的
        base64 WAV 音频导出到项目后续流程使用的音频文件。
        """

        class _FakeAudio:
            def __init__(self):
                self.data = base64.b64encode(b"RIFF-fake-wav").decode("utf-8")

        class _FakeMessage:
            def __init__(self):
                self.audio = _FakeAudio()

        class _FakeChoice:
            def __init__(self):
                self.message = _FakeMessage()

        class _FakeCompletion:
            def __init__(self):
                self.choices = [_FakeChoice()]

        class _FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return _FakeCompletion()

        class _FakeAudioSegment:
            def __len__(self):
                return 1800

            def export(self, output_file, format):
                Path(output_file).write_bytes(b"fake-mp3")

        fake_completions = _FakeCompletions()
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs,
            "OpenAI",
            return_value=fake_client,
        ) as openai_client, patch(
            "pydub.AudioSegment.from_file",
            return_value=_FakeAudioSegment(),
        ), patch.object(
            vs.config,
            "app",
            dict(
                vs.config.app,
                mimo_api_key="mimo-key",
                mimo_base_url="https://api.xiaomimimo.com/v1",
                mimo_tts_model_name="mimo-v2.5-tts",
                mimo_tts_style_prompt="用清晰的中文旁白朗读。",
            ),
        ):
            voice_file = str(Path(tmp_dir) / "mimo-tts.mp3")
            sub_maker = vs.mimo_tts(
                text="小米语音合成测试。第二句话。",
                voice_name="冰糖",
                voice_rate=1.0,
                voice_file=voice_file,
                voice_volume=1.0,
            )
            generated_audio = Path(voice_file).read_bytes()

        openai_client.assert_called_once_with(
            api_key="mimo-key",
            base_url="https://api.xiaomimimo.com/v1",
        )
        self.assertEqual(fake_completions.kwargs["model"], "mimo-v2.5-tts")
        self.assertEqual(
            fake_completions.kwargs["messages"],
            [
                {"role": "user", "content": "用清晰的中文旁白朗读。"},
                {"role": "assistant", "content": "小米语音合成测试。第二句话。"},
            ],
        )
        self.assertEqual(
            fake_completions.kwargs["audio"],
            {"format": "wav", "voice": "冰糖"},
        )
        self.assertEqual(generated_audio, b"fake-mp3")
        self.assertIsNotNone(sub_maker)
        self.assertEqual(getattr(sub_maker, "subs", []), ["小米语音合成测试", "第二句话"])
        self.assertEqual(len(getattr(sub_maker, "offset", [])), 2)

    def test_minimax_tts_uses_regional_endpoint_and_hex_audio(self):
        class _Response:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {"data": {"audio": b"audio".hex(), "status": 2}, "base_resp": {"status_code": 0}}

        class _Clip:
            duration = 2.5

            def close(self):
                pass

        captured = {}

        def _post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers, timeout=timeout)
            return _Response()

        settings = {
            "api_key": "test-key", "base_url": vs.MINIMAX_TTS_CN_URL,
            "model_id": "speech-2.8-turbo", "voice_id": "male-qn-qingse",
            "sample_rate": 32000, "bitrate": 128000, "audio_format": "mp3", "channel": 1,
        }
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.config, "minimax_tts", settings
        ), patch.object(vs.requests, "post", side_effect=_post), patch.object(
            vs, "AudioFileClip", return_value=_Clip()
        ):
            voice_file = str(Path(tmp_dir) / "minimax.mp3")
            result = vs.minimax_tts("Speech test.", "male-qn-qingse", 1.2, voice_file, 1.5)
            self.assertEqual(Path(voice_file).read_bytes(), b"audio")

        self.assertIsNotNone(result)
        self.assertEqual(captured["url"], "https://api.minimaxi.com/v1/t2a_v2")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["json"]["model"], "speech-2.8-turbo")
        self.assertEqual(captured["json"]["text"], "Speech test.")
        self.assertEqual(captured["json"]["voice_setting"]["voice_id"], "male-qn-qingse")
        self.assertEqual(captured["json"]["audio_setting"]["format"], "mp3")

    def test_minimax_tts_reuses_cn_llm_key_and_endpoint(self):
        """TTS 未单独配置时，应复用同区域的 MiniMax LLM 凭证和地址。"""
        class _Response:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {"data": {"audio": b"audio".hex(), "status": 2}, "base_resp": {"status_code": 0}}

        class _Clip:
            duration = 1.25

            def close(self):
                pass

        captured = {}

        def _post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, headers=headers)
            return _Response()

        settings = {
            "api_key": "", "base_url": vs.MINIMAX_TTS_GLOBAL_URL,
            "model_id": vs.MINIMAX_TTS_DEFAULT_MODEL, "audio_format": "mp3",
        }
        app_settings = {
            "minimax_api_key": "shared-cn-key",
            "minimax_base_url": "https://api.minimaxi.com/v1",
        }
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.config, "minimax_tts", settings
        ), patch.object(vs.config, "app", app_settings), patch.object(
            vs.requests, "post", side_effect=_post
        ), patch.object(vs, "AudioFileClip", return_value=_Clip()):
            voice_file = str(Path(tmp_dir) / "minimax.mp3")
            result = vs.minimax_tts("测试。", "male-qn-qingse", 1.0, voice_file)

        self.assertIsNotNone(result)
        self.assertEqual(captured["url"], vs.MINIMAX_TTS_CN_URL)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer shared-cn-key")

    def test_get_minimax_voice_catalog_normalizes_all_voice_types(self):
        """音色查询应统一不同来源的响应结构，并忽略重复或空 Voice ID。"""

        class _Response:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {
                    "system_voice": [
                        {"voice_id": "system-1", "voice_name": "系统音色"},
                        {"voice_id": "", "voice_name": "无效音色"},
                    ],
                    "voice_cloning": [
                        {"voice_id": "clone-1", "voice_name": "我的克隆音色"},
                        {"voice_id": "system-1", "voice_name": "重复音色"},
                    ],
                    "voice_generation": [{"voice_id": "generated-1"}],
                    "base_resp": {"status_code": "0"},
                }

        with patch.object(vs.requests, "post", return_value=_Response()) as post:
            catalog = vs.get_minimax_voice_catalog(
                api_key="test-key",
                endpoint=vs.MINIMAX_TTS_CN_URL,
            )

        post.assert_called_once_with(
            "https://api.minimaxi.com/v1/get_voice",
            json={"voice_type": "all"},
            headers={
                "Authorization": "Bearer test-key",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        self.assertEqual(
            catalog,
            [
                {
                    "voice_id": "system-1",
                    "voice_name": "系统音色",
                    "voice_type": "system",
                },
                {
                    "voice_id": "clone-1",
                    "voice_name": "我的克隆音色",
                    "voice_type": "voice_cloning",
                },
                {
                    "voice_id": "generated-1",
                    "voice_name": "generated-1",
                    "voice_type": "voice_generation",
                },
            ],
        )

    def test_get_minimax_voice_catalog_exposes_provider_error(self):
        """远端业务错误应明确抛出，不能被伪装成账号没有可用音色。"""

        class _Response:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {
                    "base_resp": {
                        "status_code": 1004,
                        "status_msg": "invalid api key",
                    }
                }

        with patch.object(vs.requests, "post", return_value=_Response()):
            with self.assertRaisesRegex(RuntimeError, "invalid api key"):
                vs.get_minimax_voice_catalog(api_key="invalid-key")

    def test_minimax_tts_does_not_leave_invalid_audio_output(self):
        """响应音频无法解析时，不应覆盖已有文件或留下临时文件。"""
        class _Response:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {"data": {"audio": b"invalid-audio".hex(), "status": 2}, "base_resp": {"status_code": 0}}

        settings = {
            "api_key": "test-key", "base_url": vs.MINIMAX_TTS_GLOBAL_URL,
            "model_id": vs.MINIMAX_TTS_DEFAULT_MODEL, "audio_format": "mp3",
        }
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.config, "minimax_tts", settings
        ), patch.object(vs.requests, "post", return_value=_Response()), patch.object(
            vs, "AudioFileClip", side_effect=OSError("invalid audio")
        ):
            voice_path = Path(tmp_dir) / "minimax.mp3"
            voice_path.write_bytes(b"existing-audio")
            result = vs.minimax_tts("Speech test.", "English_expressive_narrator", 1.0, str(voice_path))

            self.assertIsNone(result)
            self.assertEqual(voice_path.read_bytes(), b"existing-audio")
            self.assertEqual([path.name for path in Path(tmp_dir).iterdir()], ["minimax.mp3"])

    def test_minimax_voice_helpers_and_dispatch(self):
        with patch.object(vs.config, "minimax_tts", {"voice_id": "narrator"}):
            self.assertEqual(vs.get_minimax_voices(), ["minimax:narrator"])
        self.assertEqual(vs.get_minimax_voices("custom-voice"), ["minimax:custom-voice"])
        self.assertTrue(vs.is_minimax_voice("minimax:narrator"))
        sentinel = object()
        with patch.object(vs, "minimax_tts", return_value=sentinel) as implementation:
            result = vs.tts("test", "minimax:narrator", 1.0, "voice.mp3", 1.0)
        self.assertIs(result, sentinel)
        implementation.assert_called_once_with("test", "narrator", 1.0, "voice.mp3", 1.0)

    def test_chatterbox_voice_helpers(self):
        """is_chatterbox_voice / get_chatterbox_voices basics and normalisation."""
        self.assertTrue(vs.is_chatterbox_voice("chatterbox:default-Female"))
        self.assertFalse(vs.is_chatterbox_voice("elevenlabs:abc:Rachel"))
        self.assertFalse(vs.is_chatterbox_voice(""))
        self.assertFalse(vs.is_chatterbox_voice(None))

        # list entries are normalised to the chatterbox:<name> dispatcher format,
        # and entries that are already prefixed are left untouched
        with patch.object(
            vs.config,
            "chatterbox",
            {"voices": ["narrator-Male", "chatterbox:host"]},
        ):
            self.assertEqual(
                vs.get_chatterbox_voices(),
                ["chatterbox:narrator-Male", "chatterbox:host"],
            )

        # a comma-separated string is also accepted (TOML-friendly)
        with patch.object(vs.config, "chatterbox", {"voices": "alpha, beta ,"}):
            self.assertEqual(
                vs.get_chatterbox_voices(),
                ["chatterbox:alpha", "chatterbox:beta"],
            )

        # with nothing configured the dropdown still gets a usable default
        with patch.object(vs.config, "chatterbox", {}):
            self.assertEqual(vs.get_chatterbox_voices(), ["chatterbox:default-Female"])

    def test_chatterbox_tts_posts_to_openai_compatible_endpoint(self):
        """Success path: POST /audio/speech, write audio, return legacy SubMaker."""

        class _FakeResponse:
            status_code = 200
            content = b"RIFF-fake-wav"
            text = ""

        class _FakeClip:
            duration = 3.5

            def close(self):
                pass

        captured = {}

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.config,
            "chatterbox",
            {
                "base_url": "http://localhost:4123/v1/",
                "api_key": "secret",
                "model_id": "chatterbox",
            },
        ), patch.object(
            vs.requests, "post", side_effect=_fake_post
        ) as post, patch.object(
            vs, "AudioFileClip", return_value=_FakeClip()
        ):
            voice_file = str(Path(tmp_dir) / "chatterbox.mp3")
            sub_maker = vs.chatterbox_tts(
                text="Hello world. Second sentence.",
                voice="default",
                voice_file=voice_file,
                voice_rate=1.2,
                voice_volume=1.0,
            )
            generated_audio = Path(voice_file).read_bytes()

        post.assert_called_once()
        # trailing slash on base_url is stripped before appending /audio/speech
        self.assertEqual(captured["url"], "http://localhost:4123/v1/audio/speech")
        self.assertEqual(captured["json"]["model"], "chatterbox")
        self.assertEqual(captured["json"]["voice"], "default")
        self.assertEqual(captured["json"]["input"], "Hello world. Second sentence.")
        self.assertAlmostEqual(captured["json"]["speed"], 1.2)
        # api_key is forwarded as a bearer token
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer secret")
        # volume is intentionally not part of the OpenAI speech payload
        self.assertNotIn("volume", captured["json"])
        self.assertEqual(generated_audio, b"RIFF-fake-wav")
        self.assertIsNotNone(sub_maker)
        self.assertTrue(getattr(sub_maker, "subs", []))

    def test_chatterbox_tts_requires_base_url(self):
        """Missing base_url short-circuits without any network call."""
        with patch.object(
            vs.config, "chatterbox", {"base_url": ""}
        ), patch.object(vs.requests, "post") as post:
            result = vs.chatterbox_tts(
                text="hi", voice="default", voice_file="unused.mp3"
            )
        self.assertIsNone(result)
        post.assert_not_called()

    def test_chatterbox_tts_returns_none_on_http_error(self):
        """A non-200 response is retried up to 3 times, then fails to None."""

        class _FakeResponse:
            status_code = 500
            content = b""
            text = "boom"

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.config, "chatterbox", {"base_url": "http://localhost:4123/v1"}
        ), patch.object(
            vs.requests, "post", return_value=_FakeResponse()
        ) as post:
            voice_file = str(Path(tmp_dir) / "chatterbox.mp3")
            result = vs.chatterbox_tts(
                text="hi", voice="default", voice_file=voice_file
            )
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 3)

    def _make_broken_clip_class(self, close_calls: list):
        """Return a clip class whose .duration raises and whose .close() records calls."""

        class _BrokenClip:
            @property
            def duration(self):
                raise RuntimeError("FFmpeg probe failed")

            def close(self):
                close_calls.append(True)

        return _BrokenClip

    def test_elevenlabs_tts_audio_clip_closed_on_duration_error(self):
        """AudioFileClip.close() must be called even when reading .duration raises."""
        close_calls: list = []
        BrokenClip = self._make_broken_clip_class(close_calls)

        class _OkResponse:
            status_code = 200
            content = b"fake-mp3"
            text = ""

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out = f.name
        try:
            with (
                patch.object(
                    vs.config,
                    "elevenlabs",
                    {"api_key": "test-key", "model_id": "eleven_multilingual_v2"},
                ),
                patch.object(vs.requests, "post", return_value=_OkResponse()),
                patch.object(vs, "AudioFileClip", side_effect=lambda _: BrokenClip()),
            ):
                result = vs.elevenlabs_tts("Hello world.", "voice-id", out)
        finally:
            if os.path.exists(out):
                os.remove(out)

        self.assertIsNone(result)
        self.assertTrue(close_calls, "AudioFileClip.close() was never called")

    def test_chatterbox_tts_audio_clip_closed_on_duration_error(self):
        """AudioFileClip.close() must be called even when reading .duration raises."""
        close_calls: list = []
        BrokenClip = self._make_broken_clip_class(close_calls)

        class _OkResponse:
            status_code = 200
            content = b"fake-mp3"
            text = ""

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out = f.name
        try:
            with (
                patch.object(
                    vs.config,
                    "chatterbox",
                    {"base_url": "http://localhost:4123", "api_key": "", "model_id": "chatterbox"},
                ),
                patch.object(vs.requests, "post", return_value=_OkResponse()),
                patch.object(vs, "AudioFileClip", side_effect=lambda _: BrokenClip()),
            ):
                result = vs.chatterbox_tts("Hello world.", "default", out)
        finally:
            if os.path.exists(out):
                os.remove(out)

        self.assertIsNone(result)
        self.assertTrue(close_calls, "AudioFileClip.close() was never called")

    def test_fish_audio_tts_audio_clip_closed_on_duration_error(self):
        """AudioFileClip.close() must be called even when reading .duration raises."""
        close_calls: list = []
        BrokenClip = self._make_broken_clip_class(close_calls)

        class _OkResponse:
            status_code = 200
            content = b"x" * 200
            text = ""

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out = f.name
        try:
            with (
                patch.object(
                    vs.config,
                    "fish_audio",
                    {"api_key": "test-key", "model": "s2.1-pro-free"},
                ),
                patch.object(vs.requests, "post", return_value=_OkResponse()),
                patch.object(vs, "AudioFileClip", side_effect=lambda _: BrokenClip()),
            ):
                result = vs.fish_audio_tts("Hello world.", out)
        finally:
            if os.path.exists(out):
                os.remove(out)

        self.assertIsNone(result)
        self.assertTrue(close_calls, "AudioFileClip.close() was never called")

    def test_generate_subtitle_keeps_edge_provider_for_gemini_legacy_submaker(self):
        """
        验证 Gemini TTS 返回的 legacy 字幕结构在 edge provider 下可以直接产出
        SRT，不会因为匹配失败而回退到 Whisper。
        """
        script = "Gemini subtitle generation should work now. Testing multiple lines."
        sub_maker = vs.populate_legacy_submaker_with_full_text(
            vs.ensure_legacy_submaker_fields(vs.SubMaker()),
            script,
            2.4,
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            task_service.config,
            "app",
            dict(task_service.config.app, subtitle_provider="edge"),
        ), patch("app.services.subtitle.create") as whisper_create, patch(
            "app.utils.utils.task_dir",
            lambda tid="": str(Path(tmp_dir) / tid) if tid else str(Path(tmp_dir)),
        ):
            task_id = "gemini-subtitle-edge-task"
            Path(tmp_dir, task_id).mkdir(parents=True, exist_ok=True)
            subtitle_path = task_service.generate_subtitle(
                task_id=task_id,
                params=type("Params", (), {"subtitle_enabled": True})(),
                video_script=script,
                sub_maker=sub_maker,
                audio_file="",
            )

            self.assertTrue(subtitle_path.endswith("subtitle.srt"))
            self.assertTrue(Path(subtitle_path).exists())
            self.assertFalse(whisper_create.called)
            subtitle_content = Path(subtitle_path).read_text(encoding="utf-8")
            self.assertIn("Gemini subtitle generation should work now", subtitle_content)
            self.assertIn("Testing multiple lines", subtitle_content)

    def test_script_split_keeps_thousand_separator_comma(self):
        """
        Edge TTS 会把 "1,000 years" 作为连续文本返回。脚本断句时不能把
        数字中间的英文逗号当成句子边界，否则字幕聚合会出现 issue #894
        里的 sub_items 数量少于 script_lines，并错误回退 Whisper。
        """
        text = (
            "It takes about 1,000 years for a single drop of water to finish "
            "the whole trip!"
        )

        self.assertEqual(
            utils.split_string_by_punctuations(text),
            [
                (
                    "It takes about 1,000 years for a single drop of water to finish "
                    "the whole trip"
                )
            ],
        )

    def test_edge_cue_aggregation_handles_thousand_separator_comma(self):
        """
        复现 issue #894 的关键形态：Edge cues 中最后一句作为连续文本返回，
        包含 `1,000 years`。脚本断句必须与 cues 聚合结果一致，不能把它
        拆成两条字幕。
        """
        text = (
            "The ocean isn't just sitting stil, it moves around the world like a massive "
            "amusement park ride! Cold water at the North and South Poles sinks to the "
            "bottom because it is heavy and salty. At the same time, warm water from the "
            "sunny equator flows along the top to take its place. This creates a giant "
            "underwater conveyor belt that travels all the way around the Earth. It takes "
            "about 1,000 years for a single drop of water to finish the whole trip!"
        )
        script_lines = utils.split_string_by_punctuations(text)
        cues = []
        for index, line in enumerate(script_lines):
            # Edge 的 cue content 经常没有脚本里的空格和标点布局，这里去掉空格
            # 来模拟更严格的匹配场景。
            cues.append(
                SimpleNamespace(
                    content=line.replace(" ", ""),
                    start=timedelta(seconds=index),
                    end=timedelta(seconds=index + 0.8),
                )
            )
        sub_maker = SimpleNamespace(cues=cues)

        sub_items = vs._build_subtitle_items_from_edge_cues(sub_maker, script_lines)

        self.assertEqual(len(sub_items), len(script_lines))
        self.assertIn("1,000 years", sub_items[-1])

    def test_script_split_supports_arabic_punctuation(self):
        """
        阿拉伯语脚本常用 ، ؛ ؟ 作为自然断句标点。断句阶段必须识别这些
        标点，否则 edge-tts cue 的停顿边界和脚本行边界会错位。
        """
        text = "مرحبا بالعالم، كيف حالك؟ هذا اختبار؛ يعمل بشكل جيد."

        self.assertEqual(
            utils.split_string_by_punctuations(text),
            [
                "مرحبا بالعالم",
                "كيف حالك",
                "هذا اختبار",
                "يعمل بشكل جيد",
            ],
        )

    def test_match_script_line_normalizes_arabic_letter_forms(self):
        """
        edge-tts 可能把阿拉伯语中的不同字母形态归一化，或返回带变音符号、
        Tatweel 的 cue 文本。匹配时应容错，但最终字幕仍保留原始脚本文案。
        """
        script_lines = ["أهلاً وسهلاً بك في المدرسة"]

        matched = vs._match_script_line(
            script_lines,
            "اهلا وسهلا بك في المدرسه",
            0,
        )

        self.assertEqual(matched, script_lines[0])

    def test_edge_cue_aggregation_handles_arabic_variant_forms(self):
        """
        复现阿拉伯语字幕失败的核心路径：脚本包含 أ/ة 等字母形态，edge cue
        返回 ا/ه 等归一化形态时，聚合仍应生成完整字幕，避免回退 Whisper。
        """
        text = "أهلاً وسهلاً بك في المدرسة؟ هذا اختبار رائع، شكراً لك."
        script_lines = utils.split_string_by_punctuations(text)
        cue_texts = [
            "اهلا وسهلا بك في المدرسه",
            "هذا اختبار رائع",
            "شكرا لك",
        ]
        sub_maker = SimpleNamespace(
            cues=[
                SimpleNamespace(
                    content=cue_text,
                    start=timedelta(seconds=index),
                    end=timedelta(seconds=index + 0.8),
                )
                for index, cue_text in enumerate(cue_texts)
            ]
        )

        sub_items = vs._build_subtitle_items_from_edge_cues(sub_maker, script_lines)

        self.assertEqual(len(sub_items), len(script_lines))
        self.assertIn("أهلاً وسهلاً بك في المدرسة", sub_items[0])
        self.assertIn("شكراً لك", sub_items[-1])

    def test_create_subtitle_ignores_markdown_separator_lines(self):
        """
        用户手动脚本可能包含 `---` 这类 Markdown 分隔符。TTS 不会朗读
        这些符号行，字幕聚合也不应把它们当成目标字幕行，否则后续真实
        字幕会卡住并回退到 Whisper。
        """
        text = "第一段\n---\n第二段"
        sub_maker = SimpleNamespace(
            cues=[
                SimpleNamespace(
                    content="第一段",
                    start=timedelta(seconds=0),
                    end=timedelta(seconds=0.8),
                ),
                SimpleNamespace(
                    content="第二段",
                    start=timedelta(seconds=1),
                    end=timedelta(seconds=1.8),
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            vs.create_subtitle(
                sub_maker=sub_maker,
                text=text,
                subtitle_file=str(subtitle_file),
            )

            subtitle_content = subtitle_file.read_text(encoding="utf-8")

        self.assertIn("第一段", subtitle_content)
        self.assertIn("第二段", subtitle_content)
        self.assertNotIn("---", subtitle_content)
        self.assertNotIn("00:00:00,000 --> 00:00:00,000", subtitle_content)

    def test_create_subtitle_word_level_preserves_edge_cue_timing(self):
        """Edge TTS 的细粒度 cue 应逐项写入，不能再被按标点聚合。"""
        sub_maker = SimpleNamespace(
            cues=[
                SimpleNamespace(
                    content="人工智能",
                    start=timedelta(seconds=0.1),
                    end=timedelta(seconds=0.8),
                ),
                SimpleNamespace(
                    content="正在",
                    start=timedelta(seconds=0.9),
                    end=timedelta(seconds=1.2),
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "word-level.srt"
            vs.create_subtitle(
                sub_maker=sub_maker,
                text="人工智能正在发展。",
                subtitle_file=str(subtitle_file),
                word_level=True,
            )
            subtitle_content = subtitle_file.read_text(encoding="utf-8")

        self.assertIn("00:00:00,100 --> 00:00:00,800", subtitle_content)
        self.assertIn("人工智能", subtitle_content)
        self.assertIn("00:00:00,900 --> 00:00:01,200", subtitle_content)
        self.assertIn("正在", subtitle_content)

    def test_create_subtitle_word_level_falls_back_to_provider_granularity(self):
        """
        旧版 SubMaker 没有 cue 时，应保留语音服务返回的原始时间粒度。

        ElevenLabs、Fish Audio 等服务可能只返回短语或整句时间轴。此时不能
        按字符平均拆分并伪造逐词精度，否则字幕会逐渐偏离真实语音。
        """
        sub_maker = SimpleNamespace(
            cues=[],
            subs=["Hello world"],
            # 旧版 SubMaker 的 offset 使用 100 纳秒为单位的整数时间戳。
            offset=[(2_000_000, 11_000_000)],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "word-level-fallback.srt"
            vs.create_subtitle(
                sub_maker=sub_maker,
                text="Hello world",
                subtitle_file=str(subtitle_file),
                word_level=True,
            )
            subtitle_content = subtitle_file.read_text(encoding="utf-8")

        self.assertEqual(subtitle_content.count(" --> "), 1)
        self.assertIn("00:00:00,200 --> 00:00:01,100", subtitle_content)
        self.assertIn("Hello world", subtitle_content)

    def test_create_subtitle_ignores_markdown_underscore_marks(self):
        """
        `_` 常被用户用作 Markdown 强调标记，但 TTS 返回的 cue 通常不包含
        这些格式符。匹配时应忽略 `_`，避免生成空字幕或回退到 Whisper。
        """
        text = "这是_a_测试。"
        sub_maker = SimpleNamespace(
            cues=[
                SimpleNamespace(
                    content="这是a测试",
                    start=timedelta(seconds=0),
                    end=timedelta(seconds=0.8),
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            vs.create_subtitle(
                sub_maker=sub_maker,
                text=text,
                subtitle_file=str(subtitle_file),
            )

            subtitle_content = subtitle_file.read_text(encoding="utf-8")

        self.assertIn("这是a测试", subtitle_content)
        self.assertNotIn("这是_a_测试", subtitle_content)
        self.assertNotIn("00:00:00,000 --> 00:00:00,000", subtitle_content)

    def test_convert_rate_to_percent_signs_zero_rate(self):
        # Rates near but not exactly 1.0 round to 0 percent. edge-tts rejects
        # an unsigned "0%" (ValueError: Invalid rate '0%'), so the helper must
        # emit a sign-prefixed "+0%". Regression test for that crash.
        self.assertEqual(vs.convert_rate_to_percent(1.0), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(1.004), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(0.997), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(1.5), "+50%")
        self.assertEqual(vs.convert_rate_to_percent(0.8), "-20%")

    def test_convert_rate_to_percent_invalid_values_default_to_normal(self):
        # API 和批处理脚本可能把空语速传成 0、None 或空字符串；这些都不应让
        # edge-tts 收到 -100% 或触发异常，而是按正常语速处理。
        self.assertEqual(vs.convert_rate_to_percent(0), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(0.0), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(None), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(""), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(float("nan")), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(float("inf")), "+0%")


def _write_test_wav(filepath: str, duration_seconds: float = 1.0, sample_rate: int = 24000) -> str:
    import wave
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(round(duration_seconds * sample_rate))
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_samples)
    return filepath


class TestElevenLabsVoice(unittest.TestCase):

    def test_is_elevenlabs_voice_true(self):
        self.assertTrue(vs.is_elevenlabs_voice("elevenlabs:pNInz6obpgDQGcFmaJgB:Adam"))

    def test_is_elevenlabs_voice_false_azure(self):
        self.assertFalse(vs.is_elevenlabs_voice("zh-CN-XiaoxiaoNeural-Female"))

    def test_is_elevenlabs_voice_false_siliconflow(self):
        self.assertFalse(vs.is_elevenlabs_voice("siliconflow:model:voice-Male"))

    def test_is_elevenlabs_voice_empty(self):
        self.assertFalse(vs.is_elevenlabs_voice(""))

    def test_is_elevenlabs_voice_none(self):
        self.assertFalse(vs.is_elevenlabs_voice(None))

    def test_get_elevenlabs_voices_empty_api_key(self):
        result = vs.get_elevenlabs_voices("")
        self.assertEqual(result, [])

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "voices": [
                {"voice_id": "abc123", "name": "Adam"},
                {"voice_id": "def456", "name": "Rachel"},
            ]
        }
        result = vs.get_elevenlabs_voices("fake-api-key")
        self.assertEqual(result, [
            "elevenlabs:abc123:Adam",
            "elevenlabs:def456:Rachel",
        ])
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        self.assertIn("xi-api-key", call_kwargs.kwargs.get("headers", {}))

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_http_error(self, mock_get):
        mock_get.return_value.status_code = 401
        mock_get.return_value.text = "Unauthorized"
        result = vs.get_elevenlabs_voices("bad-key")
        self.assertEqual(result, [])

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_network_error(self, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.ConnectionError("timeout")
        result = vs.get_elevenlabs_voices("fake-key")
        self.assertEqual(result, [])

    @patch("app.services.voice.requests.post")
    @patch("app.services.voice.AudioFileClip")
    @patch("app.services.voice.config")
    def test_elevenlabs_tts_success(self, mock_config, mock_clip_cls, mock_post):
        mock_config.elevenlabs.get.return_value = "fake-api-key"
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"fake-mp3-bytes"
        mock_clip_cls.return_value.duration = 3.0
        mock_clip_cls.return_value.close = lambda: None

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out_path = f.name

        try:
            result = vs.elevenlabs_tts("Hello world", "abc123", out_path)
            self.assertIsNotNone(result)
            self.assertTrue(hasattr(result, "subs"))
            self.assertTrue(hasattr(result, "offset"))
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    @patch("app.services.voice.config")
    def test_elevenlabs_tts_no_api_key(self, mock_config):
        mock_config.elevenlabs.get.return_value = ""
        # Key 解析包含环境变量回退，测试必须显式清空宿主环境，避免开发机或 CI
        # 恰好设置 ELEVENLABS_API_KEY 后改变“未配置”的测试前提。
        with patch.dict(os.environ, {}, clear=True):
            result = vs.elevenlabs_tts("Hello", "abc123", "/tmp/test.mp3")
        self.assertIsNone(result)

    @patch("app.services.voice.config")
    def test_elevenlabs_tts_empty_text(self, mock_config):
        mock_config.elevenlabs.get.return_value = "fake-key"
        result = vs.elevenlabs_tts("  ", "abc123", "/tmp/test.mp3")
        self.assertIsNone(result)

    def test_elevenlabs_api_key_prefers_config(self):
        with (
            patch.object(vs.config, "elevenlabs", {"api_key": "config-key"}),
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "env-key"}),
        ):
            self.assertEqual(vs.get_elevenlabs_api_key(), "config-key")

    def test_elevenlabs_api_key_falls_back_to_environment(self):
        with (
            patch.object(vs.config, "elevenlabs", {"api_key": ""}),
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": " env-key "}),
        ):
            self.assertEqual(vs.get_elevenlabs_api_key(), "env-key")

    def test_elevenlabs_api_key_matches_music_service(self):
        """TTS 和配乐共用同一账号配置，两条生成链路必须解析出相同 Key。"""
        from app.services import elevenlabs_music

        for configured_key, env_key in (("config-key", "env-key"), ("", "env-key")):
            with self.subTest(configured_key=configured_key):
                with (
                    patch.object(
                        vs.config, "elevenlabs", {"api_key": configured_key}
                    ),
                    patch.object(
                        elevenlabs_music.config,
                        "elevenlabs",
                        {"api_key": configured_key},
                    ),
                    patch.dict(os.environ, {"ELEVENLABS_API_KEY": env_key}),
                ):
                    self.assertEqual(
                        vs.get_elevenlabs_api_key(),
                        elevenlabs_music.get_api_key(),
                    )


    def test_siliconflow_subtitle_spans_full_audio_duration(self):
        """Last subtitle entry must end at the actual audio end, not truncated early.

        The old ad-hoc loop applied integer division independently to every
        sentence, so accumulated truncation meant the final subtitle always
        ended a few units before the real audio end. Every other TTS provider
        already delegates to populate_legacy_submaker_with_full_text, which
        anchors the last entry to the full duration; this test verifies
        siliconflow_tts now does the same.
        """
        audio_duration_seconds = 7.3
        expected_end_100ns = int(audio_duration_seconds * 10_000_000)

        fake_response = SimpleNamespace(status_code=200, content=b"fake-mp3")
        fake_clip = SimpleNamespace(
            duration=audio_duration_seconds, close=lambda: None
        )

        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs.requests, "post", return_value=fake_response),
            patch.object(vs, "AudioFileClip", return_value=fake_clip),
            patch.object(vs.config, "siliconflow", {"api_key": "test-key"}),
        ):
            voice_file = str(Path(tmp_dir) / "test.mp3")
            sub_maker = vs.siliconflow_tts(
                text=(
                    "First sentence. Second sentence. "
                    "Third sentence. Fourth sentence."
                ),
                model="FunAudioLLM/CosyVoice2-0.5B",
                voice="FunAudioLLM/CosyVoice2-0.5B:alex",
                voice_rate=1.0,
                voice_file=voice_file,
            )

        self.assertIsNotNone(sub_maker)
        offsets = getattr(sub_maker, "offset", [])
        self.assertGreater(
            len(offsets), 1, "multi-sentence text must produce multiple subtitles"
        )
        last_end = offsets[-1][1]
        self.assertEqual(
            last_end,
            expected_end_100ns,
            f"last subtitle end ({last_end}) must equal the full audio duration "
            f"({expected_end_100ns} units = {audio_duration_seconds}s)",
        )

    def test_pause_tag_detection_and_parsing(self):
        """测试多语言停顿标签的检测、解析与清洗。"""
        sample_script = (
            "Hola a todos. [pausa: 2s] "
            "Welcome back. [pause: 1.5s] "
            "今天天气很好。[停顿: 3秒] "
            "잠시 멈춤 [일시중지: 500ms] "
            "Final sentence."
        )

        self.assertTrue(utils.has_pause_tags(sample_script))
        self.assertFalse(utils.has_pause_tags("Plain script with no pause tags."))

        segments = utils.parse_script_with_pauses(sample_script)
        self.assertEqual(len(segments), 9)
        self.assertEqual(segments[0], ("speech", "Hola a todos."))
        self.assertEqual(segments[1], ("pause", 2.0))
        self.assertEqual(segments[2], ("speech", "Welcome back."))
        self.assertEqual(segments[3], ("pause", 1.5))
        self.assertEqual(segments[4], ("speech", "今天天气很好。"))
        self.assertEqual(segments[5], ("pause", 3.0))
        self.assertEqual(segments[6], ("speech", "잠시 멈춤"))
        self.assertEqual(segments[7], ("pause", 0.5))
        self.assertEqual(segments[8], ("speech", "Final sentence."))

        cleaned = utils.remove_pause_tags(sample_script)
        self.assertNotIn("[pausa", cleaned)
        self.assertNotIn("[pause", cleaned)
        self.assertNotIn("[停顿", cleaned)
        self.assertNotIn("[일시중지", cleaned)

        normalized = utils.normalize_script_for_subtitle_matching(sample_script)
        self.assertNotIn("[pausa", normalized)
        self.assertIn("Hola a todos", normalized)
        self.assertIn("Final sentence", normalized)

        # Flexible syntax tests: without colon, with parentheses, and with default duration
        flexible_script = "Intro. [pausa 1s] Middle. (pausa: 2s) Next. [pause] End."
        self.assertTrue(utils.has_pause_tags(flexible_script))
        flex_segments = utils.parse_script_with_pauses(flexible_script)
        self.assertEqual(len(flex_segments), 7)
        self.assertEqual(flex_segments[0], ("speech", "Intro."))
        self.assertEqual(flex_segments[1], ("pause", 1.0))
        self.assertEqual(flex_segments[2], ("speech", "Middle."))
        self.assertEqual(flex_segments[3], ("pause", 2.0))
        self.assertEqual(flex_segments[4], ("speech", "Next."))
        self.assertEqual(flex_segments[5], ("pause", 1.0))
        self.assertEqual(flex_segments[6], ("speech", "End."))

        flex_cleaned = utils.remove_pause_tags(flexible_script)
        self.assertNotIn("[pausa", flex_cleaned)
        self.assertNotIn("(pausa", flex_cleaned)
        self.assertNotIn("[pause", flex_cleaned)

    def test_tts_with_pauses_shifts_submaker_timeline(self):
        """测试包含停顿标签时，SubMaker 时间轴和音频拼接正确偏移。"""
        from edge_tts.srt_composer import Subtitle

        fake_sub1 = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        fake_sub1.cues = [
            Subtitle(1, timedelta(seconds=0.1), timedelta(seconds=1.5), "Segment 1"),
        ]
        fake_sub1.subs = ["Segment 1"]
        fake_sub1.offset = [(1000000, 15000000)]

        fake_sub2 = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        fake_sub2.cues = [
            Subtitle(1, timedelta(seconds=0.2), timedelta(seconds=1.8), "Segment 2"),
        ]
        fake_sub2.subs = ["Segment 2"]
        fake_sub2.offset = [(2000000, 18000000)]

        def fake_single_tts(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
            if "Segment 1" in text:
                _write_test_wav(voice_file, 1.5)
                return fake_sub1
            _write_test_wav(voice_file, 1.8)
            return fake_sub2

        def fake_silence(duration, voice_file):
            _write_test_wav(voice_file, duration)
            return True

        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs, "_single_tts", side_effect=fake_single_tts) as mock_single_tts,
            patch.object(vs, "generate_silent_audio", side_effect=fake_silence) as mock_silence,
            patch.object(vs, "_concat_audio_files", return_value=True) as mock_concat,
        ):
            out_file = str(Path(tmp_dir) / "combined.mp3")
            script = "Segment 1. [pausa: 2s] Segment 2."
            result_submaker = vs.tts(
                text=script,
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file=out_file,
            )

            self.assertIsNotNone(result_submaker)
            self.assertEqual(mock_single_tts.call_count, 2)
            mock_silence.assert_called_once()
            mock_concat.assert_called_once()

            # 验证第二段 cues 偏移了 1.5s + 2.0s = 3.5s
            self.assertEqual(len(result_submaker.cues), 2)
            self.assertAlmostEqual(result_submaker.cues[0].start.total_seconds(), 0.1, places=2)
            self.assertAlmostEqual(result_submaker.cues[0].end.total_seconds(), 1.5, places=2)
            self.assertAlmostEqual(result_submaker.cues[1].start.total_seconds(), 3.5 + 0.2, places=2)
            self.assertAlmostEqual(result_submaker.cues[1].end.total_seconds(), 3.5 + 1.8, places=2)

            # 验证 legacy offset 也正确偏移
            self.assertEqual(len(result_submaker.offset), 2)
            self.assertEqual(result_submaker.offset[0], (1000000, 15000000))
            expected_ns_offset = int(3.5 * 10000000)
            self.assertEqual(
                result_submaker.offset[1],
                (2000000 + expected_ns_offset, 18000000 + expected_ns_offset),
            )


    def test_pause_invalid_and_excessive_durations(self):
        """测试无效时长（<= 0s）被忽略，以及超长时长被限制在最大上限内。"""
        # 1. 无效或零时长：不应识别为停顿段
        zero_script = "Hello [pause: 0s] world. [pause: -2s] Bye."
        segments = utils.parse_script_with_pauses(zero_script)
        speech_only = [s for s in segments if s[0] == "speech"]
        pause_only = [s for s in segments if s[0] == "pause"]
        self.assertEqual(len(pause_only), 0)
        self.assertTrue(any("Hello" in s[1] for s in speech_only))
        self.assertTrue(any("world" in s[1] for s in speech_only))

        # 2. 超长停顿：超过 MAX_PAUSE_DURATION_SECONDS 被 clamp
        long_script = "Hello [pause: 99s] world."
        segments_long = utils.parse_script_with_pauses(long_script)
        pauses = [s for s in segments_long if s[0] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0][1], utils.MAX_PAUSE_DURATION_SECONDS)

    def test_pause_consecutive_merging(self):
        """测试连续停顿标签自动合并为一个停顿段，且总时长受上限保护。"""
        # 两个连续停顿合并为 1s + 2s = 3s
        script = "First part. [pause: 1s] [pause: 2s] Second part."
        segments = utils.parse_script_with_pauses(script)
        pauses = [s for s in segments if s[0] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0][1], 3.0)

        # 多个停顿叠加超过最大上限时，合并后被截断在 MAX_PAUSE_DURATION_SECONDS
        over_script = "Start. [pause: 7s] [pause: 8s] End."
        over_segments = utils.parse_script_with_pauses(over_script)
        over_pauses = [s for s in over_segments if s[0] == "pause"]
        self.assertEqual(len(over_pauses), 1)
        self.assertEqual(over_pauses[0][1], utils.MAX_PAUSE_DURATION_SECONDS)

    def test_pause_leading_and_trailing(self):
        """测试开头停顿（leading）和结尾停顿（trailing）的音轨和时间轴偏移。"""
        from edge_tts.srt_composer import Subtitle

        fake_sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        fake_sub.cues = [
            Subtitle(1, timedelta(seconds=0.1), timedelta(seconds=1.2), "Hello"),
        ]
        fake_sub.subs = ["Hello"]
        fake_sub.offset = [(1000000, 12000000)]

        def fake_single_tts(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
            _write_test_wav(voice_file, 1.2)
            return fake_sub

        def fake_silence(duration, voice_file):
            _write_test_wav(voice_file, duration)
            return True

        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs, "_single_tts", side_effect=fake_single_tts),
            patch.object(vs, "generate_silent_audio", side_effect=fake_silence) as mock_silence,
            patch.object(vs, "_concat_audio_files", return_value=True),
        ):
            # Leading pause: [pause: 1.5s] Hello
            out_file = str(Path(tmp_dir) / "leading.mp3")
            result = vs.tts(
                text="[pause: 1.5s] Hello",
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file=out_file,
            )
            self.assertIsNotNone(result)
            mock_silence.assert_called_with(1.5, mock_silence.call_args[0][1])
            # 字幕 cue 应该从 1.5s + 0.1s = 1.6s 开始
            self.assertAlmostEqual(result.cues[0].start.total_seconds(), 1.6, places=2)

        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs, "_single_tts", side_effect=fake_single_tts),
            patch.object(vs, "generate_silent_audio", side_effect=fake_silence) as mock_silence,
            patch.object(vs, "_concat_audio_files", return_value=True),
        ):
            # Trailing pause: Hello [pause: 2s]
            out_file = str(Path(tmp_dir) / "trailing.mp3")
            result = vs.tts(
                text="Hello [pause: 2s]",
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file=out_file,
            )
            self.assertIsNotNone(result)
            mock_silence.assert_called_with(2.0, mock_silence.call_args[0][1])
            # 语音字幕应该保持在原本位置，不受结尾静音后移
            self.assertAlmostEqual(result.cues[0].start.total_seconds(), 0.1, places=2)
            self.assertAlmostEqual(result.cues[0].end.total_seconds(), 1.2, places=2)

    def test_pause_script_with_only_pauses(self):
        """测试脚本只包含停顿标签时的纯静音生成与安全性。"""
        def fake_silence(duration, voice_file):
            _write_test_wav(voice_file, duration)
            return True

        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs, "generate_silent_audio", side_effect=fake_silence) as mock_silence,
            patch.object(vs, "_single_tts") as mock_single_tts,
        ):
            out_file = str(Path(tmp_dir) / "only_pauses.mp3")
            result = vs.tts(
                text="[pause: 2.5s]",
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file=out_file,
            )
            self.assertIsNotNone(result)
            mock_single_tts.assert_not_called()
            mock_silence.assert_called_once_with(2.5, out_file)
            self.assertEqual(vs.get_audio_duration(result), 2.5)

            # 字幕生成应安全处理无台词脚本，不抛出异常
            srt_path = str(Path(tmp_dir) / "only_pauses.srt")
            vs.create_subtitle(result, "[pause: 2.5s]", srt_path, word_level=False)
            vs.create_subtitle(result, "[pause: 2.5s]", srt_path, word_level=True)

    def test_subtitle_sync_sentence_mode_with_pauses(self):
        """测试句子模式 (sentence) 下包含停顿标签的字幕时间轴与内容完全同步。"""
        from edge_tts.srt_composer import Subtitle

        fake_sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        # 第一段话在 0.1s - 1.5s，第二段话在停顿 2s 后 (3.5s - 5.0s)
        fake_sub.cues = [
            Subtitle(1, timedelta(seconds=0.1), timedelta(seconds=0.7), "Primera"),
            Subtitle(2, timedelta(seconds=0.8), timedelta(seconds=1.5), "frase."),
            Subtitle(3, timedelta(seconds=3.6), timedelta(seconds=4.2), "Segunda"),
            Subtitle(4, timedelta(seconds=4.3), timedelta(seconds=5.0), "frase."),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            srt_file = str(Path(tmp_dir) / "sentence_mode.srt")
            raw_script = "Primera frase. [pausa: 2s] Segunda frase."
            vs.create_subtitle(
                sub_maker=fake_sub,
                text=raw_script,
                subtitle_file=srt_file,
                word_level=False,
            )

            self.assertTrue(os.path.exists(srt_file))
            with open(srt_file, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("Primera frase", content)
            self.assertIn("Segunda frase", content)
            self.assertNotIn("[pausa", content)
            # 第一句开始于 0.1s，第二句开始于 3.6s (体现了 2s 停顿)
            self.assertIn("00:00:00,100 --> 00:00:01,500", content)
            self.assertIn("00:00:03,600 --> 00:00:05,000", content)

    def test_subtitle_sync_word_mode_with_pauses(self):
        """测试单字模式 (word_by_word) 下包含停顿标签的字幕时间轴与内容完全同步。"""
        from edge_tts.srt_composer import Subtitle

        fake_sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        fake_sub.cues = [
            Subtitle(1, timedelta(seconds=0.1), timedelta(seconds=0.5), "Hello"),
            Subtitle(2, timedelta(seconds=0.6), timedelta(seconds=1.2), "world."),
            Subtitle(3, timedelta(seconds=3.3), timedelta(seconds=3.8), "Good"),
            Subtitle(4, timedelta(seconds=3.9), timedelta(seconds=4.5), "morning."),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            srt_file = str(Path(tmp_dir) / "word_mode.srt")
            raw_script = "Hello world. [pause: 2s] Good morning."
            vs.create_subtitle(
                sub_maker=fake_sub,
                text=raw_script,
                subtitle_file=srt_file,
                word_level=True,
            )

            self.assertTrue(os.path.exists(srt_file))
            with open(srt_file, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("Hello", content)
            self.assertIn("world.", content)
            self.assertIn("Good", content)
            self.assertIn("morning.", content)
            # 第二段词条被正确偏移到了 3.3s 和 3.9s
            self.assertIn("00:00:00,100 --> 00:00:00,500", content)
            self.assertIn("00:00:03,300 --> 00:00:03,800", content)
            self.assertIn("00:00:03,900 --> 00:00:04,500", content)

    def test_tts_without_pauses_calls_single_tts_directly(self):
        """验证不包含停顿标签时，直接调用 _single_tts，原有行为和性能完全不变。"""
        with (
            patch.object(vs, "_single_tts", return_value="normal_submaker") as mock_single_tts,
            patch.object(vs, "_tts_with_pauses") as mock_pauses,
        ):
            res = vs.tts(
                text="This is regular text without any pauses.",
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file="any.mp3",
            )
            self.assertEqual(res, "normal_submaker")
            mock_single_tts.assert_called_once()
            mock_pauses.assert_not_called()

    def test_pause_invalid_tags_rejected_and_cleaned(self):
        """验证非法标签（如 [pause: -2s]、[pause: nope]、[pause: 0s]）被彻底过滤，不朗读也不生成静音。"""
        # 1. utils.remove_pause_tags 彻底清除所有非法标签
        dirty_text = "Hello [pause: 0s] world. [pause: -2s] [pause: nope] Bye."
        cleaned = utils.remove_pause_tags(dirty_text)
        self.assertNotIn("[pause", cleaned)
        self.assertNotIn("-2s", cleaned)
        self.assertNotIn("nope", cleaned)
        self.assertIn("Hello world.", cleaned)
        self.assertIn("Bye.", cleaned)

        # 2. parse_script_with_pauses 忽略非法标签，且文案中不包含这些标签
        segments = utils.parse_script_with_pauses(dirty_text)
        pauses = [s for s in segments if s[0] == "pause"]
        speech = [s for s in segments if s[0] == "speech"]
        self.assertEqual(len(pauses), 0)
        self.assertEqual(len(speech), 3)
        for _, text in speech:
            self.assertNotIn("[pause", text)
            self.assertNotIn("-2s", text)
            self.assertNotIn("nope", text)

        # 3. 当脚本全是非法标签时，tts 回退到 _single_tts，传递清洗后的文案而不是原始脏文本
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs, "_single_tts", return_value="submaker_ok") as mock_single,
        ):
            out_file = str(Path(tmp_dir) / "cleaned.mp3")
            res = vs.tts(
                text="Hello [pause: 0s] world [pause: -2s] [pause: nope]",
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file=out_file,
            )
            self.assertEqual(res, "submaker_ok")
            mock_single.assert_called_once()
            called_text = mock_single.call_args[1].get("text") or mock_single.call_args[0][0]
            self.assertNotIn("[pause", called_text)
            self.assertNotIn("-2s", called_text)
            self.assertNotIn("nope", called_text)
            self.assertIn("Hello world", called_text)

    def test_pause_minimum_duration_validation(self):
        """验证微小停顿（如 1ms）会被校验并限制在最低有效阈值 MIN_PAUSE_DURATION_SECONDS (0.1s/100ms)。"""
        script = "Start [pause: 1ms] End"
        segments = utils.parse_script_with_pauses(script)
        pauses = [s for s in segments if s[0] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0][1], utils.MIN_PAUSE_DURATION_SECONDS)
        self.assertEqual(utils.MIN_PAUSE_DURATION_SECONDS, 0.1)

    def test_tts_provider_limitation_to_azure_v1(self):
        """验证仅 Azure TTS v1 (Edge TTS) 进入分段链路，Gemini/Fish Audio/SiliconFlow/Kokoro 保持单次请求。"""
        # 1. 声音提供商判断
        self.assertTrue(vs.is_azure_v1_voice("zh-CN-XiaoxiaoNeural"))
        self.assertTrue(vs.is_azure_v1_voice("es-ES-AlvaroNeural"))
        self.assertFalse(vs.is_azure_v1_voice("gemini:Puck-Male"))
        self.assertFalse(vs.is_azure_v1_voice("fish_audio:default"))
        self.assertFalse(vs.is_azure_v1_voice("siliconflow:fishaudio/fish-speech-1.5:alex-Male"))
        self.assertFalse(vs.is_azure_v1_voice("kokoro:af_bella"))
        self.assertFalse(vs.is_azure_v1_voice("elevenlabs:voice-id:voice-name"))

        # 2. 其他提供商脚本含停顿标签时，必须先清除标签并调用单次合成，不调用 _tts_with_pauses
        non_azure_voices = [
            "gemini:Puck-Male",
            "fish_audio:default",
            "siliconflow:fishaudio/fish-speech-1.5:alex-Male",
            "kokoro:af_bella",
        ]
        script_with_pause = "Part 1. [pause: 2s] Part 2."

        for voice in non_azure_voices:
            with (
                patch.object(vs, "_single_tts", return_value="mock_sub") as mock_single,
                patch.object(vs, "_tts_with_pauses") as mock_split,
            ):
                res = vs.tts(
                    text=script_with_pause,
                    voice_name=voice,
                    voice_rate=1.0,
                    voice_file="dummy.mp3",
                )
                self.assertEqual(res, "mock_sub")
                mock_split.assert_not_called()
                mock_single.assert_called_once()
                called_text = mock_single.call_args[1].get("text") or mock_single.call_args[0][0]
                self.assertNotIn("[pause", called_text)
                self.assertIn("Part 1. Part 2.", called_text)

    def test_real_multi_segment_concatenation_no_drift(self):
        """真实音频多段拼接测试：12个1s音频与11个0.5s停顿，验证字幕偏移与真实解码样本完全一致，无累积漂移。"""
        import wave
        import struct
        import math
        import subprocess
        from edge_tts.srt_composer import Subtitle

        sr = 24000
        # 生成标准 1 秒正弦波单声道 16-bit PCM WAV
        speech_pcm = bytearray()
        for i in range(sr):
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * 440.0 * i / sr))
            speech_pcm.extend(struct.pack("<h", val))

        def make_fake_speech_submaker(idx):
            sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
            # 每段台词在自身片段内的 cue 从 0.0s 到 1.0s
            sub.cues = [
                Subtitle(1, timedelta(seconds=0.0), timedelta(seconds=1.0), f"Word_{idx}"),
            ]
            sub.subs = [f"Word_{idx}"]
            sub.offset = [(0, 10000000)]
            sub.duration = 1.0
            return sub

        with tempfile.TemporaryDirectory() as tmp_dir:
            def real_single_tts_wav(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
                # 写入真实的 1 秒 WAV 音频数据
                with wave.open(voice_file, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    wf.writeframes(speech_pcm)
                idx = int(text.split()[-1]) if text.split()[-1].isdigit() else 0
                return make_fake_speech_submaker(idx)

            # 构造 12 个台词段和 11 个 0.5s 停顿的脚本
            script_parts = []
            for i in range(12):
                script_parts.append(f"Word {i}")
                if i < 11:
                    script_parts.append("[pause: 0.5s]")
            full_script = " ".join(script_parts)

            out_mp3 = str(Path(tmp_dir) / "output.mp3")

            # 在不 mock _concat_audio_files 和 get_audio_duration 的情况下运行真实分段链路
            with patch.object(vs, "_single_tts", side_effect=real_single_tts_wav):
                result_submaker = vs._tts_with_pauses(
                    text=full_script,
                    voice_name="zh-CN-XiaoxiaoNeural",
                    voice_rate=1.0,
                    voice_file=out_mp3,
                )

            self.assertIsNotNone(result_submaker)
            self.assertTrue(os.path.exists(out_mp3))
            self.assertGreater(os.path.getsize(out_mp3), 0)

            # 验证字幕线索数量为 12
            self.assertEqual(len(result_submaker.cues), 12)

            # 验证第 12 段（最后一个台词）：
            # 前面经历了 11 个 1.0s 语音 + 11 个 0.5s 停顿 = 11.0s + 5.5s = 16.50s
            last_cue = result_submaker.cues[-1]
            # 严格断言：开始时间必须为 16.50s，绝不能漂移到 17.71s！
            self.assertAlmostEqual(last_cue.start.total_seconds(), 16.50, places=2)
            self.assertAlmostEqual(last_cue.end.total_seconds(), 17.50, places=2)

            # 真实解码输出的 MP3 音频，验证解码后的总样本时长为 17.50s
            decoded_wav = str(Path(tmp_dir) / "decoded.wav")
            ffmpeg_binary = utils.get_ffmpeg_binary()
            subprocess.run(
                [ffmpeg_binary, "-y", "-i", out_mp3, decoded_wav],
                capture_output=True,
                check=True,
            )
            with wave.open(decoded_wav, "rb") as wf:
                total_frames = wf.getnframes()
                total_sr = wf.getframerate()
                decoded_duration = total_frames / float(total_sr)

            # 验证最终解码时长与字幕结尾完全一致（17.50s）
            self.assertAlmostEqual(decoded_duration, 17.50, delta=0.06)

    def test_tts_with_pauses_fails_on_empty_chunk_audio(self):
        """回归测试：当语音片段合成生成了空文件（0字节）或文件丢失时，_tts_with_pauses 报错失败返回 None，绝不能回退生成静音掩盖错误。"""
        from edge_tts.srt_composer import Subtitle

        fake_sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        fake_sub.cues = [
            Subtitle(1, timedelta(seconds=0.0), timedelta(seconds=1.0), "Hello"),
        ]

        def fake_single_tts_empty(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
            Path(voice_file).touch()  # 0-byte empty file
            return fake_sub

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = str(Path(tmp_dir) / "out.mp3")
            with patch.object(vs, "_single_tts", side_effect=fake_single_tts_empty):
                result = vs.tts(
                    text="Hello [pause: 1s] World",
                    voice_name="zh-CN-XiaoxiaoNeural",
                    voice_rate=1.0,
                    voice_file=out_file,
                )
            self.assertIsNone(result)

    def test_tts_with_pauses_fails_on_corrupted_chunk_audio(self):
        """回归测试：当语音片段音频损坏无法解码为 PCM 时，_tts_with_pauses 必须报错返回 None，而不是用静音代替旁白继续执行。"""
        from edge_tts.srt_composer import Subtitle

        fake_sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        fake_sub.cues = [
            Subtitle(1, timedelta(seconds=0.0), timedelta(seconds=1.0), "Hello"),
        ]

        def fake_single_tts_corrupted(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
            with open(voice_file, "wb") as f:
                f.write(b"NOT_A_VALID_AUDIO_FILE_DATA_CORRUPTED_1234567890")
            return fake_sub

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = str(Path(tmp_dir) / "out.mp3")
            with patch.object(vs, "_single_tts", side_effect=fake_single_tts_corrupted):
                result = vs.tts(
                    text="Hello [pause: 1s] World",
                    voice_name="zh-CN-XiaoxiaoNeural",
                    voice_rate=1.0,
                    voice_file=out_file,
                )
            self.assertIsNone(result)

    def test_tts_passes_original_text_unchanged_without_pauses(self):
        """测试无停顿标签时，tts 将原始文本原样直通给 _single_tts，不执行正则替换或清洗。"""
        original_text = "  Leading and trailing spaces, [regular bracket] and punctuation!  \nNew line here.  "
        with patch.object(vs, "_single_tts", return_value="dummy_submaker") as mock_single:
            result = vs.tts(
                text=original_text,
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file="out.mp3",
            )
            self.assertEqual(result, "dummy_submaker")
            mock_single.assert_called_once()
            called_text = mock_single.call_args[1].get("text") or mock_single.call_args[0][0]
            self.assertEqual(called_text, original_text)


if __name__ == "__main__":
    # python -m unittest test.services.test_voice.TestVoiceService.test_azure_tts_v1
    # python -m unittest test.services.test_voice.TestVoiceService.test_azure_tts_v2
    unittest.main()
