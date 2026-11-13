"""useapi.net audio client: Kling TTS, Google Vids speech, retries and downloads.

Every request is mocked; nothing reaches the network.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.services import useapi_audio


TOKEN = "user:1234-useapi-test-token"
KLING_AUDIO_URL = "https://s21-kling.klingai.com/tts/voice.mp3"


def _response(payload=None, status_code=200, headers=None, chunks=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
        iter_content=lambda chunk_size: iter(chunks or []),
        close=lambda: None,
    )


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_poll_interval": 10,
            "useapi_run_timeout": 1800,
        }
    )
    config.proxy.clear()
    with patch.object(useapi_audio.time, "sleep"):
        yield
    config.app.clear()
    config.app.update(original_app)
    config.proxy.clear()
    config.proxy.update(original_proxy)


def test_token_prefers_config_then_useapi_environment():
    with patch.dict(os.environ, {"USEAPI_TOKEN": "environment-token"}, clear=False):
        assert useapi_audio.get_api_key() == TOKEN
        config.app["useapi_api_token"] = "   "
        assert useapi_audio.get_api_key() == "environment-token"
        os.environ["USEAPI_TOKEN"] = ""
        assert useapi_audio.get_api_key() == ""
        assert useapi_audio.is_enabled() is False


def test_missing_token_is_reported_before_any_request():
    config.app["useapi_api_token"] = ""
    with (
        patch.dict(os.environ, {"USEAPI_TOKEN": ""}, clear=False),
        patch.object(useapi_audio.requests, "post") as post,
    ):
        with pytest.raises(useapi_audio.UseAPIAudioError, match="API token"):
            useapi_audio.kling_tts("Hello.", "voice_1", "/tmp/unused.mp3")
    post.assert_not_called()


def test_kling_tts_submits_speaker_speed_emotion_and_downloads_the_mp3(tmp_path):
    output = tmp_path / "speech.mp3"
    submit = _response(
        {
            "resource": KLING_AUDIO_URL,
            "status": 99,
            "status_name": "succeed",
            "status_final": True,
        }
    )
    with (
        patch.object(useapi_audio.requests, "post", return_value=submit) as post,
        patch.object(
            useapi_audio.requests, "get", return_value=_response(chunks=[b"ID3", b"mp3"])
        ) as get,
    ):
        useapi_audio.kling_tts(
            "Hello world.", "voice_1", str(output), speed=1.3, emotion="happy"
        )

    assert output.read_bytes() == b"ID3mp3"
    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "https://api.useapi.net/v1/kling/tts/create"
    assert kwargs["json"] == {
        "speakerId": "voice_1",
        "text": "Hello world.",
        "speed": 1.3,
        "emotion": "happy",
    }
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    assert kwargs["allow_redirects"] is False
    # The Kling CDN link is signed: it gets the User-Agent, never the token.
    assert get.call_args.args[0] == KLING_AUDIO_URL
    assert "Authorization" not in get.call_args.kwargs["headers"]
    assert get.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"


def test_kling_tts_without_emotion_omits_it_and_clamps_speed(tmp_path):
    submit = _response({"resource": KLING_AUDIO_URL, "status_name": "succeed"})
    with (
        patch.object(useapi_audio.requests, "post", return_value=submit) as post,
        patch.object(useapi_audio.requests, "get", return_value=_response(chunks=[b"a"])),
    ):
        useapi_audio.kling_tts("Hi.", "voice_1", str(tmp_path / "a.mp3"), speed=3.0)
    assert post.call_args.kwargs["json"] == {
        "speakerId": "voice_1",
        "text": "Hi.",
        "speed": 2.0,
    }
    assert useapi_audio.kling_speed(0.5) == 0.8
    assert useapi_audio.kling_speed("bad") == 1.0
    assert useapi_audio.kling_speed(float("nan")) == 1.0


def test_busy_accounts_wait_and_submit_again(tmp_path):
    busy = _response({"error": "all accounts busy"}, 429, {"Retry-After": "7"})
    done = _response({"resource": KLING_AUDIO_URL, "status_name": "succeed"})
    with (
        patch.object(useapi_audio.requests, "post", side_effect=[busy, busy, done]) as post,
        patch.object(useapi_audio.requests, "get", return_value=_response(chunks=[b"a"])),
    ):
        useapi_audio.kling_tts("Hi.", "voice_1", str(tmp_path / "a.mp3"))
    assert post.call_count == 3
    assert [call.args[0] for call in useapi_audio.time.sleep.call_args_list] == [7.0, 7.0]


def test_busy_accounts_give_up_after_the_retry_limit():
    busy = _response({"error": "all accounts busy"}, 429)
    with patch.object(useapi_audio.requests, "post", return_value=busy) as post:
        with pytest.raises(useapi_audio.UseAPIAudioError, match="busy"):
            useapi_audio.kling_tts("Hi.", "voice_1", "/tmp/unused.mp3")
    assert post.call_count == useapi_audio.MAX_SUBMIT_BUSY_RETRIES + 1


@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ReadTimeout("read timed out"),
        requests.exceptions.ConnectionError("connection dropped"),
    ],
)
def test_an_ambiguous_submission_is_never_sent_twice(failure):
    with patch.object(useapi_audio.requests, "post", side_effect=failure) as post:
        with pytest.raises(useapi_audio.UseAPIAudioUnconfirmedError):
            useapi_audio.vids_speech("Hello.", "Holt", "/tmp/unused.wav")
    post.assert_called_once()


def test_server_errors_and_redirects_are_unconfirmed_and_not_retried():
    for response in (
        _response({"error": "Service busy (CM_EXT.POther)"}, 500),
        _response({}, 302, {"Location": "https://elsewhere.example"}),
    ):
        with patch.object(useapi_audio.requests, "post", return_value=response) as post:
            with pytest.raises(useapi_audio.UseAPIAudioUnconfirmedError):
                useapi_audio.kling_tts("Hi.", "voice_1", "/tmp/unused.mp3")
        post.assert_called_once()


def test_a_rejected_request_reports_the_api_error_without_the_token():
    rejected = _response({"error": f"bad speakerId for {TOKEN}"}, 400)
    with patch.object(useapi_audio.requests, "post", return_value=rejected):
        with pytest.raises(useapi_audio.UseAPIAudioError) as caught:
            useapi_audio.kling_tts("Hi.", "voice_1", "/tmp/unused.mp3")
    assert "HTTP 400" in str(caught.value)
    assert TOKEN not in str(caught.value)
    assert caught.value.status_code == 400
    assert not isinstance(caught.value, useapi_audio.UseAPIAudioUnconfirmedError)


def test_kling_failure_status_in_a_200_answer_is_an_error():
    failed = _response({"status_name": "failed", "error": "text rejected"})
    with patch.object(useapi_audio.requests, "post", return_value=failed):
        with pytest.raises(useapi_audio.UseAPIAudioError, match="text rejected"):
            useapi_audio.kling_tts("Hi.", "voice_1", "/tmp/unused.mp3")


def test_kling_voice_list_keeps_speaker_ids_names_and_enabled_emotions():
    payload = {
        "ttsList": [
            {
                "name": "Narrator",
                "speakerId": "voice_1",
                "emotions": [
                    {"name": "Happy", "key": "happy", "enable": True},
                    {"name": "Sad", "key": "sad", "enable": False},
                ],
            },
            {"name": "Duplicate", "speakerId": "voice_1"},
            {"name": "Bad", "speakerId": "has:colon"},
            {"name": "", "speakerId": "voice_2", "emotions": []},
            "not a voice",
        ]
    }
    with patch.object(
        useapi_audio.requests, "get", return_value=_response(payload)
    ) as get:
        voices = useapi_audio.kling_voices()
    assert voices == [
        {"speaker_id": "voice_1", "name": "Narrator", "emotions": ["happy"]},
        {"speaker_id": "voice_2", "name": "voice_2", "emotions": []},
    ]
    assert get.call_args.args[0] == "https://api.useapi.net/v1/kling/tts/voices"
    assert get.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"


def test_voice_list_retries_transient_errors_but_not_rejections():
    with patch.object(
        useapi_audio.requests,
        "get",
        side_effect=[
            requests.exceptions.ConnectionError("down"),
            _response({"error": "busy"}, 503),
            _response({"ttsList": []}),
        ],
    ) as get:
        assert useapi_audio.kling_voices() == []
    assert get.call_count == 3

    with patch.object(
        useapi_audio.requests, "get", return_value=_response({"error": "Unauthorized"}, 401)
    ) as get:
        with pytest.raises(useapi_audio.UseAPIAudioError) as caught:
            useapi_audio.kling_voices()
    get.assert_called_once()
    assert caught.value.status_code == 401


def test_vids_speech_sync_answer_downloads_the_media_with_the_token(tmp_path):
    output = tmp_path / "speech.wav"
    media_id = "user:12345-user@example.com-audio:eyJ1"
    completed = _response(
        {
            "jobid": "j1-u12345-email:user@example.com-bot:google-vids",
            "type": "speech",
            "status": "completed",
            "result": {"mediaId": media_id, "duration": 6.1},
        }
    )
    with (
        patch.object(useapi_audio.requests, "post", return_value=completed) as post,
        patch.object(
            useapi_audio.requests, "get", return_value=_response(chunks=[b"RIFF", b"wav"])
        ) as get,
    ):
        useapi_audio.vids_speech("Welcome back.", "charon", str(output))

    assert output.read_bytes() == b"RIFFwav"
    assert post.call_args.args[0] == "https://api.useapi.net/v1/google-vids/speech"
    # A voice id is accepted and sent as its Vids name.
    assert post.call_args.kwargs["json"] == {"script": "Welcome back.", "voice": "Holt"}
    assert get.call_args.args[0] == (
        "https://api.useapi.net/v1/google-vids/media/"
        "user%3A12345-user%40example.com-audio%3AeyJ1"
    )
    assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_vids_speech_still_running_after_the_sync_wait_is_polled(tmp_path):
    job_id = "j2-u12345-email:user@example.com-bot:google-vids"
    accepted = _response({"jobid": job_id, "status": "processing"}, 202)
    polls = [
        _response({"jobid": job_id, "status": "processing"}),
        _response(
            {"jobid": job_id, "status": "completed", "result": {"mediaId": "m:1"}}
        ),
        _response(chunks=[b"RIFF"]),
    ]
    with (
        patch.object(useapi_audio.requests, "post", return_value=accepted) as post,
        patch.object(useapi_audio.requests, "get", side_effect=polls) as get,
    ):
        useapi_audio.vids_speech("Hello.", "Kaci", str(tmp_path / "s.wav"))
    post.assert_called_once()
    urls = [call.args[0] for call in get.call_args_list]
    assert urls[0] == (
        "https://api.useapi.net/v1/google-vids/jobs/"
        "j2-u12345-email%3Auser%40example.com-bot%3Agoogle-vids"
    )
    assert urls[2] == "https://api.useapi.net/v1/google-vids/media/m%3A1"


def test_vids_speech_failed_job_and_refusal_are_errors():
    job_id = "j3"
    with (
        patch.object(
            useapi_audio.requests,
            "post",
            return_value=_response({"jobid": job_id, "status": "processing"}, 202),
        ),
        patch.object(
            useapi_audio.requests,
            "get",
            return_value=_response(
                {"jobid": job_id, "status": "failed", "error": {"code": 422}}
            ),
        ),
    ):
        with pytest.raises(useapi_audio.UseAPIAudioError, match="job failed"):
            useapi_audio.vids_speech("Hello.", "Kaci", "/tmp/unused.wav")

    refused = _response(
        {"error": {"code": 422, "message": "Google refused this request"}}, 422
    )
    with patch.object(useapi_audio.requests, "post", return_value=refused) as post:
        with pytest.raises(useapi_audio.UseAPIAudioError, match="Google refused"):
            useapi_audio.vids_speech("Hello.", "Kaci", "/tmp/unused.wav")
    post.assert_called_once()


def test_vids_speech_rejects_unknown_voices_and_long_text_before_any_request():
    with patch.object(useapi_audio.requests, "post") as post:
        with pytest.raises(useapi_audio.UseAPIAudioError, match="Unknown"):
            useapi_audio.vids_speech("Hello.", "Bob", "/tmp/unused.wav")
        with pytest.raises(useapi_audio.UseAPIAudioError, match="2500"):
            useapi_audio.vids_speech("a" * 2501, "Holt", "/tmp/unused.wav")
    post.assert_not_called()


def test_vids_voice_catalog_has_the_30_vids_voices():
    assert len(useapi_audio.VIDS_VOICES) == 30
    assert len({name for name, _, _ in useapi_audio.VIDS_VOICES}) == 30
    assert useapi_audio.vids_voice_name("NYLA") == "Nyla"
    assert useapi_audio.vids_voice_name("Achernar") == "Nyla"
    assert useapi_audio.DEFAULT_VIDS_VOICE in {n for n, _, _ in useapi_audio.VIDS_VOICES}


def test_polling_retries_transient_errors_then_gives_up_unconfirmed():
    with patch.object(
        useapi_audio.requests,
        "get",
        side_effect=requests.exceptions.ConnectionError("down"),
    ) as get:
        with pytest.raises(useapi_audio.UseAPIAudioUnconfirmedError) as caught:
            useapi_audio.wait_for_job("https://api.useapi.net/v1/x/jobs/1", TOKEN, "1")
    assert get.call_count == useapi_audio.MAX_POLL_RETRIES + 1
    assert caught.value.job_id == "1"


def test_polling_an_unknown_status_is_unconfirmed():
    with patch.object(
        useapi_audio.requests, "get", return_value=_response({"status": "mystery"})
    ):
        with pytest.raises(useapi_audio.UseAPIAudioUnconfirmedError, match="unknown"):
            useapi_audio.wait_for_job("https://api.useapi.net/v1/x/jobs/1", TOKEN, "1")


def test_download_retries_the_same_link_and_rejects_oversized_files(tmp_path):
    output = tmp_path / "a.mp3"
    with patch.object(
        useapi_audio.requests,
        "get",
        side_effect=[_response(status_code=503), _response(chunks=[b"ok"])],
    ) as get:
        useapi_audio.download(KLING_AUDIO_URL, str(output))
    assert output.read_bytes() == b"ok"
    assert get.call_count == 2
    assert get.call_args_list[0].args == get.call_args_list[1].args

    with (
        patch.object(useapi_audio, "MAX_AUDIO_BYTES", 3),
        patch.object(
            useapi_audio.requests, "get", return_value=_response(chunks=[b"ab", b"cd"])
        ),
    ):
        with pytest.raises(useapi_audio.UseAPIAudioError, match="exceeds"):
            useapi_audio.download(KLING_AUDIO_URL, str(tmp_path / "big.mp3"))
    assert not (tmp_path / "big.mp3").exists()
    assert not [name for name in os.listdir(tmp_path) if name.startswith(".useapi-audio-")]


def test_useapi_download_requires_a_token():
    with pytest.raises(useapi_audio.UseAPIAudioError, match="token"):
        useapi_audio.download(
            "https://api.useapi.net/v1/google-vids/media/x", "/tmp/unused.wav"
        )


def test_split_script_keeps_short_scripts_whole():
    assert useapi_audio.split_script("  One. Two.  ", lambda chunk: True) == ["One. Two."]
    assert useapi_audio.split_script("   ", lambda chunk: True) == []


def test_split_script_packs_whole_sentences_in_order():
    text = "First sentence here. Second one! Third? 第四句。第五句。"
    chunks = useapi_audio.split_script(text, lambda chunk: len(chunk) <= 25)
    assert chunks == ["First sentence here.", "Second one! Third? 第四句。", "第五句。"]
    assert all(len(chunk) <= 25 for chunk in chunks)
    assert "".join(chunk.replace(" ", "") for chunk in chunks) == text.replace(" ", "")


def test_split_script_breaks_an_overlong_sentence_at_clauses_then_characters():
    text = "alpha beta, gamma delta, epsilon zeta. " + "x" * 30
    chunks = useapi_audio.split_script(text, lambda chunk: len(chunk) <= 12)
    assert all(0 < len(chunk) <= 12 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


EMAIL_JOB_ID = "j1104183512448203617s-u12345-email:someone@gmail.com-bot:google-vids"


def test_safe_job_id_masks_plain_and_url_encoded_emails():
    assert useapi_audio.safe_job_id(EMAIL_JOB_ID) == (
        "j1104183512448203617s-u12345-email:***-bot:google-vids"
    )
    encoded = useapi_audio.path_segment(EMAIL_JOB_ID)
    assert "someone" not in useapi_audio.safe_text(f"GET /jobs/{encoded}")
    assert useapi_audio.safe_job_id("") == ""
    assert useapi_audio.safe_text("no address here") == "no address here"
    error = useapi_audio.UseAPIAudioError(f"failed: id={EMAIL_JOB_ID}", job_id=EMAIL_JOB_ID)
    assert "someone@gmail.com" not in str(error)
    assert error.job_id == "j1104183512448203617s-u12345-email:***-bot:google-vids"


def test_vids_job_logs_and_errors_never_contain_the_account_email(tmp_path):
    messages = []
    sink = useapi_audio.logger.add(messages.append, level="DEBUG")
    try:
        # A failed job record.
        with (
            patch.object(
                useapi_audio.requests,
                "post",
                return_value=_response({"jobid": EMAIL_JOB_ID, "status": "processing"}, 202),
            ),
            patch.object(
                useapi_audio.requests,
                "get",
                return_value=_response(
                    {
                        "jobid": EMAIL_JOB_ID,
                        "status": "failed",
                        "error": {"message": "someone@gmail.com has no speech left"},
                    }
                ),
            ) as get,
        ):
            with pytest.raises(useapi_audio.UseAPIAudioError) as failed:
                useapi_audio.vids_speech("Hello.", "Kaci", str(tmp_path / "a.wav"))
        # The raw id is still what the API is asked for.
        assert "someone%40gmail.com" in get.call_args.args[0]

        # Polling that keeps failing, and a download that keeps failing.
        with patch.object(
            useapi_audio.requests,
            "get",
            side_effect=requests.exceptions.ConnectionError(
                f"https://api.useapi.net/v1/google-vids/jobs/"
                f"{useapi_audio.path_segment(EMAIL_JOB_ID)}"
            ),
        ):
            with pytest.raises(useapi_audio.UseAPIAudioUnconfirmedError) as unconfirmed:
                useapi_audio.wait_for_job(
                    "https://api.useapi.net/v1/google-vids/jobs/x", TOKEN, EMAIL_JOB_ID
                )
            with pytest.raises(useapi_audio.UseAPIAudioError) as download:
                useapi_audio.download(
                    "https://api.useapi.net/v1/google-vids/media/x",
                    str(tmp_path / "b.wav"),
                    api_token=TOKEN,
                    job_id=EMAIL_JOB_ID,
                )
    finally:
        useapi_audio.logger.remove(sink)

    errors = [failed.value, unconfirmed.value, download.value]
    text = " ".join(str(error) for error in errors) + "".join(map(str, messages))
    text += " ".join(error.job_id for error in errors)
    assert messages
    assert "someone" not in text
    assert "email:***" in text
