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

HEYGEN_BASE_URL = "https://api.heygen.com"


def generate_heygen_video(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "heygen"
    api_key = resolve_api_key("heygen_api_key", "HEYGEN_API_KEY")
    if not api_key:
        return missing_key_result(provider)

    script = (payload.get("script") or "").strip()
    if not script:
        return error_result(provider, "script is required")

    directory = ensure_output_dir(output_dir)
    metadata = payload.get("metadata") or {}

    # Replace avatar_id and voice_id with your own resources from HeyGen dashboard.
    avatar_id = str(metadata.get("avatar_id") or "")
    voice_id = str(metadata.get("voice_id") or "")

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                },
                "voice": {
                    "type": "text",
                    "input_text": script,
                    "voice_id": voice_id,
                },
            }
        ],
        "aspect_ratio": payload.get("aspectRatio", "9:16"),
    }

    try:
        create_response = requests.post(
            f"{HEYGEN_BASE_URL}/v2/video/generate",
            json=body,
            headers=headers,
            timeout=(10, 60),
        )
        if create_response.status_code < 200 or create_response.status_code >= 300:
            return error_result(provider, f"request failed ({create_response.status_code})")

        create_data = create_response.json()
        data_field = create_data.get("data") or create_data
        video_id = str(data_field.get("video_id") or data_field.get("id") or "")
        if not video_id:
            return error_result(provider, "missing video id")

        def get_status() -> tuple[str, dict[str, Any]]:
            response = requests.get(
                f"{HEYGEN_BASE_URL}/v1/video_status.get?video_id={video_id}",
                headers=headers,
                timeout=(10, 60),
            )
            if response.status_code < 200 or response.status_code >= 300:
                return "error", {"http_status": response.status_code}
            data = response.json()
            status_payload = data.get("data") or data
            status = str(status_payload.get("status") or "processing")
            return status, status_payload

        ok, final_status, final_payload = poll_until_done(
            provider=provider,
            external_id=video_id,
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"generation {final_status}", video_id)

        remote_url = str(
            final_payload.get("video_url")
            or final_payload.get("url")
            or final_payload.get("download_url")
            or ""
        )
        if not remote_url:
            return error_result(provider, "missing output video url", video_id)

        base_name = sanitize_filename(payload.get("prompt") or script[:30], default_name="heygen-video")
        local_path = download_file(remote_url, os.path.join(directory, f"{base_name}.mp4"))

        return success_result(
            provider=provider,
            output_type="video",
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={
                "video_id": video_id,
                "status": final_status,
                "avatar_id": avatar_id,
                "voice_id": voice_id,
            },
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
