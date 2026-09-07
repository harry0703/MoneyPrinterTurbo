from __future__ import annotations

from typing import Any

import requests

from app.integrations.common import (
    ensure_output_dir,
    error_result,
    missing_key_result,
    poll_until_done,
    sanitize_filename,
    success_result,
)
from app.integrations.api_key_resolver import resolve_api_key
from app.integrations.download_file import download_file

REPLICATE_BASE_URL = "https://api.replicate.com/v1"


def _extract_first_url(output: Any) -> str:
    if isinstance(output, str) and output:
        return output
    if isinstance(output, list):
        for item in output:
            url = _extract_first_url(item)
            if url:
                return url
    if isinstance(output, dict):
        for key in ("url", "video", "image"):
            value = output.get(key)
            url = _extract_first_url(value)
            if url:
                return url
    return ""


def generate_replicate_asset(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "replicate"
    api_key = resolve_api_key("replicate_api_token", "REPLICATE_API_TOKEN")
    if not api_key:
        return missing_key_result(provider)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt and not payload.get("imageUrl"):
        return error_result(provider, "prompt or imageUrl is required")

    metadata = payload.get("metadata") or {}
    version = str(metadata.get("version") or "")
    if not version:
        return error_result(provider, "metadata.version is required for Replicate")

    directory = ensure_output_dir(output_dir)
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "version": version,
        "input": {
            "prompt": prompt,
            "image": payload.get("imageUrl"),
            "aspect_ratio": payload.get("aspectRatio", "9:16"),
        },
    }

    try:
        create_response = requests.post(
            f"{REPLICATE_BASE_URL}/predictions",
            headers=headers,
            json=body,
            timeout=(10, 60),
        )
        if create_response.status_code < 200 or create_response.status_code >= 300:
            return error_result(provider, f"request failed ({create_response.status_code})")

        create_data = create_response.json()
        prediction_id = str(create_data.get("id") or "")
        if not prediction_id:
            return error_result(provider, "missing prediction id")

        def get_status() -> tuple[str, dict[str, Any]]:
            response = requests.get(
                f"{REPLICATE_BASE_URL}/predictions/{prediction_id}",
                headers=headers,
                timeout=(10, 60),
            )
            if response.status_code < 200 or response.status_code >= 300:
                return "error", {"http_status": response.status_code}
            data = response.json()
            status = str(data.get("status") or "starting")
            return status, data

        ok, final_status, final_payload = poll_until_done(
            provider=provider,
            external_id=prediction_id,
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"generation {final_status}", prediction_id)

        remote_url = _extract_first_url(final_payload.get("output"))
        if not remote_url:
            return error_result(provider, "missing output url", prediction_id)

        base_name = sanitize_filename(prompt or "replicate", default_name="replicate-output")
        default_ext = ".mp4" if payload.get("outputType", "video") == "video" else ".png"
        local_path = download_file(remote_url, os.path.join(directory, f"{base_name}{default_ext}"))

        output_type = "video" if local_path.lower().endswith(".mp4") else "image"
        return success_result(
            provider=provider,
            output_type=output_type,
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={"prediction_id": prediction_id, "status": final_status},
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
