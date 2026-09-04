"""
Postiz API integration for cross-posting videos via the Postiz Public API.

Docs: https://docs.postiz.com/public-api/introduction
"""
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import requests
from loguru import logger
from app.config import config
from app.services.publishing_base import PublishingProvider, PUBLISHING_PROVIDER_REGISTRY

# Maps MPT platform names to Postiz __type values and integration config keys.
_POSTIZ_PLATFORM_MAP = {
    "youtube": {
        "__type": "youtube",
        "integration_key": "postiz_youtube_integration_id",
    },
    "instagram": {
        "__type": "instagram",
        "integration_key": "postiz_instagram_integration_id",
    },
    "tiktok": {
        "__type": "tiktok",
        "integration_key": "postiz_tiktok_integration_id",
    },
    "x": {
        "__type": "x",
        "integration_key": "postiz_x_integration_id",
    },
}


class PostizService(PublishingProvider):
    """Service wrapper for the Postiz Public API.

    Uses the official endpoints:
      - POST {api_url}/api/public/v1/upload  (multipart file upload)
      - POST {api_url}/api/public/v1/posts   (create / schedule post)
      - GET  {api_url}/api/public/v1/posts   (list posts)

    Authentication uses the raw API key in the Authorization header
    (no Bearer prefix), per the official docs.
    """

    @property
    def api_url(self) -> str:
        return config.app.get("postiz_api_url", "http://localhost:8004")

    @property
    def api_key(self) -> str:
        return config.app.get("postiz_api_key", "")

    @property
    def enabled(self) -> bool:
        return config.app.get("postiz_enabled", False)

    @property
    def platforms(self) -> List[str]:
        return config.app.get("postiz_platforms", ["youtube"])

    @property
    def auto_upload(self) -> bool:
        return config.app.get("postiz_auto_upload", False)

    @property
    def youtube_privacy_status(self) -> str:
        return config.app.get("postiz_youtube_privacy_status", "public")

    @property
    def max_pending_tasks(self) -> int:
        return config.app.get("postiz_max_pending_tasks", 5)

    def _auth_headers(self) -> Dict[str, str]:
        """Return headers with raw API key (no Bearer prefix)."""
        return {"Authorization": self.api_key}

    def _api_base(self) -> str:
        base = self.api_url.rstrip("/")
        return f"{base}/api/public/v1"

    def _get_integration_id(self, platform: str) -> Optional[str]:
        platform_info = _POSTIZ_PLATFORM_MAP.get(platform)
        if not platform_info:
            return None
        return config.app.get(platform_info["integration_key"], "")

    def is_configured(self) -> bool:
        if not (self.enabled and self.api_key):
            return False
        for platform in self.platforms:
            if self._get_integration_id(platform):
                return True
        return False

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            logger.warning("Postiz is not configured. Skipping cross-post.")
            return {"success": False, "error": "Postiz not configured"}

        if platforms is None:
            platforms = self.platforms

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {"success": False, "error": f"Video file not found: {video_path}"}

        logger.info(f"Uploading video to Postiz (platforms: {', '.join(platforms)})...")

        # 1. Upload the video file
        try:
            with open(video_path, "rb") as video_file:
                files = {"file": video_file}
                upload_resp = requests.post(
                    f"{self._api_base()}/upload",
                    headers=self._auth_headers(),
                    files=files,
                    timeout=300,
                )
                upload_resp.raise_for_status()
                upload_json = upload_resp.json()
                media_id = upload_json.get("id")
                media_path = upload_json.get("path")
                if not media_id or not media_path:
                    raise ValueError(f"Missing id or path in upload response: {upload_json}")
        except Exception as e:
            logger.error(f"Failed to upload media to Postiz: {e}")
            return {"success": False, "error": str(e)}

        logger.info(f"Media uploaded to Postiz: id={media_id}, path={media_path}")

        # 2. Create a post for each platform with a configured integration ID
        results: List[Dict[str, Any]] = []
        any_success = False

        for platform in platforms:
            platform_info = _POSTIZ_PLATFORM_MAP.get(platform)
            if not platform_info:
                logger.warning(f"Unsupported Postiz platform: {platform}")
                results.append({"platform": platform, "success": False, "error": f"Unsupported platform: {platform}"})
                continue

            integration_id = self._get_integration_id(platform)
            if not integration_id:
                logger.warning(f"No Postiz integration ID configured for platform: {platform}")
                results.append({"platform": platform, "success": False, "error": f"No integration ID for {platform}"})
                continue

            settings: Dict[str, Any] = {"__type": platform_info["__type"]}

            if platform == "youtube":
                settings["title"] = title[:100]
                settings["type"] = self.youtube_privacy_status
                settings["selfDeclaredMadeForKids"] = "no"
                settings["tags"] = []
            elif platform == "instagram":
                settings["post_type"] = "reels"
            elif platform == "tiktok":
                settings["privacy_level"] = "PUBLIC_TO_EVERYONE"
                settings["duet"] = True
                settings["stitch"] = True
                settings["comment"] = True
                settings["autoAddMusic"] = True
                settings["brand_content_toggle"] = False
                settings["brand_organic_toggle"] = False
                settings["content_posting_method"] = "DIRECT_POST"

            post_payload: Dict[str, Any] = {
                "type": "now",
                "date": datetime.now(timezone.utc).isoformat(),
                "shortLink": False,
                "tags": [],
                "posts": [
                    {
                        "integration": {"id": integration_id},
                        "value": [
                            {
                                "content": title[:2200],
                                "image": [{"id": media_id, "path": media_path}],
                            }
                        ],
                        "settings": settings,
                    }
                ],
            }

            try:
                post_resp = requests.post(
                    f"{self._api_base()}/posts",
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                    json=post_payload,
                    timeout=300,
                )
                post_resp.raise_for_status()
                post_json = post_resp.json()
                if isinstance(post_json, list) and len(post_json) > 0:
                    post_id = post_json[0].get("postId", "")
                    logger.info(f"Postiz post created for {platform}: postId={post_id}")
                    results.append({"platform": platform, "success": True, "post_id": post_id})
                    any_success = True
                else:
                    logger.warning(f"Unexpected Postiz response for {platform}: {post_json}")
                    results.append({"platform": platform, "success": False, "error": "Unexpected response format", "response": post_json})
            except Exception as e:
                logger.error(f"Failed to create Postiz post for {platform}: {e}")
                results.append({"platform": platform, "success": False, "error": str(e)})

        return {"success": any_success, "results": results, "media_id": media_id}

    def check_status(self, request_id: str) -> Dict[str, Any]:
        try:
            resp = requests.get(
                f"{self._api_base()}/posts",
                headers=self._auth_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to query Postiz status for {request_id}: {e}")
            return {"success": False, "error": str(e)}


postiz_service = PostizService()
PUBLISHING_PROVIDER_REGISTRY["postiz"] = postiz_service


def cross_post_video(
    video_path: str,
    title: str,
    platforms: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    return postiz_service.upload_video(video_path, title, platforms, **kwargs)
