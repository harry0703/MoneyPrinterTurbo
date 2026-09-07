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

GETIMG_BASE_URL = "https://api.getimg.ai/v1"


def generate_getimg_video(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "getimg"
    api_key = resolve_api_key("getimg_api_key", "GETIMG_API_KEY")
    if not api_key:
        return missing_key_result(provider)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return error_result(provider, "prompt is required")

    directory = ensure_output_dir(output_dir)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Change the model identifier here if you want a different getimg video model.
    output_type = str(payload.get("outputType") or "video").lower()
    request_body = {
        "prompt": prompt,
        "aspect_ratio": payload.get("aspectRatio", "9:16"),
        "duration": int(payload.get("duration", 5) or 5),
        "model": (payload.get("metadata") or {}).get("model", "getimg/video"),
    }
    create_endpoint = f"{GETIMG_BASE_URL}/video/generations"
    status_endpoint = f"{GETIMG_BASE_URL}/video/generations"
    default_extension = ".mp4"
    default_name = "getimg-video"

    if output_type == "image":
        create_endpoint = f"{GETIMG_BASE_URL}/stable-diffusion/text-to-image"
        status_endpoint = f"{GETIMG_BASE_URL}/stable-diffusion/text-to-image"
        request_body.pop("duration", None)
        request_body["width"] = (payload.get("metadata") or {}).get("width", 1080)
        request_body["height"] = (payload.get("metadata") or {}).get("height", 1920)
        default_extension = ".png"
        default_name = "getimg-image"

    try:
        create_response = requests.post(
            create_endpoint,
            json=request_body,
            headers=headers,
            timeout=(10, 60),
        )
        if create_response.status_code < 200 or create_response.status_code >= 300:
            return error_result(provider, f"request failed ({create_response.status_code})")

        create_data = create_response.json()
        immediate_url = str(
            create_data.get("url")
            or create_data.get("image_url")
            or create_data.get("video_url")
            or ""
        )
        if immediate_url:
            base_name = sanitize_filename(prompt, default_name=default_name)
            local_path = download_file(immediate_url, os.path.join(directory, f"{base_name}{default_extension}"))
            final_output_type = "video" if local_path.lower().endswith(".mp4") else "image"
            return success_result(
                provider=provider,
                output_type=final_output_type,
                local_path=local_path,
                remote_url=immediate_url,
                filename=os.path.basename(local_path),
                metadata={"status": "completed"},
            )

        generation_id = str(
            create_data.get("id")
            or create_data.get("generation_id")
            or ((create_data.get("data") or {}).get("id") if isinstance(create_data.get("data"), dict) else "")
            or ""
        )
        if not generation_id:
            return error_result(provider, "missing generation id in response")

        def get_status() -> tuple[str, dict[str, Any]]:
            status_response = requests.get(
                f"{status_endpoint}/{generation_id}",
                headers=headers,
                timeout=(10, 60),
            )
            if status_response.status_code < 200 or status_response.status_code >= 300:
                return "error", {"http_status": status_response.status_code}
            data = status_response.json()
            status = str(data.get("status") or data.get("state") or "processing")
            return status, data

        ok, final_status, status_payload = poll_until_done(
            provider=provider,
            external_id=generation_id,
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"generation {final_status}", generation_id)

        remote_url = ""
        data_field = status_payload.get("data")
        if isinstance(data_field, list) and data_field:
            remote_url = str((data_field[0] or {}).get("url") or "")
        if not remote_url:
            remote_url = str(
                status_payload.get("url")
                or status_payload.get("video_url")
                or ((status_payload.get("output") or {}).get("url") if isinstance(status_payload.get("output"), dict) else "")
                or ""
            )

        if not remote_url:
            return error_result(provider, "missing output url", generation_id)

        base_name = sanitize_filename(prompt, default_name=default_name)
        local_path = download_file(remote_url, os.path.join(directory, f"{base_name}{default_extension}"))
        final_output_type = "video" if local_path.lower().endswith(".mp4") else "image"

        return success_result(
            provider=provider,
            output_type=final_output_type,
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={"generation_id": generation_id, "status": final_status},
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
