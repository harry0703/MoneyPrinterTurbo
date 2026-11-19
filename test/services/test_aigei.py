import json
import multiprocessing
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import requests
from PIL import Image

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.services import aigei, material, task_artifacts, video_orientation


def _response(status=200, **payload):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    return response


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    monkeypatch.setattr(video_orientation, "load_detector", lambda: None)


@pytest.mark.parametrize("keyword", ["city night skyline", "城市夜景"])
def test_search_preserves_keywords_and_picks_eligible_rendition(monkeypatch, keyword):
    def variant(file_id, price, width, height, duration=8):
        return {
            "fileId": file_id,
            "fileExtName": "mp4",
            "videoProperties": {
                "videoWidthPx": width,
                "videoHeightPx": height,
                "videoDurationSeconds": duration,
            },
            "downloadFund": {"fundValue": price},
        }

    def search(method, url, **kwargs):
        assert (method, url.rsplit("/", 1)[1]) == ("POST", "search")
        assert kwargs["json"]["keyword"] == keyword
        assert kwargs["json"]["condition"]["fileVideo"]["videoLayoutEq"] == "9_16"
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        return _response(code="10001", data={"itemList": [{
            "itemId": "work-1",
            "fileList": [
                variant("too-short", 0, 1080, 1920, duration=2),
                variant("wrong-aspect", 0, 1920, 1080),
                variant("more-expensive", 4, 1080, 1920),
                variant("selected", 2, 720, 1280),
            ],
        }]})

    monkeypatch.setattr(aigei.requests, "request", search)
    result = aigei.search_videos(keyword, 5, VideoAspect.portrait, key="test-key")
    assert [(item.url, item.duration) for item in result] == [("selected", 8)]
    assert result[0].source_info["asset_id"] == "work-1"


@pytest.mark.parametrize(("directions", "sideways"), [
    ([89, 90, None, 92, None], True),
    ([269, 270, 272], True),
    ([90, 90, None, 90, 0], False),
    ([90, 90, 90, 270], False),
    ([90, 90, 45, None, None], False),
])
def test_sideways_classification_requires_consistent_confident_frames(directions, sideways):
    values = iter(directions)

    def probabilities(*args):
        angle = next(values)
        output = np.ones((1, 360), dtype=np.float32) / 360
        if angle is not None:
            output.fill(0)
            output[0, angle] = 1
        return [output]

    detector = video_orientation.SidewaysDetector(SimpleNamespace(run=probabilities))
    frame = Image.new("RGB", (72, 128))
    assert detector.is_sideways([frame] * len(directions)) is sideways


def test_preview_urls_are_bounded_and_require_aigei_https():
    accepted = [f"https://s1.aigei.com/{index}.jpg" for index in range(9)]
    candidates = accepted + [accepted[0], "http://www.aigei.com/a.jpg", "https://aigei.com.invalid/b.jpg"]
    assert aigei._preview_urls([{"prevMiniUrl": url} for url in candidates]) == accepted[::2]


def test_sideways_preview_skips_paid_download(tmp_path):
    detector = SimpleNamespace(is_sideways=lambda _: True)
    with patch.object(aigei, "download_url") as download:
        result = material._save_aigei_material(
            MaterialInfo(provider="aigei", url="other-work"), str(tmp_path), "test-key",
            VideoAspect.portrait, orientation=detector,
        )
    assert result == ""
    download.assert_not_called()


@pytest.mark.parametrize("new_download", [False, True])
def test_sideways_pixels_are_checked_in_portrait_videos(monkeypatch, tmp_path, new_download):
    def save(cache_identity, save_dir, *, resolve_url):
        if new_download:
            resolve_url()
        return str(tmp_path / "clip.mp4")

    monkeypatch.setattr(material, "save_video", save)
    monkeypatch.setattr(aigei, "download_url", lambda *_: ("https://aigei.example/video.mp4", "request-id"))
    clip = SimpleNamespace(size=(720, 1280), close=lambda: None)
    monkeypatch.setattr(material.video, "_open_video_clip_quietly", lambda _: clip)
    detector = SimpleNamespace(
        is_sideways=lambda _: False, is_sideways_video=lambda decoded: decoded is clip,
    )
    item = MaterialInfo(provider="aigei", url="other-work")
    if new_download:
        with pytest.raises(aigei.AigeiError) as exc:
            material._save_aigei_material(item, str(tmp_path), "test-key", VideoAspect.portrait, orientation=detector)
        assert exc.value.key == "aigei.sideways_content"
        assert exc.value.request_id == "request-id"
    else:
        assert material._save_aigei_material(item, str(tmp_path), "test-key", VideoAspect.portrait, orientation=detector) == ""


@pytest.mark.parametrize("match_script_order", [False, True])
@pytest.mark.parametrize("fail_saving", [False, True])
def test_stock_pipeline_stops_charging_on_exact_coverage_or_uncertain_download(
    monkeypatch, tmp_path, match_script_order, fail_saving,
):
    monkeypatch.setattr(config, "app", dict(
        config.app, aigei_api_key="test-key", material_concurrency=4,
        material_directory=str(tmp_path),
    ))
    clips = [MaterialInfo(provider="aigei", url=f"file-{i}", duration=5) for i in range(3)]
    monkeypatch.setattr(aigei, "search_videos", lambda *args, **kwargs: clips)
    monkeypatch.setattr(material, "_persist_material_sources", lambda *args: None)
    links = []

    def buy(file_id, key):
        links.append(file_id)
        return "https://aigei.example/video.mp4?signature=private", "request-id"

    def save(cache_identity, save_dir, *, resolve_url):
        assert "signature" not in cache_identity
        assert resolve_url().startswith("https://")
        if fail_saving:
            raise requests.Timeout("https://aigei.example/video.mp4?signature=private")
        return str(tmp_path / "clip.mp4")

    monkeypatch.setattr(aigei, "download_url", buy)
    monkeypatch.setattr(material, "save_video", save)
    monkeypatch.setattr(material.video, "_open_video_clip_quietly", lambda _: SimpleNamespace(size=(720, 1280), close=lambda: None))
    options = dict(
        source="aigei", match_script_order=match_script_order,
        video_concat_mode=VideoConcatMode.sequential, audio_duration=5,
    )
    if fail_saving:
        with pytest.raises(aigei.AigeiError) as exc:
            material.download_videos("task", ["城市夜景"], **options)
        assert exc.value.key == "aigei.file_failed"
        assert exc.value.request_id == "request-id"
        assert "signature" not in str(exc.value)
    else:
        assert material.download_videos("task", ["城市夜景"], **options) == [str(tmp_path / "clip.mp4")]
    assert links == ["file-0"]


def test_cached_file_does_not_request_another_paid_link(monkeypatch, tmp_path):
    purchase = []

    def link(file_id, key):
        purchase.append(file_id)
        return "https://aigei.example/video.mp4?signature=private", "request-id"

    response = SimpleNamespace(
        headers={}, raise_for_status=lambda: None, iter_content=lambda **_: [b"video"],
    )
    monkeypatch.setattr(aigei, "download_url", link)
    monkeypatch.setattr(material.requests, "get", lambda *args, **kw: nullcontext(response))
    monkeypatch.setattr(material, "_is_valid_video_file", lambda _: True)
    item = MaterialInfo(provider="aigei", url="file-1", duration=5)
    first = material._save_aigei_material(item, str(tmp_path), "test-key")
    second = material._save_aigei_material(item, str(tmp_path), "test-key")
    assert first == second
    assert purchase == ["file-1"]


@pytest.mark.parametrize("new_download", [False, True])
def test_rejects_landscape_file_in_portrait_task(monkeypatch, tmp_path, new_download):
    def save(cache_identity, save_dir, *, resolve_url):
        if new_download:
            resolve_url()
        return str(tmp_path / "clip.mp4")

    monkeypatch.setattr(material, "save_video", save)
    monkeypatch.setattr(aigei, "download_url", lambda *_: ("https://aigei.example/video.mp4", "request-id"))
    monkeypatch.setattr(material.video, "_open_video_clip_quietly", lambda _: SimpleNamespace(size=(1280, 720), close=lambda: None))
    item = MaterialInfo(provider="aigei", url="file-1", duration=5)
    if new_download:
        with pytest.raises(aigei.AigeiError) as exc:
            material._save_aigei_material(item, str(tmp_path), "test-key", VideoAspect.portrait)
        assert exc.value.key == "aigei.aspect_mismatch"
        assert exc.value.request_id == "request-id"
    else:
        assert not material._save_aigei_material(item, str(tmp_path), "test-key", VideoAspect.portrait)


@pytest.mark.parametrize("result_page, expected_pages", [(2, [1, 2]), (4, [1, 2, 3])])
def test_search_skips_empty_pages_with_a_limit(monkeypatch, result_page, expected_pages):
    pages = []

    def search(method, url, **kwargs):
        number = kwargs["json"].get("pageNumber", 1)
        pages.append(number)
        hits = [] if number < result_page else [{
            "itemId": "work-2",
            "fileList": [{
                "fileId": "file-2", "fileExtName": "mp4",
                "videoProperties": {
                    "videoWidthPx": 720, "videoHeightPx": 1280,
                    "videoDurationSeconds": 8,
                },
                "downloadFund": {"fundValue": 2},
            }],
        }]
        return _response(code="10001", data={
            "itemList": hits, "pageNumber": number, "pageSize": 40, "itemTotal": 160,
        })

    monkeypatch.setattr(aigei.requests, "request", search)
    result = aigei.search_videos("city night skyline", 5, VideoAspect.portrait, key="test-key")
    assert pages == expected_pages
    assert [item.url for item in result] == (["file-2"] if result_page == 2 else [])


@pytest.mark.parametrize("match_script_order", [False, True])
def test_paid_batch_preserves_downloaded_sources_on_later_failure(
    monkeypatch, tmp_path, match_script_order,
):
    monkeypatch.setattr(material.utils, "task_dir", lambda _: str(tmp_path))
    monkeypatch.setattr(config, "app", dict(
        config.app, aigei_api_key="test-key", material_directory=str(tmp_path),
        material_concurrency=1,
    ))
    task_artifacts.write_script_data("task", {"script": "Two scenes"})
    terms = ["city", "咖啡", "sunrise"]
    monkeypatch.setattr(aigei, "search_videos", lambda term, *args, **kwargs: [
        MaterialInfo(provider="aigei", url=term, duration=5, source_info={"asset_id": term}),
    ])
    attempted = []

    def save(item, directory, *, key, video_aspect, orientation):
        attempted.append(item.url)
        if item.url == "咖啡":
            raise aigei.AigeiError("link_failed", "request-2")
        clip = Path(directory) / "clip.mp4"
        clip.write_bytes(b"saved clip")
        return str(clip)

    monkeypatch.setattr(material, "_save_aigei_material", save)
    with pytest.raises(aigei.AigeiError) as exc:
        material.download_videos(
            "task", terms, source="aigei", audio_duration=15,
            match_script_order=match_script_order, video_concat_mode=VideoConcatMode.sequential,
        )
    assert exc.value.request_id == "request-2"
    assert attempted == ["city", "咖啡"]
    saved = json.loads((tmp_path / "script.json").read_text(encoding="utf-8"))
    assert saved["material_sources"] == [{
        "provider": "aigei", "asset_id": "city", "local_file": "clip.mp4", "duration": 5,
    }]


def _download_in_process(directory, starting, settling, release):
    def link(file_id, key):
        settling.set()
        assert release.wait(15)
        return "https://aigei.example/clip.mp4", "request-id"

    response = SimpleNamespace(
        headers={}, raise_for_status=lambda: None, iter_content=lambda **_: [b"video"],
    )
    with (
        patch.object(aigei, "download_url", link),
        patch.object(material.requests, "get", return_value=nullcontext(response)),
        patch.object(material, "_is_valid_video_file", return_value=True),
    ):
        item = MaterialInfo(provider="aigei", url="shared-file", duration=5)
        starting.set()
        assert material._save_aigei_material(item, directory, "test-key")


def test_shared_cache_settles_one_download_across_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    release = ctx.Event()
    first_ready, second_ready = ctx.Event(), ctx.Event()
    first_charge, second_charge = ctx.Event(), ctx.Event()
    first = ctx.Process(
        target=_download_in_process, args=(str(tmp_path), first_ready, first_charge, release),
    )
    second = ctx.Process(
        target=_download_in_process, args=(str(tmp_path), second_ready, second_charge, release),
    )
    started = []
    try:
        first.start()
        started.append(first)
        assert first_ready.wait(15) and first_charge.wait(5)
        second.start()
        started.append(second)
        assert second_ready.wait(15)
        assert not second_charge.wait(1)
    finally:
        release.set()
        for process in started:
            process.join(15)
            if process.is_alive():
                process.terminate()
                process.join()
    assert first.exitcode == second.exitcode == 0
    assert not second_charge.is_set()
    assert len(list(tmp_path.glob("*.mp4"))) == 1
