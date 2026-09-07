from __future__ import annotations

import os
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


SHOTSTACK_BASE_URL = os.getenv("SHOTSTACK_BASE_URL", "https://api.shotstack.io/stage")


def _build_shotstack_edit(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = payload.get("templateId")
    if template_id:
        # Put your merge fields here when using Shotstack templates.
        return {
            "template": {
                "id": template_id,
                "merge": payload.get("metadata", {}).get("merge", {}),
            },
            "output": {
                "format": "mp4",
                "aspectRatio": payload.get("aspectRatio", "9:16"),
            },
        }

    assets = payload.get("assets") or []
    tracks: list[dict[str, Any]] = [{"clips": []}]
    current_start = 0.0
    default_duration = float(payload.get("duration", 5) or 5)

    for asset in assets:
        asset_url = str(asset.get("url") or "")
        if not asset_url:
            continue
        asset_type = str(asset.get("type") or "video")
        clip_length = float(asset.get("length") or default_duration)

        clip: dict[str, Any] = {
            "start": round(current_start, 2),
            "length": round(clip_length, 2),
            "transition": {
                "in": "fade",
                "out": "fade",
            },
        }

        if asset_type == "image":
            # These defaults add a subtle motion language for integrated images.
            clip["asset"] = {
                "type": "image",
                "src": asset_url,
                "effect": "zoomIn",
            }
        elif asset_type == "audio":
            clip["asset"] = {
                "type": "audio",
                "src": asset_url,
            }
        elif asset_type == "title":
            clip["asset"] = {
                "type": "title",
                "text": str(asset.get("text") or ""),
                "style": "minimal",
            }
        else:
            clip["asset"] = {
                "type": "video",
                "src": asset_url,
            }

        tracks[0]["clips"].append(clip)
        current_start += clip_length

    return {
        "timeline": {
            "tracks": tracks,
        },
        "output": {
            "format": "mp4",
            "aspectRatio": payload.get("aspectRatio", "9:16"),
        },
    }


def render_shotstack_video(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    provider = "shotstack"
    api_key = resolve_api_key("shotstack_api_key", "SHOTSTACK_API_KEY")
    if not api_key:
        return missing_key_result(provider)

    directory = ensure_output_dir(output_dir)
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    edit = _build_shotstack_edit(payload)

    try:
        create_response = requests.post(
            f"{SHOTSTACK_BASE_URL}/v1/render",
            json={"edit": edit},
            headers=headers,
            timeout=(10, 60),
        )
        if create_response.status_code < 200 or create_response.status_code >= 300:
            return error_result(provider, f"request failed ({create_response.status_code})")

        create_data = create_response.json()
        response_data = create_data.get("response") or create_data
        render_id = str(response_data.get("id") or "")
        if not render_id:
            return error_result(provider, "missing render id")

        def get_status() -> tuple[str, dict[str, Any]]:
            response = requests.get(
                f"{SHOTSTACK_BASE_URL}/v1/render/{render_id}",
                headers=headers,
                timeout=(10, 60),
            )
            if response.status_code < 200 or response.status_code >= 300:
                return "error", {"http_status": response.status_code}
            data = response.json()
            status_payload = data.get("response") or data
            status = str(status_payload.get("status") or "queued")
            return status, status_payload

        ok, final_status, final_payload = poll_until_done(
            provider=provider,
            external_id=render_id,
            get_status=get_status,
        )
        if not ok:
            return error_result(provider, f"render {final_status}", render_id)

        remote_url = str(final_payload.get("url") or final_payload.get("src") or "")
        if not remote_url:
            return error_result(provider, "missing rendered video url", render_id)

        file_name = f"{sanitize_filename(payload.get('prompt', 'shotstack-render'))}-{render_id}.mp4"
        local_path = download_file(remote_url, os.path.join(directory, file_name))

        return success_result(
            provider=provider,
            output_type="video",
            local_path=local_path,
            remote_url=remote_url,
            filename=os.path.basename(local_path),
            metadata={"render_id": render_id, "status": final_status},
        )
    except requests.RequestException:
        return error_result(provider, "network error while contacting provider")
    except Exception as exc:
        return error_result(provider, f"unexpected error: {str(exc)}")
