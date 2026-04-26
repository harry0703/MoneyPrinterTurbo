"""
Upload-Post API integration for cross-posting videos to TikTok and Instagram.

Docs: https://docs.upload-post.com
"""
import os
import requests
from loguru import logger
from app.config import config


class UploadPostService:
    """
    Service for cross-posting videos to TikTok/Instagram via Upload-Post API.
    """

    API_BASE = "https://api.upload-post.com"

    def __init__(self):
        self.api_key = config.app.get("upload_post_api_key", "")
        self.username = config.app.get("upload_post_username", "")
        self.enabled = config.app.get("upload_post_enabled", False)
        self.platforms = config.app.get("upload_post_platforms", ["tiktok", "instagram"])
        self.auto_upload = config.app.get("upload_post_auto_upload", False)

    def is_configured(self) -> bool:
        """Check if Upload-Post is properly configured."""
        return bool(self.api_key and self.username and self.enabled)

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: list = None,
        privacy_level: str = "PUBLIC_TO_EVERYONE"
    ) -> dict:
        """
        Upload a video to TikTok and/or Instagram.

        Args:
            video_path (str): Path to the video file
            title (str): Video title/caption (max 2200 chars for Instagram)
            platforms (list): List of platforms ["tiktok", "instagram"]
            privacy_level (str): Privacy level for the video

        Returns:
            dict: API response with request_id and status
        """
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
                
                data = {
                    'user': self.username,
                    'title': title[:2200],
                    'privacy_level': privacy_level
                }
                
                # Add each platform
                for i, platform in enumerate(platforms):
                    data[f'platform[{i}]'] = platform

                headers = {
                    'Authorization': f'Apikey {self.api_key}'
                }

                response = requests.post(
                    f"{self.API_BASE}/api/upload_video",
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=300
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
                f"{self.API_BASE}/api/status/{request_id}",
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


def cross_post_video(video_path: str, title: str, platforms: list = None) -> dict:
    """
    Convenience function to cross-post a video.
    
    Args:
        video_path (str): Path to the video file
        title (str): Video title/caption
        platforms (list): List of platforms (defaults to config)
    
    Returns:
        dict: API response
    """
    return upload_post_service.upload_video(video_path, title, platforms)
