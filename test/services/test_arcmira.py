import math
import traceback
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo
from app.services import arcmira, material


@pytest.fixture(autouse=True)
def configured_key():
    with patch.object(
        config, "app", dict(config.app, arcmira_api_key="test-arcmira-key")
    ):
        yield


def response(chunks, status=200):
    return SimpleNamespace(status_code=status, json=lambda: {"chunks": chunks})


def chunk():
    return dict(
        video_id="abcdefghijk",
        start_seconds=12.5,
        text="An exact spoken passage.",
        channel_name="Example show",
        published_at="2026-09-01",
    )


def test_search_uses_one_query_and_keeps_attribution():
    with patch.object(arcmira.requests, "get", return_value=response([chunk()])) as get:
        moments = arcmira.search_arcmira_moments("  video production  ")
    assert moments == [
        arcmira.Moment(
            "abcdefghijk",
            12.5,
            "An exact spoken passage.",
            "Example show",
            "2026-09-01",
        )
    ]
    assert moments[0].watch_url == "https://www.youtube.com/watch?v=abcdefghijk&t=12.5s"
    assert get.call_args.args == ("https://api.arcmira.com/v1/search",)
    assert get.call_args.kwargs == dict(
        params={"q": "video production", "limit": 5},
        headers={"Authorization": "Bearer test-arcmira-key"},
        timeout=30,
        allow_redirects=False,
    )


def test_empty_search_returns_no_clips():
    with patch.object(arcmira.requests, "get", return_value=response([])):
        assert arcmira.search_arcmira_moments("video production") == []


@pytest.mark.parametrize("status", [301, 401, 402, 429, 500])
def test_search_errors_stop_without_retry_or_response_disclosure(status):
    with patch.object(
        arcmira.requests, "get", return_value=response([], status)
    ) as get:
        with pytest.raises(arcmira.ArcmiraError, match=f"HTTP {status}"):
            arcmira.search_arcmira_moments("video production")
    assert get.call_count == 1


def test_missing_key_fails_before_network():
    config.app["arcmira_api_key"] = ""
    with patch.object(arcmira.requests, "get") as get:
        with pytest.raises(arcmira.ArcmiraError, match="arcmira_api_key"):
            arcmira.search_arcmira_moments("video production")
    get.assert_not_called()


@pytest.mark.parametrize(
    "query,limit", [("", 5), (None, 5), ("x", 5), ("valid", 21), ("valid", True)]
)
def test_invalid_inputs_fail_before_network(query, limit):
    with patch.object(arcmira.requests, "get") as get:
        with pytest.raises(arcmira.ArcmiraError):
            arcmira.search_arcmira_moments(query, limit)
    get.assert_not_called()


def test_untrusted_passages_cannot_change_download_host_or_paths():
    malformed = [
        dict(chunk(), video_id="../../escape"),
        dict(chunk(), start_seconds=math.nan),
        dict(chunk(), start_seconds=-1),
        dict(chunk(), start_seconds=True),
        dict(chunk(), text=None),
        None,
    ]
    with patch.object(
        arcmira.requests, "get", return_value=response(malformed + [chunk()])
    ):
        assert arcmira.search_arcmira_moments("video production", limit=20) == [
            arcmira.Moment(
                "abcdefghijk",
                12.5,
                "An exact spoken passage.",
                "Example show",
                "2026-09-01",
            )
        ]


def test_connection_error_does_not_repeat_request_or_echo_key():
    with patch.object(
        arcmira.requests,
        "get",
        side_effect=requests.ConnectionError("test-arcmira-key"),
    ) as get:
        with pytest.raises(arcmira.ArcmiraError) as error:
            arcmira.search_arcmira_moments("video production")
    assert "test-arcmira-key" not in "".join(traceback.format_exception(error.value))
    assert get.call_count == 1


def test_downloader_uses_exact_bounds_and_never_ambient_auth(tmp_path):
    moment = arcmira.Moment("abcdefghijk", 12.5, "quote", "show", "2026-09-01")

    def download(command, **kwargs):
        assert command[command.index("--download-sections") + 1] == "*12.5-15.5"
        assert "--force-keyframes-at-cuts" in command and "--ignore-config" in command
        assert command[-1] == "https://www.youtube.com/watch?v=abcdefghijk&t=12.5s"
        assert not any(
            x in command
            for x in [
                "--cookies",
                "--cookies-from-browser",
                "--username",
                "--password",
                "--netrc",
            ]
        )
        assert "test-arcmira-key" not in str(command)
        assert kwargs.get("shell", False) is False
        assert command[command.index("--ffmpeg-location") + 1] == "ffmpeg-test"
        from pathlib import Path

        Path(command[command.index("-o") + 1]).write_bytes(b"test video")
        return SimpleNamespace(returncode=0, stderr="")

    with (
        patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg-test"),
        patch.object(arcmira.subprocess, "run", side_effect=download),
    ):
        assert arcmira.fetch_arcmira_clip(moment, str(tmp_path), 3) == str(
            tmp_path / "arcmira-abcdefghijk-12.5-15.5.mp4"
        )


@pytest.mark.parametrize(
    "message",
    [
        "Sign in to confirm",
        "private video",
        "members-only video",
        "age-restricted video",
    ],
)
def test_sign_in_video_is_skipped_without_retry(message, tmp_path):
    moment = arcmira.Moment("abcdefghijk", 0, "quote", "show", "")
    with (
        patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg-test"),
        patch.object(
            arcmira.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1, stderr=message),
        ) as run,
    ):
        assert arcmira.fetch_arcmira_clip(moment, str(tmp_path), 3) is None
    assert run.call_count == 1


def test_material_fetches_only_needed_seconds_and_saves_exact_sources(tmp_path):
    first = arcmira.Moment("abcdefghijk", 12.5, "First quote", "Show one", "2026-09-01")
    second = arcmira.Moment("lmnopqrstuv", 90, "Second quote", "Show two", "2026-09-02")
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)))
    fetched = []

    def fetch(moment, directory, duration):
        assert sum(arcmira.CLIP_RIGHTS_LINE in msg for msg in messages) == 1
        fetched.append((moment, duration))
        return str(tmp_path / (moment.video_id + ".mp4"))

    try:
        with (
            patch.object(
                arcmira, "search_arcmira_moments", return_value=[first, first, second]
            ) as search,
            patch.object(arcmira, "fetch_arcmira_clip", side_effect=fetch),
            patch.object(
                material, "_get_downloaded_video_duration", side_effect=[2, 1]
            ),
            patch.object(material, "_persist_material_sources") as persist,
        ):
            paths = material._download_videos_arcmira_on_demand(
                task_id="example",
                search_terms=["topic one", "unused topic"],
                audio_duration=3,
                max_clip_duration=2,
                material_directory=str(tmp_path),
            )
        assert len(paths) == 2
        search.assert_called_once_with("topic one")
        assert fetched == [(first, 2), (second, 1)]
        sources = persist.call_args.args[1]
        assert sources[0]["quote"] == "First quote"
        assert sources[0]["source_page"] == first.watch_url
        assert sources[1]["end_seconds"] == 91
        assert str(tmp_path) not in str(sources)
    finally:
        logger.remove(sink)


def test_sign_in_failure_moves_to_next_moment(tmp_path):
    moments = [
        arcmira.Moment("abcdefghijk", 0, "quote", "show", ""),
        arcmira.Moment("lmnopqrstuv", 0, "other", "show", ""),
    ]
    with (
        patch.object(arcmira, "search_arcmira_moments", return_value=moments),
        patch.object(
            arcmira, "fetch_arcmira_clip", side_effect=[None, "second.mp4"]
        ) as fetch,
        patch.object(material, "_get_downloaded_video_duration", return_value=3),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_arcmira_on_demand(
            task_id="example",
            search_terms=["topic"],
            audio_duration=3,
            max_clip_duration=3,
            material_directory=str(tmp_path),
        )
    assert paths == ["second.mp4"] and fetch.call_count == 2


def test_source_record_drops_untrusted_watch_url_and_invalid_timestamps():
    item = MaterialInfo(
        provider="arcmira",
        duration=3,
        source_info={
            "video_id": "abcdefghijk",
            "start_seconds": 0,
            "end_seconds": 3,
            "source_page": "https://example.test/?secret=value",
            "quote": "quote",
        },
    )
    assert (
        material._material_source_record(item, "clip.mp4")["source_page"]
        == "https://www.youtube.com/watch?v=abcdefghijk&t=0s"
    )
    item.source_info["start_seconds"] = -1
    assert "start_seconds" not in material._material_source_record(item, "clip.mp4")
