from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, call

import pytest

from app.models.schema import VideoParams
from app.services import asset_library, asset_retrieval, task


def _params() -> VideoParams:
    params = VideoParams(video_subject="How private networks work")
    params.photo_enabled = True
    params.photo_amount = 5
    return params


def _asset(
    asset_id: int,
    rel_path: str,
    *,
    min_display: float | None = 2.0,
    tags: tuple[str, ...] = (),
) -> asset_library.Asset:
    return asset_library.Asset(
        id=asset_id,
        sha256=str(asset_id),
        rel_path=rel_path,
        width=100,
        height=100,
        min_display=min_display,
        tags=[asset_library.AssetTag(tag=tag) for tag in tags],
    )


def _assignment(
    index: int, asset: asset_library.Asset, verdict: str = "accept"
) -> asset_retrieval.Assignment:
    return asset_retrieval.Assignment(
        index=index,
        brief=f"brief {index}",
        asset=asset,
        verdict=verdict,
    )


def _write_assets(tmp_path: Path, *assets: asset_library.Asset) -> None:
    for asset in assets:
        path = tmp_path / asset.rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"photo")


@pytest.fixture
def library_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(task.asset_library, "is_enabled", lambda: True)
    monkeypatch.setattr(
        task.asset_library, "asset_path", lambda rel_path: str(tmp_path / rel_path)
    )


def test_disabled_library_keeps_legacy_photo_directory_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = _params()
    params.photo_dir = "legacy-photos"
    discover = Mock(return_value=[])
    select = Mock()
    monkeypatch.setattr(task.asset_library, "is_enabled", lambda: False)
    monkeypatch.setattr(task.photo_library, "discover_photo_themes", discover)
    monkeypatch.setattr(task.asset_retrieval, "select_assets", select)

    assert task.generate_photo_overlays("task", params, "script", None, "") == []

    discover.assert_called_once_with("legacy-photos")
    select.assert_not_called()


def test_unconfigured_library_keeps_legacy_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    params.photo_dir = str(tmp_path)
    monkeypatch.setattr(task.asset_library, "is_enabled", lambda: False)

    assert "contains no" in str(task._validate_photo_overlay_params(params))


@pytest.mark.usefixtures("library_enabled")
def test_library_preflight_reports_unavailable_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        task.asset_library, "summary", Mock(side_effect=OSError("connection refused"))
    )

    error = task._validate_photo_overlay_params(_params())

    assert error == "photo asset library is unavailable: connection refused"


@pytest.mark.usefixtures("library_enabled")
def test_library_preflight_rejects_empty_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        task.asset_library,
        "summary",
        Mock(return_value=asset_library.LibrarySummary(0, 0, 0, {})),
    )

    assert task._validate_photo_overlay_params(_params()) == (
        "photo asset library is empty"
    )


@pytest.mark.usefixtures("library_enabled")
def test_library_preflight_checks_required_assets_and_multiplicity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    params.photo_require = ["path:flow/start.jpg", "tag:payment", "tag:payment"]
    start = _asset(1, "flow/start.jpg")
    payment = _asset(2, "flow/payment.jpg", tags=("payment",))
    _write_assets(tmp_path, start, payment)
    monkeypatch.setattr(
        task.asset_library,
        "summary",
        Mock(return_value=asset_library.LibrarySummary(2, 0, 0, {})),
    )
    monkeypatch.setattr(
        task.asset_library, "list_assets", Mock(return_value=[start, payment])
    )

    error = task._validate_photo_overlay_params(params)

    assert error == "required photo assets are missing: tag:payment"


@pytest.mark.usefixtures("library_enabled")
def test_library_preflight_accepts_existing_path_and_tag_requirements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    params.photo_require = ["path:flow/start.jpg", "tag:payment"]
    start = _asset(1, "flow/start.jpg")
    payment = _asset(2, "flow/payment.jpg", tags=("payment",))
    _write_assets(tmp_path, start, payment)
    monkeypatch.setattr(
        task.asset_library,
        "summary",
        Mock(return_value=asset_library.LibrarySummary(2, 0, 0, {})),
    )
    monkeypatch.setattr(
        task.asset_library, "list_assets", Mock(return_value=[start, payment])
    )

    assert task._validate_photo_overlay_params(params) is None


@pytest.mark.usefixtures("library_enabled")
def test_library_selection_preserves_renderer_shape_and_marks_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    params.photo_require = ["path:required.jpg"]
    params.photo_prefer_tags = ["vpn"]
    params.photo_exclude_tags = ["logo"]
    first = _asset(1, "required.jpg", min_display=3.0)
    second = _asset(2, "second.jpg", min_display=2.0)
    _write_assets(tmp_path, first, second)
    windows = [((1.0, 2.0), "one"), ((5.0, 6.0), "two"), ((9.0, 12.0), "three")]
    selection = asset_retrieval.Selection(
        assignments=[
            _assignment(0, first, asset_retrieval.VERDICT_REQUIRED),
            _assignment(1, second),
        ]
    )
    select = Mock(return_value=selection)
    record = Mock()
    monkeypatch.setattr(task, "_gif_timeline", Mock(return_value=windows))
    monkeypatch.setattr(task.asset_retrieval, "select_assets", select)
    monkeypatch.setattr(task.asset_library, "record_usage", record)
    monkeypatch.setattr(task.media_scout, "is_enabled", lambda: False)

    overlays = task.generate_photo_overlays("task-1", params, "script", None, "")

    assert overlays == [
        {"path": str(tmp_path / "required.jpg"), "start": 1.0, "end": 4.0},
        {"path": str(tmp_path / "second.jpg"), "start": 5.0, "end": 7.0},
    ]
    assert all(set(overlay) == {"path", "start", "end"} for overlay in overlays)
    assert select.call_args.kwargs["require"] == ["path:required.jpg"]
    assert select.call_args.kwargs["prefer_tags"] == ["vpn"]
    assert select.call_args.kwargs["exclude_tags"] == ["logo"]
    assert record.call_args_list == [
        call(1, "task-1"),
        call(2, "task-1"),
    ]


@pytest.mark.usefixtures("library_enabled")
def test_asset_duration_is_capped_by_max_next_overlay_and_timeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    params.photo_max_duration = 4.0
    first = _asset(1, "first.jpg", min_display=20.0)
    second = _asset(2, "second.jpg", min_display=20.0)
    _write_assets(tmp_path, first, second)
    windows = [((2.0, 2.5), "one"), ((5.0, 5.5), "two"), ((8.0, 9.0), "end")]
    monkeypatch.setattr(task, "_gif_timeline", Mock(return_value=windows))
    monkeypatch.setattr(
        task,
        "_select_library_assets",
        Mock(return_value=[_assignment(0, first), _assignment(1, second)]),
    )
    monkeypatch.setattr(task.asset_library, "record_usage", Mock())

    overlays = task.generate_photo_overlays("task", params, "script", None, "")

    assert overlays[0]["start"] == 2.0
    assert overlays[0]["end"] == 5.0
    assert overlays[1]["start"] == 5.0
    assert overlays[1]["end"] == 9.0


@pytest.mark.usefixtures("library_enabled")
def test_missing_min_duration_uses_legacy_duration_and_jitter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    params.photo_duration = 3.0
    asset = _asset(1, "photo.jpg", min_display=None)
    _write_assets(tmp_path, asset)
    monkeypatch.setattr(
        task, "_gif_timeline", Mock(return_value=[((0.0, 10.0), "one")])
    )
    monkeypatch.setattr(
        task, "_select_library_assets", Mock(return_value=[_assignment(0, asset)])
    )
    monkeypatch.setattr(task.video, "_deterministic_unit", Mock(return_value=1.0))
    monkeypatch.setattr(task.asset_library, "record_usage", Mock())

    overlays = task.generate_photo_overlays("task", params, "script", None, "")

    assert overlays[0]["end"] == 3.5


@pytest.mark.usefixtures("library_enabled")
def test_meaningless_interval_is_dropped_and_not_marked_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _params()
    first = _asset(1, "first.jpg", min_display=3.0)
    second = _asset(2, "second.jpg", min_display=3.0)
    _write_assets(tmp_path, first, second)
    record = Mock()
    monkeypatch.setattr(
        task,
        "_gif_timeline",
        Mock(return_value=[((0.0, 3.0), "one"), ((0.5, 5.0), "two")]),
    )
    monkeypatch.setattr(
        task,
        "_select_library_assets",
        Mock(return_value=[_assignment(0, first), _assignment(1, second)]),
    )
    monkeypatch.setattr(task.asset_library, "record_usage", record)

    overlays = task.generate_photo_overlays("task", params, "script", None, "")

    assert [overlay["start"] for overlay in overlays] == [0.5]
    record.assert_called_once_with(2, "task")


@pytest.mark.usefixtures("library_enabled")
def test_scouted_asset_fills_unsatisfied_slot_in_same_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = _params()
    existing = _asset(1, "existing.jpg")
    downloaded = _asset(2, "downloaded.jpg", min_display=None)
    selection = asset_retrieval.Selection(
        assignments=[_assignment(0, existing)],
        unsatisfied=[
            asset_retrieval.Unsatisfied(
                index=1,
                brief="phone showing a secure connection",
                reason=asset_retrieval.REASON_NO_CANDIDATES,
            )
        ],
    )
    monkeypatch.setattr(
        task.asset_retrieval, "select_assets", Mock(return_value=selection)
    )
    monkeypatch.setattr(task.media_scout, "is_enabled", lambda: True)
    monkeypatch.setattr(task.media_scout, "search_limit", lambda: 1)
    scout = Mock(return_value=[downloaded])
    monkeypatch.setattr(task.media_scout, "scout_images", scout)

    assignments = task._select_library_assets(
        params, [((0.0, 1.0), "one"), ((1.0, 2.0), "two")]
    )

    assert [(item.index, item.asset.id) for item in assignments] == [(0, 1), (1, 2)]
    scout.assert_called_once_with("phone showing a secure connection", limit=1)


@pytest.mark.usefixtures("library_enabled")
def test_hard_only_tags_suppress_scouting(monkeypatch: pytest.MonkeyPatch) -> None:
    params = _params()
    params.photo_only_tags = ["owned"]
    selection = asset_retrieval.Selection(
        unsatisfied=[
            asset_retrieval.Unsatisfied(
                index=0,
                brief="anything",
                reason=asset_retrieval.REASON_NO_CANDIDATES,
            )
        ]
    )
    scout = Mock()
    monkeypatch.setattr(
        task.asset_retrieval, "select_assets", Mock(return_value=selection)
    )
    monkeypatch.setattr(task.media_scout, "is_enabled", lambda: True)
    monkeypatch.setattr(task.media_scout, "scout_images", scout)

    assert task._select_library_assets(params, [((0.0, 1.0), "one")]) == []
    scout.assert_not_called()


@pytest.mark.usefixtures("library_enabled")
def test_scout_search_count_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    params = _params()
    selection = asset_retrieval.Selection(
        unsatisfied=[
            asset_retrieval.Unsatisfied(
                index=index,
                brief=f"query {index}",
                reason=asset_retrieval.REASON_NO_CANDIDATES,
            )
            for index in range(3)
        ]
    )
    scout = Mock(return_value=[])
    monkeypatch.setattr(
        task.asset_retrieval, "select_assets", Mock(return_value=selection)
    )
    monkeypatch.setattr(task.media_scout, "is_enabled", lambda: True)
    monkeypatch.setattr(task.media_scout, "search_limit", lambda: 2)
    monkeypatch.setattr(task.media_scout, "scout_images", scout)

    task._select_library_assets(
        params, [((float(index), float(index + 1)), "line") for index in range(3)]
    )

    assert scout.call_count == 2


def test_pipeline_preflight_fails_before_script_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = _params()
    script = Mock()
    failed = Mock(return_value={"error": "preflight"})
    monkeypatch.setattr(
        task, "_validate_photo_overlay_params", Mock(return_value="empty")
    )
    monkeypatch.setattr(task, "generate_script", script)
    monkeypatch.setattr(task, "_mark_task_failed", failed)
    monkeypatch.setattr(task.sm.state, "update_task", Mock())

    result = task._run_pipeline("task", params, stop_at="video")

    assert result == {"error": "preflight"}
    failed.assert_called_once_with("task", "preflight", "empty")
    script.assert_not_called()


def test_stop_at_script_bypasses_photo_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = _params()
    preflight = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(task, "_validate_photo_overlay_params", preflight)
    monkeypatch.setattr(task, "generate_script", Mock(return_value="ready"))
    monkeypatch.setattr(task.sm.state, "update_task", Mock())

    result = task._run_pipeline("task", params, stop_at="script")

    assert result == {"script": "ready"}
    preflight.assert_not_called()


def test_stop_at_subtitle_does_not_select_library_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = _params()
    overlays = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(task, "generate_script", Mock(return_value="ready"))
    monkeypatch.setattr(task, "generate_terms", Mock(return_value=["term"]))
    monkeypatch.setattr(task, "save_script_data", Mock())
    monkeypatch.setattr(
        task, "generate_audio", Mock(return_value=("audio.mp3", 2.0, object()))
    )
    monkeypatch.setattr(task, "generate_subtitle", Mock(return_value="subtitle.srt"))
    monkeypatch.setattr(task, "generate_photo_overlays", overlays)
    monkeypatch.setattr(task.sm.state, "update_task", Mock())

    result = task._run_pipeline("task", params, stop_at="subtitle")

    assert result == {"subtitle_path": "subtitle.srt"}
    overlays.assert_not_called()
