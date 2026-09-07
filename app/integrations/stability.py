from __future__ import annotations

import base64
import os
from typing import Any

import requests

from app.integrations.common import (
    ensure_output_dir,
    error_result,
    missing_key_result,
    sanitize_filename,
    success_result,
)
from app.integrations.api_key_resolver import resolve_api_key
from app.integrations.download_file import download_file

STABILITY_IMAGE_URL = "https://api.stability.ai/v2beta/stable-image/generate/core"


def generate_stability_image(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "stability"
    api_key = resolve_api_key("stability_api_key", "STABILITY_API_KEY")
    if not api_key:
        return missing_key_result(provider)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return error_result(provider, "prompt is required")

    directory = ensure_output_dir(output_dir)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, image/*",
    }
    form_data = {
        "prompt": prompt,
        "output_format": "png",  # Change this if you prefer webp/jpg.
        "aspect_ratio": payload.get("aspectRatio", "9:16"),
    }

    try:
        response = requests.post(
            STABILITY_IMAGE_URL,
            headers=headers,
            files={"none": (None, "")},
            data=form_data,
            timeout=(10, 120),
        )
        if response.status_code < 200 or response.status_code >= 300:
            return error_result(provider, f"request failed ({response.status_code})")

        content_type = (response.headers.get("Content-Type") or "").lower()
        base_name = sanitize_filename(prompt, default_name="stability-image")

        if "image/" in content_type:
            local_path = os.path.join(directory, f"{base_name}.png")
            with open(local_path, "wb") as file_handle:
                file_handle.write(response.content)
            remote_url = ""
            return success_result(
                provider=provider,
                output_type="image",
                local_path=local_path,
                remote_url=remote_url,
                filename=os.path.basename(local_path),
                metadata={"status": "completed"},
            )

        data = response.json()
        artifacts = data.get("artifacts") if isinstance(data, dict) else None
        if isinstance(artifacts, list) and artifacts:
            b64_data = (artifacts[0] or {}).get("base64")
            if b64_data:
                local_path = os.path.join(directory, f"{base_name}.png")
                with open(local_path, "wb") as file_handle:
                    file_handle.write(base64.b64decode(b64_data))
                return success_result(
                    provider=provider,
                    output_type="image",
                    local_path=local_path,
                    remote_url="",
                    filename=os.path.basename(local_path),
                    metadata={"status": "completed"},
                )

        remote_url = str(data.get("url") or data.get("image_url") or "")
        if remote_url:
            local_path = download_file(remote_url, os.path.join(directory, f"{base_name}.png"))
            return success_result(
                provider=provider,
                output_type="image",
                local_path=local_path,
                remote_url=remote_url,
                filename=os.path.basename(local_path),
                metadata={"status": "completed"},
            )

        return error_result(provider, "missing image output in response")
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
