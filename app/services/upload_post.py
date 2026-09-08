"""
Upload-Post API integration for cross-posting videos to TikTok, Instagram and YouTube Shorts.

Docs: https://docs.upload-post.com
"""
import os
from typing import Optional

import requests
from loguru import logger
from app.config import config
from app.services.publishing_base import PublishingProvider, PUBLISHING_PROVIDER_REGISTRY


class UploadPostService(PublishingProvider):
    API_BASE = "https://api.upload-post.com"

    @property
    def api_key(self) -> str:
        return config.app.get("upload_post_api_key", "")

    @property
    def username(self) -> str:
        return config.app.get("upload_post_username", "")

    @property
    def enabled(self) -> bool:
        return config.app.get("upload_post_enabled", False)

    @property
    def platforms(self) -> list:
        return config.app.get("upload_post_platforms", ["tiktok", "instagram"])

    @property
    def auto_upload(self) -> bool:
        return config.app.get("upload_post_auto_upload", False)

    @property
    def youtube_privacy_status(self) -> str:
        return config.app.get("upload_post_youtube_privacy_status", "public")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.username and self.enabled)

    def snapshot_targets(self) -> dict:
        """Capture queue-time publishing destinations + privacy settings.

        Called once at queue time by the task pipeline. The returned dict is
        JSON-serializable and passed into the background worker, which must
        use it exclusively instead of re-reading live config at execution.

        Frozen here: platforms, youtube_privacy_status, and privacy_level.
        Intentionally NOT frozen (read live at execution): API key/username
        and API_BASE endpoint, which ``upload_video`` resolves at call time.
        """
        return {
            "provider": "upload_post",
            "platforms": list(self.platforms or []),
            "youtube_privacy_status": self.youtube_privacy_status,
            "extra": {
                # No WebUI selector exists for this (webui/Main.py only
                # exposes a youtube_privacy_status selectbox for
                # upload_post); the upstream API default is
                # PUBLIC_TO_EVERYONE, so the constant is frozen here
                # intentionally rather than threaded from config.
                "privacy_level": "PUBLIC_TO_EVERYONE",
            },
        }

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: Optional[list] = None,
        # No WebUI selector for privacy_level (only youtube_privacy_status
        # has one); keep the upstream API default as the constant default.
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        youtube_extra: Optional[dict] = None,
        skip_config_check: bool = False,
    ) -> dict:
        # Snapshot execution passes skip_config_check=True so queue-time
        # destinations survive a config change before the worker runs.
        if not skip_config_check and not self.is_configured():
            logger.warning("Upload-Post is not configured. Skipping cross-post.")
            return {"success": False, "error": "Upload-Post not configured"}

        if platforms is None:
            platforms = self.platforms

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {"success": False, "error": f"Video file not found: {video_path}"}

        logger.info(f"Cross-posting video to {', '.join(platforms)} via Upload-Post...")

        try:
            with open(video_path, 'rb') as video_file:
                files = {'video': video_file}

                data = [
                    ('user', self.username),
                    ('title', title[:2200]),
                    ('privacy_level', privacy_level),
                ]

                for platform in platforms:
                    data.append(('platform[]', platform))

                if youtube_extra and any(p.startswith("youtube") for p in platforms):
                    if "youtube_title" in youtube_extra:
                        data.append(('youtube_title', youtube_extra["youtube_title"][:100]))
                    if "youtube_description" in youtube_extra:
                        data.append(('youtube_description', youtube_extra["youtube_description"]))
                    for tag in youtube_extra.get("tags", []):
                        data.append(('tags[]', tag))
                    data.append(('privacyStatus', youtube_extra.get("privacyStatus", "public")))
                    data.append(('containsSyntheticMedia', "true"))

                headers = {'Authorization': f'Apikey {self.api_key}'}

                response = requests.post(
                    f"{self.API_BASE}/api/upload",
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=300,
                )

                response.raise_for_status()
                result = response.json()

                if result.get('success'):
                    logger.info(f"✅ Video cross-posted successfully! Request ID: {result.get('request_id')}")
                else:
                    logger.warning(f"Cross-post failed: {result.get('message', 'Unknown error')}")

                return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to cross-post video: {str(e)}")
            return {"success": False, "error": str(e)}

    def check_status(self, request_id: str) -> dict:
        """
        Check the status of an upload request.

        Args:
            request_id (str): The request ID from upload

        Returns:
            dict: Status information
        """
        try:
            headers = {
                'Authorization': f'Apikey {self.api_key}'
            }

            response = requests.get(
                f"{self.API_BASE}/api/uploadposts/status",
                params={'request_id': request_id},
                headers=headers,
                timeout=30
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check status: {str(e)}")
            return {"success": False, "error": str(e)}


# Singleton instance
upload_post_service = UploadPostService()
PUBLISHING_PROVIDER_REGISTRY["upload_post"] = upload_post_service


def cross_post_video(
    video_path: str,
    title: str,
    platforms: Optional[list] = None,
    youtube_extra: Optional[dict] = None,
) -> dict:
    return upload_post_service.upload_video(video_path, title, platforms, youtube_extra=youtube_extra)
