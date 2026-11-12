"""useapi.net voices inside MPT's voice pipeline: dispatch, splitting, joining
and subtitle timing.  The useapi.net client and FFmpeg work are mocked."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

from app.config import config
from app.services import useapi_audio, voice


class _Clip:
    """Minimal AudioFileClip: durations by file name, usable as a context manager."""

    durations = {}

    def __init__(self, path):
        self.duration = self.durations.get(path.rsplit("/", 1)[-1], 1.0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.fixture
def pipeline(tmp_path):
    """Mock the decode checks and joins; record the synthesized chunks."""
    calls = {"chunks": [], "concat": None, "encode": None}

    def concat(files, output):
        calls["concat"] = list(files)
        with open(output, "wb") as handle:
            handle.write(b"joined")
        return True

    def encode(source, output):
        calls["encode"] = (source, output)
        with open(output, "wb") as handle:
            handle.write(b"encoded")
        return True

    _Clip.durations = {}
    with ExitStack() as stack:
        stack.enter_context(patch.object(voice, "AudioFileClip", _Clip))
        stack.enter_context(patch.object(voice, "_validate_remote_tts_audio"))
        stack.enter_context(patch.object(voice, "_concat_audio_files", side_effect=concat))
        stack.enter_context(patch.object(voice, "_encode_tts_audio", side_effect=encode))
        yield calls


def _fake_synth(calls, data=b"audio"):
    def synth(text, *args, **kwargs):
        output = args[-1]
        calls["chunks"].append(text)
        with open(output, "wb") as handle:
            handle.write(data)
    return synth


def test_voice_identities_are_recognized_and_parsed():
    kling = "useapi-kling:voice_1:Narrator"
    vids = "useapi-vids:Holt-Informative"
    assert voice.is_useapi_kling_voice(kling)
    assert voice.parse_useapi_kling_speaker_id(kling) == "voice_1"
    assert voice.parse_useapi_kling_speaker_id("useapi-kling:voice_2") == "voice_2"
    assert voice.is_useapi_vids_voice(vids)
    assert voice.parse_useapi_vids_voice_name(vids) == "Holt"
    assert voice.parse_useapi_vids_voice_name("useapi-vids:Nyla") == "Nyla"
    for name in (kling, vids):
        assert not voice.is_azure_v1_voice(name)
        assert voice.parse_voice_name(name) == name


def test_vids_voice_list_is_local_and_complete():
    voices = voice.get_useapi_vids_voices()
    assert len(voices) == 30
    assert voices[0] == "useapi-vids:Nyla-Soft"
    assert "useapi-vids:Holt-Informative" in voices


def test_kling_voice_list_uses_the_useapi_catalog():
    catalog = [{"speaker_id": "voice_1", "name": "Narrator", "emotions": []}]
    with patch.object(useapi_audio, "kling_voices", return_value=catalog) as load:
        assert voice.get_useapi_kling_voices("token") == ["useapi-kling:voice_1:Narrator"]
    load.assert_called_once_with("token")


def test_kling_voice_reads_the_script_in_one_request(tmp_path, pipeline):
    output = tmp_path / "audio.mp3"
    _Clip.durations = {"chunk_0.mp3": 4.0, "narration.mp3": 4.0}
    with patch.object(
        useapi_audio, "kling_tts", side_effect=_fake_synth(pipeline)
    ) as kling:
        sub_maker = voice.tts(
            "Hello there. How are you?", "useapi-kling:voice_1:Narrator", 1.2, str(output)
        )

    assert sub_maker is not None
    assert output.read_bytes() == b"audio"
    assert pipeline["chunks"] == ["Hello there. How are you?"]
    assert kling.call_args.args[1] == "voice_1"
    assert kling.call_args.kwargs == {"speed": 1.2, "emotion": ""}
    assert pipeline["concat"] is None and pipeline["encode"] is None
    assert sub_maker.subs == ["Hello there", "How are you"]
    assert sub_maker.offset[-1][1] == 40_000_000
    assert voice.get_audio_duration(sub_maker) == pytest.approx(4.0)


def test_kling_voice_passes_the_configured_emotion(tmp_path, pipeline):
    with (
        patch.dict(config.app, {"useapi_kling_tts_emotion": "happy"}),
        patch.object(useapi_audio, "kling_tts", side_effect=_fake_synth(pipeline)) as kling,
    ):
        voice.tts("Hi.", "useapi-kling:voice_1", 1.0, str(tmp_path / "a.mp3"))
    assert kling.call_args.kwargs["emotion"] == "happy"


def test_a_long_kling_script_is_split_at_sentences_and_joined_in_order(
    tmp_path, pipeline
):
    sentence = "This sentence is read aloud by the narrator. "
    text = (sentence * 400).strip()
    output = tmp_path / "audio.mp3"
    with patch.object(useapi_audio, "kling_tts", side_effect=_fake_synth(pipeline)):
        sub_maker = voice.tts(text, "useapi-kling:voice_1", 1.0, str(output))

    chunks = pipeline["chunks"]
    assert len(chunks) > 1
    assert all(chunk.endswith(".") for chunk in chunks)
    assert " ".join(chunks) == text
    assert all(
        voice.estimate_no_voice_duration(chunk)
        <= useapi_audio.KLING_TTS_CHUNK_SECONDS
        for chunk in chunks
    )
    assert [path.rsplit("/", 1)[-1] for path in pipeline["concat"]] == [
        f"chunk_{index}.mp3" for index in range(len(chunks))
    ]
    assert output.read_bytes() == b"joined"
    assert len(sub_maker.subs) == 400
    # Offsets run on across the joins without going backwards.
    ends = [end for _start, end in sub_maker.offset]
    assert ends == sorted(ends)


def test_slower_kling_speed_makes_smaller_chunks(tmp_path, pipeline):
    text = ("A short sentence for timing. " * 300).strip()
    with patch.object(useapi_audio, "kling_tts", side_effect=_fake_synth(pipeline)):
        voice.tts(text, "useapi-kling:voice_1", 2.0, str(tmp_path / "fast.mp3"))
    fast = len(pipeline["chunks"])
    pipeline["chunks"].clear()
    with patch.object(useapi_audio, "kling_tts", side_effect=_fake_synth(pipeline)):
        voice.tts(text, "useapi-kling:voice_1", 0.8, str(tmp_path / "slow.mp3"))
    assert len(pipeline["chunks"]) > fast


def test_vids_voice_converts_its_wav_and_ignores_speed(tmp_path, pipeline):
    output = tmp_path / "audio.mp3"
    with (
        patch.object(useapi_audio, "vids_speech", side_effect=_fake_synth(pipeline)) as vids,
        patch.object(voice.logger, "warning") as warning,
    ):
        sub_maker = voice.tts("Welcome back.", "useapi-vids:Holt-Informative", 1.5, str(output))

    assert sub_maker is not None
    assert vids.call_args.args[1] == "Holt"
    # One WAV chunk is re-encoded into the MP3 the pipeline asked for.
    assert pipeline["encode"][0].endswith("chunk_0.wav")
    assert output.read_bytes() == b"encoded"
    assert any("Google Vids speech" in str(call.args[0]) for call in warning.call_args_list)


def test_a_vids_script_over_the_request_limit_uses_as_few_requests_as_possible(
    tmp_path, pipeline
):
    text = ("Every sentence here has the same length to keep it simple. " * 90).strip()
    assert len(text) > 2 * useapi_audio.VIDS_SPEECH_MAX_CHARS
    with patch.object(useapi_audio, "vids_speech", side_effect=_fake_synth(pipeline)):
        voice.tts(text, "useapi-vids:Kaci-Bright", 1.0, str(tmp_path / "a.mp3"))
    chunks = pipeline["chunks"]
    assert len(chunks) == 3
    assert all(len(chunk) <= useapi_audio.VIDS_SPEECH_MAX_CHARS for chunk in chunks)
    assert " ".join(chunks) == text


def test_a_failed_request_returns_none_and_leaves_no_partial_output(tmp_path, pipeline):
    output = tmp_path / "audio.mp3"
    calls = {"count": 0}

    def fail_second(text, speaker, path, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise useapi_audio.UseAPIAudioError("Kling refused the text")
        with open(path, "wb") as handle:
            handle.write(b"audio")

    text = ("This sentence is read aloud by the narrator. " * 400).strip()
    with patch.object(useapi_audio, "kling_tts", side_effect=fail_second):
        assert voice.tts(text, "useapi-kling:voice_1", 1.0, str(output)) is None
    assert calls["count"] == 2
    assert not output.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".useapi-tts-")]


def test_invalid_voice_names_fail_without_a_request(tmp_path):
    with (
        patch.object(useapi_audio, "kling_tts") as kling,
        patch.object(useapi_audio, "vids_speech") as vids,
    ):
        assert voice.tts("Hi.", "useapi-kling:", 1.0, str(tmp_path / "a.mp3")) is None
        assert voice.tts("Hi.", "useapi-vids:", 1.0, str(tmp_path / "b.mp3")) is None
    kling.assert_not_called()
    vids.assert_not_called()


def test_voice_errors_are_logged_without_the_account_email(tmp_path, pipeline):
    messages = []
    sink = voice.logger.add(messages.append, level="DEBUG")
    try:
        with patch.object(
            useapi_audio,
            "vids_speech",
            side_effect=useapi_audio.UseAPIAudioError(
                "job failed: id=j1-u1-email:someone@gmail.com-bot:google-vids",
                job_id="j1-u1-email:someone@gmail.com-bot:google-vids",
            ),
        ):
            assert voice.tts("Hi.", "useapi-vids:Holt", 1.0, str(tmp_path / "a.mp3")) is None
    finally:
        voice.logger.remove(sink)
    logged = "".join(map(str, messages))
    assert "email:***" in logged
    assert "someone" not in logged
