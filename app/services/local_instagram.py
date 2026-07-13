"""
Local Instagram publisher integration.

Sends generated videos to a local MoneyPrinterTurbo-compatible Instagram
publishing endpoint (e.g. the Express server in this project's root).

Expected endpoint contract:
    POST <endpoint>
    Content-Type: application/json
    Body: {
        "filePath": "/absolute/path/to/video.mp4",
        "description": "Caption text for the Instagram post"
    }
"""
import os
from typing import Optional

import requests
from loguru import logger

from app.config import config


class LocalInstagramService:
    def __init__(self):
        self.enabled = config.app.get("local_instagram_enabled", False)
        self.endpoint = config.app.get(
            "local_instagram_endpoint", "http://localhost:3000/upload"
        )
        self.description_template = config.app.get(
            "local_instagram_description_template", "{subject}"
        )
        self.timeout = config.app.get("local_instagram_timeout", 600)

    def is_configured(self) -> bool:
        return bool(self.enabled and self.endpoint)

    def build_description(self, subject: str, caption: str = "") -> str:
        """
        Build the Instagram caption from the configured template.

        Available placeholders:
          - {subject}: the video subject
          - {caption}: an optional generated caption (falls back to subject)
        """
        return self.description_template.format(
            subject=subject or "",
            caption=caption or subject or "",
        )

    def upload_video(
        self,
        video_path: str,
        subject: str,
        caption: str = "",
    ) -> dict:
        """
        Send a single generated video to the local Instagram publisher endpoint.

        Args:
            video_path: Absolute or relative path to the rendered video file.
            subject: Video subject/title used to build the caption.
            caption: Optional pre-generated caption text.

        Returns:
            dict: Parsed JSON response from the endpoint.
        """
        if not self.is_configured():
            logger.debug("Local Instagram publisher is not configured. Skipping.")
            return {"success": False, "error": "Local Instagram publisher not configured"}

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {"success": False, "error": f"Video file not found: {video_path}"}

        description = self.build_description(subject, caption)
        payload = {
            "filePath": video_path,
            "description": description,
        }

        logger.info(f"Sending video to local Instagram endpoint: {self.endpoint}")
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(
                    f"✅ Local Instagram publish accepted: {result.get('postId', 'n/a')}"
                )
            else:
                logger.warning(
                    f"Local Instagram publish refused: {result.get('error', 'Unknown error')}"
                )

            return result

        except requests.exceptions.Timeout:
            logger.error(
                f"Timeout while calling local Instagram endpoint ({self.timeout}s): {self.endpoint}"
            )
            return {"success": False, "error": "Request timed out"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to call local Instagram endpoint: {str(e)}")
            return {"success": False, "error": str(e)}

    def upload_videos(
        self,
        video_paths: list[str],
        subject: str,
        caption: str = "",
    ) -> list[dict]:
        """Publish multiple videos in sequence."""
        results = []
        for video_path in video_paths:
            results.append(self.upload_video(video_path, subject, caption))
        return results


# Singleton instance
local_instagram_service = LocalInstagramService()


def publish_videos(
    video_paths: list[str],
    subject: str,
    caption: str = "",
) -> list[dict]:
    return local_instagram_service.upload_videos(video_paths, subject, caption)
