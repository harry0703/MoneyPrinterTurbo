"""Best-effort webhook notification for videos published to YouTube.

Kept as its own module so ``task_cross_post.py`` doesn't grow another
concern: building the payload and doing the HTTP call is unrelated to the
publishing logic itself, and a webhook failure must never affect the
already-successful upload.
"""

from typing import Any

import requests
from loguru import logger

from app.config import config

WEBHOOK_TIMEOUT_SECONDS = 10


def _webhook_url() -> str:
    return str(config.app.get("youtube_publish_webhook_url", "") or "").strip()


def notify_video_published(
    *,
    task_id: str,
    video_id: str,
    url: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    video_subject: str = "",
    video_language: str = "",
) -> None:
    """POST video metadata to the configured webhook; never raises."""
    webhook_url = _webhook_url()
    if not webhook_url:
        return

    payload: dict[str, Any] = {
        "event": "video.published",
        "platform": "youtube",
        "task_id": task_id,
        "video_id": video_id,
        "url": url,
        "title": title,
        "description": description,
        "tags": tags,
        "privacy_status": privacy_status,
        "subject": video_subject,
        "language": video_language,
        "success": True,
    }

    try:
        response = requests.post(
            webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as exc:
        # A notificação é best-effort: o vídeo já foi publicado com sucesso,
        # então uma falha aqui não pode propagar para o fluxo de publicação.
        logger.warning(
            f"failed to notify publish webhook, task_id: {task_id}, "
            f"video_id: {video_id}, error: {exc}"
        )
