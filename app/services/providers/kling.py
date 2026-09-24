"""Kling AI generated video provider for the creative pipeline.

Submits text-to-video tasks (or image-to-video when a public reference
image is attached to the shot) to the Kling API, polls the task until it
succeeds and downloads the resulting MP4 into the shot directory.

The Kling API authenticates every request with a short-lived HS256 JWT
(iss = access key, signed with the secret key); a fresh token is generated
for each HTTP call.

The vanilla MoneyPrinterTurbo flow never imports this module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional

import requests
from loguru import logger

from app.models.creative import ShotPlanItem
from app.services.providers.base import GeneratedVideoProvider, ProviderError

DEFAULT_BASE_URL = "https://api-singapore.klingai.com"
DEFAULT_MODEL_NAME = "kling-v2-master"

_SUCCESS_STATUS = "succeed"
_FAILED_STATUS = "failed"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(access_key: str, secret_key: str, now: Optional[int] = None) -> str:
    """Build the HS256 JWT the Kling API expects as Bearer token."""
    timestamp = int(now if now is not None else time.time())
    header = _b64url(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    payload = _b64url(
        json.dumps(
            {"iss": access_key, "exp": timestamp + 1800, "nbf": timestamp - 5},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(
        secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_b64url(signature)}"


class KlingVideoProvider(GeneratedVideoProvider):
    """Generate video shots through the Kling API."""

    name = "kling"

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model_name: str = DEFAULT_MODEL_NAME,
        cfg_scale: float = 0.8,
        poll_interval: float = 10.0,
        timeout_seconds: float = 900.0,
        session: Optional[Any] = None,
    ):
        self.access_key = str(access_key or "").strip()
        self.secret_key = str(secret_key or "").strip()
        self.base_url = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model_name = str(model_name or DEFAULT_MODEL_NAME)
        self.cfg_scale = float(cfg_scale) if cfg_scale else 0.8
        self.poll_interval = max(float(poll_interval), 0.0)
        self.timeout_seconds = float(timeout_seconds)
        self._session = session if session is not None else requests

    @classmethod
    def from_config(cls, cfg: dict) -> "KlingVideoProvider":
        access_key = str(cfg.get("access_key") or "").strip()
        secret_key = str(cfg.get("secret_key") or "").strip()
        if not access_key or not secret_key:
            raise ProviderError(
                "kling provider needs both access_key and secret_key"
            )
        return cls(
            access_key=access_key,
            secret_key=secret_key,
            base_url=str(cfg.get("base_url") or DEFAULT_BASE_URL),
            model_name=str(cfg.get("model_name") or DEFAULT_MODEL_NAME),
            cfg_scale=float(cfg.get("cfg_scale") or 0.8),
            poll_interval=float(cfg.get("poll_interval") or 10.0),
            timeout_seconds=float(cfg.get("timeout_seconds") or 900),
        )

    def is_available(self) -> bool:
        return bool(self.access_key and self.secret_key)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {make_jwt(self.access_key, self.secret_key)}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _unwrap(envelope: dict) -> dict:
        if not isinstance(envelope, dict):
            raise ProviderError("kling api returned an unexpected response")
        code = envelope.get("code")
        if code != 0:
            raise ProviderError(
                f"kling api error {code}: "
                f"{envelope.get('message') or 'no message'}"
            )
        return envelope.get("data") or {}

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.post(
                url, json=body, headers=self._headers(), timeout=30
            )
            response.raise_for_status()
            envelope = response.json()
        except (requests.RequestException, ValueError, OSError) as exc:
            raise ProviderError(f"kling submit request failed: {exc}") from None
        return self._unwrap(envelope)

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.get(
                url, headers=self._headers(), timeout=30
            )
            response.raise_for_status()
            envelope = response.json()
        except (requests.RequestException, ValueError, OSError) as exc:
            raise ProviderError(f"kling status request failed: {exc}") from None
        return self._unwrap(envelope)

    # ------------------------------------------------------------------
    # Generation flow
    # ------------------------------------------------------------------

    def generate_video(self, shot: ShotPlanItem, context: dict[str, Any]) -> str:
        prompt = str(shot.prompt or "").strip()
        if not prompt:
            raise ProviderError("kling shot is missing a generation prompt")
        image_url = self._public_reference_image(shot)
        body: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": str(shot.negative_prompt or "").strip(),
            "cfg_scale": self.cfg_scale,
            "aspect_ratio": _aspect((context or {}).get("video_aspect")),
            "duration": self._duration_for(shot),
            "model_name": self.model_name,
        }
        path = "/v1/videos/text2video"
        if image_url:
            body["image"] = image_url
            path = "/v1/videos/image2video"
        data = self._post(path, body)
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            raise ProviderError("kling submit returned no task_id")
        logger.info(f"[kling] submitted video task {task_id} via {path}")
        video_url = self._wait_for_task(task_id, path)
        return self._download(video_url, context)

    @staticmethod
    def _public_reference_image(shot: ShotPlanItem) -> Optional[str]:
        for ref in shot.reference_images or []:
            if str(ref).startswith(("http://", "https://")):
                return str(ref)
        return None

    @staticmethod
    def _duration_for(shot: ShotPlanItem) -> str:
        try:
            seconds = float(shot.duration)
        except (TypeError, ValueError):
            seconds = 5.0
        return "10" if seconds >= 7.5 else "5"

    def _wait_for_task(self, task_id: str, path: str) -> str:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            data = self._get(f"{path}/{task_id}")
            status = str(data.get("task_status") or "").strip().lower()
            if status == _SUCCESS_STATUS:
                videos = (data.get("task_result") or {}).get("videos") or []
                if not videos or not str((videos[0] or {}).get("url") or ""):
                    raise ProviderError(
                        f"kling task {task_id} succeeded without a video url"
                    )
                return str(videos[0]["url"])
            if status == _FAILED_STATUS:
                detail = data.get("task_status_msg") or "no detail"
                raise ProviderError(f"kling task {task_id} failed: {detail}")
            if time.monotonic() >= deadline:
                raise ProviderError(
                    f"kling task {task_id} did not finish within "
                    f"{self.timeout_seconds:.0f}s (last status: "
                    f"{status or 'unknown'})"
                )
            if self.poll_interval:
                time.sleep(self.poll_interval)

    def _download(self, video_url: str, context: dict[str, Any]) -> str:
        output_dir = str((context or {}).get("output_dir") or "").strip()
        if not output_dir:
            raise ProviderError("kling context is missing 'output_dir'")
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "video.mp4")
        try:
            response = self._session.get(video_url, timeout=300)
            response.raise_for_status()
            payload = response.content
        except (requests.RequestException, OSError) as exc:
            raise ProviderError(f"kling video download failed: {exc}") from None
        with open(path, "wb") as f:
            f.write(payload)
        logger.info(f"[kling] saved video for shot: {path}")
        return path


def _aspect(value: Any) -> str:
    value = getattr(value, "value", value)
    return str(value or "16:9").strip().lower() or "16:9"
