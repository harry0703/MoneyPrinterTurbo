from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material
from app.services import task as task_service
from app.services.state import MemoryState
import cli


def _item(provider, url, duration=5, term="term"):
    return MaterialInfo(
        provider=provider,
        url=url,
        duration=duration,
        source_info={"provider": provider, "search_term": term},
    )


class _ProviderResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self.text = ""
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def _typed_provider_result(provider, *, response=None, request_error=None):
    request_behavior = (
        {"side_effect": request_error}
        if request_error is not None
        else {"return_value": response}
    )
    with (
        patch.object(material, "get_api_key", return_value="provider-secret"),
        patch.object(material.requests, "get", **request_behavior),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
    ):
        return material._provider_search(
            provider,
            "typed outcome",
            minimum_duration=1,
            video_aspect=VideoAspect.portrait,
        )


@pytest.mark.parametrize("provider", material.STOCK_PROVIDERS)
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(401, "authentication"), (429, "rate_limit")],
)
def test_every_provider_classifies_authentication_and_rate_limits(
    provider, status_code, error_type
):
    result = _typed_provider_result(
        provider, response=_ProviderResponse(status_code=status_code, payload={})
    )

    assert result.error is not None
    assert result.error.error_type == error_type


@pytest.mark.parametrize("provider", material.STOCK_PROVIDERS)
def test_every_provider_classifies_network_errors(provider):
    result = _typed_provider_result(
        provider, request_error=requests.ConnectionError("network unavailable")
    )

    assert result.error is not None
    assert result.error.error_type == "network"


@pytest.mark.parametrize("provider", material.STOCK_PROVIDERS)
def test_every_provider_classifies_malformed_responses(provider):
    result = _typed_provider_result(
        provider,
        response=_ProviderResponse(json_error=ValueError("not JSON")),
    )

    assert result.error is not None
    assert result.error.error_type == "malformed_response"


@pytest.mark.parametrize(
    ("provider", "payload"),
    [("pexels", {"videos": []}), ("pixabay", {"hits": []}), ("coverr", {"hits": []})],
)
def test_every_provider_preserves_valid_zero_result(provider, payload):
    result = _typed_provider_result(
        provider, response=_ProviderResponse(payload=payload)
    )

    assert result.error is None
    assert result.empty


def test_legacy_provider_mapping_and_ordered_unique_values():
    assert (
        VideoParams(video_subject="x", video_source="pexels_pixabay").model_dump()[
            "material_provider_mode"
        ]
        == "fan_out"
    )
    assert VideoParams(
        video_subject="x", video_source="pexels_pixabay"
    ).material_providers == [
        "pexels",
        "pixabay",
    ]
    params = VideoParams(
        video_subject="x",
        material_provider_mode="fallback",
        material_providers=["pixabay", "pexels", "pixabay"],
    )
    assert params.material_providers == ["pixabay", "pexels"]


def test_locked_strategy_never_contacts_second_provider():
    calls = []

    def searcher(**kwargs):
        calls.append(kwargs["search_term"])
        return [_item("pexels", "https://a", term=kwargs["search_term"])]

    with (
        patch.object(material, "search_videos_pexels", side_effect=searcher),
        patch.object(
            material, "search_videos_pixabay", side_effect=AssertionError("contacted")
        ),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
    ):
        items, records = material.search_materials_with_strategy(
            ["one", "two"],
            mode="locked",
            providers=["pexels", "pixabay"],
            minimum_duration=1,
            video_aspect=VideoAspect.portrait,
        )
    assert calls == ["one", "two"]
    assert [item.url for item in items] == ["https://a"]
    assert all(record["status"] == "success" for record in records)


def test_locked_strategy_keeps_successful_terms_before_provider_error():
    def pexels(**kwargs):
        if kwargs["search_term"] == "broken":
            raise material.ProviderSearchError("pexels", "broken", "timeout")
        return [_item("pexels", "https://ok", term="ok")]

    with (
        patch.object(material, "search_videos_pexels", side_effect=pexels),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
    ):
        items, records = material.search_materials_with_strategy(
            ["ok", "broken"],
            mode="locked",
            providers=["pexels"],
            minimum_duration=1,
            video_aspect=VideoAspect.portrait,
        )
    assert [item.url for item in items] == ["https://ok"]
    assert [record["status"] for record in records] == ["success", "error"]


def test_fan_out_merges_provider_priority_and_deduplicates_urls():
    responses = {
        ("pexels", "one"): [_item("pexels", "https://shared", term="one")],
        ("pixabay", "one"): [_item("pixabay", "https://shared", term="one")],
        ("pexels", "two"): [_item("pexels", "https://p2", term="two")],
        ("pixabay", "two"): [_item("pixabay", "https://b2", term="two")],
    }

    # Use HTTP-shaped provider substitutes to keep the test independent of the
    # actual network.
    def pexels(**kwargs):
        return responses[("pexels", kwargs["search_term"])]

    def pixabay(**kwargs):
        return responses[("pixabay", kwargs["search_term"])]

    with (
        patch.object(material, "search_videos_pexels", side_effect=pexels),
        patch.object(material, "search_videos_pixabay", side_effect=pixabay),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
    ):
        items, _ = material.search_materials_with_strategy(
            ["one", "two"],
            mode="fan_out",
            providers=["pexels", "pixabay"],
            minimum_duration=1,
            video_aspect=VideoAspect.portrait,
            max_workers=2,
        )
    assert [item.url for item in items] == [
        "https://shared",
        "https://p2",
        "https://b2",
    ]


def test_fan_out_preserves_successful_terms_when_one_call_errors():
    def pexels(**kwargs):
        if kwargs["search_term"] == "broken":
            raise material.ProviderSearchError("pexels", "broken", "timeout")
        return [_item("pexels", "https://ok", term="ok")]

    with (
        patch.object(material, "search_videos_pexels", side_effect=pexels),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
    ):
        items, records = material.search_materials_with_strategy(
            ["ok", "broken"],
            mode="fan_out",
            providers=["pexels"],
            minimum_duration=1,
            video_aspect=VideoAspect.portrait,
            max_workers=2,
        )
    assert [item.url for item in items] == ["https://ok"]
    assert [record["status"] for record in records] == ["success", "error"]
    assert records[1]["error_type"] == "provider"


def test_fallback_continues_after_empty_or_typed_error():
    calls = []

    def empty(**kwargs):
        calls.append("pexels")
        return []

    def failed(**kwargs):
        calls.append("pixabay")
        raise material.ProviderSearchError("pixabay", kwargs["search_term"], "quota")

    def coverr(**kwargs):
        calls.append("coverr")
        return [_item("coverr", "https://coverr", term=kwargs["search_term"])]

    with (
        patch.object(material, "search_videos_pexels", side_effect=empty),
        patch.object(material, "search_videos_pixabay", side_effect=failed),
        patch.object(material, "search_videos_coverr", side_effect=coverr),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
    ):
        items, records = material.search_materials_with_strategy(
            ["term"],
            mode="fallback",
            providers=["pexels", "pixabay", "coverr"],
            minimum_duration=1,
            video_aspect=VideoAspect.portrait,
        )
    assert calls == ["pexels", "pixabay", "coverr"]
    assert [item.provider for item in items] == ["coverr"]
    assert [record["status"] for record in records] == ["empty", "error", "success"]


def test_fallback_downloads_next_provider_after_duration_deficit():
    first = _item("pexels", "https://pexels/short", duration=2)
    second = _item("pixabay", "https://pixabay/long", duration=4)

    def pexels(**kwargs):
        return [first]

    def pixabay(**kwargs):
        return [second]

    with (
        patch.object(material, "search_videos_pexels", side_effect=pexels),
        patch.object(material, "search_videos_pixabay", side_effect=pixabay),
        patch.object(
            material.material_cache, "load_material_search_cache", return_value=None
        ),
        patch.object(material.material_cache, "save_material_search_cache"),
        patch.object(
            material,
            "save_video",
            side_effect=lambda video_url, save_dir="": (
                f"/tmp/{video_url.rsplit('/', 1)[-1]}.mp4"
            ),
        ) as save,
        patch.object(material, "_persist_material_provider_results") as persist_results,
        patch.object(material.task_artifacts, "patch_script_data", return_value=True),
    ):
        result = material.download_videos(
            task_id="fallback-deficit",
            search_terms=["term"],
            source="pexels",
            audio_duration=5,
            max_clip_duration=5,
            material_provider_mode="fallback",
            material_providers=["pexels", "pixabay"],
        )
    assert result == ["/tmp/short.mp4", "/tmp/long.mp4"]
    assert [call.args[0] for call in save.call_args_list] == [
        "https://pexels/short",
        "https://pixabay/long",
    ]
    summaries = persist_results.call_args.args[1]
    assert [summary["provider"] for summary in summaries] == ["pexels", "pixabay"]
    assert [summary["status"] for summary in summaries] == [
        "insufficient",
        "success",
    ]
    assert [summary["downloaded_duration"] for summary in summaries] == [2.0, 4.0]


def test_selected_provider_key_validation_requires_all_selected_keys():
    original = dict(config.app)
    try:
        config.app["pexels_api_keys"] = ["pexels-key"]
        config.app["pixabay_api_keys"] = []
        with pytest.raises(ValueError, match="pixabay"):
            material.validate_material_provider_keys(["pexels", "pixabay"])
    finally:
        config.app.clear()
        config.app.update(original)


def test_default_stock_pipeline_preflights_before_script_generation():
    params = VideoParams(video_subject="legacy default")
    state = MemoryState()
    with (
        patch.object(task_service.sm, "state", state),
        patch.object(
            task_service.material,
            "validate_material_provider_keys",
            side_effect=ValueError(
                "missing API key for selected material provider(s): pexels"
            ),
        ) as validate,
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service._run_pipeline("legacy-preflight", params, stop_at="video")
    validate.assert_called_once_with(["pexels"])
    generate_script.assert_not_called()
    assert result["failed_stage"] == "preflight"


def test_intermediate_stop_before_materials_skips_stock_preflight():
    params = VideoParams(video_subject="terms only")
    state = MemoryState()
    with (
        patch.object(task_service.sm, "state", state),
        patch.object(
            task_service.material, "validate_material_provider_keys"
        ) as validate,
        patch.object(task_service, "generate_script", return_value="script"),
        patch.object(task_service, "generate_terms", return_value=["term"]),
        patch.object(task_service, "save_script_data"),
    ):
        result = task_service._run_pipeline("terms-only", params, stop_at="terms")
    validate.assert_not_called()
    assert result == {"script": "script", "terms": ["term"]}


def test_cli_does_not_offer_unconfirmed_loomloom_video_source():
    with pytest.raises(SystemExit):
        cli.parse_args(["--video-subject", "x", "--video-source", "loomloom"])
