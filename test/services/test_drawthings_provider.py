import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.creative import ShotPlanItem
from app.services.providers.base import ProviderError
from app.services.providers import drawthings as dt_mod
from app.services.providers.drawthings import DrawThingsProvider, _parse_host_port

FAKE_BASE_URL = "dt.test:7860"

_state = {}


class FakeImageBuffer:
    def __init__(self, payload=b"PNGDATA"):
        self._payload = payload
        self.metadata = {"seed": -1}

    def to_file(self, path):
        with open(path, "wb") as f:
            f.write(self._payload)


class FakeResult:
    def __init__(self, images):
        self.images = list(images)


class FakeGenConfig:
    def __init__(self, origin):
        self.origin = origin
        self.data = {"model": "preset-default.ckpt", "steps": 28}

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value


class FakeRequestBuilder:
    def __init__(self, config, prompt, negative_prompt=None):
        self.config = config
        self.prompt = prompt
        self.negative_prompt = negative_prompt
        self.moodboard = []

    def add_moodboard_image(self, image, weight=1.0):
        self.moodboard.append((image, weight))


class FakeChannel:
    def __init__(self, host, port, ssl=None):
        self.host = host
        self.port = port
        self.ssl = ssl
        self.closed = False

    def close(self):
        self.closed = True


class FakeServiceStub:
    def __init__(self, channel):
        self.channel = channel


def _make_fake_classes(behavior):
    class FakeGrpcService:
        def __init__(
            self, host, port, progressbar=False, disable_messages=False
        ):
            self._host = host
            self._port = port
            self._channel = None
            self._service = None
            self._models = None
            self.closed = False
            self.behavior = behavior

        async def connect(self):
            # Unpatched (TLS) connect path of the real client.
            _state["tls_connects"] += 1
            self._channel = object()
            self._service = FakeServiceStub(self._channel)

        async def _ensure_service(self):
            await self.connect()
            if self._service is None:
                raise RuntimeError("Service not connected")
            return self._service

        async def _fetch_models(self):
            await self._ensure_service()
            if self.behavior.get("delay"):
                await asyncio.sleep(self.behavior["delay"])
            if not self.behavior.get("models_up", True):
                raise ConnectionError("backend down")
            self._models = object()

        async def get_models(self, refresh_cache=False):
            if self._models is not None and not refresh_cache:
                return self._models
            await self._fetch_models()
            return self._models

        async def generate(self, request):
            _state["builders"].append(request)
            await self._ensure_service()
            if self.behavior.get("delay"):
                await asyncio.sleep(self.behavior["delay"])
            if "fail" in self.behavior:
                raise self.behavior["fail"]
            images = self.behavior.get("images")
            if images is None:
                images = [FakeImageBuffer()]
            return FakeResult(images)

        async def close(self):
            self.closed = True

    class FakeConfigs:
        @classmethod
        def from_preset(cls, name):
            if name in behavior.get("bad_presets", []):
                raise ValueError(f"Unknown preset: {name}")
            cfg = FakeGenConfig(f"preset:{name}")
            _state["configs"].append(cfg)
            return cfg

        @classmethod
        def from_json(cls, data):
            cfg = FakeGenConfig(f"json:{data}")
            _state["configs"].append(cfg)
            return cfg

    class FakeDrawThings:
        @staticmethod
        def grpc(host, port, progressbar=False, disable_messages=False):
            service = FakeGrpcService(host=host, port=port)
            _state["services"].append(service)
            return service

    return FakeGrpcService, FakeConfigs, FakeDrawThings


def install_fake(behavior=None):
    behavior = behavior or {}
    _state.clear()
    _state.update(
        services=[], tls_connects=0, builders=[], configs=[], behavior=behavior
    )
    fake_service_cls, fake_configs, fake_drawthings = _make_fake_classes(behavior)

    dt = types.ModuleType("drawthings_py")
    grpc_mod = types.ModuleType("drawthings_py.grpc")
    grpc_service_mod = types.ModuleType("drawthings_py.grpc.grpc_service")
    grpc_service_mod.GrpcService = fake_service_cls
    generated_mod = types.ModuleType("drawthings_py.generated")
    dt_grpc_mod = types.ModuleType("drawthings_py.generated.dt_grpc")
    image_service_mod = types.ModuleType(
        "drawthings_py.generated.dt_grpc.image_service"
    )
    image_service_mod.ImageGenerationServiceStub = FakeServiceStub
    grpclib_mod = types.ModuleType("grpclib")
    grpclib_client_mod = types.ModuleType("grpclib.client")
    grpclib_client_mod.Channel = FakeChannel

    dt.Configs = fake_configs
    dt.DrawThings = fake_drawthings
    dt.RequestBuilder = FakeRequestBuilder
    dt.grpc = grpc_mod
    dt.generated = generated_mod
    grpc_mod.grpc_service = grpc_service_mod
    generated_mod.dt_grpc = dt_grpc_mod
    dt_grpc_mod.image_service = image_service_mod
    grpclib_mod.client = grpclib_client_mod

    sys.modules["drawthings_py"] = dt
    sys.modules["drawthings_py.grpc"] = grpc_mod
    sys.modules["drawthings_py.grpc.grpc_service"] = grpc_service_mod
    sys.modules["drawthings_py.generated"] = generated_mod
    sys.modules["drawthings_py.generated.dt_grpc"] = dt_grpc_mod
    sys.modules["drawthings_py.generated.dt_grpc.image_service"] = image_service_mod
    sys.modules["grpclib"] = grpclib_mod
    sys.modules["grpclib.client"] = grpclib_client_mod

    dt_mod._insecure_patch_applied = False
    return fake_service_cls


def uninstall_fake():
    for name in (
        "drawthings_py",
        "drawthings_py.grpc",
        "drawthings_py.grpc.grpc_service",
        "drawthings_py.generated",
        "drawthings_py.generated.dt_grpc",
        "drawthings_py.generated.dt_grpc.image_service",
        "grpclib",
        "grpclib.client",
    ):
        sys.modules.pop(name, None)
    dt_mod._insecure_patch_applied = False


def make_provider(**kwargs):
    defaults = {
        "base_url": FAKE_BASE_URL,
        "model_file": "Flux 1 Dev_q8p.ckpt",
        "preset": "flux_1_dev",
        "timeout_seconds": 5,
        "probe_timeout": 1,
    }
    defaults.update(kwargs)
    return DrawThingsProvider(**defaults)


def make_shot(**kwargs):
    defaults = {
        "index": 1,
        "source_type": "generated_image",
        "prompt": "a red van at dusk",
        "negative_prompt": "blurry",
        "provider": "drawthings",
    }
    defaults.update(kwargs)
    return ShotPlanItem(**defaults)


class TestParseHostPort(unittest.TestCase):
    def test_plain_host_port(self):
        self.assertEqual(
            _parse_host_port("100.71.253.58:7860"), ("100.71.253.58", 7860)
        )

    def test_strips_scheme_and_path(self):
        self.assertEqual(
            _parse_host_port("http://dt.test:7860/health"), ("dt.test", 7860)
        )

    def test_grpc_scheme(self):
        self.assertEqual(_parse_host_port("grpc://dt.test:7859"), ("dt.test", 7859))

    def test_default_port(self):
        self.assertEqual(_parse_host_port("dt.test"), ("dt.test", 7859))

    def test_invalid_port_raises(self):
        with self.assertRaises(ProviderError):
            _parse_host_port("dt.test:abc")

    def test_missing_host_raises(self):
        with self.assertRaises(ProviderError):
            _parse_host_port(":7860")

    def test_empty_raises(self):
        with self.assertRaises(ProviderError):
            _parse_host_port("")


class TestDrawThingsProviderConfig(unittest.TestCase):
    def setUp(self):
        install_fake()

    def tearDown(self):
        uninstall_fake()

    def test_from_config_requires_enabled(self):
        with self.assertRaises(ProviderError):
            DrawThingsProvider.from_config(
                {"enabled": False, "base_url": FAKE_BASE_URL, "preset": "flux_1_dev"}
            )

    def test_from_config_requires_base_url(self):
        with self.assertRaises(ProviderError):
            DrawThingsProvider.from_config({"enabled": True, "preset": "flux_1_dev"})

    def test_from_config_requires_preset_or_preset_path(self):
        with self.assertRaises(ProviderError):
            DrawThingsProvider.from_config(
                {"enabled": True, "base_url": FAKE_BASE_URL}
            )

    def test_from_config_maps_fields(self):
        provider = DrawThingsProvider.from_config(
            {
                "enabled": True,
                "base_url": "http://dt.test:7860",
                "model_file": "krea_2_turbo_q8p.ckpt",
                "preset": "z_image_turbo",
                "preset_path": "",
                "steps": 8,
                "guidance": 1.0,
                "shift": 3.0,
                "seed": 7,
                "use_tls": True,
                "timeout_seconds": 120,
                "probe_timeout": 2.5,
            }
        )
        self.assertEqual(provider.host, "dt.test")
        self.assertEqual(provider.port, 7860)
        self.assertEqual(provider.model_file, "krea_2_turbo_q8p.ckpt")
        self.assertEqual(provider.preset, "z_image_turbo")
        self.assertEqual(provider.preset_path, "")
        self.assertEqual(provider.steps, 8)
        self.assertEqual(provider.guidance, 1.0)
        self.assertEqual(provider.shift, 3.0)
        self.assertEqual(provider.seed, 7)
        self.assertTrue(provider.use_tls)
        self.assertEqual(provider.timeout_seconds, 120)
        self.assertEqual(provider.probe_timeout, 2.5)

    def test_default_seed_is_random(self):
        provider = make_provider()
        self.assertEqual(provider.seed, -1)


class TestDrawThingsProviderAvailability(unittest.TestCase):
    def setUp(self):
        self.fake_cls = install_fake()

    def tearDown(self):
        uninstall_fake()

    def test_true_when_backend_up(self):
        provider = make_provider()
        self.assertTrue(provider.is_available())

    def test_false_when_backend_down(self):
        install_fake({"models_up": False})
        provider = make_provider()
        self.assertFalse(provider.is_available())

    def test_false_on_probe_timeout(self):
        install_fake({"delay": 0.2})
        provider = make_provider(probe_timeout=0.05)
        self.assertFalse(provider.is_available())

    def test_service_closed_after_probe(self):
        provider = make_provider()
        provider.is_available()
        self.assertTrue(_state["services"][-1].closed)


class TestDrawThingsProviderGenerate(unittest.TestCase):
    def setUp(self):
        self.fake_cls = install_fake()
        self._tmp = tempfile.TemporaryDirectory()
        self.context = {
            "output_dir": os.path.join(self._tmp.name, "assets", "shot_001"),
            "video_aspect": "16:9",
            "task_id": "0123456789abcdef",
            "seed": 42,
        }

    def tearDown(self):
        self._tmp.cleanup()
        uninstall_fake()

    def test_happy_path_writes_file(self):
        provider = make_provider()
        paths = provider.generate(make_shot(), self.context)
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("generated_001.png"))
        self.assertTrue(os.path.isfile(paths[0]))
        with open(paths[0], "rb") as f:
            self.assertEqual(f.read(), b"PNGDATA")

    def test_injects_prompt_config_and_seed(self):
        provider = make_provider()
        provider.generate(make_shot(), self.context)
        builder = _state["builders"][-1]
        self.assertEqual(builder.prompt, "a red van at dusk")
        self.assertEqual(builder.negative_prompt, "blurry")
        config = builder.config
        self.assertEqual(config.origin, "preset:flux_1_dev")
        self.assertEqual(config.data["width"], 1280)
        self.assertEqual(config.data["height"], 720)
        self.assertEqual(config.data["seed"], 42)
        self.assertEqual(config.data["model"], "Flux 1 Dev_q8p.ckpt")
        self.assertEqual(config.data["steps"], 28)

    def test_uses_insecure_plaintext_channel(self):
        provider = make_provider()
        provider.generate(make_shot(), self.context)
        service = _state["services"][-1]
        self.assertIsInstance(service._channel, FakeChannel)
        self.assertIs(service._channel.ssl, False)
        self.assertEqual(service._channel.host, "dt.test")
        self.assertEqual(service._channel.port, 7860)
        self.assertEqual(_state["tls_connects"], 0)
        self.assertEqual(
            service._service.channel, service._channel
        )

    def test_use_tls_keeps_default_connect(self):
        provider = make_provider(use_tls=True)
        provider.generate(make_shot(), self.context)
        service = _state["services"][-1]
        self.assertNotIsInstance(service._channel, FakeChannel)
        self.assertEqual(_state["tls_connects"], 1)

    def test_two_images_written_in_order(self):
        install_fake(
            {"images": [FakeImageBuffer(b"A"), FakeImageBuffer(b"B")]}
        )
        provider = make_provider()
        paths = provider.generate(make_shot(), self.context)
        self.assertEqual(len(paths), 2)
        self.assertTrue(paths[0].endswith("generated_001.png"))
        self.assertTrue(paths[1].endswith("generated_002.png"))
        with open(paths[0], "rb") as f:
            self.assertEqual(f.read(), b"A")
        with open(paths[1], "rb") as f:
            self.assertEqual(f.read(), b"B")

    def test_vertical_aspect_size(self):
        provider = make_provider()
        context = dict(self.context, video_aspect="9:16")
        provider.generate(make_shot(), context)
        config = _state["builders"][-1].config
        self.assertEqual(config.data["width"], 720)
        self.assertEqual(config.data["height"], 1280)

    def test_unknown_aspect_falls_back_to_16_9(self):
        provider = make_provider()
        context = dict(self.context, video_aspect="4:3")
        provider.generate(make_shot(), context)
        config = _state["builders"][-1].config
        self.assertEqual(config.data["width"], 1280)
        self.assertEqual(config.data["height"], 720)

    def test_seed_falls_back_to_provider_seed(self):
        provider = make_provider(seed=7)
        context = {k: v for k, v in self.context.items() if k != "seed"}
        provider.generate(make_shot(), context)
        config = _state["builders"][-1].config
        self.assertEqual(config.data["seed"], 7)

    def test_sampler_overrides_applied(self):
        provider = make_provider(steps=4, guidance=3.5, shift=2.0)
        provider.generate(make_shot(), self.context)
        config = _state["builders"][-1].config
        self.assertEqual(config.data["steps"], 4)
        self.assertEqual(config.data["guidance"], 3.5)
        self.assertEqual(config.data["shift"], 2.0)

    def test_zero_overrides_left_to_preset(self):
        provider = make_provider()
        provider.generate(make_shot(), self.context)
        config = _state["builders"][-1].config
        self.assertNotIn("guidance", config.data)
        self.assertNotIn("shift", config.data)

    def test_preset_path_loaded_from_json_file(self):
        preset_file = os.path.join(self._tmp.name, "preset.json")
        with open(preset_file, "w", encoding="utf-8") as f:
            f.write('{"configuration": {"steps": 8}}')
        provider = make_provider(preset="", preset_path=preset_file)
        provider.generate(make_shot(), self.context)
        config = _state["builders"][-1].config
        self.assertEqual(config.origin, 'json:{"configuration": {"steps": 8}}')
        self.assertEqual(config.data["seed"], 42)

    def test_unreadable_preset_path_raises(self):
        provider = make_provider(
            preset="", preset_path=os.path.join(self._tmp.name, "missing.json")
        )
        with self.assertRaises(ProviderError):
            provider.generate(make_shot(), self.context)

    def test_unknown_preset_raises(self):
        install_fake({"bad_presets": ["flux_1_dev"]})
        provider = make_provider()
        with self.assertRaises(ProviderError):
            provider.generate(make_shot(), self.context)

    def test_prompt_falls_back_to_script_segment(self):
        provider = make_provider()
        shot = make_shot(prompt=None, script_segment="fallback line")
        provider.generate(shot, self.context)
        self.assertEqual(_state["builders"][-1].prompt, "fallback line")

    def test_empty_prompt_raises(self):
        provider = make_provider()
        shot = make_shot(prompt=None, script_segment="")
        with self.assertRaises(ProviderError):
            provider.generate(shot, self.context)

    def test_missing_output_dir_raises(self):
        provider = make_provider()
        context = {k: v for k, v in self.context.items() if k != "output_dir"}
        with self.assertRaises(ProviderError):
            provider.generate(make_shot(), context)

    def test_generation_failure_raises(self):
        install_fake({"fail": RuntimeError("boom")})
        provider = make_provider()
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("boom", str(ctx.exception))

    def test_timeout_raises(self):
        install_fake({"delay": 0.2})
        provider = make_provider(timeout_seconds=0.05)
        with self.assertRaises(ProviderError) as ctx:
            provider.generate(make_shot(), self.context)
        self.assertIn("timed out", str(ctx.exception))

    def test_empty_result_raises(self):
        install_fake({"images": []})
        provider = make_provider()
        with self.assertRaises(ProviderError):
            provider.generate(make_shot(), self.context)

    def test_local_reference_image_attached(self):
        ref = os.path.join(self._tmp.name, "ref.png")
        with open(ref, "wb") as f:
            f.write(b"REFDATA")
        provider = make_provider()
        shot = make_shot(reference_images=[ref])
        provider.generate(shot, self.context)
        self.assertEqual(_state["builders"][-1].moodboard, [(ref, 1.0)])

    def test_url_reference_image_downloaded(self):
        class FakeResponse:
            status_code = 200
            content = b"REFDATA"

        provider = make_provider()
        shot = make_shot(reference_images=["https://cdn.test/ref.png"])
        with mock.patch.object(
            dt_mod.requests, "get", return_value=FakeResponse()
        ) as get:
            provider.generate(shot, self.context)
        get.assert_called_once_with("https://cdn.test/ref.png", timeout=60)
        local = os.path.join(
            self.context["output_dir"], "reference_001.png"
        )
        self.assertTrue(os.path.isfile(local))
        with open(local, "rb") as f:
            self.assertEqual(f.read(), b"REFDATA")
        self.assertEqual(_state["builders"][-1].moodboard, [(local, 1.0)])

    def test_url_reference_download_failure_skips(self):
        class FakeResponse:
            status_code = 500
            content = b""

        provider = make_provider()
        shot = make_shot(reference_images=["https://cdn.test/broken.png"])
        with mock.patch.object(dt_mod.requests, "get", return_value=FakeResponse()):
            provider.generate(shot, self.context)
        self.assertEqual(_state["builders"][-1].moodboard, [])

    def test_missing_local_reference_skips(self):
        provider = make_provider()
        shot = make_shot(
            reference_images=[os.path.join(self._tmp.name, "nope.png")]
        )
        provider.generate(shot, self.context)
        self.assertEqual(_state["builders"][-1].moodboard, [])


class TestDrawThingsProviderRegistry(unittest.TestCase):
    def setUp(self):
        from app.config import config

        install_fake()
        self._config = config
        self._comfyui = dict(config.comfyui)
        self._drawthings = dict(getattr(config, "drawthings", {}))

    def tearDown(self):
        config = self._config
        config.comfyui.clear()
        config.comfyui.update(self._comfyui)
        config.drawthings.clear()
        config.drawthings.update(self._drawthings)
        uninstall_fake()

    def test_not_registered_when_disabled(self):
        from app.services.providers.base import build_registry

        self._config.comfyui.clear()
        self._config.comfyui.update({"enabled": False})
        self._config.drawthings.clear()
        self._config.drawthings.update({"enabled": False})
        registry = build_registry()
        self.assertEqual(registry.names(), [])

    def test_registered_when_enabled(self):
        from app.services.providers.base import build_registry

        self._config.comfyui.clear()
        self._config.comfyui.update({"enabled": False})
        self._config.drawthings.clear()
        self._config.drawthings.update(
            {"enabled": True, "base_url": FAKE_BASE_URL, "preset": "flux_1_dev"}
        )
        registry = build_registry()
        self.assertIn("drawthings", registry.names())

    def test_invalid_config_skips_registration(self):
        from app.services.providers.base import build_registry

        self._config.comfyui.clear()
        self._config.comfyui.update({"enabled": False})
        self._config.drawthings.clear()
        self._config.drawthings.update({"enabled": True, "base_url": FAKE_BASE_URL})
        registry = build_registry()
        self.assertEqual(registry.names(), [])


if __name__ == "__main__":
    unittest.main()
