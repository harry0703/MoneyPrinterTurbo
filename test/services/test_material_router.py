import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.creative import (
    SHOT_STATUS_FAILED,
    SHOT_STATUS_PLANNED,
    SHOT_STATUS_RESOLVED,
    ShotPlan,
    ShotPlanItem,
)
from app.services.material_router import (
    FALLBACK_LOCAL_PLACEHOLDER,
    FALLBACK_NONE,
    FALLBACK_RETRY,
    FALLBACK_STOCK,
    MaterialRouter,
)
from app.services.providers.base import (
    MaterialProvider,
    ProviderError,
    ProviderRegistry,
)


class FakeImageProvider(MaterialProvider):
    name = "fakegen"

    def __init__(self, fail_times=0):
        self.calls = 0
        self.fail_times = fail_times

    def is_available(self) -> bool:
        return True

    def generate(self, shot, context):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("generation exploded")
        os.makedirs(context["output_dir"], exist_ok=True)
        path = os.path.join(context["output_dir"], "generated.png")
        with open(path, "wb") as f:
            f.write(b"IMG")
        return [path]


class UnavailableProvider(MaterialProvider):
    name = "down"

    def is_available(self) -> bool:
        return False

    def generate(self, shot, context):
        raise AssertionError("must not be called when unavailable")


def make_plan(shots):
    return ShotPlan(version=1, task_id="test-task", shots=shots)


class TestMaterialRouter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.media_root = os.path.join(self._tmp.name, "assets")
        os.makedirs(self.media_root)
        self.context = {
            "task_id": "test-task",
            "media_root": self.media_root,
            "video_aspect": "16:9",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _stock(self, fail=False):
        calls = {"n": 0}

        def _resolve(shot, context):
            calls["n"] += 1
            if fail:
                raise ProviderError(
                    "stock search returned no results for query 'x'"
                )
            shot_dir = os.path.join(
                context["media_root"], f"shot_{shot.index:03d}"
            )
            os.makedirs(shot_dir, exist_ok=True)
            path = os.path.join(shot_dir, "stock.mp4")
            with open(path, "wb") as f:
                f.write(b"VID")
            return path

        return _resolve, calls

    def _local_file(self, relative, content=b"LOCAL"):
        path = os.path.join(self.media_root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_stock_shot_resolves(self):
        stock, calls = self._stock()
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=stock
        )
        plan = make_plan(
            [ShotPlanItem(index=1, source_type="stock", query="city")]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_RESOLVED)
        self.assertEqual(shot.provider, "stock")
        self.assertTrue(os.path.isfile(shot.asset_path))
        self.assertIsNone(shot.error)
        self.assertEqual(calls["n"], 1)

    def test_stock_failure_fails_with_none_fallback(self):
        stock, _ = self._stock(fail=True)
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=stock
        )
        plan = make_plan(
            [ShotPlanItem(index=1, source_type="stock", query="city")]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_FAILED)
        self.assertIn("stock", shot.error)
        self.assertIsNone(shot.asset_path)

    def test_failure_falls_back_to_placeholder(self):
        stock, _ = self._stock(fail=True)
        router = MaterialRouter(
            registry=ProviderRegistry(),
            stock_source=stock,
            fallback=FALLBACK_LOCAL_PLACEHOLDER,
        )
        plan = make_plan(
            [ShotPlanItem(index=1, source_type="stock", query="city")]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_RESOLVED)
        self.assertEqual(shot.provider, "placeholder")
        self.assertTrue(shot.asset_path.endswith("placeholder.png"))
        with open(shot.asset_path, "rb") as f:
            self.assertEqual(f.read(4), b"\x89PNG")

    def test_local_shot_resolves_relative_to_media_root(self):
        path = self._local_file("clips/a.mp4")
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=self._stock()[0]
        )
        plan = make_plan(
            [ShotPlanItem(index=1, source_type="local", query="clips/a.mp4")]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_RESOLVED)
        self.assertEqual(shot.provider, "local")
        self.assertEqual(shot.asset_path, path)

    def test_local_shot_resolves_absolute_path(self):
        path = self._local_file("clips/abs.mp4")
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=self._stock()[0]
        )
        plan = make_plan(
            [ShotPlanItem(index=1, source_type="local", query=path)]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        self.assertEqual(resolved.shots[0].asset_path, path)

    def test_missing_local_file_fails(self):
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=self._stock()[0]
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1, source_type="local", query="clips/missing.mp4"
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_FAILED)
        self.assertIn("not found", shot.error)

    def test_graphic_and_archive_resolve(self):
        for source in ("graphic", "archive"):
            with self.subTest(source=source):
                path = self._local_file("g.png", content=b"PNG")
                router = MaterialRouter(
                    registry=ProviderRegistry(), stock_source=self._stock()[0]
                )
                plan = make_plan(
                    [ShotPlanItem(index=1, source_type=source, query="g.png")]
                )
                resolved = router.resolve_shot_plan(plan, self.context)
                self.assertEqual(
                    resolved.shots[0].provider, source
                )
                self.assertEqual(resolved.shots[0].asset_path, path)

    def test_generated_image_uses_registered_provider(self):
        provider = FakeImageProvider()
        router = MaterialRouter(
            registry=ProviderRegistry([provider]),
            stock_source=self._stock()[0],
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1,
                    source_type="generated_image",
                    prompt="a red van",
                    provider="fakegen",
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_RESOLVED)
        self.assertEqual(shot.provider, "fakegen")
        self.assertTrue(shot.asset_path.endswith("generated.png"))
        self.assertEqual(provider.calls, 1)

    def test_generated_image_defaults_to_config_provider(self):
        original = dict(config.creative)
        config.creative["default_image_provider"] = "fakegen"
        try:
            provider = FakeImageProvider()
            router = MaterialRouter(
                registry=ProviderRegistry([provider]),
                stock_source=self._stock()[0],
            )
            plan = make_plan(
                [
                    ShotPlanItem(
                        index=1,
                        source_type="generated_image",
                        prompt="a red van",
                    )
                ]
            )
            resolved = router.resolve_shot_plan(plan, self.context)
            self.assertEqual(resolved.shots[0].provider, "fakegen")
        finally:
            config.creative.clear()
            config.creative.update(original)

    def test_generated_image_unavailable_provider_fails(self):
        router = MaterialRouter(
            registry=ProviderRegistry([UnavailableProvider()]),
            stock_source=self._stock()[0],
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1,
                    source_type="generated_image",
                    prompt="x",
                    provider="down",
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_FAILED)
        self.assertIn("not available", shot.error)

    def test_generated_video_fails_until_provider_exists(self):
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=self._stock()[0]
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1, source_type="generated_video", prompt="x"
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_FAILED)
        self.assertIn("no material provider", shot.error)

    def test_retry_fallback_retries_once(self):
        provider = FakeImageProvider(fail_times=1)
        router = MaterialRouter(
            registry=ProviderRegistry([provider]),
            stock_source=self._stock()[0],
            fallback=FALLBACK_RETRY,
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1,
                    source_type="generated_image",
                    prompt="x",
                    provider="fakegen",
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        self.assertEqual(resolved.shots[0].status, SHOT_STATUS_RESOLVED)
        self.assertEqual(provider.calls, 2)

    def test_retry_fallback_gives_up_after_failure(self):
        provider = FakeImageProvider(fail_times=99)
        router = MaterialRouter(
            registry=ProviderRegistry([provider]),
            stock_source=self._stock()[0],
            fallback=FALLBACK_RETRY,
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1,
                    source_type="generated_image",
                    prompt="x",
                    provider="fakegen",
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_FAILED)
        self.assertIn("generation exploded", shot.error)
        self.assertEqual(provider.calls, 2)

    def test_stock_fallback_from_failed_generated_shot(self):
        provider = FakeImageProvider(fail_times=99)
        router = MaterialRouter(
            registry=ProviderRegistry([provider]),
            stock_source=self._stock()[0],
            fallback=FALLBACK_STOCK,
        )
        plan = make_plan(
            [
                ShotPlanItem(
                    index=1,
                    source_type="generated_image",
                    prompt="x",
                    provider="fakegen",
                )
            ]
        )
        resolved = router.resolve_shot_plan(plan, self.context)
        shot = resolved.shots[0]
        self.assertEqual(shot.status, SHOT_STATUS_RESOLVED)
        self.assertEqual(shot.provider, "stock")
        self.assertTrue(shot.asset_path.endswith("stock.mp4"))

    def test_input_plan_is_not_mutated(self):
        stock, _ = self._stock()
        router = MaterialRouter(
            registry=ProviderRegistry(), stock_source=stock
        )
        plan = make_plan(
            [ShotPlanItem(index=1, source_type="stock", query="city")]
        )
        router.resolve_shot_plan(plan, self.context)
        self.assertEqual(plan.shots[0].status, SHOT_STATUS_PLANNED)
        self.assertIsNone(plan.shots[0].asset_path)
        self.assertIsNone(plan.shots[0].error)

    def test_unknown_fallback_rejected(self):
        with self.assertRaises(ValueError):
            MaterialRouter(
                registry=ProviderRegistry(),
                stock_source=self._stock()[0],
                fallback="bogus",
            )


if __name__ == "__main__":
    unittest.main()
