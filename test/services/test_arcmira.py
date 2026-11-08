import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
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
        Path(command[command.index("-o") + 1]).write_bytes(b"test video")
        return SimpleNamespace(returncode=0, stderr="")

    with (
        patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg-test"),
        patch.object(arcmira, "_run_downloader", side_effect=download),
        patch.object(arcmira, "_usable_clip", side_effect=lambda path: path.is_file()),
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
            arcmira,
            "_run_downloader",
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


@pytest.fixture
def two_second_video(tmp_path):
    import imageio_ffmpeg

    target = tmp_path / "valid.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=10",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


def test_script_order_searches_each_topic_before_reusing_first(
    tmp_path, two_second_video
):
    terms = ["forest", "city", "mountain"]
    searched = []

    def search(term):
        searched.append(term)
        index = terms.index(term)
        return [
            arcmira.Moment(f"{index:010d}{n}", 0, term, "show", "") for n in range(3)
        ]

    def fetch(moment, directory, duration):
        target = tmp_path / f"{moment.video_id}.mp4"
        shutil.copyfile(two_second_video, target)
        return str(target)

    with (
        patch.object(arcmira, "search_arcmira_moments", side_effect=search),
        patch.object(arcmira, "fetch_arcmira_clip", side_effect=fetch),
        patch.object(material, "_persist_material_sources") as persist,
    ):
        paths = material.download_videos(
            task_id="ordered-test",
            source="arcmira",
            search_terms=terms,
            audio_duration=6,
            max_clip_duration=2,
            match_script_order=True,
        )
    assert searched == ["forest", "city", "mountain"]
    assert [record["search_term"] for record in persist.call_args.args[1]] == terms
    assert len(paths) == 3


def test_failed_duration_probe_skips_candidate(tmp_path):
    moments = [
        arcmira.Moment("abcdefghijk", 0, "bad", "show", ""),
        arcmira.Moment("lmnopqrstuv", 0, "good", "show", ""),
    ]
    with (
        patch.object(arcmira, "search_arcmira_moments", return_value=moments),
        patch.object(
            arcmira, "fetch_arcmira_clip", side_effect=["bad.mp4", "good.mp4"]
        ),
        patch.object(
            material,
            "_get_downloaded_video_duration",
            side_effect=[ValueError("corrupt clip"), 2],
        ),
        patch.object(material, "_persist_material_sources") as persist,
    ):
        paths = material.download_videos(
            task_id="corrupt-test",
            source="arcmira",
            search_terms=["topic"],
            audio_duration=2,
            max_clip_duration=2,
        )
    assert paths == ["good.mp4"]
    assert len(persist.call_args.args[1]) == 1


def test_corrupt_cached_clip_is_replaced(tmp_path, two_second_video, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    output = media / "arcmira-abcdefghijk-0-2.mp4"
    output.write_bytes(b"corrupt video")
    original_popen = subprocess.Popen

    def downloader(command, **kwargs):
        if "-m" in command and "yt_dlp" in command:
            destination = command[command.index("-o") + 1]
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; import shutil,sys; p=Path(sys.argv[2]); "
                "shutil.copyfile(sys.argv[1],p) if not p.exists() else None",
                str(two_second_video),
                destination,
            ]
        return original_popen(command, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", downloader)
    result = arcmira.fetch_arcmira_clip(
        arcmira.Moment("abcdefghijk", 0, "quote", "show", ""), str(media), 2
    )
    assert result == str(output)
    assert material._get_downloaded_video_duration(result) == pytest.approx(2)


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX process-group regression")
def test_timeout_stops_ffmpeg_child_and_removes_partial_files(tmp_path, monkeypatch):
    import imageio_ffmpeg

    media = tmp_path / "media"
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "downloader.py"
    script.write_text("""import subprocess,sys,pathlib
p=subprocess.Popen([sys.argv[1], '-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi', '-i', 'color=s=64x64:r=10', '-t', '60', '-y', sys.argv[3]+'.part.mp4'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pathlib.Path(sys.argv[2]).write_text(str(p.pid))
p.wait()
""")
    original_popen, original_run = subprocess.Popen, subprocess.run

    def downloader(command, **kwargs):
        if "-m" in command and "yt_dlp" in command:
            command = [
                sys.executable,
                str(script),
                imageio_ffmpeg.get_ffmpeg_exe(),
                str(pid_file),
                command[command.index("-o") + 1],
            ]
        return original_popen(command, **kwargs)

    def shortened_run(command, **kwargs):
        if "-m" in command and "yt_dlp" in command:
            kwargs["timeout"] = 0.6
        return original_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", downloader)
    monkeypatch.setattr(subprocess, "run", shortened_run)
    monkeypatch.setattr(arcmira, "DOWNLOAD_TIMEOUT_SECONDS", 0.6, raising=False)
    child = None
    try:
        assert (
            arcmira.fetch_arcmira_clip(
                arcmira.Moment("abcdefghijk", 0, "quote", "show", ""), str(media), 2
            )
            is None
        )
        child = int(pid_file.read_text())
        status = original_run(
            ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True
        ).stdout.strip()
        assert not status or status.startswith("Z"), f"FFmpeg still running: {status}"
        assert not list(media.rglob("*.part.mp4"))
    finally:
        if child is None and pid_file.exists():
            child = int(pid_file.read_text())
        if child:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
