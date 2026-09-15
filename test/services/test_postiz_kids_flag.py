"""Security M1 (COPPA): YouTube audience declaration must flow to Postiz.

Regression coverage: ``PostizService`` previously hardcoded
``selfDeclaredMadeForKids: "no"`` and swallowed the task pipeline's
``youtube_extra`` kwarg. The declared upstream value (True/False) must reach
Postiz as ``"yes"``/``"no"``; an absent declaration must OMIT the key
(explicit absent) and NEVER silently assert ``"no"``.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.postiz import PostizService
from app.services import task as tm
from app.services.state import MemoryState

_BASE_CONFIG = {
    "postiz_enabled": True,
    "postiz_api_key": "test-key",
    "postiz_platforms": ["youtube"],
    "postiz_auto_upload": True,
    "postiz_youtube_privacy_status": "public",
    "postiz_youtube_integration_id": "yt-int-id",
    "postiz_max_pending_tasks": 5,
}


def _upload_then_post_side_effect(post_json=None):
    def post_side_effect(url, headers=None, files=None, json=None, *args, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url.endswith("/upload"):
            resp.json.return_value = {"id": "media123", "path": "/media/path/video.mp4"}
        elif url.endswith("/posts"):
            resp.json.return_value = post_json if post_json is not None else [{"postId": "post456"}]
        else:
            resp.json.return_value = {}
        return resp

    return post_side_effect


def _capture_youtube_settings(mock_post):
    for call in mock_post.call_args_list:
        url = call.args[0] if call.args else call.kwargs.get("url", "")
        if str(url).endswith("/posts"):
            payload = call.kwargs.get("json") or {}
            return payload["posts"][0]["settings"]
    raise AssertionError("no create-post payload captured")


def _run_upload(**kwargs):
    with (
        patch("app.services.postiz.config.app", _BASE_CONFIG),
        patch("app.services.postiz.os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=b"fake video data")),
        patch("app.services.postiz.requests.post") as mock_post,
    ):
        mock_post.side_effect = _upload_then_post_side_effect()
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Test Title", **kwargs)
    assert result.get("success") is True
    return _capture_youtube_settings(mock_post)


# ---------------------------------------------------------------------
# Behavior matrix: declared yes / no / absent -> value sent to Postiz
# ---------------------------------------------------------------------


def test_declared_true_sends_yes():
    settings = _run_upload(youtube_made_for_kids=True)
    assert settings["selfDeclaredMadeForKids"] == "yes"


def test_declared_false_sends_no():
    settings = _run_upload(youtube_made_for_kids=False)
    assert settings["selfDeclaredMadeForKids"] == "no"


def test_absent_declaration_omits_key_never_no():
    """No upstream value -> key omitted (explicit absent), not "no"."""
    settings = _run_upload()
    assert "selfDeclaredMadeForKids" not in settings


def test_snapshot_extra_is_primary_over_explicit_kwarg():
    settings = _run_upload(
        youtube_extra={"selfDeclaredMadeForKids": True},
        youtube_made_for_kids=False,
    )
    assert settings["selfDeclaredMadeForKids"] == "yes"


def test_explicit_kwarg_is_fallback_when_extra_absent():
    settings = _run_upload(youtube_made_for_kids=True)
    assert settings["selfDeclaredMadeForKids"] == "yes"


@pytest.mark.parametrize("invalid", ["bogus", "", 42, 0, 1, [], {}])
def test_invalid_declaration_omits_key_never_no(invalid):
    """Unrecognised values fail to absent (omit), never to "no".

    Note: real bools are handled before this; ints 0/1 are NOT bools here.
    """
    if isinstance(invalid, bool):
        pytest.skip("bools are valid declarations")
    settings = _run_upload(youtube_made_for_kids=invalid)
    assert "selfDeclaredMadeForKids" not in settings


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(True, "yes"), (False, "no"), ("yes", "yes"), ("no", "no")],
)
def test_settings_youtube_direct_matrix(declared, expected):
    settings = PostizService._settings_youtube("T", "public", made_for_kids=declared)
    assert settings["selfDeclaredMadeForKids"] == expected


def test_settings_youtube_absent_omits_key():
    settings = PostizService._settings_youtube("T", "public")
    assert "selfDeclaredMadeForKids" not in settings


# ---------------------------------------------------------------------
# Snapshot path: per-entry stamp, kwarg-only, snapshot primary
# ---------------------------------------------------------------------


@pytest.mark.parametrize("selected", [False, True])
def test_snapshot_builder_stamps_kids_per_entry(selected):
    postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
    with (
        patch.object(postiz_service, "is_configured", return_value=True),
        patch.object(type(postiz_service), "auto_upload", new_callable=PropertyMock, return_value=True),
        patch.object(type(postiz_service), "platforms", new_callable=PropertyMock, return_value=["youtube"]),
        patch.object(tm.upload_post.upload_post_service, "is_configured", return_value=False),
        patch.object(
            type(tm.upload_post.upload_post_service),
            "youtube_made_for_kids",
            new_callable=PropertyMock,
            return_value=selected,
        ),
        patch.dict(tm.config.app, {"postiz_youtube_integration_id": "yt-int-id"}, clear=False),
    ):
        snapshots = tm._snapshot_publishing_targets()
    assert len(snapshots) == 1
    assert snapshots[0]["extra"]["youtube_made_for_kids"] is selected


def test_worker_snapshot_stamp_is_primary_over_worker_arg():
    """Snapshot True + raced worker arg False must still declare "yes"."""
    postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
    snapshot = [
        {
            "provider": "postiz",
            "platforms": ["youtube"],
            "youtube_privacy_status": "public",
            "extra": {
                "tiktok_auto_add_music": "no",
                "reddit_subreddit": "",
                "integration_ids": {"youtube": "yt-int-id"},
                "youtube_made_for_kids": True,
            },
        }
    ]
    results: list = []
    with (
        patch.object(
            tm.llm,
            "generate_social_metadata",
            return_value={"title": "T", "caption": "C", "hashtags": []},
        ),
        patch.object(postiz_service, "upload_video", return_value={"success": True}) as upload,
    ):
        tm._run_cross_post_from_snapshot(
            "kids-primary",
            ("final.mp4",),
            "Subject",
            "script",
            "en",
            snapshot,
            results,
            False,  # raced worker arg: snapshot stamp must win
        )
    kwargs = upload.call_args[1]
    assert kwargs.get("youtube_made_for_kids") is True
    assert kwargs.get("youtube_extra", {}).get("selfDeclaredMadeForKids") is True


def test_worker_legacy_snapshot_without_stamp_falls_back_to_worker_arg():
    """Pre-M1 snapshots (no stamp) use the explicit worker declaration."""
    postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
    snapshot = [
        {
            "provider": "postiz",
            "platforms": ["youtube"],
            "youtube_privacy_status": "public",
            "extra": {
                "tiktok_auto_add_music": "no",
                "reddit_subreddit": "",
                "integration_ids": {"youtube": "yt-int-id"},
            },
        }
    ]
    results: list = []
    with (
        patch.object(
            tm.llm,
            "generate_social_metadata",
            return_value={"title": "T", "caption": "C", "hashtags": []},
        ),
        patch.object(postiz_service, "upload_video", return_value={"success": True}) as upload,
    ):
        tm._run_cross_post_from_snapshot(
            "kids-fallback",
            ("final.mp4",),
            "Subject",
            "script",
            "en",
            snapshot,
            results,
            True,
        )
    kwargs = upload.call_args[1]
    assert kwargs.get("youtube_made_for_kids") is True
    assert kwargs.get("youtube_extra", {}).get("selfDeclaredMadeForKids") is True


def test_end_to_end_snapshot_true_reaches_postiz_as_yes():
    """Full path: snapshot stamp True -> Postiz payload "yes"."""
    snapshot = [
        {
            "provider": "postiz",
            "platforms": ["youtube"],
            "youtube_privacy_status": "public",
            "extra": {
                "tiktok_auto_add_music": "no",
                "reddit_subreddit": "",
                "integration_ids": {"youtube": "yt-int-id"},
                "api_url": "http://instance-a:8004",
                "api_key": "key-a",
                "youtube_made_for_kids": True,
            },
        }
    ]
    state = MemoryState()
    state.update_task("kids-e2e", state=tm.const.TASK_STATE_COMPLETE)
    with (
        patch.object(tm.sm, "state", state),
        patch("app.services.postiz.config.app", _BASE_CONFIG),
        patch("app.services.postiz.os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=b"fake video data")),
        patch("app.services.postiz.requests.post") as mock_post,
        patch.object(
            tm.llm,
            "generate_social_metadata",
            return_value={"title": "T", "caption": "C", "hashtags": []},
        ),
    ):
        mock_post.side_effect = _upload_then_post_side_effect()
        results: list = []
        tm._run_cross_post_from_snapshot(
            "kids-e2e",
            ("final.mp4",),
            "Subject",
            "script",
            "en",
            snapshot,
            results,
            True,
        )
    settings = _capture_youtube_settings(mock_post)
    assert settings["selfDeclaredMadeForKids"] == "yes"
