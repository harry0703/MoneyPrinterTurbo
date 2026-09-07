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

DID_BASE_URL = "https://api.d-id.com"


def generate_did_talk(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "did"
    api_key = resolve_api_key("did_api_key", "DID_API_KEY")
    if not api_key:
        return missing_key_result(provider)

    image_url = (payload.get("imageUrl") or "").strip()
    script = (payload.get("script") or "").strip()
    if not image_url:
        return error_result(provider, "imageUrl is required")
    if not script:
        return error_result(provider, "script is required")

    directory = ensure_output_dir(output_dir)
    headers = {
        "Authorization": f"Basic {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "source_url": image_url,
        "script": {
            "type": "text",
            "input": script,
        },
    }

    try:
        create_response = requests.post(
            f"{DID_BASE_URL}/talks",
            json=body,
            headers=headers,
            timeout=(10, 60),
        )
        if create_response.status_code < 200 or create_response.status_code >= 300:
            return error_result(provider, f"request failed ({create_response.status_code})")

        create_data = create_response.json()
        talk_id = str(create_data.get("id") or "")
        if not talk_id:
            return error_result(provider, "missing talk id")

        def get_status() -> tuple[str, dict[str, Any]]:
            response = requests.get(
                f"{DID_BASE_URL}/talks/{talk_id}",
                headers=headers,
                timeout=(10, 60),
            )
            if response.status_code < 200 or response.status_code >= 300:
                return "error", {"http_status": response.status_code}
            data = response.json()
            status = str(data.get("status") or "created")
            return status, data

        ok, final_status, final_payload = poll_until_done(
            provider=provider,
            external_id=talk_id,
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"generation {final_status}", talk_id)

        remote_url = str(
            final_payload.get("result_url")
            or final_payload.get("video_url")
            or final_payload.get("url")
            or ""
        )
        if not remote_url:
            return error_result(provider, "missing output video url", talk_id)

        base_name = sanitize_filename(payload.get("prompt") or script[:30], default_name="did-talk")
        local_path = download_file(remote_url, os.path.join(directory, f"{base_name}.mp4"))

        return success_result(
            provider=provider,
            output_type="video",
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={"talk_id": talk_id, "status": final_status},
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
