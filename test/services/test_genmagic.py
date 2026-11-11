import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import genmagic, material, state as sm
from app.services import task as task_service


RUN_INTEGRATION_TESTS = os.environ.get("MPT_RUN_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}

# Catalog rows follow GET /api/v1/models?category=video. The ids are fixtures,
# not real model names: the code under test never hardcodes a model.
CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "example/clip-model",
            "category": "video",
            "capabilities": {"text_to_video": True},
            "pricing": {
                "video": {
                    "durations_seconds": [8, 4, 6],
                    "resolutions": ["720p", "1080p"],
                }
            },
        },
        {
            "id": "example/fixed-model",
            "category": "video",
            "capabilities": {"text_to_video": True},
            "pricing": {"video": {"durations_seconds": [5, 10]}},
        },
        {
            "id": "example/no-lengths-model",
            "category": "video",
            "capabilities": {"text_to_video": True},
            "pricing": {"video": {"resolutions": ["720p"]}},
        },
        {
            "id": "example/edit-only-model",
            "category": "video",
            "capabilities": {"text_to_video": False},
            "pricing": {"video": {"durations_seconds": [5]}},
        },
    ],
}


def _body(payload):
    if isinstance(payload, Exception):
        raise payload
    return payload


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: _body(payload),
    )


def _router(polls, catalog=None):
    """A fake ``requests.get``: the catalog URL gets the catalog, others get polls."""
    polls = list(polls)

    def fake_get(url, **kwargs):
        if url.endswith("/models"):
            if isinstance(catalog, Exception):
                raise catalog
            return catalog if catalog is not None else _response(CATALOG)
        item = polls.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return fake_get


def _completed(task_id, url="https://cdn.example.com/video.mp4"):
    return _response(
        {
            "id": task_id,
            "object": "video.generation",
            "model": "example/clip-model",
            "status": "completed",
            "url": url,
            "cost_cents": 12.5,
        }
    )


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "genmagic_api_key": "gm_live_test-key",
            "genmagic_base_url": genmagic.DEFAULT_BASE_URL,
            "genmagic_video_model": "",
            "genmagic_resolution": "",
            "genmagic_poll_interval": 5,
            "genmagic_run_timeout": 1800,
        }
    )
    config.proxy.clear()
    genmagic._catalog_cache.clear()
    yield
    genmagic._catalog_cache.clear()
    config.app.clear()
    config.app.update(original_app)
    config.proxy.clear()
    config.proxy.update(original_proxy)


def test_api_key_prefers_config_then_genmagic_environment():
    with patch.dict(os.environ, {"GENMAGIC_API_KEY": "environment-key"}, clear=False):
        assert genmagic.get_api_key() == "gm_live_test-key"
        config.app["genmagic_api_key"] = "   "
        assert genmagic.get_api_key() == "environment-key"
        os.environ["GENMAGIC_API_KEY"] = ""
        assert genmagic.get_api_key() == ""
        assert not genmagic.is_enabled()


@pytest.mark.parametrize("term", ["", "   ", None])
def test_invalid_input_fails_before_paid_submission(term):
    with patch.object(genmagic.requests, "post") as post:
        with pytest.raises(genmagic.GenMagicError):
            genmagic.generate_videos(term, 5)
    post.assert_not_called()


def test_missing_key_fails_before_submission():
    config.app["genmagic_api_key"] = ""
    with patch.dict(os.environ, {"GENMAGIC_API_KEY": ""}):
        with patch.object(genmagic.requests, "post") as post:
            with pytest.raises(genmagic.GenMagicError, match="API key"):
                genmagic.generate_videos("sunrise", 5)
    post.assert_not_called()


def test_submit_poll_and_parse_successful_video():
    submit = _response(
        {
            "id": "job-1",
            "object": "video.generation",
            "model": "example/default-model",
            "status": "queued",
            "status_url": "/api/v1/videos/job-1",
        },
        202,
    )
    polls = [
        _response({"id": "job-1", "status": "queued"}),
        _response({"id": "job-1", "status": "processing"}),
        _completed("job-1"),
    ]
    with (
        patch.object(genmagic.requests, "post", return_value=submit) as post,
        patch.object(genmagic.requests, "get", side_effect=_router(polls)) as get,
        patch.object(genmagic.time, "sleep") as sleep,
    ):
        result = genmagic.generate_videos(
            "  sunrise over mountains  ",
            minimum_duration=5,
            video_aspect=VideoAspect.portrait,
        )

    assert len(result) == 1
    item = result[0]
    assert item.provider == "genmagic"
    assert item.url == "https://cdn.example.com/video.mp4"
    assert item.duration == 5
    assert item.source_info == {
        "provider": "genmagic",
        "search_term": "sunrise over mountains",
        "asset_id": "job-1",
        "rendition": {"id": "job-1", "width": 1080, "height": 1920},
    }
    assert post.call_args.args[0] == "https://genmagic.co/api/v1/videos"
    assert post.call_args.kwargs["headers"] == {
        "Authorization": "Bearer gm_live_test-key",
        "Content-Type": "application/json",
        "X-GenMagic-Client": "moneyprinterturbo/1.0.0",
    }
    assert post.call_args.kwargs["allow_redirects"] is False
    # No model, length or resolution is sent unless one is configured: GenMagic
    # uses its default model. Sound is never requested because MPT discards it.
    assert post.call_args.kwargs["json"] == {
        "prompt": "sunrise over mountains",
        "aspect_ratio": "9:16",
        "generate_audio": False,
    }
    poll_calls = get.call_args_list
    assert len(poll_calls) == 3
    assert all(
        call.args[0] == "https://genmagic.co/api/v1/videos/job-1"
        for call in poll_calls
    )
    assert all(call.kwargs["allow_redirects"] is False for call in poll_calls)
    assert all(
        call.kwargs["headers"]["Authorization"] == "Bearer gm_live_test-key"
        for call in poll_calls
    )
    assert [call.args[0] for call in sleep.call_args_list] == [5, 5]


def test_configured_model_and_resolution_follow_the_catalog_lengths():
    config.app.update(
        {
            "genmagic_video_model": "example/clip-model",
            "genmagic_resolution": "720p",
            "genmagic_base_url": "https://gateway.example.test/api/v1/",
        }
    )
    submit = _response({"id": "job-model"}, 202)
    with (
        patch.object(genmagic.requests, "post", return_value=submit) as post,
        patch.object(
            genmagic.requests,
            "get",
            side_effect=_router([_completed("job-model")]),
        ) as get,
    ):
        result = genmagic.generate_videos("city", 5, VideoAspect.landscape)

    # The model lists 4, 6 and 8 seconds: 5 rounds up to 6.
    assert result[0].duration == 6
    assert post.call_args.args[0] == "https://gateway.example.test/api/v1/videos"
    assert post.call_args.kwargs["json"] == {
        "prompt": "city",
        "aspect_ratio": "16:9",
        "generate_audio": False,
        "model": "example/clip-model",
        "duration": 6,
        "resolution": "720p",
    }
    catalog_call = get.call_args_list[0]
    assert catalog_call.args[0] == "https://gateway.example.test/api/v1/models"
    assert catalog_call.kwargs["params"] == {"category": "video"}
    # The catalog is a free public lookup: the key is never sent to it.
    assert "Authorization" not in catalog_call.kwargs["headers"]


@pytest.mark.parametrize(
    "requested, expected",
    [(1, 4), (4, 4), (5, 6), (8, 8), (99, 8)],
)
def test_clip_length_uses_shortest_listed_length_that_covers_the_request(
    requested, expected
):
    config.app["genmagic_video_model"] = "example/clip-model"
    with patch.object(genmagic.requests, "get", side_effect=_router([])):
        assert genmagic._pick_duration(
            "example/clip-model", requested, genmagic.DEFAULT_BASE_URL
        ) == expected


@pytest.mark.parametrize(
    "model",
    [
        "",
        "example/unknown-model",
        "example/no-lengths-model",
        "example/edit-only-model",
    ],
)
def test_length_is_left_to_genmagic_when_the_catalog_cannot_confirm_one(model):
    with patch.object(genmagic.requests, "get", side_effect=_router([])):
        assert genmagic._pick_duration(model, 5, genmagic.DEFAULT_BASE_URL) is None


@pytest.mark.parametrize(
    "catalog",
    [
        requests.exceptions.ConnectionError("offline"),
        _response({}, status_code=503),
        _response({"data": "not a list"}),
        _response(ValueError("not json")),
    ],
)
def test_unreachable_catalog_never_blocks_a_submission(catalog):
    config.app["genmagic_video_model"] = "example/clip-model"
    submit = _response({"id": "job-nocatalog"}, 202)
    with (
        patch.object(genmagic.requests, "post", return_value=submit) as post,
        patch.object(
            genmagic.requests,
            "get",
            side_effect=_router([_completed("job-nocatalog")], catalog=catalog),
        ),
    ):
        result = genmagic.generate_videos("sunrise", 5)

    assert len(result) == 1
    sent = post.call_args.kwargs["json"]
    assert sent["model"] == "example/clip-model"
    assert "duration" not in sent


def test_catalog_is_cached_between_clips():
    config.app["genmagic_video_model"] = "example/clip-model"
    with patch.object(genmagic.requests, "get", side_effect=_router([])) as get:
        genmagic._pick_duration("example/clip-model", 5, genmagic.DEFAULT_BASE_URL)
        genmagic._pick_duration("example/clip-model", 7, genmagic.DEFAULT_BASE_URL)
    assert get.call_count == 1


def test_unsafe_base_url_is_rejected_before_any_request():
    for bad in ("not a url", "ftp://genmagic.co/api/v1", "https://user:pw@genmagic.co/v1"):
        config.app["genmagic_base_url"] = bad
        with patch.object(genmagic.requests, "post") as post:
            with pytest.raises(genmagic.GenMagicError, match="genmagic_base_url"):
                genmagic.generate_videos("sunrise", 5)
        post.assert_not_called()


def test_rejected_submission_reports_the_error_envelope_and_is_not_retried():
    rejected = _response(
        {
            "error": {
                "message": "Insufficient credits gm_live_test-key",
                "code": "insufficient_credits",
                "type": "insufficient_quota",
            }
        },
        status_code=402,
    )
    with patch.object(genmagic.requests, "post", return_value=rejected) as post:
        with pytest.raises(genmagic.GenMagicError) as raised:
            genmagic.generate_videos("unsafe", 5)

    assert not isinstance(raised.value, genmagic.GenMagicUnconfirmedTaskError)
    assert "HTTP 402" in str(raised.value)
    assert "insufficient_credits" in str(raised.value)
    assert "gm_live_test-key" not in str(raised.value)
    assert post.call_count == 1


def test_wrong_key_is_a_clean_authentication_error():
    rejected = _response(
        {"error": {"message": "Invalid API key.", "code": "invalid_api_key"}},
        status_code=401,
    )
    with patch.object(genmagic.requests, "post", return_value=rejected) as post:
        with pytest.raises(genmagic.GenMagicError, match="HTTP 401"):
            genmagic.generate_videos("sunrise", 5)
    assert post.call_count == 1


def test_ambiguous_submission_is_unconfirmed_and_not_retried():
    for side_effect, response in (
        (requests.exceptions.ConnectionError("offline"), None),
        (requests.exceptions.ReadTimeout("slow"), None),
        (None, _response({"error": {"message": "bad gateway"}}, status_code=502)),
        (None, _response(ValueError("not json"), status_code=202)),
    ):
        with patch.object(
            genmagic.requests,
            "post",
            side_effect=side_effect,
            return_value=response,
        ) as post:
            with pytest.raises(genmagic.GenMagicUnconfirmedTaskError):
                genmagic.generate_videos("sunrise", 5)
        assert post.call_count == 1


def test_submission_redirect_is_unconfirmed_and_never_followed():
    redirect = _response(
        {},
        status_code=307,
        headers={"Location": "https://attacker.example/submit?key=gm_live_test-key"},
    )
    with (
        patch.object(genmagic.requests, "post", return_value=redirect) as post,
        patch.object(genmagic.requests, "get") as get,
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError) as raised:
            genmagic.generate_videos("sunrise", 5)

    assert "gm_live_test-key" not in str(raised.value)
    assert post.call_count == 1
    assert post.call_args.kwargs["allow_redirects"] is False
    get.assert_not_called()


def test_poll_redirect_is_unconfirmed_and_never_retried():
    submit = _response({"id": "job-redirect"}, 202)
    redirect = _response(
        {}, status_code=307, headers={"Location": "https://attacker.example/result"}
    )
    with (
        patch.object(genmagic.requests, "post", return_value=submit) as post,
        patch.object(genmagic.requests, "get", return_value=redirect) as get,
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError) as raised:
            genmagic.generate_videos("sunrise", 5)

    assert raised.value.task_id == "job-redirect"
    assert post.call_count == 1
    assert get.call_count == 1
    assert get.call_args.kwargs["allow_redirects"] is False


def test_poll_retries_transient_errors_on_the_same_job():
    submit = _response({"id": "job-retry"}, 202)
    polls = [
        _response({"error": {"message": "slow down"}}, status_code=429),
        requests.exceptions.ConnectionError("offline"),
        _response({"error": {"message": "bad gateway"}}, status_code=502),
        _completed("job-retry"),
    ]
    with (
        patch.object(genmagic.requests, "post", return_value=submit) as post,
        patch.object(genmagic.requests, "get", side_effect=_router(polls)) as get,
        patch.object(genmagic.time, "sleep") as sleep,
    ):
        result = genmagic.generate_videos("sunrise", 5)

    assert len(result) == 1
    assert post.call_count == 1
    assert get.call_count == 4
    assert all(call.args[0].endswith("/videos/job-retry") for call in get.call_args_list)
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0, 3.0]


def test_poll_gives_up_after_bounded_retries_and_keeps_the_job_id():
    submit = _response({"id": "job-exhausted"}, 202)
    polls = [_response({}, status_code=503)] * (genmagic.MAX_POLL_RETRIES + 1)
    with (
        patch.object(genmagic.requests, "post", return_value=submit) as post,
        patch.object(genmagic.requests, "get", side_effect=_router(polls)) as get,
        patch.object(genmagic.time, "sleep"),
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError) as raised:
            genmagic.generate_videos("sunrise", 5)

    assert raised.value.task_id == "job-exhausted"
    assert post.call_count == 1
    assert get.call_count == genmagic.MAX_POLL_RETRIES + 1


@pytest.mark.parametrize("status_code", [401, 404])
def test_polling_error_leaves_the_job_state_unknown(status_code):
    submit = _response({"id": "job-lookup"}, 202)
    lookup = _response(
        {"error": {"message": "nope", "code": "not_found"}}, status_code=status_code
    )
    with (
        patch.object(genmagic.requests, "post", return_value=submit),
        patch.object(genmagic.requests, "get", return_value=lookup) as get,
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError) as raised:
            genmagic.generate_videos("sunrise", 5)

    assert raised.value.task_id == "job-lookup"
    assert get.call_count == 1


def test_unknown_status_is_unconfirmed():
    with patch.object(
        genmagic.requests,
        "get",
        return_value=_response({"id": "job-odd", "status": "teleporting"}),
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError) as raised:
            genmagic._wait_for_task(
                task_id="job-odd",
                base_url=genmagic.DEFAULT_BASE_URL,
                headers={},
                api_key="gm_live_test-key",
            )
    assert raised.value.task_id == "job-odd"


def test_local_wait_timeout_is_unconfirmed_with_the_job_id():
    config.app["genmagic_run_timeout"] = 60
    clock = iter([0.0, 0.0, 10.0, 61.0])
    fake_time = SimpleNamespace(
        monotonic=lambda: next(clock), sleep=lambda _seconds: None
    )
    with (
        patch.object(genmagic, "time", fake_time),
        patch.object(
            genmagic.requests,
            "get",
            return_value=_response({"id": "job-slow", "status": "processing"}),
        ),
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError) as raised:
            genmagic._wait_for_task(
                task_id="job-slow",
                base_url=genmagic.DEFAULT_BASE_URL,
                headers={},
                api_key="gm_live_test-key",
            )
    assert raised.value.task_id == "job-slow"


@pytest.mark.parametrize("payload", [{}, {"id": "   "}, [], None])
def test_missing_job_id_is_unconfirmed_and_never_polled(payload):
    with (
        patch.object(genmagic.requests, "post", return_value=_response(payload, 202)),
        patch.object(genmagic.requests, "get") as get,
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError):
            genmagic.generate_videos("sunrise", 5)
    get.assert_not_called()


@pytest.mark.parametrize("url", [None, "", "ftp://cdn.example.com/v.mp4", 7])
def test_completed_job_without_a_downloadable_url_keeps_the_job_id(url):
    completed = _response({"id": "job-no-url", "status": "completed", "url": url})
    with (
        patch.object(
            genmagic.requests, "post", return_value=_response({"id": "job-no-url"}, 202)
        ),
        patch.object(genmagic.requests, "get", return_value=completed),
    ):
        with pytest.raises(genmagic.GenMagicError) as raised:
            genmagic.generate_videos("sunrise", 5)
    assert raised.value.task_id == "job-no-url"


def test_failed_job_returns_no_material_so_the_next_keyword_can_run():
    failed = _response(
        {
            "id": "job-failed",
            "status": "failed",
            "error": "The model could not render this prompt gm_live_test-key",
        }
    )
    with (
        patch.object(
            genmagic.requests, "post", return_value=_response({"id": "job-failed"}, 202)
        ),
        patch.object(genmagic.requests, "get", return_value=failed),
    ):
        assert genmagic.generate_videos("sunrise", 5) == []


def test_on_demand_generation_stops_after_required_duration():
    generated_item = MaterialInfo(
        provider="genmagic",
        url="https://cdn.example.com/video.mp4",
        duration=5,
        source_info={"asset_id": "gm-paid-1"},
    )
    with (
        patch.object(genmagic, "generate_videos", return_value=[generated_item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value="/tmp/video.mp4"),
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_genmagic_on_demand(
            task_id="local-task",
            search_terms=["first", "second"],
            video_aspect=VideoAspect.landscape,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )

    assert paths == ["/tmp/video.mp4"]
    assert generate.call_count == 1
    assert generate.call_args.kwargs["search_term"] == "first"


def test_on_demand_counts_actual_downloaded_duration_before_next_paid_submission():
    generated_items = [
        MaterialInfo(
            provider="genmagic",
            url="https://cdn.example.com/short.mp4",
            duration=5,
            source_info={"asset_id": "gm-paid-short"},
        ),
        MaterialInfo(
            provider="genmagic",
            url="https://cdn.example.com/full.mp4",
            duration=5,
            source_info={"asset_id": "gm-paid-full"},
        ),
    ]
    with (
        patch.object(
            genmagic,
            "generate_videos",
            side_effect=[[generated_items[0]], [generated_items[1]]],
        ) as generate,
        patch.object(
            material,
            "_save_generated_video_with_retry",
            side_effect=["/tmp/short.mp4", "/tmp/full.mp4"],
        ),
        patch.object(
            material, "_get_downloaded_video_duration", side_effect=[2.0, 5.0]
        ),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_genmagic_on_demand(
            task_id="local-task",
            search_terms=["short scene", "full scene", "never used"],
            video_aspect=VideoAspect.landscape,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )

    assert paths == ["/tmp/short.mp4", "/tmp/full.mp4"]
    assert [call.kwargs["search_term"] for call in generate.call_args_list] == [
        "short scene",
        "full scene",
    ]


def test_on_demand_moves_on_to_the_next_keyword_after_a_failed_job():
    generated_item = MaterialInfo(
        provider="genmagic",
        url="https://cdn.example.com/second.mp4",
        duration=5,
        source_info={"asset_id": "gm-paid-second"},
    )
    with (
        patch.object(
            genmagic, "generate_videos", side_effect=[[], [generated_item]]
        ) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value="/tmp/second.mp4"),
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_genmagic_on_demand(
            task_id="local-task",
            search_terms=["rejected", "accepted"],
            video_aspect=VideoAspect.landscape,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )

    assert paths == ["/tmp/second.mp4"]
    assert generate.call_count == 2


def test_on_demand_stops_placing_jobs_after_an_unconfirmed_one():
    unconfirmed = genmagic.GenMagicUnconfirmedTaskError("unknown", task_id="gm-lost")
    with (
        patch.object(genmagic, "generate_videos", side_effect=unconfirmed) as generate,
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(genmagic.GenMagicUnconfirmedTaskError):
            material._download_videos_genmagic_on_demand(
                task_id="local-task",
                search_terms=["one", "two"],
                video_aspect=VideoAspect.landscape,
                audio_duration=10,
                max_clip_duration=5,
                material_directory="/tmp",
            )
    assert generate.call_count == 1


@pytest.mark.parametrize("audio_duration", [float("nan"), float("inf"), None, "bad"])
def test_on_demand_rejects_invalid_audio_duration_before_submission(audio_duration):
    with patch.object(genmagic, "generate_videos") as generate:
        with pytest.raises(genmagic.GenMagicError, match="audio duration"):
            material.download_videos(
                task_id="genmagic-invalid-audio",
                search_terms=["one", "two"],
                source="genmagic",
                audio_duration=audio_duration,
                max_clip_duration=5,
            )
    generate.assert_not_called()


def test_download_failure_stops_later_paid_submissions_and_keeps_job_id():
    generated_item = MaterialInfo(
        provider="genmagic",
        url="https://cdn.example.com/video.mp4",
        duration=5,
        source_info={"asset_id": "gm-paid-download"},
    )
    with (
        patch.object(genmagic, "generate_videos", return_value=[generated_item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
    ):
        with pytest.raises(genmagic.GenMagicDownloadError) as raised:
            material.download_videos(
                task_id="genmagic-download-failed",
                search_terms=["one", "two"],
                source="genmagic",
                audio_duration=10,
                max_clip_duration=5,
            )
    assert raised.value.task_id == "gm-paid-download"
    assert generate.call_count == 1


def test_task_preflight_rejects_missing_key_before_script_generation():
    params = VideoParams(video_subject="GenMagic preflight", video_source="genmagic")
    memory_state = sm.MemoryState()
    with (
        patch.object(genmagic, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("genmagic-preflight", params, stop_at="materials")

    assert result["failed_stage"] == "preflight"
    assert "GenMagic video generation requires a GenMagic API key" in result["error"]
    generate_script.assert_not_called()


def test_material_failure_keeps_genmagic_job_id_in_task_state():
    params = VideoParams(video_subject="space fleet", video_source="genmagic")
    failure = genmagic.GenMagicUnconfirmedTaskError(
        "remote state unknown", task_id="gm-recover-1"
    )
    with (
        patch.object(task_service.material, "download_videos", side_effect=failure),
        patch.object(sm.state, "update_task") as update_task,
    ):
        result = task_service.get_video_materials(
            "local-task",
            params,
            ["space fleet"],
            audio_duration=5,
        )

    assert result is None
    failed_update = update_task.call_args.kwargs
    assert failed_update["genmagic_task_id"] == "gm-recover-1"


@pytest.mark.skipif(
    not RUN_INTEGRATION_TESTS,
    reason="MPT_RUN_INTEGRATION_TESTS not set",
)
def test_live_wrong_key_is_answered_401_without_creating_a_job():
    """A wrong key is rejected before any job exists, so this call is free."""
    config.app["genmagic_api_key"] = "gm_live_invalid_key_for_integration_test"
    with pytest.raises(genmagic.GenMagicError) as raised:
        genmagic.generate_videos("a calm sunrise over mountains", 5)
    assert not isinstance(raised.value, genmagic.GenMagicUnconfirmedTaskError)
    assert "HTTP 401" in str(raised.value)
    assert raised.value.task_id == ""


@pytest.mark.skipif(
    not RUN_INTEGRATION_TESTS,
    reason="MPT_RUN_INTEGRATION_TESTS not set",
)
def test_live_video_catalog_needs_no_key():
    """The catalog is a free public lookup that lists lengths per model."""
    config.app["genmagic_api_key"] = ""
    models = genmagic.list_video_models()
    assert models
    assert all(model["capabilities"]["text_to_video"] is True for model in models)
