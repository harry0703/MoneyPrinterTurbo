"""Google Flow Music background music through useapi.net (all requests mocked)."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import config
from app.models.schema import VideoParams
from app.services import bgm as bgm_service
from app.services import task as task_service
from app.services import useapi_audio, useapi_flowmusic


TOKEN = "user:1234-useapi-test-token"
JOB_ID = "job:aaaa-user:1234-user@email.com-bot:flowmusic"
CLIP_ID = "user:1234-user@email.com-clip:a1b2"


def _response(payload=None, status_code=200, headers=None, chunks=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
        iter_content=lambda chunk_size: iter(chunks or []),
        close=lambda: None,
    )


def _completed(clips=None):
    return {
        "jobid": JOB_ID,
        "status": "completed",
        "clips": clips
        if clips is not None
        else [
            {
                "clip": CLIP_ID,
                "duration_s": 173.0,
                "audio_url": "https://storage.googleapis.com/x/a1b2.m4a",
            }
        ],
    }


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_flowmusic_model": "lyria-3.5",
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


@pytest.fixture
def fit():
    """Mock FFmpeg: the fitted file is a copy of the downloaded track."""
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        source = command[command.index("-i") + 1]
        with open(source, "rb") as src, open(command[-1], "wb") as dst:
            dst.write(src.read())
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    with (
        patch.object(useapi_flowmusic.subprocess, "run", side_effect=run),
        patch.object(bgm_service, "validate_audio_file") as validate,
    ):
        yield SimpleNamespace(calls=calls, validate=validate)


def test_generate_bgm_submits_polls_downloads_and_fits_the_track(tmp_path, fit):
    output = tmp_path / "flowmusic-bgm-1.mp3"
    submit = _response(
        {"jobid": JOB_ID, "status": "pending", "request": {"mode": "async"}}, 201
    )
    gets = [
        _response({"jobid": JOB_ID, "status": "pending"}),
        _response(_completed()),
        _response(chunks=[b"ID3", b"track"]),
    ]
    with (
        patch.object(useapi_audio.requests, "post", return_value=submit) as post,
        patch.object(useapi_audio.requests, "get", side_effect=gets) as get,
    ):
        result = useapi_flowmusic.generate_bgm(
            str(tmp_path / "combined.mp4"), str(output), 42.5, "calm piano"
        )

    assert result == str(output)
    assert output.read_bytes() == b"ID3track"
    assert post.call_args.args[0] == "https://api.useapi.net/v1/flowmusic/music"
    assert post.call_args.kwargs["json"] == {
        "prompt": "calm piano",
        "instrumental": True,
        "model": "lyria-3.5",
        "mode": "async",
    }
    assert post.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    urls = [call.args[0] for call in get.call_args_list]
    assert urls[0] == (
        "https://api.useapi.net/v1/flowmusic/jobs/"
        "job%3Aaaaa-user%3A1234-user%40email.com-bot%3Aflowmusic"
    )
    assert urls[2] == (
        "https://api.useapi.net/v1/flowmusic/music/download"
        "?id=user%3A1234-user%40email.com-clip%3Aa1b2&format=mp3"
    )
    assert get.call_args_list[2].kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    # The track is looped or trimmed to the video length.
    command = fit.calls[0]
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert command[command.index("-t") + 1] == "42.500"
    # FFmpeg reads only local audio containers, never a playlist's targets.
    input_index = command.index("-i")
    assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
    assert command[command.index("-format_whitelist") + 1] == (
        "mp3,mov,aac,wav,flac,ogg,asf"
    )
    assert command.index("-protocol_whitelist") < input_index
    assert command.index("-format_whitelist") < input_index
    # The download is validated before FFmpeg fits it, the result after.
    validated = [call.args[0] for call in fit.validate.call_args_list]
    assert len(validated) == 2
    assert os.path.basename(validated[0]).startswith(".flowmusic-track-")
    assert os.path.basename(validated[1]).startswith(".flowmusic-fitted-")
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".flowmusic-")]


def test_a_downloaded_file_that_is_not_audio_never_reaches_ffmpeg(tmp_path, fit):
    playlist = b"#EXTM3U\n#EXTINF:10,\nfile:///etc/passwd\n"
    fit.validate.side_effect = bgm_service.BgmUploadError(
        "uploaded file must contain a decodable audio stream"
    )
    with (
        patch.object(
            useapi_audio.requests, "post", return_value=_response(_completed())
        ),
        patch.object(
            useapi_audio.requests, "get", return_value=_response(chunks=[playlist])
        ),
    ):
        with pytest.raises(useapi_flowmusic.FlowMusicError, match="not audio"):
            useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    assert fit.calls == []
    fit.validate.assert_called_once()
    assert not (tmp_path / "o.mp3").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".flowmusic-")]


def test_job_ids_and_errors_never_expose_the_account_email(tmp_path, fit):
    messages = []
    sink = useapi_flowmusic.logger.add(messages.append, level="DEBUG")
    failed = {
        "jobid": JOB_ID,
        "status": "failed",
        "error": {"code": "x", "message": "account user@email.com declined"},
    }
    try:
        with (
            patch.object(
                useapi_audio.requests,
                "post",
                return_value=_response({"jobid": JOB_ID, "status": "pending"}, 201),
            ),
            patch.object(useapi_audio.requests, "get", return_value=_response(failed)),
        ):
            with pytest.raises(useapi_flowmusic.FlowMusicError) as caught:
                useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    finally:
        useapi_flowmusic.logger.remove(sink)
    text = str(caught.value) + "".join(str(message) for message in messages)
    assert "user@email.com" not in text
    assert "job:aaaa-user:***-bot:flowmusic" in str(caught.value)
    assert "job:aaaa-user:***-bot:flowmusic" in text


def test_a_sync_completed_answer_skips_polling(tmp_path, fit):
    with (
        patch.object(
            useapi_audio.requests, "post", return_value=_response(_completed())
        ),
        patch.object(
            useapi_audio.requests, "get", return_value=_response(chunks=[b"mp3"])
        ) as get,
    ):
        useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    assert get.call_count == 1
    assert "/flowmusic/music/download" in get.call_args.args[0]


def test_the_track_link_is_used_when_the_mp3_download_fails(tmp_path, fit):
    failures = [_response(status_code=500)] * useapi_audio.DOWNLOAD_ATTEMPTS
    with (
        patch.object(
            useapi_audio.requests, "post", return_value=_response(_completed())
        ),
        patch.object(
            useapi_audio.requests,
            "get",
            side_effect=[*failures, _response(chunks=[b"m4a"])],
        ) as get,
    ):
        useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    fallback = get.call_args_list[-1]
    assert fallback.args[0] == "https://storage.googleapis.com/x/a1b2.m4a"
    assert "Authorization" not in fallback.kwargs["headers"]


def test_a_failed_job_raises_the_provider_error(tmp_path, fit):
    failed = {
        "jobid": JOB_ID,
        "status": "failed",
        "error": {"code": "moderation_reject", "message": "declined"},
    }
    with (
        patch.object(
            useapi_audio.requests,
            "post",
            return_value=_response({"jobid": JOB_ID, "status": "pending"}, 201),
        ),
        patch.object(useapi_audio.requests, "get", return_value=_response(failed)),
    ):
        with pytest.raises(useapi_flowmusic.FlowMusicError, match="job failed"):
            useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    assert not (tmp_path / "o.mp3").exists()
    assert fit.calls == []


@pytest.mark.parametrize(
    "status_code, payload",
    [
        (402, {"error": "User has insufficient credits", "code": 402}),
        (422, {"status": "failed", "error": {"message": "declined"}}),
    ],
)
def test_rejections_are_provider_errors_and_not_retried(tmp_path, status_code, payload):
    with patch.object(
        useapi_audio.requests, "post", return_value=_response(payload, status_code)
    ) as post:
        with pytest.raises(useapi_flowmusic.FlowMusicError, match=f"HTTP {status_code}"):
            useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    post.assert_called_once()


def test_busy_accounts_wait_then_submit_again(tmp_path, fit):
    busy = _response({"error": "All 3 FlowMusic accounts are at maxJobs"}, 429)
    with (
        patch.object(
            useapi_audio.requests, "post", side_effect=[busy, _response(_completed())]
        ) as post,
        patch.object(useapi_audio.requests, "get", return_value=_response(chunks=[b"a"])),
    ):
        useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    assert post.call_count == 2


def test_an_ambiguous_submission_is_not_retried(tmp_path):
    import requests

    with patch.object(
        useapi_audio.requests,
        "post",
        side_effect=requests.exceptions.ReadTimeout("timed out"),
    ) as post:
        with pytest.raises(useapi_flowmusic.FlowMusicError, match="no response"):
            useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x")
    post.assert_called_once()


def test_invalid_inputs_fail_before_any_request(tmp_path):
    with patch.object(useapi_audio.requests, "post") as post:
        for duration in (0, -1, float("nan"), "bad", 4000):
            with pytest.raises(useapi_flowmusic.FlowMusicError):
                useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), duration)
        with pytest.raises(useapi_flowmusic.FlowMusicError, match="2000"):
            useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10, "x" * 2001)
        config.app["useapi_api_token"] = ""
        with patch.dict(os.environ, {"USEAPI_TOKEN": ""}, clear=False):
            assert useapi_flowmusic.is_enabled() is False
            with pytest.raises(useapi_flowmusic.FlowMusicError, match="token"):
                useapi_flowmusic.generate_bgm("v.mp4", str(tmp_path / "o.mp3"), 10)
    post.assert_not_called()


def test_model_falls_back_to_the_default_when_unknown():
    config.app["useapi_flowmusic_model"] = "lyria-3-pro"
    assert useapi_flowmusic.model_id() == "lyria-3-pro"
    config.app["useapi_flowmusic_model"] = "lyria-9"
    assert useapi_flowmusic.model_id() == useapi_flowmusic.DEFAULT_MODEL


def test_default_prompt_is_instrumental_and_names_the_subject():
    prompt = useapi_flowmusic.default_prompt("a paper boat at dawn")
    assert "Instrumental" in prompt and "no vocals" in prompt
    assert prompt.endswith("Topic: a paper boat at dawn")
    assert "Topic:" in useapi_flowmusic.default_prompt("", "A script about foxes.")
    assert "Topic:" not in useapi_flowmusic.default_prompt()
    long_prompt = useapi_flowmusic.default_prompt("word " * 500)
    assert len(long_prompt) <= useapi_flowmusic.MAX_PROMPT_LENGTH


def test_task_uses_the_subject_prompt_only_when_the_style_is_empty():
    params = VideoParams(video_subject="a paper boat", bgm_type="flowmusic")
    assert task_service._get_video_music_prompt(params).endswith("Topic: a paper boat")
    params.video_music_prompt = "lo-fi piano"
    assert task_service._get_video_music_prompt(params) == "lo-fi piano"
    params = VideoParams(video_subject="a paper boat", bgm_type="elevenlabs")
    assert task_service._get_video_music_prompt(params) == ""


def test_flow_music_is_registered_as_a_video_music_provider():
    provider = task_service._VIDEO_MUSIC_PROVIDERS["flowmusic"]
    assert provider["service"] is useapi_flowmusic
    assert provider["error_type"] is useapi_flowmusic.FlowMusicError
    assert provider["suffix"] == ".mp3"
    assert provider["warning_code"] == "flowmusic_bgm_failed"
    for name in ("is_enabled", "generate_bgm", "validate_generation_access"):
        assert callable(getattr(useapi_flowmusic, name))


def test_connection_check_counts_working_accounts_without_generating():
    accounts = {
        "a@example.com": {"email": "a@example.com", "tier": "plus"},
        "b@example.com": {"email": "b@example.com", "error": "refresh token rejected"},
    }
    with (
        patch.object(
            useapi_audio.requests, "get", return_value=_response(accounts)
        ) as get,
        patch.object(useapi_audio.requests, "post") as post,
    ):
        assert useapi_flowmusic.test_connection() == 1
    assert get.call_args.args[0] == "https://api.useapi.net/v1/flowmusic/accounts"
    post.assert_not_called()


def test_preflight_stops_only_on_certain_failures():
    with patch.object(useapi_audio.requests, "get", return_value=_response({})):
        with pytest.raises(useapi_flowmusic.FlowMusicAccessError, match="No working"):
            useapi_flowmusic.validate_generation_access()
    with patch.object(
        useapi_audio.requests, "get", return_value=_response({"error": "x"}, 401)
    ):
        with pytest.raises(useapi_flowmusic.FlowMusicAccessError):
            useapi_flowmusic.validate_generation_access()
    # An outage proves nothing; generation itself decides.
    with patch.object(
        useapi_audio.requests, "get", return_value=_response({"error": "x"}, 503)
    ):
        useapi_flowmusic.validate_generation_access()
