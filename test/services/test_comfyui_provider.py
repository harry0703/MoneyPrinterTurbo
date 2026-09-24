import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.creative import ShotPlanItem
from app.services.providers.base import ProviderError
from app.services.providers.comfyui import (
    ComfyUIProvider,
    DEFAULT_TEMPLATE_DIR,
    render_template,
)

BASE = "http://comfyui.test:8190"
LAUNCHER = "http://launcher.test:8080"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class ComfyFake:
    """Stateful fake of the ComfyUI + launcher HTTP surface."""

    def __init__(self, up=True, history=None, view_content=b"PNGDATA"):
        self.up = up
        self.history = list(history or [])
        self.view_content = view_content
        self.started = False
        self.history_calls = 0
        self.prompt_payloads = []
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url == f"{BASE}/system_stats":
            if not self.up:
                raise requests.ConnectionError("backend down")
            return FakeResponse(200, {"system": {}})
        if url == f"{LAUNCHER}/api/status":
            return FakeResponse(200, {"running": self.started})
        if url.startswith(f"{BASE}/history/"):
            if self.history_calls < len(self.history):
                entry = self.history[self.history_calls]
                self.history_calls += 1
            else:
                entry = self.history[-1]
            if entry is None:
                return FakeResponse(200, {})
            prompt_id = url.rsplit("/", 1)[1]
            return FakeResponse(200, {prompt_id: entry})
        if url == f"{BASE}/view":
            return FakeResponse(200, content=self.view_content)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        if url == f"{LAUNCHER}/api/start":
            self.started = True
            self.up = True
            return FakeResponse(200, {"ok": True})
        if url == f"{BASE}/prompt":
            self.prompt_payloads.append(kwargs.get("json"))
            return FakeResponse(200, {"prompt_id": "p1"})
        raise AssertionError(f"unexpected POST {url}")


def ok_history(**extra):
    entry = {
        "prompt": [["p1", 1]],
        "outputs": {
            "7": {
                "images": [
                    {
                        "filename": "mpt_01234567_shot001.png",
                        "subfolder": "",
                        "type": "output",
                    }
                ]
            }
        },
        "status": {"status_str": "success", "completed": True},
    }
    entry.update(extra)
    return entry


def make_shot(**kwargs):
    defaults = {
        "index": 1,
        "source_type": "generated_image",
        "prompt": "a red van at dusk",
        "negative_prompt": "blurry",
        "provider": "comfyui",
    }
    defaults.update(kwargs)
    return ShotPlanItem(**defaults)


def make_provider(fake, **kwargs):
    defaults = {
        "base_url": BASE,
        "launcher_url": LAUNCHER,
        "template": "image_basic",
        "timeout_seconds": 5,
        "poll_interval": 0.01,
        "probe_timeout": 1,
        "session": fake,
    }
    defaults.update(kwargs)
    return ComfyUIProvider(**defaults)


class TestRenderTemplate(unittest.TestCase):
    def test_replaces_quoted_string_and_number_tokens(self):
        template = {
            "meta": {"nodes": {"sampler": "5"}},
            "prompt": {
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{positive}}"}},
                "4": {"class_type": "EmptyLatentImage", "inputs": {"width": "{{width}}"}},
            },
        }
        graph, meta = render_template(
            template, {"positive": 'she said "hi" \\ ok', "width": 720}
        )
        self.assertEqual(graph["2"]["inputs"]["text"], 'she said "hi" \\ ok')
        self.assertEqual(graph["4"]["inputs"]["width"], 720)
        self.assertEqual(meta["nodes"]["sampler"], "5")

    def test_replaces_bare_token(self):
        template = {"prompt": {"4": {"inputs": {"width": "{{width}}"}}}}
        graph, _ = render_template(template, {"width": 512})
        self.assertEqual(graph["4"]["inputs"]["width"], 512)

    def test_missing_parameter_raises(self):
        template = {"prompt": {"2": {"inputs": {"text": "{{positive}}"}}}}
        with self.assertRaises(ProviderError):
            render_template(template, {})

    def test_missing_prompt_section_raises(self):
        with self.assertRaises(ProviderError):
            render_template({"meta": {}}, {"positive": "x"})

    def test_bundled_templates_render(self):
        params = {
            "positive": "p",
            "negative": "n",
            "width": 1280,
            "height": 720,
            "seed": 7,
            "filename_prefix": "mpt_x_shot001",
            "checkpoint": "v1-5-pruned-emaonly.safetensors",
        }
        for name in ("image_basic", "image_krea2"):
            with self.subTest(template=name):
                path = os.path.join(DEFAULT_TEMPLATE_DIR, f"{name}.json")
                with open(path, mode="r", encoding="utf-8") as f:
                    template = json.load(f)
                graph, meta = render_template(template, params)
                self.assertTrue(graph)
                sampler_id = meta["nodes"]["sampler"]
                sampler = graph[sampler_id]
                self.assertEqual(sampler["class_type"], "KSampler")
                self.assertEqual(sampler["inputs"]["seed"], 7)


class TestComfyUIProviderConfig(unittest.TestCase):
    def test_is_available_true_when_backend_up(self):
        provider = make_provider(ComfyFake(up=True))
        self.assertTrue(provider.is_available())

    def test_is_available_false_when_backend_down(self):
        provider = make_provider(ComfyFake(up=False))
        self.assertFalse(provider.is_available())

    def test_from_config_requires_enabled(self):
        with self.assertRaises(ProviderError):
            ComfyUIProvider.from_config({"enabled": False, "base_url": BASE})

    def test_from_config_requires_base_url(self):
        with self.assertRaises(ProviderError):
            ComfyUIProvider.from_config({"enabled": True})


class TestComfyUIProviderGenerate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.context = {
            "output_dir": os.path.join(self._tmp.name, "assets", "shot_001"),
            "video_aspect": "16:9",
            "task_id": "0123456789abcdef",
            "seed": 42,
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_happy_path_writes_file(self):
        fake = ComfyFake(history=[None, ok_history()])
        provider = make_provider(fake)
        paths = provider.generate(make_shot(), self.context)
        self.assertEqual(len(paths), 1)
        self.assertTrue(os.path.isfile(paths[0]))
        with open(paths[0], "rb") as f:
            self.assertEqual(f.read(), b"PNGDATA")
        self.assertTrue(paths[0].endswith("generated_001.png"))

    def test_injects_prompt_aspect_and_seed(self):
        fake = ComfyFake(history=[ok_history()])
        provider = make_provider(fake)
        context = dict(self.context, video_aspect="9:16")
        provider.generate(make_shot(), context)
        payload = fake.prompt_payloads[0]["prompt"]
        positive = payload["2"]["inputs"]
        self.assertEqual(positive["text"], "a red van at dusk")
        latent = payload["4"]["inputs"]
        self.assertEqual(latent["width"], 720)
        self.assertEqual(latent["height"], 1280)
        self.assertEqual(payload["5"]["inputs"]["seed"], 42)
        self.assertEqual(
            payload["7"]["inputs"]["filename_prefix"], "mpt_01234567_shot001"
        )

    def test_config_overrides_sampler_and_checkpoint(self):
        fake = ComfyFake(history=[ok_history()])
        provider = make_provider(
            fake,
            steps=12,
            cfg=3.5,
            sampler_name="dpmpp_2m",
            scheduler="karras",
            checkpoint="other.safetensors",
        )
        provider.generate(make_shot(), self.context)
        payload = fake.prompt_payloads[0]["prompt"]
        sampler = payload["5"]["inputs"]
        self.assertEqual(sampler["steps"], 12)
        self.assertEqual(sampler["cfg"], 3.5)
        self.assertEqual(sampler["sampler_name"], "dpmpp_2m")
        self.assertEqual(sampler["scheduler"], "karras")
        self.assertEqual(payload["1"]["inputs"]["ckpt_name"], "other.safetensors")

    def test_starts_backend_via_launcher_when_down(self):
        fake = ComfyFake(up=False, history=[ok_history()])
        provider = make_provider(fake)
        paths = provider.generate(make_shot(), self.context)
        self.assertEqual(len(paths), 1)
        self.assertTrue(fake.started)

    def test_fails_when_backend_down_without_launcher(self):
        fake = ComfyFake(up=False)
        provider = make_provider(fake, launcher_url="")
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("launcher_url", str(ctx.exception))

    def test_prompt_rejection_raises(self):
        fake = ComfyFake(history=[ok_history()])

        def post(url, **kwargs):
            if url == f"{BASE}/prompt":
                return FakeResponse(
                    400,
                    {
                        "error": {"message": "prompt has invalid inputs"},
                        "node_errors": {
                            "5": {
                                "class_type": "KSampler",
                                "inputs": {"steps": "expected int"},
                            }
                        },
                    },
                )
            return fake.post(url, **kwargs)

        fake.post = post
        provider = make_provider(fake)
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("KSampler", str(ctx.exception))

    def test_execution_error_raises(self):
        fake = ComfyFake(
            history=[
                ok_history(
                    status={"status_str": "error", "completed": False},
                    execution_error={
                        "exception_message": "Weights only load failed",
                        "node_id": "1",
                    },
                    outputs={},
                )
            ]
        )
        provider = make_provider(fake)
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        message = str(ctx.exception)
        self.assertIn("Weights only load failed", message)
        self.assertIn("node 1", message)

    def test_timeout_raises(self):
        fake = ComfyFake(history=[None])
        provider = make_provider(fake, timeout_seconds=0.05)
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("timed out", str(ctx.exception))

    def test_no_images_in_outputs_raises(self):
        fake = ComfyFake(history=[ok_history(outputs={})])
        provider = make_provider(fake)
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("without producing images", str(ctx.exception))

    def test_missing_output_dir_raises(self):
        fake = ComfyFake(history=[ok_history()])
        provider = make_provider(fake)
        context = {k: v for k, v in self.context.items() if k != "output_dir"}
        with self.assertRaises(ProviderError):
            provider.generate(make_shot(), context)

    def test_unknown_template_raises(self):
        fake = ComfyFake(history=[ok_history()])
        provider = make_provider(fake, template="does_not_exist")
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("template not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
