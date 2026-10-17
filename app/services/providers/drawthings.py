"""Draw Things material provider.

Generates images through a Draw Things gRPC server using the drawthings-py
client. A bundled community preset (or a preset JSON file) supplies the
sampler recipe; the checkpoint file and per-shot values such as prompt,
negative prompt, size and seed are applied on top at call time.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import requests
from loguru import logger

from app.models.creative import ShotPlanItem
from app.services.providers.base import MaterialProvider, ProviderError

DEFAULT_ASPECT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (1024, 1024),
}

DEFAULT_PORT = 7859

_insecure_patch_applied = False


def _import_drawthings_py():
    try:
        import drawthings_py
    except ImportError:
        raise ProviderError(
            "drawthings-py is not installed in the api container"
        ) from None
    return drawthings_py


def _parse_host_port(base_url: str) -> tuple[str, int]:
    url = str(base_url or "").strip()
    if not url:
        raise ProviderError("drawthings base_url is required")
    for prefix in ("grpc://", "http://", "https://"):
        if url.lower().startswith(prefix):
            url = url[len(prefix):]
            break
    url = url.split("/", 1)[0]
    if ":" not in url:
        return url, DEFAULT_PORT
    host, _, port = url.rpartition(":")
    if not host:
        raise ProviderError(f"drawthings base_url has no host: {base_url!r}")
    if not port.isdigit():
        raise ProviderError(
            f"drawthings base_url has an invalid port: {base_url!r}"
        )
    return host, int(port)


def _apply_insecure_connect_patch() -> None:
    """Point GrpcService.connect at a plaintext channel.

    drawthings-py opens TLS channels by default, while a Draw Things gRPC
    deployment such as the one behind this provider listens in plaintext.
    The class method is replaced once per process; the transport imports
    stay inside the replacement so it only runs against the real client.
    """
    global _insecure_patch_applied
    if _insecure_patch_applied:
        return
    from drawthings_py.grpc.grpc_service import GrpcService

    async def insecure_connect(self):
        if self._channel is None:
            from grpclib.client import Channel
            from drawthings_py.generated.dt_grpc import image_service

            self._channel = Channel(self._host, self._port, ssl=False)
            self._service = image_service.ImageGenerationServiceStub(self._channel)
            await self._fetch_models()

    GrpcService.connect = insecure_connect
    _insecure_patch_applied = True


class DrawThingsProvider(MaterialProvider):
    """Material provider backed by a Draw Things gRPC server."""

    name = "drawthings"

    def __init__(
        self,
        base_url: str,
        model_file: str = "",
        preset: str = "",
        preset_path: str = "",
        steps: int = 0,
        guidance: float = 0.0,
        shift: float = 0.0,
        seed: int = -1,
        use_tls: bool = False,
        timeout_seconds: int = 900,
        probe_timeout: float = 5.0,
        service_factory: Optional[Any] = None,
    ):
        self.host, self.port = _parse_host_port(base_url)
        self.model_file = (model_file or "").strip()
        self.preset = (preset or "").strip()
        self.preset_path = (preset_path or "").strip()
        if not self.preset and not self.preset_path:
            raise ProviderError("drawthings requires 'preset' or 'preset_path'")
        self.steps = int(steps or 0)
        self.guidance = float(guidance or 0.0)
        self.shift = float(shift or 0.0)
        self.seed = int(seed if seed is not None else -1)
        self.use_tls = bool(use_tls)
        self.timeout_seconds = int(timeout_seconds or 900)
        self.probe_timeout = float(probe_timeout or 5.0)
        self._service_factory = service_factory

    @classmethod
    def from_config(cls, cfg: dict) -> "DrawThingsProvider":
        if not cfg.get("enabled", False):
            raise ProviderError("drawthings provider is disabled in config")
        return cls(
            base_url=cfg.get("base_url", ""),
            model_file=cfg.get("model_file", ""),
            preset=cfg.get("preset", ""),
            preset_path=cfg.get("preset_path", ""),
            steps=cfg.get("steps", 0),
            guidance=cfg.get("guidance", 0.0),
            shift=cfg.get("shift", 0.0),
            seed=cfg.get("seed", -1),
            use_tls=cfg.get("use_tls", False),
            timeout_seconds=cfg.get("timeout_seconds", 900),
            probe_timeout=cfg.get("probe_timeout", 5.0),
        )

    def _new_service(self):
        if self._service_factory is not None:
            return self._service_factory()
        if not self.use_tls:
            _apply_insecure_connect_patch()
        dt = _import_drawthings_py()
        return dt.DrawThings.grpc(
            host=self.host,
            port=self.port,
            progressbar=False,
            disable_messages=True,
        )

    def is_available(self) -> bool:
        async def probe():
            service = self._new_service()
            try:
                await service.get_models()
            finally:
                await service.close()

        try:
            asyncio.run(asyncio.wait_for(probe(), timeout=self.probe_timeout))
        except Exception:
            return False
        return True

    def generate(self, shot: ShotPlanItem, context: dict[str, Any]) -> list[str]:
        context = context or {}
        output_dir = context.get("output_dir") or ""
        if not output_dir:
            raise ProviderError("drawthings context is missing 'output_dir'")
        os.makedirs(output_dir, exist_ok=True)

        prompt = (shot.prompt or shot.script_segment or "").strip()
        if not prompt:
            raise ProviderError(
                f"drawthings shot {shot.index} has no prompt or script segment"
            )
        negative = (shot.negative_prompt or "").strip()

        raw_aspect = context.get("video_aspect")
        aspect = str(getattr(raw_aspect, "value", raw_aspect) or "16:9").strip().lower()
        width, height = DEFAULT_ASPECT_SIZES.get(
            aspect, DEFAULT_ASPECT_SIZES["16:9"]
        )
        seed = context.get("seed")
        if seed is None:
            seed = self.seed

        config = self._build_config(width, height, int(seed))
        builder = _import_drawthings_py().RequestBuilder(
            config, prompt, negative or None
        )
        for position, ref in enumerate(shot.reference_images or [], start=1):
            local = self._resolve_reference(ref, position, output_dir)
            if local is not None:
                builder.add_moodboard_image(local, weight=1.0)

        try:
            result = asyncio.run(
                asyncio.wait_for(
                    self._run_generation(builder), timeout=self.timeout_seconds
                )
            )
        except asyncio.TimeoutError:
            raise ProviderError(
                f"drawthings generation timed out after {self.timeout_seconds}s "
                f"for shot {shot.index}"
            ) from None
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"drawthings generation failed for shot {shot.index}: {exc}"
            ) from None

        images = list(getattr(result, "images", None) or [])
        if not images:
            raise ProviderError(
                f"drawthings finished without producing images for shot "
                f"{shot.index}"
            )
        paths: list[str] = []
        for position, image in enumerate(images, start=1):
            local_path = os.path.join(output_dir, f"generated_{position:03d}.png")
            try:
                image.to_file(local_path)
            except Exception as exc:
                raise ProviderError(
                    f"drawthings could not save the image for shot "
                    f"{shot.index}: {exc}"
                ) from None
            paths.append(local_path)
        logger.info(
            f"drawthings generated {len(paths)} image(s) for shot {shot.index} "
            f"(host={self.host}:{self.port})"
        )
        return paths

    async def _run_generation(self, builder) -> Any:
        service = self._new_service()
        try:
            return await service.generate(builder)
        finally:
            await service.close()

    def _build_config(self, width: int, height: int, seed: int) -> Any:
        dt = _import_drawthings_py()
        if self.preset_path:
            try:
                with open(self.preset_path, "r", encoding="utf-8") as f:
                    preset_json = f.read()
            except OSError as exc:
                raise ProviderError(
                    f"drawthings preset file is not readable: "
                    f"{self.preset_path} ({exc})"
                ) from None
            try:
                config = dt.Configs.from_json(preset_json)
            except Exception as exc:
                raise ProviderError(
                    f"drawthings preset file is not a valid preset: "
                    f"{self.preset_path} ({exc})"
                ) from None
        else:
            try:
                config = dt.Configs.from_preset(self.preset)
            except Exception as exc:
                raise ProviderError(
                    f"drawthings preset not found: {self.preset!r} ({exc})"
                ) from None
        config["width"] = int(width)
        config["height"] = int(height)
        config["seed"] = int(seed)
        if self.model_file:
            config["model"] = self.model_file
        if self.steps > 0:
            config["steps"] = int(self.steps)
        if self.guidance > 0:
            config["guidance"] = float(self.guidance)
        if self.shift != 0:
            config["shift"] = float(self.shift)
        return config

    def _resolve_reference(
        self, ref: str, position: int, output_dir: str
    ) -> Optional[str]:
        ref = (ref or "").strip()
        if not ref:
            return None
        if ref.startswith(("http://", "https://")):
            local_path = os.path.join(output_dir, f"reference_{position:03d}.png")
            try:
                response = requests.get(ref, timeout=60)
            except requests.RequestException as exc:
                logger.warning(
                    f"drawthings reference download failed, skipping {ref}: {exc}"
                )
                return None
            if response.status_code != 200 or not response.content:
                logger.warning(
                    f"drawthings reference download failed "
                    f"(HTTP {response.status_code}), skipping {ref}"
                )
                return None
            with open(local_path, "wb") as f:
                f.write(response.content)
            return local_path
        if os.path.isfile(ref):
            return ref
        logger.warning(
            f"drawthings reference image not found, skipping: {ref}"
        )
        return None
