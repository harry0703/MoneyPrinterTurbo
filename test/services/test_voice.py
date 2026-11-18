import asyncio
import base64
import os
import shutil
import subprocess
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
        # The data has moved from an inline string to azure_voices.json; make sure it still loads completely
        self.assertEqual(len(voices), 331)
        # The result should be in "Name-Gender" format and sorted
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
        No-voice-over mode doesn't call any external TTS provider and only generates silent audio as a timeline placeholder.
        FFmpeg is mocked here to verify that the request parameters, output file and legacy subtitle structure all meet the expectations
        of the later video composition pipeline.
        """

        def fake_run(command, capture_output, text, check, **kwargs):
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
        Custom audio (custom_audio_file) is often in non-mp3 formats such as m4a/wav/aac.
        get_audio_duration must not report "Invalid target type" and return 0 just because the extension isn't .mp3,
        but should hand it to moviepy (ffmpeg) to read the real duration.
        """
        for path in ("custom-audio.m4a", "voice.wav", "clip.aac"):
            with patch.object(vs.os.path, "exists", return_value=True), \
                    patch.object(vs, "AudioFileClip") as mock_afc:
                mock_afc.return_value.__enter__.return_value.duration = 28.89
                self.assertEqual(vs.get_audio_duration(path), 28.89)
                mock_afc.assert_called_once_with(path)

    def test_get_audio_duration_missing_file_returns_zero(self):
        """Safely return 0 when the audio file doesn't exist, instead of raising or failing to read."""
        with patch.object(vs.os.path, "exists", return_value=False):
            self.assertEqual(vs.get_audio_duration("does-not-exist.m4a"), 0.0)

    def test_no_voice_alias_none_is_supported_temporarily(self):
        """
        Support the none sentinel once used in PR #981, so the few users calling the API directly
        don't break immediately after upgrading. The new UI and new code still use no-voice.
        """
        self.assertTrue(vs.is_no_voice("none"))
        self.assertTrue(vs.is_no_voice(vs.NO_VOICE_NAME))
        self.assertFalse(vs.is_no_voice(""))

    def test_no_voice_duration_estimates_non_ascii_languages(self):
        """
        No voice-over has no real TTS audio, so reading time can only be estimated from the script text. Non-ASCII text such as Russian, Arabic,
        Japanese kana and Korean must also count toward the estimate, rather than all falling to the 3-second minimum.
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
        Even if the FFmpeg process returns success, confirm the output file really exists and isn't empty. This keeps
        the error contained in the TTS stage rather than surfacing only later during video composition.
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

    def test_no_voice_ffmpeg_timeout_preserves_previous_output(self):
        def timed_out(command, **kwargs):
            self.assertIn("-nostdin", command)
            self.assertGreater(kwargs.get("timeout", 0), 0)
            Path(command[-1]).write_bytes(b"partial-silence")
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "silent.mp3"
            output.write_bytes(b"previous-success")
            with patch.object(vs.subprocess, "run", side_effect=timed_out):
                self.assertFalse(vs.generate_silent_audio(3.0, str(output)))
            self.assertEqual(output.read_bytes(), b"previous-success")

    def test_empty_voice_name_does_not_enable_no_voice_mode(self):
        """
        An empty voice usually means missing config or a wrong API parameter, and must not switch to no-voice-over mode automatically.
        Otherwise users with a mistyped TTS config would also get a "successful" silent video, which is harder to diagnose.
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
        # The SiliconFlow API Key lives in [siliconflow].api_key, and the runtime code also reads it from
        # config.siliconflow; the same config source must be used here, so the test isn't wrongly skipped
        # when credentials are configured correctly.
        if not vs.config.siliconflow.get("api_key"):
            self.skipTest("siliconflow_api_key is not configured")

        voice_name = "siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male"
        voice_name = vs.parse_voice_name(voice_name)
        
        async def _do():
            parts = voice_name.split(":")
            if len(parts) >= 3:
                model = parts[1]
                # Remove the gender suffix, e.g. "alex-Male" -> "alex"
                voice_with_gender = parts[2]
                voice = voice_with_gender.split("-")[0]
                # Build the full voice parameter, in the format "model:voice"
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
                self.assertGreater(audio_duration, 0)
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

        voice_file = f"{temp_dir}/tts-azure-v1-{voice_name}.mp3"
        subtitle_file = f"{temp_dir}/tts-azure-v1-{voice_name}.srt"
        sub_maker = vs.azure_tts_v1(
            text=text_zh, voice_name=voice_name, voice_file=voice_file, voice_rate=voice_rate
        )
        if not sub_maker:
            self.fail("azure tts v1 failed")
        vs.create_subtitle(sub_maker=sub_maker, text=text_zh, subtitle_file=subtitle_file)
        audio_duration = vs.get_audio_duration(sub_maker)
        self.assertGreater(audio_duration, 0)

    def test_azure_tts_v1_supports_legacy_edge_tts_without_boundary(self):
        """
        Verify Azure TTS V1 keeps working when an old edge_tts dependency lingers.

        This regression scenario corresponds to a failed Windows portable package update, where the field environment is still on an old
        edge_tts:
        1. `Communicate.__init__()` doesn't accept `boundary`
        2. Only an async `stream()` exists, no `stream_sync()`
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

    def test_azure_tts_v1_rejects_boundary_only_stream(self):
        """Subtitle events without audio must not produce a successful TTS result."""

        class _BoundaryOnlyCommunicate:
            def __init__(self, text, voice, rate="+0%", boundary=None):
                pass

            def stream_sync(self):
                yield {
                    "type": "WordBoundary",
                    "offset": 0,
                    "duration": 10000000,
                    "text": "hello",
                }

        class _FakeSubMaker:
            def __init__(self):
                self.events = []

            def feed(self, chunk):
                self.events.append(chunk)

            def get_srt(self):
                return "1\n00:00:00,000 --> 00:00:01,000\nhello\n" if self.events else ""

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.edge_tts, "Communicate", _BoundaryOnlyCommunicate
        ), patch.object(vs.edge_tts, "SubMaker", _FakeSubMaker):
            voice_file = Path(tmp_dir) / "boundary-only.mp3"
            result = vs.azure_tts_v1(
                text="hello",
                voice_name="en-US-AriaNeural-Female",
                voice_file=str(voice_file),
                voice_rate=1.0,
            )

            self.assertIsNone(result)
            self.assertFalse(voice_file.exists())

    def test_azure_tts_v1_times_out_hanging_stream_sync(self):
        """
        Verify Azure TTS V1 fails fast when the edge_tts sync stream hangs.

        In the field, when the network fails, the server rate-limits, or the voice language doesn't match the text,
        `stream_sync()` may not return for a long time, leaving the WebUI task stuck at
        `start, voice name...`. A blocking fake stream reproduces that scenario here,
        confirming the timeout protection ends the function and returns None.
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
            self.assertGreater(audio_duration, 0)

        self.loop.run_until_complete(_do())

    def test_azure_tts_v2_ssml_applies_rate_and_escapes_text(self):
        """Azure V2 must apply the speech rate via SSML, and user text must not break the XML."""
        ssml = vs._build_azure_v2_ssml(
            text='A < B & "quoted"',
            voice_name="zh-CN-XiaoxiaoMultilingualNeural",
            voice_rate=1.8,
        )

        self.assertIn('xml:lang="zh-CN"', ssml)
        self.assertIn('rate="1.8"', ssml)
        self.assertIn("A &lt; B &amp; \"quoted\"", ssml)

    def test_tts_forwards_rate_to_azure_v2(self):
        """The unified TTS entry must not lose voice_rate when dispatching to Azure V2."""
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
        """The official style description in the Gemini dropdown must not become part of the API voice_name."""
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
        Verify Gemini TTS still returns the project's compatible subtitle structure under edge_tts 7.x,
        and that it can be consumed directly by the `subtitle_provider=edge` subtitle pipeline,
        avoiding another fallback to Whisper. A nonexistent nested output directory is also used, covering the edge case where the API or
        CLI calls the service directly without creating the task directory first.
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
        Verify Xiaomi MiMo TTS can consume the OpenAI-compatible audio response structure.

        A fake OpenAI client and fake AudioSegment replace the real network and ffmpeg here,
        confirming the runtime code puts the text to synthesize into an assistant message and exports the returned
        base64 WAV audio to the audio file used by the project's later flow.
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
        class _FakeClient:
            chat = SimpleNamespace(completions=fake_completions)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

        fake_client = _FakeClient()

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
                mimo_tts_style_prompt="Read with clear Chinese narration.",
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
            max_retries=0,
            timeout=120.0,
        )
        self.assertTrue(fake_client.closed)
        self.assertEqual(fake_completions.kwargs["model"], "mimo-v2.5-tts")
        self.assertEqual(
            fake_completions.kwargs["messages"],
            [
                {"role": "user", "content": "Read with clear Chinese narration."},
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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
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

        def _post(url, json=None, headers=None, timeout=None, allow_redirects=True):
            self.assertFalse(allow_redirects)
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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_minimax_tts_reuses_cn_llm_key_and_endpoint(self):
        """When TTS isn't configured separately, the same-region MiniMax LLM credentials and address should be reused."""
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

        def _post(url, json=None, headers=None, timeout=None, allow_redirects=True):
            self.assertFalse(allow_redirects)
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
        """Voice queries should unify response structures from different sources and ignore duplicate or empty Voice IDs."""

        class _Response:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {
                    "system_voice": [
                        {"voice_id": "system-1", "voice_name": "System voice"},
                        {"voice_id": "", "voice_name": "Invalid voice"},
                    ],
                    "voice_cloning": [
                        {"voice_id": "clone-1", "voice_name": "My cloned voice"},
                        {"voice_id": "system-1", "voice_name": "Duplicate voice"},
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
                    "voice_name": "System voice",
                    "voice_type": "system",
                },
                {
                    "voice_id": "clone-1",
                    "voice_name": "My cloned voice",
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
        """Remote business errors should be raised explicitly, not disguised as the account having no available voices."""

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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_minimax_tts_does_not_leave_invalid_audio_output(self):
        """When the response audio can't be parsed, the existing file must not be overwritten and no temp file left behind."""
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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
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

        def _fake_post(url, json=None, headers=None, timeout=None, allow_redirects=True):
            self.assertFalse(allow_redirects)
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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_elevenlabs_tts_audio_clip_closed_on_duration_error(self):
        """AudioFileClip.close() must be called even when reading .duration raises."""
        close_calls: list = []
        BrokenClip = self._make_broken_clip_class(close_calls)

        class _OkResponse:
            status_code = 200
            content = b"fake-mp3"
            text = ""

            def iter_content(self, chunk_size):
                yield self.content

            def close(self):
                pass

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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
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
        Verify the legacy subtitle structure returned by Gemini TTS produces an SRT directly under the edge provider,
        without falling back to Whisper because of matching failures.
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
        Edge TTS returns "1,000 years" as continuous text. Script sentence splitting must not treat
        the English comma inside a number as a sentence boundary, otherwise subtitle aggregation hits the issue #894
        case where sub_items has fewer entries than script_lines and wrongly falls back to Whisper.
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
        Reproduce the key shape of issue #894: the last sentence in the Edge cues is returned as continuous text
        containing `1,000 years`. Script sentence splitting must match the cue aggregation result and must not
        split it into two subtitles.
        """
        text = (
            "The ocean isn't just sitting still, it moves around the world like a massive "
            "amusement park ride! Cold water at the North and South Poles sinks to the "
            "bottom because it is heavy and salty. At the same time, warm water from the "
            "sunny equator flows along the top to take its place. This creates a giant "
            "underwater conveyor belt that travels all the way around the Earth. It takes "
            "about 1,000 years for a single drop of water to finish the whole trip!"
        )
        script_lines = utils.split_string_by_punctuations(text)
        cues = []
        for index, line in enumerate(script_lines):
            # Edge cue content often lacks the script's spaces and punctuation layout; spaces are removed here
            # to simulate a stricter matching scenario.
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

    def test_script_split_keeps_clock_time_colon(self):
        """
        Edge TTS returns a clock time such as "10:30" as one word, so the script split
        must not break a line at its colon.
        """
        text = "The class starts at 10:30 every morning. We film everything in 16:9."

        self.assertEqual(
            utils.split_string_by_punctuations(text),
            ["The class starts at 10:30 every morning", "We film everything in 16:9"],
        )

    def test_edge_cue_aggregation_handles_clock_time(self):
        """
        The word boundaries edge-tts 7.3.1 returns for this script with en-US-JennyNeural:
        "10:30" is one word, "16:9" is three. Both lines must still get a subtitle each,
        without falling back to Whisper.
        """
        text = "We film everything in 16:9. The class starts at 10:30 every morning."
        script_lines = utils.split_string_by_punctuations(text)
        words = "We film everything in 16 : 9 The class starts at 10:30 every morning".split()
        cues = [
            SimpleNamespace(
                content=word,
                start=timedelta(seconds=index * 0.3),
                end=timedelta(seconds=index * 0.3 + 0.25),
            )
            for index, word in enumerate(words)
        ]

        sub_items = vs._build_subtitle_items_from_edge_cues(
            SimpleNamespace(cues=cues), script_lines
        )

        self.assertEqual(len(sub_items), len(script_lines))
        self.assertIn("10:30 every morning", sub_items[-1])

    def test_script_split_keeps_fullwidth_separators_between_digits(self):
        """
        Chinese and Japanese scripts often write times, scores and numbers with the
        full-width "：", "，" or "、". Edge TTS (zh-CN-XiaoxiaoNeural) returns "10：30", "3：2",
        "1，299元" and "第1、2" as one word each, so the script split must not break a line
        inside them.
        """
        text = "会议在10：30开始，请准时参加。比分是3：2，价格是1，299元。第1、2名都是中国选手。"

        self.assertEqual(
            utils.split_string_by_punctuations(text),
            [
                "会议在10：30开始",
                "请准时参加",
                "比分是3：2",
                "价格是1，299元",
                "第1、2名都是中国选手",
            ],
        )

    def test_edge_cue_aggregation_handles_fullwidth_separators_between_digits(self):
        """
        The word boundaries edge-tts 7.3.1 returns for this script with
        zh-CN-XiaoxiaoNeural: "10：30", "1，299元" and "第1、2" are one word each.
        Every line must still get its own subtitle.
        """
        text = "会议在10：30开始，请准时参加。价格是1，299元。第1、2名都是中国选手。"
        script_lines = utils.split_string_by_punctuations(text)
        words = [
            *"会议 在 10：30 开始 请 准时 参加".split(),
            *"价格 是 1，299元".split(),
            *"第1、2 名都 是 中国 选手".split(),
        ]
        cues = [
            SimpleNamespace(
                content=word,
                start=timedelta(seconds=index * 0.3),
                end=timedelta(seconds=index * 0.3 + 0.25),
            )
            for index, word in enumerate(words)
        ]

        sub_items = vs._build_subtitle_items_from_edge_cues(
            SimpleNamespace(cues=cues), script_lines
        )

        self.assertEqual(len(sub_items), len(script_lines))
        self.assertIn("会议在10：30开始", sub_items[0])
        self.assertIn("价格是1，299元", sub_items[2])
        self.assertIn("第1、2名都是中国选手", sub_items[3])

    def test_script_split_keeps_dots_inside_abbreviations_and_names(self):
        """A dot between two letters belongs to "U.S.", "e.g." or "example.com", not a line break."""
        text = (
            "The U.S. economy grew. Visit example.com for the details, e.g. the prices."
        )

        self.assertEqual(
            utils.split_string_by_punctuations(text),
            [
                "The U.S",
                "economy grew",
                "Visit example.com for the details",
                "e.g",
                "the prices",
            ],
        )

    def test_script_split_breaks_cjk_sentences_at_half_width_full_stops(self):
        """
        A Chinese or Japanese sentence ended with "." instead of "。" is still a
        sentence end, unlike the dot inside "U.S." or "example.com".
        """
        text = "今天天气很好.我们去公园散步.然后一起吃午饭.美国U.S.经济增长了.今日はいい天気です.公園に行きます."

        self.assertEqual(
            utils.split_string_by_punctuations(text),
            [
                "今天天气很好",
                "我们去公园散步",
                "然后一起吃午饭",
                "美国U.S",
                "经济增长了",
                "今日はいい天気です",
                "公園に行きます",
            ],
        )

    def test_edge_cue_aggregation_handles_dotted_abbreviations(self):
        """
        The word boundaries edge-tts 7.3.1 returns for each of these sentences with
        en-US-AriaNeural: "U.S.", "9 a.m." and "example.com" are one word each. Every line
        must still get its own subtitle, without falling back to Whisper.
        """
        text = (
            "The U.S. economy grew last year. Dr. Smith arrives at 9 a.m. sharp. "
            "Visit example.com for the details."
        )
        script_lines = utils.split_string_by_punctuations(text)
        words = [
            *"The U.S. economy grew last year Dr. Smith arrives at".split(),
            "9 a.m.",
            *"sharp Visit example.com for the details".split(),
        ]
        cues = [
            SimpleNamespace(
                content=word,
                start=timedelta(seconds=index * 0.3),
                end=timedelta(seconds=index * 0.3 + 0.25),
            )
            for index, word in enumerate(words)
        ]

        sub_items = vs._build_subtitle_items_from_edge_cues(
            SimpleNamespace(cues=cues), script_lines
        )

        self.assertEqual(len(sub_items), len(script_lines))
        self.assertIn("Smith arrives at 9 a.m", sub_items[-3])
        self.assertIn("Visit example.com for the details", sub_items[-1])

    def test_script_split_keeps_dots_between_letters_and_digits(self):
        """
        Edge TTS usually returns "No.1", "Vol.2", "Fig.3" and the full-width "ＮＯ.1" as one
        word, so a dot between a letter and a digit is no line break. A dot followed by a
        space still ends the sentence, and so does a dot right after a Chinese character, as
        in "很好.2025年".
        """
        self.assertEqual(
            utils.split_string_by_punctuations(
                "这款手机销量No.1，值得购买。我们发布了Vol.2版本。全网销量ＮＯ.1。"
                "今天天气很好.2025年会更好."
            ),
            [
                "这款手机销量No.1",
                "值得购买",
                "我们发布了Vol.2版本",
                "全网销量ＮＯ.1",
                "今天天气很好",
                "2025年会更好",
            ],
        )
        self.assertEqual(
            utils.split_string_by_punctuations(
                "Our brand is No.1 in sales. 3 stores opened this year. "
                "Fig.3 shows version 2.0 of the app."
            ),
            [
                "Our brand is No.1 in sales",
                "3 stores opened this year",
                "Fig.3 shows version 2.0 of the app",
            ],
        )

    def test_edge_cue_aggregation_handles_dots_between_letters_and_digits(self):
        """
        The word boundaries edge-tts 7.3.1 returns for this script with
        zh-CN-XiaoxiaoNeural: "No.1" and "Vol.2" are one word each. Every line must
        still get its own subtitle.
        """
        text = "这款手机销量No.1，值得购买。我们发布了Vol.2版本，欢迎体验。"
        script_lines = utils.split_string_by_punctuations(text)
        words = "这 款 手机 销量 No.1 值得 购买 我们 发布 了 Vol.2 版本 欢迎 体验".split()
        cues = [
            SimpleNamespace(
                content=word,
                start=timedelta(seconds=index * 0.3),
                end=timedelta(seconds=index * 0.3 + 0.25),
            )
            for index, word in enumerate(words)
        ]

        sub_items = vs._build_subtitle_items_from_edge_cues(
            SimpleNamespace(cues=cues), script_lines
        )

        self.assertEqual(len(sub_items), len(script_lines))
        self.assertIn("这款手机销量No.1", sub_items[0])
        self.assertIn("我们发布了Vol.2版本", sub_items[2])

    def test_script_split_supports_arabic_punctuation(self):
        """
        Arabic scripts commonly use ، ؛ ؟ as natural sentence-break punctuation. Sentence splitting must recognize these
        marks, otherwise edge-tts cue pause boundaries and script line boundaries become misaligned.
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

    def test_script_split_supports_native_full_stops(self):
        """
        Hindi and Bengali (danda), Urdu, Burmese, Khmer and Amharic end sentences
        with their own full stop. Without them the whole script stays one line.
        """
        cases = {
            "यह पहला वाक्य है। यह दूसरा वाक्य है॥ और यह तीसरा वाक्य है।": [
                "यह पहला वाक्य है",
                "यह दूसरा वाक्य है",
                "और यह तीसरा वाक्य है",
            ],
            "یہ پہلا جملہ ہے۔ یہ دوسرا جملہ ہے۔": [
                "یہ پہلا جملہ ہے",
                "یہ دوسرا جملہ ہے",
            ],
            "ဒါက ပထမ စာကြောင်း ဖြစ်ပါတယ်။ ဒါက ဒုတိယ စာကြောင်း ဖြစ်ပါတယ်။": [
                "ဒါက ပထမ စာကြောင်း ဖြစ်ပါတယ်",
                "ဒါက ဒုတိယ စာကြောင်း ဖြစ်ပါတယ်",
            ],
            "នេះជាប្រយោគទីមួយ។ នេះជាប្រយោគទីពីរ។": ["នេះជាប្រយោគទីមួយ", "នេះជាប្រយោគទីពីរ"],
            "ይህ የመጀመሪያው ዓረፍተ ነገር ነው። ይህ ሁለተኛው ዓረፍተ ነገር ነው።": [
                "ይህ የመጀመሪያው ዓረፍተ ነገር ነው",
                "ይህ ሁለተኛው ዓረፍተ ነገር ነው",
            ],
        }
        for text, expected_lines in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    utils.split_string_by_punctuations(text), expected_lines
                )

    def test_edge_cue_aggregation_splits_sentences_at_native_full_stops(self):
        """
        Word boundaries edge-tts 7.3.1 returns for these scripts: hi-IN-SwaraNeural
        leaves the danda out, am-ET-MekdesNeural attaches "።" to the last word.
        Each sentence must still get its own subtitle.
        """
        cases = [
            (
                "यह पहला वाक्य है। यह दूसरा वाक्य है। और यह तीसरा वाक्य है।",
                "यह पहला वाक्य है यह दूसरा वाक्य है और यह तीसरा वाक्य है".split(),
                ["यह पहला वाक्य है", "यह दूसरा वाक्य है", "और यह तीसरा वाक्य है"],
            ),
            (
                "ይህ የመጀመሪያው ዓረፍተ ነገር ነው። ይህ ሁለተኛው ዓረፍተ ነገር ነው።",
                "ይህ የመጀመሪያው ዓረፍተ ነገር ነው። ይህ ሁለተኛው ዓረፍተ ነገር ነው።".split(),
                ["ይህ የመጀመሪያው ዓረፍተ ነገር ነው", "ይህ ሁለተኛው ዓረፍተ ነገር ነው"],
            ),
        ]
        for text, words, expected_lines in cases:
            with self.subTest(text=text):
                script_lines = utils.split_string_by_punctuations(text)
                cues = [
                    SimpleNamespace(
                        content=word,
                        start=timedelta(seconds=index * 0.4),
                        end=timedelta(seconds=index * 0.4 + 0.3),
                    )
                    for index, word in enumerate(words)
                ]

                sub_items = vs._build_subtitle_items_from_edge_cues(
                    SimpleNamespace(cues=cues), script_lines
                )

                self.assertEqual(len(sub_items), len(expected_lines))
                for item, line in zip(sub_items, expected_lines):
                    self.assertIn(line, item)

    def test_script_split_supports_thai_and_lao_sentence_spaces(self):
        """
        Thai and Lao separate sentences with a space instead of a full stop. A space
        next to a number, a word in Latin letters, the repetition mark ๆ or the
        abbreviation mark ฯ is inside the sentence, and Korean keeps its lines.
        """
        coffee = (
            "กาแฟเป็นเครื่องดื่มที่ได้รับความนิยมทั่วโลก ทุกเช้าผู้คนนับล้านเริ่มต้นวันด้วยกาแฟหนึ่งแก้ว "
            "กาแฟช่วยให้ร่างกายตื่นตัวและมีสมาธิมากขึ้น แต่การดื่มมากเกินไปอาจทำให้นอนไม่หลับ"
        )
        cases = {
            coffee: [
                "กาแฟเป็นเครื่องดื่มที่ได้รับความนิยมทั่วโลก",
                "ทุกเช้าผู้คนนับล้านเริ่มต้นวันด้วยกาแฟหนึ่งแก้ว",
                "กาแฟช่วยให้ร่างกายตื่นตัวและมีสมาธิมากขึ้น",
                "แต่การดื่มมากเกินไปอาจทำให้นอนไม่หลับ",
            ],
            "เด็ก ๆ ชอบเล่นฟุตบอล ทุกวันหลังเลิกเรียน": [
                "เด็ก ๆ ชอบเล่นฟุตบอล",
                "ทุกวันหลังเลิกเรียน",
            ],
            "ราคา 100 บาท ถูกมาก ฉันใช้ iPhone ทุกวัน มันดีมาก": [
                "ราคา 100 บาท",
                "ถูกมาก",
                "ฉันใช้ iPhone ทุกวัน",
                "มันดีมาก",
            ],
            "กรุงเทพฯ เป็นเมืองหลวงของประเทศไทย  มีประชากรมากกว่าสิบล้านคน": [
                "กรุงเทพฯ เป็นเมืองหลวงของประเทศไทย",
                "มีประชากรมากกว่าสิบล้านคน",
            ],
            "ສະບາຍດີ ມື້ນີ້ອາກາດດີຫຼາຍ ພວກເຮົາໄປທ່ຽວກັນ": [
                "ສະບາຍດີ",
                "ມື້ນີ້ອາກາດດີຫຼາຍ",
                "ພວກເຮົາໄປທ່ຽວກັນ",
            ],
            "안녕하세요 오늘은 날씨가 좋네요": ["안녕하세요 오늘은 날씨가 좋네요"],
        }
        for text, expected_lines in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    utils.split_string_by_punctuations(text), expected_lines
                )
        self.assertEqual(
            utils.split_string_by_punctuations(
                coffee, split_thai_and_lao_sentences=False
            ),
            [coffee],
        )

    def test_edge_cue_aggregation_splits_thai_and_lao_sentences_at_spaces(self):
        """
        Word boundaries edge-tts 7.3.1 returns for these scripts with
        th-TH-PremwadeeNeural and lo-LA-KeomanyNeural. The Thai words have no space
        in them, except "เด็ก ๆ", and the Lao words are the parts between the
        spaces. Each sentence must still get its own subtitle.
        """
        cases = [
            (
                "กาแฟเป็นเครื่องดื่มที่ได้รับความนิยมทั่วโลก ทุกเช้าผู้คนนับล้านเริ่มต้นวันด้วยกาแฟหนึ่งแก้ว "
                "กาแฟช่วยให้ร่างกายตื่นตัวและมีสมาธิมากขึ้น แต่การดื่มมากเกินไปอาจทำให้นอนไม่หลับ",
                [
                    *"กาแฟ เป็น เครื่อง ดื่ม ที่ ได้ รับ ความ นิยม ทั่ว โลก".split(),
                    *"ทุก เช้า ผู้คน นับ ล้าน เริ่มต้น วัน ด้วย กาแฟ หนึ่ง แก้ว".split(),
                    *"กาแฟ ช่วย ให้ ร่างกาย ตื่นตัว และ มี สมาธิ มาก ขึ้น".split(),
                    *"แต่ การ ดื่ม มาก เกิน ไป อาจ ทำ ให้ นอน ไม่ หลับ".split(),
                ],
                [
                    "กาแฟเป็นเครื่องดื่มที่ได้รับความนิยมทั่วโลก",
                    "ทุกเช้าผู้คนนับล้านเริ่มต้นวันด้วยกาแฟหนึ่งแก้ว",
                    "กาแฟช่วยให้ร่างกายตื่นตัวและมีสมาธิมากขึ้น",
                    "แต่การดื่มมากเกินไปอาจทำให้นอนไม่หลับ",
                ],
            ),
            (
                "เด็ก ๆ ชอบเล่นฟุตบอล ทุกวันหลังเลิกเรียน",
                ["เด็ก ๆ", *"ชอบ เล่น ฟุตบอล ทุก วัน หลัง เลิก เรียน".split()],
                ["เด็ก ๆ ชอบเล่นฟุตบอล", "ทุกวันหลังเลิกเรียน"],
            ),
            (
                "ราคา 100 บาท ถูกมาก ฉันใช้ iPhone ทุกวัน มันดีมาก",
                "ราคา 100 บาท ถูก มาก ฉัน ใช้ iPhone ทุก วัน มัน ดี มาก".split(),
                ["ราคา 100 บาท", "ถูกมาก", "ฉันใช้ iPhone ทุกวัน", "มันดีมาก"],
            ),
            (
                "ສະບາຍດີ ມື້ນີ້ອາກາດດີຫຼາຍ ພວກເຮົາໄປທ່ຽວກັນ",
                "ສະບາຍດີ ມື້ນີ້ອາກາດດີຫຼາຍ ພວກເຮົາໄປທ່ຽວກັນ".split(),
                ["ສະບາຍດີ", "ມື້ນີ້ອາກາດດີຫຼາຍ", "ພວກເຮົາໄປທ່ຽວກັນ"],
            ),
        ]
        for text, words, expected_lines in cases:
            with self.subTest(text=text):
                script_lines = utils.split_string_by_punctuations(text)
                cues = [
                    SimpleNamespace(
                        content=word,
                        start=timedelta(seconds=index * 0.4),
                        end=timedelta(seconds=index * 0.4 + 0.3),
                    )
                    for index, word in enumerate(words)
                ]

                sub_items = vs._build_subtitle_items_from_edge_cues(
                    SimpleNamespace(cues=cues), script_lines
                )

                self.assertEqual(len(sub_items), len(expected_lines))
                for item, line in zip(sub_items, expected_lines):
                    self.assertIn(line, item)

    def test_match_script_line_normalizes_arabic_letter_forms(self):
        """
        edge-tts may normalize different Arabic letter forms, or return cue text with diacritics or
        Tatweel. Matching should tolerate this, while the final subtitles keep the original script text.
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
        Reproduce the core path of the Arabic subtitle failure: the script contains letter forms like أ/ة, and when the edge cues
        return normalized forms like ا/ه, aggregation should still produce complete subtitles, avoiding a Whisper fallback.
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
        Manually written scripts may contain Markdown separators like `---`. TTS doesn't read
        these symbol lines aloud, and subtitle aggregation shouldn't treat them as target subtitle lines either, otherwise later real
        subtitles get stuck and fall back to Whisper.
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
        """Fine-grained Edge TTS cues should be written one by one and no longer aggregated by punctuation."""
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
        When an old SubMaker has no cues, the original timing granularity returned by the speech service should be kept.

        Services like ElevenLabs and Fish Audio may only return phrase- or sentence-level timelines. They must not
        be split evenly by character to fake per-word precision, otherwise subtitles gradually drift from the real speech.
        """
        sub_maker = SimpleNamespace(
            cues=[],
            subs=["Hello world"],
            # The old SubMaker offset uses integer timestamps in units of 100 nanoseconds.
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
        Users often use `_` as a Markdown emphasis marker, but cues returned by TTS usually don't contain
        these formatting symbols. Matching should ignore `_`, avoiding empty subtitles or a Whisper fallback.
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
        # API and batch scripts may pass an empty speech rate as 0, None or an empty string; none of these should make
        # edge-tts receive -100% or raise, but should be treated as the normal rate.
        self.assertEqual(vs.convert_rate_to_percent(0), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(0.0), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(None), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(""), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(float("nan")), "+0%")
        self.assertEqual(vs.convert_rate_to_percent(float("inf")), "+0%")

    def test_edge_voices_with_a_script_subtag_pass_edge_tts_validation(self):
        # edge-tts only expands short names like en-US-AriaNeural; the listed
        # Inuktitut voices carry a script subtag (iu-Cans-CA, iu-Latn-CA).
        prefix = "Microsoft Server Speech Text to Speech Voice"
        for short_name, full_name in (
            ("iu-Cans-CA-SiqiniqNeural", f"{prefix} (iu-Cans-CA, SiqiniqNeural)"),
            ("iu-Latn-CA-TaqqiqNeural", f"{prefix} (iu-Latn-CA, TaqqiqNeural)"),
            ("zh-CN-liaoning-XiaobeiNeural", f"{prefix} (zh-CN-liaoning, XiaobeiNeural)"),
        ):
            with self.subTest(short_name=short_name):
                communicate = vs.create_edge_tts_communicate("word", short_name, "+0%")
                self.assertEqual(communicate.tts_config.voice, full_name)


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
    def test_get_elevenlabs_voices_does_not_forward_key_on_redirect(self, mock_get):
        mock_get.return_value.status_code = 302
        mock_get.return_value.text = "moved"

        self.assertEqual(vs.get_elevenlabs_voices("secret-key"), [])
        self.assertEqual(mock_get.call_args.kwargs["allow_redirects"], False)

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_network_error(self, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.ConnectionError("timeout")
        result = vs.get_elevenlabs_voices("fake-key")
        self.assertEqual(result, [])

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    @patch("app.services.voice.requests.post")
    @patch("app.services.voice.AudioFileClip")
    @patch("app.services.voice.config")
    def test_elevenlabs_tts_success(self, mock_config, mock_clip_cls, mock_post):
        mock_config.elevenlabs.get.return_value = "fake-api-key"
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"fake-mp3-bytes"
        mock_post.return_value.iter_content.return_value = iter((b"fake-mp3-bytes",))
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

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_elevenlabs_tts_rejects_oversize_audio_without_replacing_existing_file(self):
        """A paid 200 response can be much larger than usable speech."""
        response = SimpleNamespace(
            status_code=200,
            content=b"oversize-audio",
            iter_content=lambda chunk_size: iter((b"oversize-audio",)),
            close=lambda: None,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "voice.mp3"
            output.write_bytes(b"previous-valid-audio")
            with (
                patch.object(vs, "get_elevenlabs_api_key", return_value="test-key"),
                patch.object(vs.requests, "post", return_value=response) as post,
                patch.object(vs, "AudioFileClip") as clip,
                patch.object(vs, "_ELEVENLABS_TTS_MAX_AUDIO_BYTES", 5, create=True),
            ):
                clip.return_value.duration = 1.0
                result = vs.elevenlabs_tts("Hello", "voice-id", str(output))

            self.assertIsNone(result)
            self.assertEqual(output.read_bytes(), b"previous-valid-audio")
            self.assertEqual(post.call_count, 1)
            self.assertEqual(sorted(path.name for path in Path(tmp_dir).iterdir()), ["voice.mp3"])

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_elevenlabs_tts_decode_failure_preserves_existing_file(self):
        """A corrupt successful response must not publish a partial final MP3."""
        response = SimpleNamespace(
            status_code=200,
            content=b"corrupt-audio",
            iter_content=lambda chunk_size: iter((b"corrupt-audio",)),
            close=lambda: None,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "voice.mp3"
            output.write_bytes(b"previous-valid-audio")
            with (
                patch.object(vs, "get_elevenlabs_api_key", return_value="test-key"),
                patch.object(vs.requests, "post", return_value=response) as post,
                patch.object(vs, "AudioFileClip", side_effect=OSError("bad mp3")),
            ):
                result = vs.elevenlabs_tts("Hello", "voice-id", str(output))

            self.assertIsNone(result)
            self.assertEqual(output.read_bytes(), b"previous-valid-audio")
            self.assertEqual(post.call_count, 1)
            self.assertEqual(sorted(path.name for path in Path(tmp_dir).iterdir()), ["voice.mp3"])

    def test_elevenlabs_tts_does_not_follow_or_retry_redirect(self):
        response = SimpleNamespace(
            status_code=307,
            close=unittest.mock.Mock(),
            iter_content=unittest.mock.Mock(return_value=iter((b"moved",))),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "voice.mp3"
            with (
                patch.object(vs, "get_elevenlabs_api_key", return_value="secret-key"),
                patch.object(vs.requests, "post", return_value=response) as post,
            ):
                self.assertIsNone(vs.elevenlabs_tts("Hello", "voice-id", str(output)))

            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs["allow_redirects"], False)
            self.assertFalse(output.exists())
            response.close.assert_called_once()

    @patch("app.services.voice.config")
    def test_elevenlabs_tts_no_api_key(self, mock_config):
        mock_config.elevenlabs.get.return_value = ""
        # Key resolution includes an environment variable fallback, so the test must explicitly clear the host environment, so that a dev machine or CI
        # that happens to set ELEVENLABS_API_KEY doesn't change the "not configured" premise of the test.
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
        """TTS and music share the same account config, so both generation paths must resolve the same Key."""
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


    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
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

    def test_siliconflow_tts_bounds_each_network_attempt(self):
        """A pre-connect timeout can be retried without submitting paid work."""
        timeouts = []

        def stalled_post(_url, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            raise vs.requests.exceptions.ConnectTimeout("could not connect")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(vs.requests, "post", side_effect=stalled_post),
            patch.object(vs.config, "siliconflow", {"api_key": "test-key"}),
        ):
            voice_file = str(Path(temp_dir) / "narration.mp3")
            result = vs.siliconflow_tts(
                text="An example narration",
                model="FunAudioLLM/CosyVoice2-0.5B",
                voice="FunAudioLLM/CosyVoice2-0.5B:alex",
                voice_rate=1.0,
                voice_file=voice_file,
            )
            self.assertFalse(Path(voice_file).exists())

        self.assertIsNone(result)
        self.assertEqual(timeouts, [(10, 300)] * 3)

    def test_paid_tts_does_not_repeat_ambiguous_read_timeout(self):
        """A lost POST response may still have created billable speech remotely."""
        settings = {
            "api_key": "test-key",
            "model_id": vs.MINIMAX_TTS_DEFAULT_MODEL,
            "audio_format": "mp3",
        }
        cases = (
            ("elevenlabs", lambda path: vs.elevenlabs_tts("Hello", "voice", path)),
            ("fish", lambda path: vs.fish_audio_tts("Hello", path)),
            (
                "minimax",
                lambda path: vs.minimax_tts("Hello", "voice", 1.0, path),
            ),
            (
                "siliconflow",
                lambda path: vs.siliconflow_tts(
                    "Hello", "model", "voice", 1.0, path
                ),
            ),
        )
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch.object(vs.requests, "post", side_effect=vs.requests.exceptions.ReadTimeout("response lost")) as post,
            patch.object(vs, "get_elevenlabs_api_key", return_value="test-key"),
            patch.object(vs, "get_fish_audio_api_key", return_value="test-key"),
            patch.object(vs, "get_minimax_tts_api_key", return_value="test-key"),
            patch.object(vs, "get_minimax_tts_endpoint", return_value="https://example.test/v1/t2a_v2"),
            patch.object(vs.config, "fish_audio", {"model": vs.FISH_AUDIO_DEFAULT_MODEL}),
            patch.object(vs.config, "minimax_tts", settings),
            patch.object(vs.config, "siliconflow", {"api_key": "test-key"}),
        ):
            for provider, synthesize in cases:
                with self.subTest(provider=provider):
                    post.reset_mock()
                    result = synthesize(str(Path(tmp_dir) / f"{provider}.mp3"))
                    self.assertIsNone(result)
                    post.assert_called_once()

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_siliconflow_tts_rejects_invalid_success_audio(self):
        """HTTP 200 with corrupt audio must not become a fake 10-second success."""
        fake_response = SimpleNamespace(status_code=200, content=b"invalid mp3")
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(vs.requests, "post", return_value=fake_response) as post,
            patch.object(vs, "AudioFileClip", side_effect=OSError("invalid audio")),
            patch.object(vs.config, "siliconflow", {"api_key": "test-key"}),
        ):
            voice_file = str(Path(temp_dir) / "narration.mp3")
            result = vs.siliconflow_tts(
                text="An example narration",
                model="FunAudioLLM/CosyVoice2-0.5B",
                voice="FunAudioLLM/CosyVoice2-0.5B:alex",
                voice_rate=1.0,
                voice_file=voice_file,
            )
            self.assertFalse(Path(voice_file).exists())

        self.assertIsNone(result)
        post.assert_called_once()

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_siliconflow_tts_invalid_audio_preserves_existing_narration(self):
        fake_response = SimpleNamespace(status_code=200, content=b"invalid mp3")
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(vs.requests, "post", return_value=fake_response),
            patch.object(vs, "AudioFileClip", side_effect=OSError("invalid audio")),
            patch.object(vs.config, "siliconflow", {"api_key": "test-key"}),
        ):
            voice_file = Path(temp_dir) / "narration.mp3"
            voice_file.write_bytes(b"previous valid narration")
            result = vs.siliconflow_tts(
                text="An example narration",
                model="FunAudioLLM/CosyVoice2-0.5B",
                voice="FunAudioLLM/CosyVoice2-0.5B:alex",
                voice_rate=1.0,
                voice_file=str(voice_file),
            )

            self.assertIsNone(result)
            self.assertEqual(voice_file.read_bytes(), b"previous valid narration")
            self.assertEqual(list(Path(temp_dir).iterdir()), [voice_file])

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_siliconflow_tts_publishes_only_after_audio_validation(self):
        fake_response = SimpleNamespace(status_code=200, content=b"new mp3")
        with tempfile.TemporaryDirectory() as temp_dir:
            voice_file = Path(temp_dir) / "narration.mp3"
            voice_file.write_bytes(b"previous valid narration")

            def validate_audio(candidate):
                self.assertNotEqual(Path(candidate), voice_file)
                self.assertEqual(voice_file.read_bytes(), b"previous valid narration")
                self.assertEqual(Path(candidate).read_bytes(), b"new mp3")
                return SimpleNamespace(duration=2.5, close=lambda: None)

            with (
                patch.object(vs.requests, "post", return_value=fake_response),
                patch.object(vs, "AudioFileClip", side_effect=validate_audio),
                patch.object(vs.config, "siliconflow", {"api_key": "test-key"}),
            ):
                result = vs.siliconflow_tts(
                    text="An example narration",
                    model="FunAudioLLM/CosyVoice2-0.5B",
                    voice="FunAudioLLM/CosyVoice2-0.5B:alex",
                    voice_rate=1.0,
                    voice_file=str(voice_file),
                )

            self.assertIsNotNone(result)
            self.assertEqual(voice_file.read_bytes(), b"new mp3")
            self.assertEqual(list(Path(temp_dir).iterdir()), [voice_file])

    def test_pause_tag_detection_and_parsing(self):
        """Test detection, parsing and cleaning of multilingual pause tags."""
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

    def test_pause_tags_accept_duration_directly_after_cjk_keyword(self):
        """Chinese and Japanese writers often omit the colon or space, so `[停顿3秒]` must also be recognized as a pause rather than read aloud."""
        script = "大家好。[停顿3秒]今天聊聊理财。[ポーズ2秒]最後。[pause2s]End."

        self.assertTrue(utils.has_pause_tags("[暂停2秒]"))
        self.assertEqual(
            utils.parse_script_with_pauses(script),
            [
                ("speech", "大家好。"),
                ("pause", 3.0),
                ("speech", "今天聊聊理财。"),
                ("pause", 2.0),
                ("speech", "最後。"),
                ("pause", 2.0),
                ("speech", "End."),
            ],
        )
        self.assertNotIn("停顿", utils.remove_pause_tags(script))

        # Ordinary text with a letter right after the keyword is still not a pause tag.
        for text in ("[paused]", "(pauses)", "[暂停一下]"):
            self.assertFalse(utils.has_pause_tags(text), text)

    def test_pause_tags_accept_fullwidth_brackets(self):
        """Full-width brackets typed by Chinese input methods must also be pauses, so the tag text isn't read aloud."""
        samples = (
            ("（停顿：2秒）你好", [("pause", 2.0), ("speech", "你好")]),
            ("（pause: 2s）Hi", [("pause", 2.0), ("speech", "Hi")]),
            ("［pause: 1s］Hi", [("pause", 1.0), ("speech", "Hi")]),
            ("【pause: 1.5s】Hi", [("pause", 1.5), ("speech", "Hi")]),
        )
        for script, expected in samples:
            with self.subTest(script=script):
                self.assertEqual(utils.parse_script_with_pauses(script), expected)
                cleaned = utils.remove_pause_tags(script)
                self.assertNotIn("停顿", cleaned)
                self.assertNotIn("pause", cleaned.lower())
        for text in ("（暂停一下）", "【paused】", "［pauses］"):
            self.assertFalse(utils.has_pause_tags(text), text)

    def test_concat_audio_files_reads_pcm_in_bounded_chunks(self):
        """Long pause-aware narration should not load each WAV into memory."""
        real_wave_open = vs.wave.open
        read_sizes = []

        class RecordingReader:
            def __init__(self, reader):
                self.reader = reader

            def __enter__(self):
                self.reader.__enter__()
                return self

            def __exit__(self, *args):
                return self.reader.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.reader, name)

            def readframes(self, frame_count):
                read_sizes.append(frame_count)
                return self.reader.readframes(frame_count)

        def recording_wave_open(file, mode):
            opened = real_wave_open(file, mode)
            return RecordingReader(opened) if mode == "rb" else opened

        with tempfile.TemporaryDirectory() as temp_dir:
            inputs = [str(Path(temp_dir) / f"input-{i}.wav") for i in range(2)]
            output = str(Path(temp_dir) / "joined.wav")
            for input_path in inputs:
                with real_wave_open(input_path, "wb") as writer:
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(24000)
                    writer.writeframes(b"\x01\x00" * 20000)

            with patch.object(vs.wave, "open", side_effect=recording_wave_open):
                self.assertTrue(vs._concat_audio_files(inputs, output))

            with real_wave_open(output, "rb") as result:
                self.assertEqual(result.getnframes(), 40000)

        self.assertTrue(read_sizes)
        self.assertLessEqual(max(read_sizes), 8192)

    def test_pause_audio_decode_timeout_fails_without_publishing(self):
        def timed_out(command, **kwargs):
            self.assertIn("-nostdin", command)
            self.assertGreater(kwargs.get("timeout", 0), 0)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temp_dir:
            inputs = [str(Path(temp_dir) / f"chunk-{index}.mp3") for index in range(2)]
            for input_path in inputs:
                Path(input_path).write_bytes(b"compressed-audio")
            output = str(Path(temp_dir) / "voice.mp3")
            with patch.object(vs.subprocess, "run", side_effect=timed_out):
                self.assertFalse(vs._concat_audio_files(inputs, output))
            self.assertFalse(Path(output).exists())

    def test_pause_audio_encode_timeout_preserves_previous_output(self):
        def timed_out(command, **kwargs):
            self.assertIn("-nostdin", command)
            self.assertGreater(kwargs.get("timeout", 0), 0)
            Path(command[-1]).write_bytes(b"partial-output")
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temp_dir:
            inputs = [str(Path(temp_dir) / f"chunk-{index}.wav") for index in range(2)]
            for input_path in inputs:
                with vs.wave.open(input_path, "wb") as writer:
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(24000)
                    writer.writeframes(b"\0\0" * 20)
            output = Path(temp_dir) / "voice.mp3"
            output.write_bytes(b"previous-success")
            with patch.object(vs.subprocess, "run", side_effect=timed_out):
                self.assertFalse(vs._concat_audio_files(inputs, str(output)))
            self.assertEqual(output.read_bytes(), b"previous-success")

    def test_tts_with_pauses_shifts_submaker_timeline(self):
        """Test that the SubMaker timeline and audio concatenation are offset correctly when pause tags are present."""
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

            # Verify the second segment's cues are offset by 1.5s + 2.0s = 3.5s
            self.assertEqual(len(result_submaker.cues), 2)
            self.assertAlmostEqual(result_submaker.cues[0].start.total_seconds(), 0.1, places=2)
            self.assertAlmostEqual(result_submaker.cues[0].end.total_seconds(), 1.5, places=2)
            self.assertAlmostEqual(result_submaker.cues[1].start.total_seconds(), 3.5 + 0.2, places=2)
            self.assertAlmostEqual(result_submaker.cues[1].end.total_seconds(), 3.5 + 1.8, places=2)

            # Verify the legacy offset is also offset correctly
            self.assertEqual(len(result_submaker.offset), 2)
            self.assertEqual(result_submaker.offset[0], (1000000, 15000000))
            expected_ns_offset = int(3.5 * 10000000)
            self.assertEqual(
                result_submaker.offset[1],
                (2000000 + expected_ns_offset, 18000000 + expected_ns_offset),
            )


    def test_pause_invalid_and_excessive_durations(self):
        """Test that invalid durations (<= 0s) are ignored and overlong durations are capped at the maximum."""
        # 1. Invalid or zero duration: must not be recognized as a pause segment
        zero_script = "Hello [pause: 0s] world. [pause: -2s] Bye."
        segments = utils.parse_script_with_pauses(zero_script)
        speech_only = [s for s in segments if s[0] == "speech"]
        pause_only = [s for s in segments if s[0] == "pause"]
        self.assertEqual(len(pause_only), 0)
        self.assertTrue(any("Hello" in s[1] for s in speech_only))
        self.assertTrue(any("world" in s[1] for s in speech_only))

        # 2. Overlong pause: anything over MAX_PAUSE_DURATION_SECONDS is clamped
        long_script = "Hello [pause: 99s] world."
        segments_long = utils.parse_script_with_pauses(long_script)
        pauses = [s for s in segments_long if s[0] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0][1], utils.MAX_PAUSE_DURATION_SECONDS)

    def test_pause_consecutive_merging(self):
        """Test that consecutive pause tags are merged into one pause segment, with the total duration capped."""
        # Two consecutive pauses merge into 1s + 2s = 3s
        script = "First part. [pause: 1s] [pause: 2s] Second part."
        segments = utils.parse_script_with_pauses(script)
        pauses = [s for s in segments if s[0] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0][1], 3.0)

        # When several pauses add up to more than the maximum, the merged pause is truncated at MAX_PAUSE_DURATION_SECONDS
        over_script = "Start. [pause: 7s] [pause: 8s] End."
        over_segments = utils.parse_script_with_pauses(over_script)
        over_pauses = [s for s in over_segments if s[0] == "pause"]
        self.assertEqual(len(over_pauses), 1)
        self.assertEqual(over_pauses[0][1], utils.MAX_PAUSE_DURATION_SECONDS)

    def test_pause_leading_and_trailing(self):
        """Test the audio track and timeline offsets of leading and trailing pauses."""
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
            # The subtitle cue should start at 1.5s + 0.1s = 1.6s
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
            # Speech subtitles should stay in place and not be pushed back by the trailing silence
            self.assertAlmostEqual(result.cues[0].start.total_seconds(), 0.1, places=2)
            self.assertAlmostEqual(result.cues[0].end.total_seconds(), 1.2, places=2)

    def test_pause_script_with_only_pauses(self):
        """Test pure silence generation and safety when the script contains only pause tags."""
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

            # Subtitle generation should safely handle a script with no speech, without raising
            srt_path = str(Path(tmp_dir) / "only_pauses.srt")
            vs.create_subtitle(result, "[pause: 2.5s]", srt_path, word_level=False)
            vs.create_subtitle(result, "[pause: 2.5s]", srt_path, word_level=True)

    def test_subtitle_sync_sentence_mode_with_pauses(self):
        """Test that subtitle timeline and content stay fully in sync with pause tags in sentence mode."""
        from edge_tts.srt_composer import Subtitle

        fake_sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
        # The first line is at 0.1s - 1.5s, the second line after a 2s pause (3.5s - 5.0s)
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
            # The first sentence starts at 0.1s, the second at 3.6s (reflecting the 2s pause)
            self.assertIn("00:00:00,100 --> 00:00:01,500", content)
            self.assertIn("00:00:03,600 --> 00:00:05,000", content)

    def test_subtitle_sync_word_mode_with_pauses(self):
        """Test that subtitle timeline and content stay fully in sync with pause tags in word_by_word mode."""
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
            # The second segment's word entries are correctly offset to 3.3s and 3.9s
            self.assertIn("00:00:00,100 --> 00:00:00,500", content)
            self.assertIn("00:00:03,300 --> 00:00:03,800", content)
            self.assertIn("00:00:03,900 --> 00:00:04,500", content)

    def test_tts_without_pauses_calls_single_tts_directly(self):
        """Verify that without pause tags _single_tts is called directly, with original behavior and performance completely unchanged."""
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
        """Verify invalid tags (e.g. [pause: -2s], [pause: nope], [pause: 0s]) are fully filtered, neither read aloud nor producing silence."""
        # 1. utils.remove_pause_tags fully removes all invalid tags
        dirty_text = "Hello [pause: 0s] world. [pause: -2s] [pause: nope] Bye."
        cleaned = utils.remove_pause_tags(dirty_text)
        self.assertNotIn("[pause", cleaned)
        self.assertNotIn("-2s", cleaned)
        self.assertNotIn("nope", cleaned)
        self.assertIn("Hello world.", cleaned)
        self.assertIn("Bye.", cleaned)

        # 2. parse_script_with_pauses ignores invalid tags, and the text doesn't contain them
        segments = utils.parse_script_with_pauses(dirty_text)
        pauses = [s for s in segments if s[0] == "pause"]
        speech = [s for s in segments if s[0] == "speech"]
        self.assertEqual(len(pauses), 0)
        self.assertEqual(len(speech), 3)
        for _, text in speech:
            self.assertNotIn("[pause", text)
            self.assertNotIn("-2s", text)
            self.assertNotIn("nope", text)

        # 3. When the script consists only of invalid tags, tts falls back to _single_tts, passing the cleaned text rather than the raw dirty text
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
        """Verify tiny pauses (e.g. 1ms) are validated and raised to the minimum effective threshold MIN_PAUSE_DURATION_SECONDS (0.1s/100ms)."""
        script = "Start [pause: 1ms] End"
        segments = utils.parse_script_with_pauses(script)
        pauses = [s for s in segments if s[0] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0][1], utils.MIN_PAUSE_DURATION_SECONDS)
        self.assertEqual(utils.MIN_PAUSE_DURATION_SECONDS, 0.1)

    def test_tts_provider_limitation_to_azure_v1(self):
        """Verify only Azure TTS v1 (Edge TTS) enters the segmented pipeline, while Gemini/Fish Audio/SiliconFlow/Kokoro keep a single request."""
        # 1. Voice provider detection
        self.assertTrue(vs.is_azure_v1_voice("zh-CN-XiaoxiaoNeural"))
        self.assertTrue(vs.is_azure_v1_voice("es-ES-AlvaroNeural"))
        self.assertFalse(vs.is_azure_v1_voice("gemini:Puck-Male"))
        self.assertFalse(vs.is_azure_v1_voice("fish_audio:default"))
        self.assertFalse(vs.is_azure_v1_voice("siliconflow:fishaudio/fish-speech-1.5:alex-Male"))
        self.assertFalse(vs.is_azure_v1_voice("kokoro:af_bella"))
        self.assertFalse(vs.is_azure_v1_voice("elevenlabs:voice-id:voice-name"))

        # 2. When other providers' scripts contain pause tags, the tags must be removed first and single synthesis called, without calling _tts_with_pauses
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
        """Real multi-segment audio concatenation test: 12 1s audio clips and 11 0.5s pauses, verifying subtitle offsets match the real decoded samples exactly with no accumulated drift."""
        import wave
        import struct
        import math
        import subprocess
        from edge_tts.srt_composer import Subtitle

        sr = 24000
        # Generate a standard 1-second mono 16-bit PCM WAV sine wave
        speech_pcm = bytearray()
        for i in range(sr):
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * 440.0 * i / sr))
            speech_pcm.extend(struct.pack("<h", val))

        def make_fake_speech_submaker(idx):
            sub = vs.ensure_legacy_submaker_fields(vs.SubMaker())
            # Each line's cue within its own segment runs from 0.0s to 1.0s
            sub.cues = [
                Subtitle(1, timedelta(seconds=0.0), timedelta(seconds=1.0), f"Word_{idx}"),
            ]
            sub.subs = [f"Word_{idx}"]
            sub.offset = [(0, 10000000)]
            sub.duration = 1.0
            return sub

        with tempfile.TemporaryDirectory() as tmp_dir:
            def real_single_tts_wav(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
                # Write real 1-second WAV audio data
                with wave.open(voice_file, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    wf.writeframes(speech_pcm)
                idx = int(text.split()[-1]) if text.split()[-1].isdigit() else 0
                return make_fake_speech_submaker(idx)

            # Build a script with 12 speech segments and 11 0.5s pauses
            script_parts = []
            for i in range(12):
                script_parts.append(f"Word {i}")
                if i < 11:
                    script_parts.append("[pause: 0.5s]")
            full_script = " ".join(script_parts)

            out_mp3 = str(Path(tmp_dir) / "output.mp3")

            # Run the real segmented pipeline without mocking _concat_audio_files and get_audio_duration
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

            # Verify there are 12 subtitle cues
            self.assertEqual(len(result_submaker.cues), 12)

            # Verify the 12th segment (the last speech segment):
            # it's preceded by 11 1.0s speech segments + 11 0.5s pauses = 11.0s + 5.5s = 16.50s
            last_cue = result_submaker.cues[-1]
            # Strict assertion: the start time must be 16.50s and must never drift to 17.71s!
            self.assertAlmostEqual(last_cue.start.total_seconds(), 16.50, places=2)
            self.assertAlmostEqual(last_cue.end.total_seconds(), 17.50, places=2)

            # Decode the real output MP3 audio and verify the total decoded sample duration is 17.50s
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

            # Verify the final decoded duration matches the subtitle end exactly (17.50s)
            self.assertAlmostEqual(decoded_duration, 17.50, delta=0.06)

    def test_tts_with_pauses_fails_on_empty_chunk_audio(self):
        """Regression test: when a speech segment produces an empty file (0 bytes) or the file is missing, _tts_with_pauses fails and returns None, never covering the error with generated silence."""
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
        """Regression test: when a speech segment's audio is corrupted and can't be decoded to PCM, _tts_with_pauses must fail and return None rather than replacing narration with silence and continuing."""
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

    def test_tts_with_pauses_decode_timeout_returns_failure(self):
        def fake_single_tts(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
            Path(voice_file).write_bytes(b"synthesized-audio")
            return vs.SubMaker()

        def timed_out(command, **kwargs):
            self.assertIn("-nostdin", command)
            self.assertGreater(kwargs.get("timeout", 0), 0)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "narration.mp3"
            with (
                patch.object(vs, "_single_tts", side_effect=fake_single_tts),
                patch.object(vs.subprocess, "run", side_effect=timed_out),
            ):
                result = vs._tts_with_pauses(
                    text="Hello [pause: 1s] world",
                    voice_name="zh-CN-XiaoxiaoNeural",
                    voice_rate=1.0,
                    voice_file=str(output),
                )
            self.assertIsNone(result)
            self.assertFalse(output.exists())

    def test_tts_passes_original_text_unchanged_without_pauses(self):
        """Test that without pause tags, tts passes the original text through to _single_tts unchanged, with no regex replacement or cleaning."""
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
