"""A scheduled publish belongs to the account selected at scheduling time."""

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import requests

from app.config import config
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.services import upload_post


def _response(payload):
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    return response


class TestUploadPostAccountSnapshot(unittest.TestCase):
    def test_queued_publish_keeps_original_account(self):
        released = threading.Event()
        state = sm.MemoryState()
        task_id = "account-snapshot"
        state.update_task(task_id, cross_post_state=const.CROSS_POST_STATE_PENDING)
        account_a = {
            "upload_post_enabled": True,
            "upload_post_api_key": "account-a-test-key",
            "upload_post_username": "channel-a",
        }
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory, "video.mp4")
            video.write_bytes(b"local video fixture")
            with ThreadPoolExecutor(max_workers=1) as executor:
                blocker = executor.submit(released.wait, 10)
                try:
                    with (
                        patch.dict(config.app, account_a),
                        patch.object(sm, "state", state),
                        patch.object(tm, "_cross_post_executor", executor),
                        patch.object(tm.llm, "generate_social_metadata", return_value={}),
                        patch.object(upload_post.requests, "post", return_value=_response({
                            "success": True, "results": {"tiktok": {"success": True}}
                        })) as post,
                    ):
                        error = tm._schedule_cross_post(
                            task_id, [str(video)], VideoParams(video_subject="Coffee"),
                            "Prepared script", ["tiktok"], "public",
                        )
                        self.assertIsNone(error)
                        with tm._cross_post_registry_lock:
                            future = tm._cross_post_futures[task_id]
                        config.app.update({
                            "upload_post_api_key": "account-b-test-key",
                            "upload_post_username": "channel-b",
                        })
                        released.set()
                        blocker.result(timeout=10)
                        future.result(timeout=10)
                        post.assert_called_once()
                        self.assertEqual(post.call_args.kwargs["headers"], {
                            "Authorization": "Apikey account-a-test-key"
                        })
                        self.assertEqual(dict(post.call_args.kwargs["data"])["user"], "channel-a")
                        self.assertEqual(state.get_task(task_id)["cross_post_state"], const.CROSS_POST_STATE_COMPLETE)
                finally:
                    released.set()

    def test_background_status_keeps_account_that_accepted_the_video(self):
        state = sm.MemoryState()
        task_id = "account-background"
        state.update_task(task_id, cross_post_state=const.CROSS_POST_STATE_PENDING)
        account_a = {
            "upload_post_enabled": True,
            "upload_post_api_key": "account-a-test-key",
            "upload_post_username": "channel-a",
        }

        def accepted(*args, **kwargs):
            config.app.update({
                "upload_post_api_key": "account-b-test-key",
                "upload_post_username": "channel-b",
            })
            return _response({"success": True, "request_id": "accepted-by-a"})

        with (
            tempfile.TemporaryDirectory() as directory,
            ThreadPoolExecutor(max_workers=1) as executor,
            patch.dict(config.app, account_a),
            patch.object(sm, "state", state),
            patch.object(tm, "_cross_post_executor", executor),
            patch.object(tm.llm, "generate_social_metadata", return_value={}),
            patch.object(upload_post.requests, "post", side_effect=accepted),
            patch.object(upload_post.requests, "get", return_value=_response({
                "status": "completed", "results": {"tiktok": {"success": True}}
            })) as get,
        ):
            video = Path(directory, "video.mp4")
            video.write_bytes(b"local video fixture")
            error = tm._schedule_cross_post(
                task_id, [str(video)], VideoParams(video_subject="Coffee"),
                "Prepared script", ["tiktok"], "public",
            )
            self.assertIsNone(error)
            # Wait for real executor work even if its done callback already
            # removed the future from the registry.
            executor.submit(lambda: None).result(timeout=10)
            get.assert_called_once()
            self.assertEqual(get.call_args.kwargs["headers"], {
                "Authorization": "Apikey account-a-test-key"
            })
            self.assertEqual(state.get_task(task_id)["cross_post_state"], const.CROSS_POST_STATE_COMPLETE)
