import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.creative import ShotPlanItem
from app.services.providers.base import ProviderError
from app.services.providers.kling import KlingVideoProvider

_SUCCEED = {
    "task_status": "succeed",
    "task_result": {
        "videos": [{"id": "v1", "url": "https://cdn.example.com/v.mp4"}]
    },
}


def _make_shot(prompt="a harbor at dawn", **kwargs):
    defaults = dict(index=1, source_type="generated_video", prompt=prompt)
    defaults.update(kwargs)
    return ShotPlanItem(**defaults)


class FakeResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self._payload = payload if payload is not None else {}
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"http error {self.status_code}")


class FakeSession:
    def __init__(self, statuses=None, post_payload=None):
        self.statuses = list(statuses or [])
        self.post_payload = post_payload
        self.posts = []
        self.status_paths = []
        self.downloads = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "body": json, "headers": headers})
        payload = self.post_payload or {
            "code": 0,
            "message": "Succ",
            "data": {"task_id": "task-1"},
        }
        return FakeResponse(payload=payload)

    def get(self, url, headers=None, timeout=None):
        if url.startswith("https://cdn.example.com/"):
            self.downloads.append(url)
            return FakeResponse(content=b"MP4-BYTES")
        self.status_paths.append(url)
        data = self.statuses.pop(0) if self.statuses else {
            "task_status": "processing"
        }
        return FakeResponse(payload={"code": 0, "message": "Succ", "data": data})


def _provider(session, **overrides):
    values = dict(
        access_key="ak-test",
        secret_key="sk-test",
        base_url="https://api-singapore.klingai.com",
        model_name="kling-v2-master",
        cfg_scale=0.8,
        poll_interval=0,
        timeout_seconds=5,
    )
    values.update(overrides)
    return KlingVideoProvider(**values, session=session)


def _b64_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


class TestKlingProviderConfig(unittest.TestCase):
    def test_from_config_requires_keys(self):
        with self.assertRaises(ProviderError):
            KlingVideoProvider.from_config(
                {"access_key": "", "secret_key": "sk"}
            )
        with self.assertRaises(ProviderError):
            KlingVideoProvider.from_config(
                {"access_key": "ak", "secret_key": ""}
            )

    def test_is_available(self):
        self.assertTrue(
            KlingVideoProvider("ak", "sk", session=FakeSession()).is_available()
        )
        self.assertFalse(
            KlingVideoProvider("", "sk", session=FakeSession()).is_available()
        )

    def test_from_config_applies_values(self):
        provider = KlingVideoProvider.from_config(
            {
                "access_key": "ak-1",
                "secret_key": "sk-1",
                "base_url": "https://api-beijing.klingai.com",
                "model_name": "kling-v1-6",
                "cfg_scale": 0.5,
                "poll_interval": 1.0,
                "timeout_seconds": 42,
            }
        )
        self.assertEqual(provider.base_url, "https://api-beijing.klingai.com")
        self.assertEqual(provider.model_name, "kling-v1-6")
        self.assertEqual(provider.cfg_scale, 0.5)
        self.assertEqual(provider.poll_interval, 1.0)
        self.assertEqual(provider.timeout_seconds, 42)


class TestKlingProviderFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = os.path.join(self._tmp.name, "shot_001")
        self.context = {
            "output_dir": self.output_dir,
            "video_aspect": "16:9",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_text_to_video_flow(self):
        session = FakeSession(
            statuses=[
                {"task_status": "submitted"},
                {"task_status": "processing"},
                _SUCCEED,
            ]
        )
        provider = _provider(session)
        path = provider.generate_video(
            _make_shot(negative_prompt="blur"), self.context
        )
        post = session.posts[0]
        self.assertEqual(
            post["url"], "https://api-singapore.klingai.com/v1/videos/text2video"
        )
        body = post["body"]
        self.assertEqual(body["prompt"], "a harbor at dawn")
        self.assertEqual(body["negative_prompt"], "blur")
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertEqual(body["duration"], "5")
        self.assertEqual(body["model_name"], "kling-v2-master")
        self.assertEqual(body["cfg_scale"], 0.8)
        self.assertNotIn("image", body)
        self.assertEqual(
            session.status_paths,
            [
                "https://api-singapore.klingai.com/v1/videos/text2video/task-1"
            ]
            * 3,
        )
        self.assertEqual(session.downloads, ["https://cdn.example.com/v.mp4"])
        self.assertEqual(path, os.path.join(self.output_dir, "video.mp4"))
        self.assertTrue(os.path.isfile(path))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"MP4-BYTES")

    def test_image_to_video_flow_uses_public_reference(self):
        session = FakeSession(statuses=[_SUCCEED])
        provider = _provider(session)
        shot = _make_shot(
            reference_images=["https://img.example.com/first.png"]
        )
        provider.generate_video(shot, self.context)
        post = session.posts[0]
        self.assertEqual(
            post["url"], "https://api-singapore.klingai.com/v1/videos/image2video"
        )
        self.assertEqual(post["body"]["image"], "https://img.example.com/first.png")
        self.assertEqual(
            session.status_paths,
            ["https://api-singapore.klingai.com/v1/videos/image2video/task-1"],
        )

    def test_local_reference_image_falls_back_to_text_to_video(self):
        session = FakeSession(statuses=[_SUCCEED])
        provider = _provider(session)
        shot = _make_shot(
            reference_images=["/tmp/shot_001/generated.png"]
        )
        provider.generate_video(shot, self.context)
        post = session.posts[0]
        self.assertTrue(post["url"].endswith("/v1/videos/text2video"))
        self.assertNotIn("image", post["body"])

    def test_duration_mapping(self):
        for duration, expected in ((4, "5"), (None, "5"), (9, "10")):
            with self.subTest(duration=duration):
                session = FakeSession(statuses=[_SUCCEED])
                provider = _provider(session)
                shot_kwargs = {} if duration is None else {"duration": duration}
                provider.generate_video(_make_shot(**shot_kwargs), self.context)
                self.assertEqual(session.posts[0]["body"]["duration"], expected)

    def test_jwt_header_is_hs256_signed(self):
        session = FakeSession(statuses=[_SUCCEED])
        provider = _provider(session)
        provider.generate_video(_make_shot(), self.context)
        headers = session.posts[0]["headers"]
        token = headers["Authorization"]
        self.assertTrue(token.startswith("Bearer "))
        token = token[len("Bearer "):]
        header_b64, payload_b64, signature_b64 = token.split(".")
        payload = json.loads(_b64_decode(payload_b64))
        self.assertEqual(payload["iss"], "ak-test")
        self.assertGreater(payload["exp"], payload["nbf"])
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(b"sk-test", signing_input, hashlib.sha256).digest()
        self.assertEqual(_b64_decode(signature_b64), expected)

    def test_failed_task_raises_with_detail(self):
        session = FakeSession(
            statuses=[
                {
                    "task_status": "failed",
                    "task_status_msg": "sensitive content",
                }
            ]
        )
        provider = _provider(session)
        with self.assertRaises(ProviderError) as caught:
            provider.generate_video(_make_shot(), self.context)
        self.assertIn("sensitive content", str(caught.exception))

    def test_api_error_envelope_raises(self):
        session = FakeSession(
            post_payload={"code": 1000, "message": "invalid api key", "data": None}
        )
        provider = _provider(session)
        with self.assertRaises(ProviderError) as caught:
            provider.generate_video(_make_shot(), self.context)
        self.assertIn("invalid api key", str(caught.exception))

    def test_timeout_raises(self):
        session = FakeSession(
            statuses=[{"task_status": "processing"}] * 200
        )
        provider = _provider(session, timeout_seconds=0.01)
        with self.assertRaises(ProviderError) as caught:
            provider.generate_video(_make_shot(), self.context)
        self.assertIn("did not finish", str(caught.exception))

    def test_missing_output_dir_raises(self):
        session = FakeSession(statuses=[_SUCCEED])
        provider = _provider(session)
        with self.assertRaises(ProviderError) as caught:
            provider.generate_video(_make_shot(), {"video_aspect": "16:9"})
        self.assertIn("output_dir", str(caught.exception))

    def test_succeed_without_video_url_raises(self):
        session = FakeSession(
            statuses=[
                {"task_status": "succeed", "task_result": {"videos": []}}
            ]
        )
        provider = _provider(session)
        with self.assertRaises(ProviderError) as caught:
            provider.generate_video(_make_shot(), self.context)
        self.assertIn("video url", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
