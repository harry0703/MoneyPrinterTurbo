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

FAL_QUEUE_BASE = "https://queue.fal.run"


def _extract_media_url(payload: dict[str, Any]) -> str:
    for key in ("video_url", "image_url", "url", "render_url", "media_url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("video", "image", "data", "output", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _extract_media_url(value)
            if nested:
                return nested
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first:
                return first
            if isinstance(first, dict):
                nested = _extract_media_url(first)
                if nested:
                    return nested
    return ""


def generate_fal_video(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "fal"
    api_key = resolve_api_key("fal_api_key", "FAL_KEY")
    if not api_key:
        return missing_key_result(provider)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return error_result(provider, "prompt is required")

    directory = ensure_output_dir(output_dir)
    metadata = payload.get("metadata") or {}
    model_name = str(metadata.get("model") or "fal-ai/ltx-video-v097")

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }
    submit_body = {
        "prompt": prompt,
        "aspect_ratio": payload.get("aspectRatio", "9:16"),
        "duration": int(payload.get("duration", 5) or 5),
    }

    try:
        submit_response = requests.post(
            f"{FAL_QUEUE_BASE}/{model_name}",
            json=submit_body,
            headers=headers,
            timeout=(10, 60),
        )
        if submit_response.status_code < 200 or submit_response.status_code >= 300:
            return error_result(provider, f"request failed ({submit_response.status_code})")

        submit_data = submit_response.json()
        request_id = str(submit_data.get("request_id") or submit_data.get("id") or "")
        status_url = str(submit_data.get("status_url") or "")
        response_url = str(submit_data.get("response_url") or "")

        if not request_id and not status_url:
            return error_result(provider, "missing queue request id")

        if not status_url and request_id:
            status_url = f"{FAL_QUEUE_BASE}/{model_name}/requests/{request_id}/status"
        if not response_url and request_id:
            response_url = f"{FAL_QUEUE_BASE}/{model_name}/requests/{request_id}"

        def get_status() -> tuple[str, dict[str, Any]]:
            response = requests.get(status_url, headers=headers, timeout=(10, 60))
            if response.status_code < 200 or response.status_code >= 300:
                return "error", {"http_status": response.status_code}
            data = response.json()
            status = str(data.get("status") or data.get("state") or "IN_PROGRESS")
            return status, data

        ok, final_status, _ = poll_until_done(
            provider=provider,
            external_id=request_id or "fal-request",
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"generation {final_status}", request_id)

        final_response = requests.get(response_url, headers=headers, timeout=(10, 60))
        if final_response.status_code < 200 or final_response.status_code >= 300:
            return error_result(provider, f"response fetch failed ({final_response.status_code})", request_id)

        final_data = final_response.json()
        remote_url = _extract_media_url(final_data)
        if not remote_url:
            return error_result(provider, "missing output url", request_id)

        file_extension = ".mp4" if payload.get("outputType", "video") == "video" else ".png"
        base_name = sanitize_filename(prompt, default_name="fal-output")
        local_path = download_file(remote_url, os.path.join(directory, f"{base_name}{file_extension}"))

        output_type = "video" if local_path.lower().endswith(".mp4") else "image"
        return success_result(
            provider=provider,
            output_type=output_type,
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={
                "request_id": request_id,
                "status_url": status_url,
                "response_url": response_url,
                "status": final_status,
            },
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
