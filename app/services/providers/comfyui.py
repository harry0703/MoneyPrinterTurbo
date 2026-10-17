"""ComfyUI material provider.

Generates images through the ComfyUI HTTP API. The request graph comes from a
small workflow template (API-format prompt) stored under
``resources/workflows/comfyui/``; per-shot values such as prompt, negative
prompt, size and seed are injected into ``{{token}}`` placeholders at call
time. Sampler settings and the checkpoint default to the template values and
can be overridden from config.

If the backend is unreachable and a launcher URL is configured, the provider
asks the launcher to start the backend before queueing the prompt.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Any, Optional

import requests
from loguru import logger

from app.models.creative import ShotPlanItem
from app.services.providers.base import MaterialProvider, ProviderError

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DEFAULT_TEMPLATE_DIR = os.path.join(_REPO_ROOT, "resources", "workflows", "comfyui")

DEFAULT_ASPECT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (832, 832),
}

_TOKEN_RE = re.compile(r'(?P<q>"?)\{\{(?P<name>[a-zA-Z0-9_]+)\}\}(?P=q)')
_BARE_TOKEN_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def render_template(template: dict, params: dict[str, Any]) -> tuple[dict, dict]:
    """
    Render a workflow template into an API-format prompt graph.

    ``{{name}}`` tokens in the template's ``prompt`` section are replaced with
    the JSON-encoded value from ``params`` (tokens may appear quoted or bare).
    Returns the rendered graph and the template ``meta`` section.
    """
    if not isinstance(template, dict) or "prompt" not in template:
        raise ProviderError("workflow template is missing the 'prompt' section")
    document = json.dumps(template["prompt"], ensure_ascii=False)

    def _replace(match: re.Match) -> str:
        name = match.group("name")
        if name not in params:
            raise ProviderError(
                f"workflow template references missing parameter {name!r}"
            )
        return json.dumps(params[name], ensure_ascii=False)

    rendered = _TOKEN_RE.sub(_replace, document)
    remaining = set(_BARE_TOKEN_RE.findall(rendered))
    if remaining:
        raise ProviderError(
            f"unresolved workflow template parameters: {sorted(remaining)}"
        )
    graph = json.loads(rendered)
    if not isinstance(graph, dict) or not graph:
        raise ProviderError("workflow template prompt graph must be a non-empty object")
    return graph, template.get("meta", {}) or {}


def _response_detail(response: requests.Response) -> str:
    try:
        return json.dumps(response.json(), ensure_ascii=False)[:500]
    except ValueError:
        return (response.text or "")[:500]


class ComfyUIProvider(MaterialProvider):
    """Material provider backed by a ComfyUI server."""

    name = "comfyui"

    def __init__(
        self,
        base_url: str,
        launcher_url: str = "",
        template: str = "image_basic",
        checkpoint: str = "",
        steps: int = 0,
        cfg: float = 0.0,
        sampler_name: str = "",
        scheduler: str = "",
        timeout_seconds: int = 600,
        poll_interval: float = 2.0,
        probe_timeout: float = 5.0,
        session: Optional[requests.Session] = None,
        template_dir: Optional[str] = None,
    ):
        if not base_url:
            raise ProviderError("comfyui base_url is required")
        self.base_url = base_url.rstrip("/")
        self.launcher_url = (launcher_url or "").rstrip("/")
        self.template_name = template or "image_basic"
        self.checkpoint = checkpoint or ""
        self.steps = int(steps or 0)
        self.cfg = float(cfg or 0.0)
        self.sampler_name = sampler_name or ""
        self.scheduler = scheduler or ""
        self.timeout_seconds = int(timeout_seconds or 600)
        self.poll_interval = float(poll_interval or 2.0)
        self.probe_timeout = float(probe_timeout or 5.0)
        self._session = session if session is not None else requests.Session()
        self._template_dir = template_dir or DEFAULT_TEMPLATE_DIR

    @classmethod
    def from_config(cls, cfg: dict) -> "ComfyUIProvider":
        if not cfg.get("enabled", False):
            raise ProviderError("comfyui provider is disabled in config")
        return cls(
            base_url=cfg.get("base_url", ""),
            launcher_url=cfg.get("launcher_url", ""),
            template=cfg.get("template", "image_basic"),
            checkpoint=cfg.get("checkpoint", ""),
            steps=cfg.get("steps", 0),
            cfg=cfg.get("cfg", 0.0),
            sampler_name=cfg.get("sampler_name", ""),
            scheduler=cfg.get("scheduler", ""),
            timeout_seconds=cfg.get("timeout_seconds", 600),
            poll_interval=cfg.get("poll_interval", 2.0),
        )

    def is_available(self) -> bool:
        try:
            response = self._session.get(
                f"{self.base_url}/system_stats", timeout=self.probe_timeout
            )
        except requests.RequestException:
            return False
        return response.status_code == 200

    def _load_template(self) -> dict:
        path = os.path.join(self._template_dir, f"{self.template_name}.json")
        try:
            with open(path, mode="r", encoding="utf-8") as f:
                template = json.load(f)
        except FileNotFoundError:
            raise ProviderError(f"comfyui workflow template not found: {path}") from None
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"comfyui workflow template is not valid JSON: {path} ({exc})"
            ) from None
        return template

    def _ensure_running(self) -> None:
        if self.is_available():
            return
        if not self.launcher_url:
            raise ProviderError(
                f"comfyui backend unreachable at {self.base_url} "
                "and no launcher_url configured"
            )
        try:
            status = self._session.get(
                f"{self.launcher_url}/api/status", timeout=self.probe_timeout
            ).json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(
                f"comfyui launcher unreachable at {self.launcher_url}: {exc}"
            ) from None
        if not status.get("running"):
            self._session.post(
                f"{self.launcher_url}/api/start", timeout=self.probe_timeout
            )
            logger.info("comfyui launcher asked to start the backend, waiting")
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if self.is_available():
                return
            time.sleep(self.poll_interval)
        raise ProviderError(
            f"comfyui backend not reachable after startup: {self.base_url}"
        )

    def generate(self, shot: ShotPlanItem, context: dict[str, Any]) -> list[str]:
        context = context or {}
        output_dir = context.get("output_dir") or ""
        if not output_dir:
            raise ProviderError("comfyui context is missing 'output_dir'")
        os.makedirs(output_dir, exist_ok=True)

        raw_aspect = context.get("video_aspect")
        aspect = str(getattr(raw_aspect, "value", raw_aspect) or "16:9").strip().lower()
        task_id = str(context.get("task_id") or "")
        seed = context.get("seed")
        if seed is None:
            seed = random.randint(0, 2**32 - 1)

        template = self._load_template()
        meta = template.get("meta", {}) or {}
        sizes = meta.get("sizes") or DEFAULT_ASPECT_SIZES
        width, height = self._aspect_size(sizes, aspect)

        params = {
            "positive": shot.prompt or "",
            "negative": shot.negative_prompt or "",
            "width": int(width),
            "height": int(height),
            "seed": int(seed),
            "filename_prefix": f"mpt_{task_id[:8]}_shot{shot.index:03d}",
            "checkpoint": self.checkpoint,
        }
        graph, meta = render_template(template, params)
        self._apply_overrides(graph, meta)

        self._ensure_running()
        prompt_id = self._queue_prompt(graph)
        outputs = self._wait_for_outputs(prompt_id)
        paths = self._download_images(outputs, output_dir)
        logger.info(
            f"comfyui generated {len(paths)} image(s) for shot {shot.index} "
            f"(prompt_id={prompt_id})"
        )
        return paths

    def _aspect_size(self, sizes: dict, aspect: str) -> tuple[int, int]:
        size = sizes.get(aspect, sizes.get("16:9"))
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise ProviderError(
                "comfyui template sizes must map each aspect to [width, height]"
            )
        return int(size[0]), int(size[1])

    def _apply_overrides(self, graph: dict, meta: dict) -> None:
        if self.checkpoint:
            for node in graph.values():
                if (
                    isinstance(node, dict)
                    and node.get("class_type") == "CheckpointLoaderSimple"
                ):
                    node.setdefault("inputs", {})["ckpt_name"] = self.checkpoint
        sampler_id = str(meta.get("nodes", {}).get("sampler", ""))
        node = graph.get(sampler_id)
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if isinstance(inputs, dict):
            if self.steps > 0:
                inputs["steps"] = self.steps
            if self.cfg > 0:
                inputs["cfg"] = self.cfg
            if self.sampler_name:
                inputs["sampler_name"] = self.sampler_name
            if self.scheduler:
                inputs["scheduler"] = self.scheduler

    def _queue_prompt(self, graph: dict) -> str:
        try:
            response = self._session.post(
                f"{self.base_url}/prompt",
                json={"prompt": graph},
                timeout=max(self.probe_timeout * 2, 15),
            )
        except requests.RequestException as exc:
            raise ProviderError(f"comfyui /prompt request failed: {exc}") from None
        if response.status_code != 200:
            raise ProviderError(
                f"comfyui rejected the prompt (HTTP {response.status_code}): "
                f"{_response_detail(response)}"
            )
        try:
            prompt_id = response.json().get("prompt_id")
        except ValueError:
            raise ProviderError(
                f"comfyui /prompt response is not valid JSON: "
                f"{_response_detail(response)}"
            ) from None
        if not prompt_id:
            raise ProviderError(
                f"comfyui /prompt response has no prompt_id: "
                f"{_response_detail(response)}"
            )
        return prompt_id

    def _wait_for_outputs(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        url = f"{self.base_url}/history/{prompt_id}"
        while True:
            if time.monotonic() >= deadline:
                raise ProviderError(
                    f"comfyui generation timed out after {self.timeout_seconds}s "
                    f"(prompt_id={prompt_id})"
                )
            time.sleep(self.poll_interval)
            try:
                response = self._session.get(
                    url, timeout=max(self.probe_timeout * 2, 15)
                )
            except requests.RequestException as exc:
                raise ProviderError(f"comfyui history lookup failed: {exc}") from None
            if response.status_code != 200:
                raise ProviderError(
                    f"comfyui history lookup failed (HTTP {response.status_code})"
                )
            try:
                history = response.json()
            except ValueError:
                raise ProviderError(
                    "comfyui history response is not valid JSON"
                ) from None
            entry = history.get(prompt_id)
            if not entry:
                continue
            status = entry.get("status") or {}
            if status.get("status_str") == "error" or "execution_error" in entry:
                error = entry.get("execution_error") or {}
                message = error.get("exception_message") or "unknown execution error"
                node_id = error.get("node_id")
                suffix = f" (node {node_id})" if node_id is not None else ""
                raise ProviderError(f"comfyui execution failed{suffix}: {message}")
            return entry.get("outputs") or {}

    def _download_images(self, outputs: dict, output_dir: str) -> list[str]:
        images: list[dict] = []
        for node_output in outputs.values():
            if isinstance(node_output, dict):
                for item in node_output.get("images") or []:
                    if isinstance(item, dict) and item.get("filename"):
                        images.append(item)
        if not images:
            raise ProviderError("comfyui finished without producing images")
        paths: list[str] = []
        for position, item in enumerate(images, start=1):
            filename = item["filename"]
            extension = os.path.splitext(filename)[1] or ".png"
            local_path = os.path.join(
                output_dir, f"generated_{position:03d}{extension}"
            )
            params = {
                "filename": filename,
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            }
            try:
                response = self._session.get(
                    f"{self.base_url}/view",
                    params=params,
                    timeout=max(self.probe_timeout * 2, 30),
                )
            except requests.RequestException as exc:
                raise ProviderError(f"comfyui image download failed: {exc}") from None
            if response.status_code != 200 or not response.content:
                raise ProviderError(
                    f"comfyui image download failed (HTTP {response.status_code})"
                )
            with open(local_path, "wb") as f:
                f.write(response.content)
            paths.append(local_path)
        return paths
