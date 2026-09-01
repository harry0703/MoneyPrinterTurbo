"""
Upload-Post API integration for cross-posting videos to TikTok and Instagram.

YouTube is published through the official YouTube Data API v3 instead; see
``app.services.youtube_upload``.

Docs: https://docs.upload-post.com
"""
import os
from typing import Optional

import requests
from loguru import logger
from app.config import config


class UploadPostService:
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

    def is_configured(self) -> bool:
        return bool(self.api_key and self.username and self.enabled)

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: Optional[list] = None,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> dict:
        if not self.is_configured():
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


def cross_post_video(
    video_path: str,
    title: str,
    platforms: Optional[list] = None,
) -> dict:
    return upload_post_service.upload_video(video_path, title, platforms)
