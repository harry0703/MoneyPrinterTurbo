from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

import requests

ALLOWED_EXTENSIONS = {".mp4", ".png", ".jpg", ".jpeg", ".webp"}
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": ".mp4",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _extension_from_url(url: str) -> str:
    path = urlparse(url).path or ""
    _, ext = os.path.splitext(path)
    return ext.lower()


def _extension_from_content_type(content_type: str) -> str:
    normalized = (content_type or "").split(";")[0].strip().lower()
    return CONTENT_TYPE_EXTENSIONS.get(normalized, "")


def download_file(url: str, output_path: str, timeout_seconds: int = 120) -> str:
    if not url:
        raise ValueError("download url is required")

    target_dir = os.path.dirname(output_path) or "."
    os.makedirs(target_dir, exist_ok=True)

    response = requests.get(url, stream=True, timeout=(10, timeout_seconds))
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"download failed with status {response.status_code}")

    desired_ext = os.path.splitext(output_path)[1].lower()
    guessed_ext = _extension_from_url(url) or _extension_from_content_type(
        response.headers.get("Content-Type", "")
    )

    final_ext = desired_ext or guessed_ext
    if final_ext and final_ext not in ALLOWED_EXTENSIONS:
        raise RuntimeError(f"unsupported output extension: {final_ext}")

    final_output_path = output_path
    if not desired_ext and final_ext:
        final_output_path = f"{output_path}{final_ext}"

    with open(final_output_path, "wb") as file_handle:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            if chunk:
                file_handle.write(chunk)

    return final_output_path
