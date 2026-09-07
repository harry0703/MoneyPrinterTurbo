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

BANNERBEAR_BASE_URL = "https://api.bannerbear.com/v2"


def _pick_output_url(payload: dict[str, Any]) -> str:
    for key in ("video_url", "url", "render_url", "media_url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = _pick_output_url(value)
            if nested:
                return nested
    return ""


def generate_bannerbear_video(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "bannerbear"
    api_key = resolve_api_key("bannerbear_api_key", "BANNERBEAR_API_KEY")
    if not api_key:
        return missing_key_result(provider)

    template_id = (payload.get("templateId") or "").strip()
    if not template_id:
        return error_result(provider, "templateId is required")

    directory = ensure_output_dir(output_dir)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "template": template_id,
        "modifications": (payload.get("metadata") or {}).get("modifications", []),
        "render": True,
    }

    try:
        create_response = requests.post(
            f"{BANNERBEAR_BASE_URL}/videos",
            json=body,
            headers=headers,
            timeout=(10, 60),
        )
        if create_response.status_code < 200 or create_response.status_code >= 300:
            return error_result(provider, f"request failed ({create_response.status_code})")

        create_data = create_response.json()
        request_id = str(create_data.get("uid") or create_data.get("id") or "")
        if not request_id:
            return error_result(provider, "missing request id")

        def get_status() -> tuple[str, dict[str, Any]]:
            response = requests.get(
                f"{BANNERBEAR_BASE_URL}/videos/{request_id}",
                headers=headers,
                timeout=(10, 60),
            )
            if response.status_code < 200 or response.status_code >= 300:
                return "error", {"http_status": response.status_code}
            data = response.json()
            status = str(data.get("status") or "pending")
            return status, data

        ok, final_status, final_payload = poll_until_done(
            provider=provider,
            external_id=request_id,
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"generation {final_status}", request_id)

        remote_url = _pick_output_url(final_payload)
        if not remote_url:
            return error_result(provider, "missing output url", request_id)

        base_name = sanitize_filename(payload.get("prompt") or "bannerbear", default_name="bannerbear")
        local_path = download_file(remote_url, os.path.join(directory, f"{base_name}.mp4"))

        return success_result(
            provider=provider,
            output_type="video",
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={"request_id": request_id, "status": final_status},
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
